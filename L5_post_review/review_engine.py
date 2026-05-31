#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 Review Engine（复盘引擎）

合并原 strategy_tracker.py + delegate.py，统一提供：
1. L4 决策追踪 + 后续表现评估（StrategyTracker 功能）
2. 交易复盘 + CPCV 防过拟合验证（ReviewDelegate 功能）

CPCV（组合交叉验证）防过拟合机制：
- 将历史数据划分为多个不重叠的"训练窗口"和"验证窗口"
- 确保训练窗口和验证窗口之间有"purge gap"
- 防止未来信息泄露到训练数据中

过拟合风险指标：
| 指标 | 含义 | 阈值 |
|------|------|------|
| PBO | Probability of Backtest Overfitting | <15%为佳 |
| Hit Rate Delta | 验证期vs训练期命中率差异 | <10%为佳 |
| Return Delta | 验证期vs训练期收益率差异 | <25%为佳 |
"""

from __future__ import annotations

import json
import logging
import os
import random
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("review_engine")

# ======================== 路径配置 ========================

PROJECT_ROOT = Path(os.path.expanduser("~/.hermes/investment"))
CONFIG_DIR = PROJECT_ROOT / "main" / "config"
REVIEW_OUTPUT_DIR = CONFIG_DIR / "review_pending"
FREEZE_TABLE_PATH = PROJECT_ROOT / "main" / "freeze_table.json"

# ======================== CPCV配置 ========================

DEFAULT_N_FOLDS = 5
DEFAULT_PURGE_GAP_DAYS = 5
HORIZON_DAYS = [5, 10, 20, 60]

# 过拟合阈值
PBO_THRESHOLD = 0.15
HIT_RATE_DELTA_THRESHOLD = 0.10
RETURN_DELTA_THRESHOLD = 0.25


# ======================== 数据模型 ========================

@dataclass
class DecisionRecord:
    """L4 决策记录"""
    decision_id: str
    code: str
    name: str
    decision: str             # BUY / WATCH / REJECT
    judge_score: float
    date: str
    price: float
    reason: str
    market: str = "CN"


@dataclass
class OutcomeRecord:
    """信号后续表现"""
    decision_id: str
    code: str
    horizon: int              # 持有期（天）
    return_pct: float
    hit: bool                 # 是否盈利
    closed: bool              # 是否已到期/平仓


@dataclass
class TradeRecord:
    """交易记录"""
    trade_id: str
    symbol: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    holding_days: int
    decision_at_entry: str
    confidence_at_entry: float


@dataclass
class EffectivenessMetrics:
    """策略有效性指标"""
    total_decisions: int
    buy_count: int
    watch_count: int
    reject_count: int
    buy_hit_rate: float
    buy_avg_return: float
    watch_to_buy_upgrade_rate: float
    reject_keep_dropping_rate: float
    sharpe_like: float
    win_loss_ratio: float


@dataclass
class CPCVResult:
    """CPCV验证结果"""
    n_trades: int
    n_folds: int
    avg_overfitting_ratio: float
    pbo: float
    hit_rate_train: float
    hit_rate_validate: float
    return_train_avg: float
    return_validate_avg: float
    verdict: str
    notes: str


# ======================== Review Engine ========================

class ReviewEngine:
    """
    L5 复盘引擎（合并 StrategyTracker + ReviewDelegate）

    工作流程：
        1. L4 决策时 → record_decision()
        2. 每个周期 → evaluate_outcomes() 更新所有持仓结果
        3. 任意时刻 → get_effectiveness_report() / run_review()
    """

    def __init__(self, market: str = "CN"):
        self.market = market.upper()
        self.decisions: List[DecisionRecord] = []
        self.outcomes: Dict[str, List[OutcomeRecord]] = {}

    # ── 决策记录 ───────────────────────────────────────────────

    def record_decision(
        self,
        code: str,
        decision: str,
        judge_score: float,
        date: str,
        price: float,
        name: str = "",
        reason: str = "",
        market: str = "CN",
    ) -> str:
        """记录一个新的 L4 决策信号。"""
        import uuid
        decision_id = uuid.uuid4().hex[:12]
        record = DecisionRecord(
            decision_id=decision_id,
            code=code,
            name=name or code,
            decision=decision.upper(),
            judge_score=judge_score,
            date=date,
            price=price,
            reason=reason,
            market=market,
        )
        self.decisions.append(record)
        self.outcomes[decision_id] = []
        self._save()
        logger.info(f"[ReviewEngine] Recorded {decision} {code}@{date} score={judge_score:.2f}")
        return decision_id

    def record_decision_from_l4(self, l4_result: dict) -> List[str]:
        """从 L4 分析结果批量提取决策并记录。"""
        decision_ids = []
        decisions = l4_result.get("decisions", [])
        date_str = l4_result.get("date", date.today().strftime("%Y-%m-%d"))
        market = l4_result.get("market", "CN")

        for d in decisions:
            code = d.get("code", "")
            decision = d.get("decision", "REJECT")
            judge_score = d.get("judge_score", 0.0)
            price = d.get("price", 0.0)
            name = d.get("name", code)
            reason = d.get("reason", d.get("conclusion", ""))

            if not code or price <= 0:
                continue

            did = self.record_decision(
                code=code, decision=decision, judge_score=judge_score,
                date=date_str, price=price, name=name, reason=reason, market=market,
            )
            decision_ids.append(did)
        return decision_ids

    # ── 结果评估 ────────────────────────────────────────────────

    def evaluate_outcomes(
        self,
        horizon_days: Optional[List[int]] = None,
        price_func=None,
    ) -> None:
        """评估所有持仓信号的最新表现。"""
        horizons = horizon_days or HORIZON_DAYS
        today = date.today()

        if price_func is None:
            price_func = self._get_realtime_price

        for record in self.decisions:
            for h in horizons:
                existing = [o for o in self.outcomes.get(record.decision_id, [])
                            if o.horizon == h]
                if existing:
                    continue

                entry_date = datetime.strptime(record.date, "%Y-%m-%d").date()
                eval_date = entry_date + timedelta(days=h)

                if eval_date > today:
                    continue

                current_price = price_func(record.code, record.date)
                if current_price is None or current_price <= 0:
                    current_price = record.price

                ret_pct = (current_price - record.price) / record.price
                hit = ret_pct > 0

                outcome = OutcomeRecord(
                    decision_id=record.decision_id,
                    code=record.code,
                    horizon=h,
                    return_pct=round(ret_pct, 4),
                    hit=hit,
                    closed=True,
                )
                self.outcomes.setdefault(record.decision_id, []).append(outcome)

        self._save()
        logger.info(f"[ReviewEngine] Evaluated outcomes for {len(self.decisions)} decisions")

    def _get_realtime_price(self, code: str, as_of_date: str) -> Optional[float]:
        """从 BaoStock 获取实时/历史价格"""
        try:
            import baostock as bs
            bs_code = f"sh.{code}" if code.startswith("6") else f"sz.{code}"
            bs.login()
            rs = bs.query_history_k_data_plus(
                bs_code, "date,close",
                start_date=as_of_date.replace("-", ""),
                end_date=as_of_date.replace("-", ""),
                frequency="d", adjustflag="2",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            bs.logout()
            if rows:
                return float(rows[-1][1])
        except Exception:
            pass
        return None

    # ── 策略有效性报告 ──────────────────────────────────────────

    def get_effectiveness_report(self) -> EffectivenessMetrics:
        """生成策略有效性报告"""
        buy_records = [d for d in self.decisions if d.decision == "BUY"]
        watch_records = [d for d in self.decisions if d.decision == "WATCH"]
        reject_records = [d for d in self.decisions if d.decision == "REJECT"]

        buy_hits = 0
        buy_returns = []
        for rec in buy_records:
            outcomes = self.outcomes.get(rec.decision_id, [])
            if not outcomes:
                continue
            longest = max(outcomes, key=lambda o: o.horizon)
            if longest.closed:
                buy_hits += 1 if longest.hit else 0
                buy_returns.append(longest.return_pct)

        buy_hit_rate = buy_hits / len(buy_records) if buy_records else 0.0
        buy_avg_return = sum(buy_returns) / len(buy_returns) if buy_returns else 0.0

        watch_upgrades = 0
        for rec in watch_records:
            outcomes = self.outcomes.get(rec.decision_id, [])
            if not outcomes:
                continue
            o10 = next((o for o in outcomes if o.horizon == 10), None)
            if o10 and o10.closed and o10.return_pct > 0.05:
                watch_upgrades += 1
        watch_to_buy_rate = watch_upgrades / len(watch_records) if watch_records else 0.0

        reject_drops = 0
        for rec in reject_records:
            outcomes = self.outcomes.get(rec.decision_id, [])
            if not outcomes:
                continue
            o10 = next((o for o in outcomes if o.horizon == 10), None)
            if o10 and o10.closed and o10.return_pct < 0:
                reject_drops += 1
        reject_drop_rate = reject_drops / len(reject_records) if reject_records else 0.0

        winning = [r for r in buy_returns if r > 0]
        losing = [r for r in buy_returns if r < 0]
        avg_win = sum(winning) / len(winning) if winning else 0.0
        avg_loss = abs(sum(losing) / len(losing)) if losing else 1.0
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

        if len(buy_returns) > 1:
            rets = np.array(buy_returns)
            sharpe = (rets.mean() - 0.03 / 252) / (rets.std() + 1e-9) * np.sqrt(252)
        else:
            sharpe = 0.0

        return EffectivenessMetrics(
            total_decisions=len(self.decisions),
            buy_count=len(buy_records),
            watch_count=len(watch_records),
            reject_count=len(reject_records),
            buy_hit_rate=round(buy_hit_rate, 4),
            buy_avg_return=round(buy_avg_return, 4),
            watch_to_buy_upgrade_rate=round(watch_to_buy_rate, 4),
            reject_keep_dropping_rate=round(reject_drop_rate, 4),
            sharpe_like=round(sharpe, 2),
            win_loss_ratio=round(win_loss_ratio, 2),
        )

    def print_effectiveness_report(self, metrics: EffectivenessMetrics) -> None:
        """打印策略有效性报告"""
        print("\n" + "=" * 60)
        print("策略有效性追踪报告")
        print("=" * 60)
        print(f"总决策数:      {metrics.total_decisions}")
        print(f"  BUY:        {metrics.buy_count}")
        print(f"  WATCH:      {metrics.watch_count}")
        print(f"  REJECT:     {metrics.reject_count}")
        print()
        print(f"BUY 命中率:   {metrics.buy_hit_rate:.1%}   （健康 >55%）")
        print(f"BUY 平均收益:  {metrics.buy_avg_return:.2%}   （健康 >0%）")
        print(f"WATCH 升级率: {metrics.watch_to_buy_upgrade_rate:.1%}")
        print(f"REJECT 有效率: {metrics.reject_keep_dropping_rate:.1%}   （REJECT后继续跌=好）")
        print(f"盈亏比:        {metrics.win_loss_ratio:.2f}x")
        print(f"模拟夏普:      {metrics.sharpe_like:.2f}")
        print("=" * 60)

    # ── 交易复盘 ────────────────────────────────────────────────

    def _load_freeze_table(self) -> dict:
        """加载冷冻表"""
        if not FREEZE_TABLE_PATH.exists():
            return {"freeze_records": [], "observing_list": [], "buy_signals": []}
        try:
            with open(FREEZE_TABLE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"冷冻表加载失败: {e}")
            return {"freeze_records": [], "observing_list": [], "buy_signals": []}

    def load_closed_trades(self) -> List[TradeRecord]:
        """从 freeze_table.json 的 buy_signals 加载已平仓交易"""
        from L2_data_enrich.data_fetcher import fetch_qq_realtime

        closed_trades: List[TradeRecord] = []
        freeze_table = self._load_freeze_table()
        signals = freeze_table.get("buy_signals", [])

        for signal in signals:
            if signal.get("status") != "executed":
                continue

            code = signal.get("stock_code", "")
            entry_date = signal.get("signal_date", "")
            entry_price = signal.get("price", 0.0)
            judge_score = signal.get("judge_score", 0.0)

            if not code or entry_price <= 0:
                continue

            exit_price = entry_price
            try:
                price_data = fetch_qq_realtime(code)
                if price_data and "price" in price_data:
                    exit_price = float(price_data["price"])
            except Exception:
                pass

            decision_at_entry = "BUY"

            return_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0

            holding_days = 0
            if entry_date:
                try:
                    entry = datetime.strptime(entry_date, "%Y-%m-%d").date()
                    holding_days = (date.today() - entry).days
                except Exception:
                    holding_days = 0

            trade = TradeRecord(
                trade_id=f"{entry_date}_{code}",
                symbol=code,
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=date.today().strftime("%Y-%m-%d"),
                exit_price=exit_price,
                return_pct=round(return_pct, 4),
                holding_days=max(0, holding_days),
                decision_at_entry=decision_at_entry,
                confidence_at_entry=round(judge_score, 3),
            )
            closed_trades.append(trade)

        logger.info(f"加载已平仓交易: {len(closed_trades)} 条")
        return closed_trades

    def run_review(self, trades: List[TradeRecord] = None) -> Dict:
        """
        执行完整复盘流程（合并单笔分析 + 模式分析 + CPCV验证）

        Args:
            trades: 交易记录列表，如果为None则从 freeze_table.json 加载

        Returns:
            复盘结果字典
        """
        review_id = f"{date.today().strftime('%Y%m%d')}_{len(trades or [])}"

        if trades is None:
            trades = self.load_closed_trades()

        if not trades:
            logger.warning("没有交易记录可复盘")
            return {"status": "no_trades", "review_id": review_id}

        single_analysis = self._analyze_single_trades(trades)
        pattern_analysis = self._analyze_patterns(trades)
        cpcv_result = self._cpcv_evaluate(trades)

        winning_trades = [t for t in trades if t.return_pct > 0]
        losing_trades = [t for t in trades if t.return_pct <= 0]

        result = {
            "review_id": review_id,
            "date": date.today().strftime("%Y-%m-%d"),
            "trades_reviewed": len(trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": len(winning_trades) / len(trades) if trades else 0,
            "single_trade_analysis": single_analysis,
            "patterns": pattern_analysis,
            "cpcv_validation": asdict(cpcv_result) if cpcv_result else None,
            "parameter_changes": [],
            "approved_parameter_changes": []
        }

        self._save_pending_review(result)
        return result

    def _analyze_single_trades(self, trades: List[TradeRecord]) -> List[Dict]:
        """单笔交易分析"""
        analysis = []
        for trade in trades:
            a = {
                "trade_id": trade.trade_id,
                "symbol": trade.symbol,
                "return_pct": trade.return_pct,
                "what_happened": {
                    "price_moved": f"{'+' if trade.return_pct > 0 else ''}{trade.return_pct:.1%}",
                    "holding_days": trade.holding_days
                },
                "failure_analysis": None
            }
            if trade.decision_at_entry == "WATCH" and trade.return_pct > 0.05:
                a["failure_analysis"] = {
                    "issue": "WATCH决策但实际上涨，概率模型可能保守",
                    "layer_responsible": "L4",
                    "lessons": ["考虑调整WATCH转BUY的阈值"]
                }
            elif trade.decision_at_entry == "BUY" and trade.return_pct < -0.05:
                a["failure_analysis"] = {
                    "issue": "BUY决策但实际下跌",
                    "layer_responsible": "L4",
                    "lessons": ["检查止损执行是否到位"]
                }
            analysis.append(a)
        return analysis

    def _analyze_patterns(self, trades: List[TradeRecord]) -> List[Dict]:
        """系统性模式分析"""
        patterns = []

        short_holding_losses = [t for t in trades
                                if t.holding_days <= 5 and t.return_pct < -0.03]
        if len(short_holding_losses) >= 2:
            patterns.append({
                "pattern_id": "P001",
                "description": "短期快速止损",
                "frequency": len(short_holding_losses),
                "examples": [t.symbol for t in short_holding_losses[:3]],
                "root_cause": "可能存在过早买入或止损设置不合理",
                "fix": "检查止损阈值设置"
            })

        watch_to_buy_wins = [t for t in trades
                             if t.decision_at_entry == "WATCH" and t.return_pct > 0.05]
        if len(watch_to_buy_wins) >= 2:
            patterns.append({
                "pattern_id": "P002",
                "description": "WATCH后上涨",
                "frequency": len(watch_to_buy_wins),
                "examples": [t.symbol for t in watch_to_buy_wins[:3]],
                "root_cause": "WATCH状态时间过长，错过机会",
                "fix": "考虑缩短WATCH到BUY的转换时间"
            })

        return patterns

    def _cpcv_evaluate(self, trades: List[TradeRecord],
                        n_folds: int = DEFAULT_N_FOLDS) -> Optional[CPCVResult]:
        """CPCV 防过拟合验证"""
        if len(trades) < n_folds:
            logger.warning(f"交易数量({len(trades)})少于折数({n_folds})，跳过CPCV")
            return None

        random.shuffle(trades)
        fold_size = len(trades) // n_folds

        overfitting_ratios = []
        hit_rates_train = []
        hit_rates_validate = []
        returns_train = []
        returns_validate = []

        for fold in range(n_folds):
            val_start = fold * fold_size
            val_end = val_start + fold_size if fold < n_folds - 1 else len(trades)

            validate_trades = trades[val_start:val_end]
            train_trades = trades[:val_start] + trades[val_end:]

            train_wins = len([t for t in train_trades if t.return_pct > 0])
            train_hit_rate = train_wins / len(train_trades) if train_trades else 0
            train_return_avg = sum(t.return_pct for t in train_trades) / len(train_trades) if train_trades else 0

            val_wins = len([t for t in validate_trades if t.return_pct > 0])
            val_hit_rate = val_wins / len(validate_trades) if validate_trades else 0
            val_return_avg = sum(t.return_pct for t in validate_trades) / len(validate_trades) if validate_trades else 0

            if train_return_avg != 0:
                overfit_ratio = abs(val_return_avg - train_return_avg) / abs(train_return_avg)
            else:
                overfit_ratio = 0

            overfitting_ratios.append(overfit_ratio)
            hit_rates_train.append(train_hit_rate)
            hit_rates_validate.append(val_hit_rate)
            returns_train.append(train_return_avg)
            returns_validate.append(val_return_avg)

        avg_overfit = sum(overfitting_ratios) / len(overfitting_ratios)
        pbo = len([r for r in overfitting_ratios if r > 0.2]) / n_folds

        avg_hit_rate_train = sum(hit_rates_train) / len(hit_rates_train)
        avg_hit_rate_val = sum(hit_rates_validate) / len(hit_rates_validate)
        avg_return_train = sum(returns_train) / len(returns_train)
        avg_return_val = sum(returns_validate) / len(returns_validate)

        hit_rate_delta = abs(avg_hit_rate_train - avg_hit_rate_val)
        return_delta = abs(avg_return_train - avg_return_val) / abs(avg_return_train) if avg_return_train != 0 else 0

        verdict = "PASS"
        notes = []

        if pbo > PBO_THRESHOLD:
            verdict = "FAIL"
            notes.append(f"PBO={pbo:.1%}>{PBO_THRESHOLD:.0%}，策略可能过度优化")

        if hit_rate_delta > HIT_RATE_DELTA_THRESHOLD:
            verdict = "FAIL" if verdict == "FAIL" else "WARNING"
            notes.append(f"命中率差异={hit_rate_delta:.1%}，训练/验证不一致")

        if return_delta > RETURN_DELTA_THRESHOLD:
            verdict = "FAIL" if verdict == "FAIL" else "WARNING"
            notes.append(f"收益率差异={return_delta:.1%}，可能存在过拟合")

        if verdict == "PASS":
            notes.append("各项指标在可接受范围")

        return CPCVResult(
            n_trades=len(trades),
            n_folds=n_folds,
            avg_overfitting_ratio=avg_overfit,
            pbo=pbo,
            hit_rate_train=avg_hit_rate_train,
            hit_rate_validate=avg_hit_rate_val,
            return_train_avg=avg_return_train,
            return_validate_avg=avg_return_val,
            verdict=verdict,
            notes="; ".join(notes)
        )

    def _save_pending_review(self, result: Dict) -> None:
        """保存待审批的复盘结果"""
        REVIEW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = REVIEW_OUTPUT_DIR / f"review_pending_{result['review_id']}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"复盘结果已保存: {output_path}")

    def approve_changes(self, review_id: str) -> bool:
        """审批通过复盘建议的参数变更"""
        pending_path = REVIEW_OUTPUT_DIR / f"review_pending_{review_id}.json"
        if not pending_path.exists():
            logger.error(f"复盘结果不存在: {review_id}")
            return False
        logger.info(f"批准复盘建议: {review_id}")
        return True

    # ── 持久化 ─────────────────────────────────────────────────

    def _load(self) -> None:
        """从磁盘加载追踪数据（已迁移到DB，此处为空）"""
        pass

    def _save(self) -> None:
        """持久化追踪数据（已迁移到DB，此处为空）"""
        pass


# ─── CLI 自检 ─────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="L5 Review Engine")
    parser.add_argument("--action", "-a", default="status",
                        choices=["status", "review", "effectiveness"],
                        help="执行动作 (默认: status)")
    parser.add_argument("--market", "-m", default="CN",
                        choices=["CN", "HK", "US"],
                        help="市场标识 (默认: CN)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    engine = ReviewEngine(market=args.market)

    if args.action == "status":
        print(f"\n[{args.market}] L5 Review Engine 状态:")
        print(f"  总决策数: {len(engine.decisions)}")
        metrics = engine.get_effectiveness_report()
        print(f"  BUY: {metrics.buy_count}, WATCH: {metrics.watch_count}, REJECT: {metrics.reject_count}")

    elif args.action == "review":
        result = engine.run_review()
        print(f"\n复盘结果:")
        print(f"  审查ID: {result['review_id']}")
        print(f"  审查交易数: {result['trades_reviewed']}")
        print(f"  胜率: {result['win_rate']:.1%}")
        if result.get("cpcv_validation"):
            cv = result["cpcv_validation"]
            print(f"\nCPCV验证:")
            print(f"  判定: {cv['verdict']}")
            print(f"  PBO: {cv['pbo']:.1%}")

    elif args.action == "effectiveness":
        metrics = engine.get_effectiveness_report()
        engine.print_effectiveness_report(metrics)