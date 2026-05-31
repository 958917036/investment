#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 Position Tracker（持仓追踪模块）

职责：
1. 跟踪 freeze_table.json 中 buy_signals 的状态变化
2. 每日收盘后检查止损/止盈是否触发
3. 更新 status 和 exit_price/exit_date

状态机：
    pending → executed（实际成交）
                   ↓
        ┌──────────┼──────────┐
        ↓          ↓          ↓
    stopped   take_profit   expired（>60天）
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional

import sys
BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import info, warn, error

# ======================== 路径配置 ========================

PROJECT_ROOT = Path(os.path.expanduser("~/.hermes/investment"))
FREEZE_TABLE_PATHS = {
    "CN": PROJECT_ROOT / "main" / "freeze_table.json",
    "HK": PROJECT_ROOT / "main" / "freeze_table_hk.json",
    "US": PROJECT_ROOT / "main" / "freeze_table_us.json",
}

# ======================== 常量 ========================

MAX_HOLDING_DAYS = 60


# ======================== 数据模型 ========================

@dataclass
class PositionRecord:
    """持仓记录"""
    stock_code: str
    stock_name: str
    entry_date: str                          # 信号记录日期
    entry_price: float # 买入价格
    stop_loss: float                         # 止损价
    take_profit: float                       # 止盈价
    kelly_fraction: float
    judge_score: float
    reason: str
    status: str = "pending" # pending / executed / stopped / take_profit / expired
    signal_date: str = "" # 原始信号日期
    exit_date: Optional[str] = None          # 退出日期
    exit_price: Optional[float] = None       # 退出价格
    exit_reason: Optional[str] = None        # stop_loss / take_profit / expired / manual


@dataclass
class PositionStatus:
    """持仓状态汇总"""
    total_count: int = 0
    pending_count: int = 0
    executed_count: int = 0
    stopped_count: int = 0
    take_profit_count: int = 0
    expired_count: int = 0
    total_pnl_pct: float = 0.0
    avg_holding_days: float = 0.0


@dataclass
class TriggerResult:
    """触发结果"""
    record: PositionRecord
    trigger_type: str          # stop_loss / take_profit / expired / unchanged
    current_price: float
    current_date: str


# ======================== Position Tracker ========================

class PositionTracker:
    """
    持仓追踪器

    职责：
    1. 跟踪 freeze_table.json 中 buy_signals 的状态
    2. 每日收盘后检查止损/止盈是否触发
    3. 更新 status 和 exit_price/exit_date
    """

    def __init__(self, market: str = "CN"):
        self.market = market.upper()
        self.freeze_table_path = FREEZE_TABLE_PATHS.get(self.market, FREEZE_TABLE_PATHS["CN"])
        self._freeze_table: Optional[dict] = None

    def _load_freeze_table(self) -> dict:
        """加载冷冻表"""
        if not self.freeze_table_path.exists():
            return {"buy_signals": []}
        try:
            with open(self.freeze_table_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            warn("position_tracker", f"冷冻表加载失败: {e}")
            return {"buy_signals": []}

    def _save_freeze_table(self, table: dict) -> bool:
        """保存冷冻表"""
        try:
            self.freeze_table_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.freeze_table_path, "w", encoding="utf-8") as f:
                json.dump(table, f, ensure_ascii=False, indent=2)
            info("position_tracker", f"冷冻表已保存: {self.freeze_table_path}")
            return True
        except IOError as e:
            error("position_tracker", f"冷冻表保存失败: {e}")
            return False

    def _signal_to_record(self, signal: dict) -> PositionRecord:
        """将 buy_signal dict 转为 PositionRecord"""
        return PositionRecord(
            stock_code=signal.get("stock_code", ""),
            stock_name=signal.get("stock_name", signal.get("stock_code", "")),
            entry_date=signal.get("signal_date", ""),
            entry_price=signal.get("price", 0.0),
            stop_loss=signal.get("stop_loss", 0.0),
            take_profit=signal.get("take_profit", 0.0),
            kelly_fraction=signal.get("kelly_fraction", 0.0),
            judge_score=signal.get("judge_score", 0.0),
            reason=signal.get("reason", ""),
            status=signal.get("status", "pending"),
            signal_date=signal.get("signal_date", ""),
            exit_date=signal.get("exit_date"),
            exit_price=signal.get("exit_price"),
            exit_reason=signal.get("exit_reason"),
        )

    def _record_to_signal(self, record: PositionRecord) -> dict:
        """将 PositionRecord 转为 buy_signal dict"""
        return {
            "stock_code": record.stock_code,
            "stock_name": record.stock_name,
            "judge_score": record.judge_score,
            "price": record.entry_price,
            "stop_loss": record.stop_loss,
            "take_profit": record.take_profit,
            "kelly_fraction": record.kelly_fraction,
            "signal_date": record.signal_date or record.entry_date,
            "reason": record.reason,
            "status": record.status,
            "exit_date": record.exit_date,
            "exit_price": record.exit_price,
            "exit_reason": record.exit_reason,
        }

    def _get_current_price(self, stock_code: str) -> Optional[float]:
        """获取当前价格（从腾讯行情API）"""
        try:
            import sys
            PROJECT_ROOT = Path(os.path.expanduser("~/.hermes/investment"))
            sys.path.insert(0, str(PROJECT_ROOT))
            from L2_data_enrich.data_fetcher import fetch_qq_realtime
            data = fetch_qq_realtime(stock_code)
            if data and "price" in data:
                return float(data["price"])
        except Exception as e:
            warn("position_tracker", f"获取{stock_code}价格失败: {e}")
        return None

    # ── 核心方法 ────────────────────────────────────────────────

    def check_triggers(self, check_date: str = None) -> Dict[str, List[PositionRecord]]:
        """
        每日收盘后检查止损/止盈是否触发

        Args:
            check_date: 检查日期 YYYY-MM-DD，默认为今天

        Returns:
            {
                "stop_loss": [PositionRecord, ...],
                "take_profit": [PositionRecord, ...],
                "expired": [PositionRecord, ...],
                "unchanged": [PositionRecord, ...]
            }

        副作用：
            - 更新 freeze_table.json 中对应 buy_signals 的 status
            - 对 executed 状态的信号，记录 exit_price 和 exit_date
        """
        if check_date is None:
            check_date = date.today().strftime("%Y-%m-%d")

        table = self._load_freeze_table()
        signals = table.get("buy_signals", [])

        result: Dict[str, List[PositionRecord]] = {
            "stop_loss": [],
            "take_profit": [],
            "expired": [],
            "unchanged": [],
        }

        for signal in signals:
            record = self._signal_to_record(signal)

            # 只检查 executed 状态的持仓
            if record.status not in ("pending", "executed"):
                continue

            # 计算持有天数
            try:
                entry_d = datetime.strptime(record.signal_date or record.entry_date, "%Y-%m-%d").date()
                check_d = datetime.strptime(check_date, "%Y-%m-%d").date()
                holding_days = (check_d - entry_d).days
            except Exception:
                holding_days = 0

            # 检查是否过期
            if holding_days > MAX_HOLDING_DAYS:
                record.status = "expired"
                record.exit_date = check_date
                record.exit_reason = "expired"
                result["expired"].append(record)
                self._update_signal(table, record)
                continue

            # 获取当前价格
            current_price = self._get_current_price(record.stock_code)
            if current_price is None:
                result["unchanged"].append(record)
                continue

            # 检查止损
            if record.stop_loss > 0 and current_price <= record.stop_loss:
                record.status = "stopped"
                record.exit_date = check_date
                record.exit_price = current_price
                record.exit_reason = "stop_loss"
                result["stop_loss"].append(record)
                self._update_signal(table, record)
            # 检查止盈
            elif record.take_profit > 0 and current_price >= record.take_profit:
                record.status = "take_profit"
                record.exit_date = check_date
                record.exit_price = current_price
                record.exit_reason = "take_profit"
                result["take_profit"].append(record)
                self._update_signal(table, record)
            else:
                result["unchanged"].append(record)

        self._save_freeze_table(table)
        return result

    def _update_signal(self, table: dict, record: PositionRecord) -> None:
        """更新 table 中的 buy_signals 列表"""
        signals = table.get("buy_signals", [])
        for i, sig in enumerate(signals):
            if sig.get("stock_code") == record.stock_code and \
               sig.get("signal_date") == (record.signal_date or record.entry_date):
                signals[i] = self._record_to_signal(record)
                break

    def update_position_status(
        self,
        stock_code: str,
        status: str,
        exit_price: Optional[float] = None,
        exit_date: Optional[str] = None,
        exit_reason: Optional[str] = None
    ) -> bool:
        """
        更新单个持仓的状态

        Args:
            stock_code: 股票代码
            status: 新状态（pending/executed/stopped/take_profit/expired）
            exit_price: 退出价格
            exit_date: 退出日期
            exit_reason: 退出原因

        Returns:
            bool: 更新是否成功
        """
        table = self._load_freeze_table()
        signals = table.get("buy_signals", [])

        for sig in signals:
            if sig.get("stock_code") == stock_code:
                sig["status"] = status
                if exit_price is not None:
                    sig["exit_price"] = exit_price
                if exit_date is not None:
                    sig["exit_date"] = exit_date
                if exit_reason is not None:
                    sig["exit_reason"] = exit_reason
                self._save_freeze_table(table)
                info("position_tracker", f"更新持仓状态: {stock_code} → {status}")
                return True

        warn("position_tracker", f"股票不在持仓表中: {stock_code}")
        return False

    def record_execution(
        self,
        stock_code: str,
        execution_price: float,
        execution_date: str
    ) -> bool:
        """
        记录实际成交（从 pending 转为 executed）

        Args:
            stock_code: 股票代码
            execution_price: 成交价格
            execution_date: 成交日期

        Returns:
            bool: 记录是否成功
        """
        table = self._load_freeze_table()
        signals = table.get("buy_signals", [])

        for sig in signals:
            if sig.get("stock_code") == stock_code and sig.get("status") == "pending":
                sig["status"] = "executed"
                sig["exit_price"] = execution_price
                sig["exit_date"] = execution_date
                self._save_freeze_table(table)
                info("position_tracker", f"记录成交: {stock_code} @ {execution_price}")
                return True

        warn("position_tracker", f"找不到待执行信号: {stock_code}")
        return False

    def get_positions(self, status: str = None) -> List[PositionRecord]:
        """
        获取持仓列表

        Args:
            status: 按状态筛选（可选），不指定则返回全部

        Returns:
            List[PositionRecord]
        """
        table = self._load_freeze_table()
        signals = table.get("buy_signals", [])

        records = [self._signal_to_record(s) for s in signals]

        if status:
            records = [r for r in records if r.status == status]

        return records

    def get_position_summary(self) -> PositionStatus:
        """
        获取持仓状态汇总

        Returns:
            PositionStatus
        """
        positions = self.get_positions()

        total = len(positions)
        pending = len([p for p in positions if p.status == "pending"])
        executed = len([p for p in positions if p.status == "executed"])
        stopped = len([p for p in positions if p.status == "stopped"])
        take_profit = len([p for p in positions if p.status == "take_profit"])
        expired = len([p for p in positions if p.status == "expired"])

        # 计算总收益/亏损
        total_pnl = 0.0
        holding_days_list = []
        today = date.today()

        for p in positions:
            if p.exit_price and p.exit_date and p.entry_price > 0:
                pnl = (p.exit_price - p.entry_price) / p.entry_price
                total_pnl += pnl
            try:
                entry_d = datetime.strptime(p.signal_date or p.entry_date, "%Y-%m-%d").date()
                if p.exit_date:
                    exit_d = datetime.strptime(p.exit_date, "%Y-%m-%d").date()
                else:
                    exit_d = today
                holding_days_list.append((exit_d - entry_d).days)
            except Exception:
                pass

        avg_holding = sum(holding_days_list) / len(holding_days_list) if holding_days_list else 0.0

        return PositionStatus(
            total_count=total,
            pending_count=pending,
            executed_count=executed,
            stopped_count=stopped,
            take_profit_count=take_profit,
            expired_count=expired,
            total_pnl_pct=round(total_pnl, 4),
            avg_holding_days=round(avg_holding, 1),
        )


# ─── CLI 自检 ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="L5 Position Tracker")
    parser.add_argument("--action", "-a", default="status",
                        choices=["status", "check_triggers"],
                        help="执行动作")
    parser.add_argument("--market", "-m", default="CN",
                        choices=["CN", "HK", "US"],
                        help="市场标识")
    parser.add_argument("--date", "-d", default=None,
                        help="检查日期 YYYY-MM-DD")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    tracker = PositionTracker(market=args.market)

    if args.action == "status":
        summary = tracker.get_position_summary()
        print(f"\n[{args.market}] 持仓状态:")
        print(f"  总持仓: {summary.total_count}")
        print(f"  待执行: {summary.pending_count}")
        print(f"  已执行: {summary.executed_count}")
        print(f"  止损触发: {summary.stopped_count}")
        print(f"  止盈触发: {summary.take_profit_count}")
        print(f"  已过期: {summary.expired_count}")
        print(f"  总收益/亏损: {summary.total_pnl_pct:.2%}")
        print(f"  平均持仓天数: {summary.avg_holding_days:.1f}天")

    elif args.action == "check_triggers":
        result = tracker.check_triggers(check_date=args.date)
        for trigger_type, records in result.items():
            if records:
                print(f"\n[{trigger_type}]: {len(records)}个")
                for r in records:
                    print(f"  {r.stock_code} {r.stock_name} @{r.entry_price}")