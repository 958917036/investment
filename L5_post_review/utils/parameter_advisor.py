#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 Parameter Advisor（参数调参建议模块）

职责：
1. 基于 CPCV 验证结果，判断是否需要调整参数
2. 分析哪些策略/阈值需要调整
3. 生成参数调整建议写入 review_pending 目录
4. 支持审批和应用已审批的建议
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import info, warn, error

# ======================== 路径配置 ========================

PROJECT_ROOT = Path(os.path.expanduser("~/.hermes/investment"))
CONFIG_DIR = PROJECT_ROOT / "main" / "config"
REVIEW_OUTPUT_DIR = CONFIG_DIR / "review_pending"
REVIEW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ========================阈值常量 ========================

# 健康阈值
BUY_HIT_RATE_THRESHOLD = 0.55
WATCH_UPGRADE_RATE_THRESHOLD = 0.30
REJECT_DROP_RATE_THRESHOLD = 0.70
WIN_LOSS_RATIO_THRESHOLD = 1.5
SHARPE_THRESHOLD = 0.0

# CPCV 阈值
PBO_THRESHOLD = 0.15
HIT_RATE_DELTA_THRESHOLD = 0.10
RETURN_DELTA_THRESHOLD = 0.25

# 调参步长
THRESHOLD_STEP = 0.05
INITIAL_THRESHOLD_STEP = 0.02


# ======================== 数据模型 ========================

@dataclass
class ParameterSuggestion:
    """单条参数调整建议"""
    layer: str                          # L1 / L2 / L3 / L4
    strategy_name: str # 策略名称
    parameter_path: str                # 参数路径
    current_value: Any                 # 当前值
    suggested_value: Any               # 建议值
    reason: str                         # 调整原因
    evidence: Dict[str, Any] = field(default_factory=dict)  # 证据数据
    confidence: float = 0.5 # 置信度 0-1
    review_id: str = "" # 关联的复盘ID
    created_at: str = ""


@dataclass
class ParameterAdviceReport:
    """参数调参建议报告"""
    review_id: str
    date: str
    week_start: Optional[str] = None
    week_end: Optional[str] = None
    suggestions: List[ParameterSuggestion] = field(default_factory=list)
    overall_confidence: float = 0.0
    report_type: str = "daily"
    markets: List[str] = field(default_factory=list)
    approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    applied: bool = False
    applied_at: Optional[str] = None
    created_at: str = ""


# ======================== Parameter Advisor ========================

class ParameterAdvisor:
    """
    参数调参建议器

    职责：
    1. 基于 CPCV 验证结果，判断是否需要调整参数
    2. 分析哪些策略/阈值需要调整
    3. 生成参数调整建议写入 review_pending 目录
    """

    def __init__(self, market: str = "CN"):
        self.market = market.upper()
        self._engine = None

    @property
    def review_engine(self):
        """懒加载 ReviewEngine"""
        if self._engine is None:
            from L5_post_review.review_engine import ReviewEngine
            self._engine = ReviewEngine(market=self.market)
        return self._engine

    # ── 主入口 ────────────────────────────────────────────────

    def analyze_and_suggest(
        self,
        cpcv_result: Optional[dict] = None,
        effectiveness_metrics: Optional[dict] = None,
        positions: Optional[List[Any]] = None,
        date: Optional[str] = None
    ) -> List[ParameterSuggestion]:
        """
        分析并生成参数调整建议

        Args:
            cpcv_result: CPCV 验证结果（dict 或 CPCVResult）
            effectiveness_metrics: 策略有效性指标（dict 或 EffectivenessMetrics）
            positions: 持仓记录列表
            date: 复盘日期

        Returns:
            List[ParameterSuggestion]
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        review_id = f"{date}_advice"

        suggestions = []

        # L1 调参建议
        if cpcv_result and effectiveness_metrics:
            l1_suggestions = self.suggest_l1_adjustments(cpcv_result, effectiveness_metrics)
            suggestions.extend(l1_suggestions)

        # L4 调参建议
        if cpcv_result and positions and effectiveness_metrics:
            l4_suggestions = self.suggest_l4_adjustments(
                cpcv_result, positions, effectiveness_metrics
            )
            suggestions.extend(l4_suggestions)

        # 计算整体置信度
        if suggestions:
            overall_conf = sum(s.confidence for s in suggestions) / len(suggestions)
        else:
            overall_conf = 0.0

        # 保存报告
        if suggestions:
            report = ParameterAdviceReport(
                review_id=review_id,
                date=date,
                suggestions=suggestions,
                overall_confidence=overall_conf,
                report_type="daily",
                markets=[self.market],
                created_at=datetime.now().isoformat(),
            )
            self.save_advice_report(report)

        return suggestions

    # ── 各层分析 ──────────────────────────────────────────────

    def suggest_l1_adjustments(
        self,
        cpcv_result: dict,
        effectiveness: dict
    ) -> List[ParameterSuggestion]:
        """
        分析 L1 参数调整建议

        关注点：
        - 动量/反转/价值等策略阈值是否合适
        - 筛选条件是否过严（命中率低）或过松（噪声多）
        - PBO 高说明训练数据过拟合，需要放宽或收紧
        """
        suggestions = []
        review_id = f"advice_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 获取当前配置
        config = self._load_config_for_layer("L1")
        if not config:
            return suggestions

        signals_config = config.get("signals", {})

        # BUY 命中率偏低 → 放宽筛选阈值
        buy_hit_rate = effectiveness.get("buy_hit_rate", 0)
        if buy_hit_rate > 0 and buy_hit_rate < BUY_HIT_RATE_THRESHOLD:
            delta = buy_hit_rate - BUY_HIT_RATE_THRESHOLD
            # 命中率越低，需要放宽越多
            step = THRESHOLD_STEP * (1 + abs(delta) * 2)

            for strategy, sig_cfg in signals_config.items():
                thresholds = sig_cfg.get("thresholds", [])
                if len(thresholds) >= 2:
                    old_mid = thresholds[1]
                    new_mid = max(0.30, old_mid - step)  # 最低不低于 0.30

                    if abs(new_mid - old_mid) >= 0.01:
                        suggestions.append(ParameterSuggestion(
                            layer="L1",
                            strategy_name=strategy,
                            parameter_path=f"signals.{strategy}.thresholds[1]",
                            current_value=old_mid,
                            suggested_value=round(new_mid, 2),
                            reason=f"BUY 命中率 {buy_hit_rate:.1%} 偏低 (<{BUY_HIT_RATE_THRESHOLD:.0%})，建议放宽中阈值",
                            evidence={"buy_hit_rate": buy_hit_rate, "threshold": "middle"},
                            confidence=min(0.9, 0.5 + abs(delta)),
                            review_id=review_id,
                            created_at=datetime.now().isoformat(),
                        ))

        # PBO 过高 → 收紧初筛阈值
        pbo = cpcv_result.get("pbo", 0)
        if pbo > PBO_THRESHOLD:
            delta = pbo - PBO_THRESHOLD
            step = INITIAL_THRESHOLD_STEP * (1 + delta * 5)

            for strategy, sig_cfg in signals_config.items():
                thresholds = sig_cfg.get("thresholds", [])
                if thresholds:
                    old_init = thresholds[0]
                    new_init = min(0.60, old_init + step)  # 最高不超 0.60

                    if abs(new_init - old_init) >= 0.01:
                        suggestions.append(ParameterSuggestion(
                            layer="L1",
                            strategy_name=strategy,
                            parameter_path=f"signals.{strategy}.thresholds[0]",
                            current_value=old_init,
                            suggested_value=round(new_init, 2),
                            reason=f"PBO {pbo:.1%} 过高 (>{(PBO_THRESHOLD):.0%})，策略可能过拟合，建议收紧初筛阈值",
                            evidence={"pbo": pbo},
                            confidence=min(0.85, 0.5 + delta),
                            review_id=review_id,
                            created_at=datetime.now().isoformat(),
                        ))

        return suggestions

    def suggest_l2_adjustments(
        self,
        effectiveness: dict,
        positions: List[Any]
    ) -> List[ParameterSuggestion]:
        """L2 调参建议（预留）"""
        return []

    def suggest_l3_adjustments(
        self,
        cpcv_result: dict,
        effectiveness: dict
    ) -> List[ParameterSuggestion]:
        """L3 调参建议（预留）"""
        return []

    def suggest_l4_adjustments(
        self,
        cpcv_result: dict,
        positions: List[Any],
        effectiveness: dict
    ) -> List[ParameterSuggestion]:
        """
        分析 L4 参数调整建议

        关注点：
        - WATCH 转 BUY 的阈值
        - 止损/止盈设置是否合理
        - Kelly 仓位系数
        """
        suggestions = []
        review_id = f"advice_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 获取当前配置
        config = self._load_config_for_layer("L4")
        if not config:
            return suggestions

        # WATCH 升级率偏低 → 降低 WATCH 转 BUY 的门槛
        watch_upgrade_rate = effectiveness.get("watch_to_buy_upgrade_rate", 0)
        if watch_upgrade_rate > 0 and watch_upgrade_rate < WATCH_UPGRADE_RATE_THRESHOLD:
            delta = WATCH_UPGRADE_RATE_THRESHOLD - watch_upgrade_rate
            step = 0.02 * (1 + delta)

            current_threshold = config.get("watch_to_buy", {}).get("upgrade_threshold", 0.05)
            new_threshold = max(0.01, current_threshold - step)

            if abs(new_threshold - current_threshold) >= 0.005:
                suggestions.append(ParameterSuggestion(
                    layer="L4",
                    strategy_name="watch_to_buy",
                    parameter_path="watch_to_buy.upgrade_threshold",
                    current_value=current_threshold,
                    suggested_value=round(new_threshold, 3),
                    reason=f"WATCH 升级率 {watch_upgrade_rate:.1%} 偏低 (<{WATCH_UPGRADE_RATE_THRESHOLD:.0%})，建议降低转 BUY 门槛",
                    evidence={"watch_upgrade_rate": watch_upgrade_rate},
                    confidence=min(0.8, 0.4 + delta),
                    review_id=review_id,
                    created_at=datetime.now().isoformat(),
                ))

        # 止损触发过多 → 放宽止损
        stopped_count = sum(1 for p in positions if getattr(p, "status", None) == "stopped")
        executed_count = sum(1 for p in positions if getattr(p, "status", None) == "executed")
        if executed_count > 0 and stopped_count > executed_count * 0.4:
            stop_loss_pct = config.get("stop_loss_pct", -0.08)
            new_stop_loss_pct = min(-0.05, stop_loss_pct + 0.01)  # 放宽至 -5% 以上

            suggestions.append(ParameterSuggestion(
                layer="L4",
                strategy_name="stop_loss",
                parameter_path="stop_loss_pct",
                current_value=stop_loss_pct,
                suggested_value=new_stop_loss_pct,
                reason=f"止损触发 {stopped_count}/{executed_count} ({stopped_count/executed_count:.0%}) 过于频繁，建议放宽止损",
                evidence={"stopped_count": stopped_count, "executed_count": executed_count},
                confidence=0.6,
                review_id=review_id,
                created_at=datetime.now().isoformat(),
            ))

        # 止盈触发过少 → 收紧止盈
        take_profit_count = sum(1 for p in positions if getattr(p, "status", None) == "take_profit")
        if executed_count > 0 and take_profit_count < executed_count * 0.1:
            take_profit_pct = config.get("take_profit_pct", 0.20)
            new_take_profit_pct = max(0.10, take_profit_pct - 0.05)

            suggestions.append(ParameterSuggestion(
                layer="L4",
                strategy_name="take_profit",
                parameter_path="take_profit_pct",
                current_value=take_profit_pct,
                suggested_value=new_take_profit_pct,
                reason=f"止盈触发 {take_profit_count}/{executed_count} 较少，建议收紧止盈",
                evidence={"take_profit_count": take_profit_count, "executed_count": executed_count},
                confidence=0.55,
                review_id=review_id,
                created_at=datetime.now().isoformat(),
            ))

        return suggestions

    # ── 配置读写 ──────────────────────────────────────────────

    def _load_config_for_layer(self, layer: str) -> dict:
        """加载指定层的配置文件"""
        config_map = {
            "L1": "l1_config.json",
            "L2": "l2_config.json",
            "L3": "l3_config.json",
            "L4": "l4_risk_config.json",
        }

        filename = config_map.get(layer)
        if not filename:
            return {}

        path = CONFIG_DIR / filename
        if not path.exists():
            warn("parameter_advisor", f"配置文件不存在: {path}")
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            warn("parameter_advisor", f"配置文件加载失败: {e}")
            return {}

    def _apply_parameter_change(
        self,
        layer: str,
        parameter_path: str,
        new_value: Any
    ) -> bool:
        """
        修改指定层的配置参数

        Args:
            layer: L1 / L2 / L3 / L4
            parameter_path: 参数路径（如 "signals.momentum.thresholds[1]"）
            new_value: 新值

        Returns:
            bool: 是否修改成功
        """
        config_map = {
            "L1": "l1_config.json",
            "L2": "l2_config.json",
            "L3": "l3_config.json",
            "L4": "l4_risk_config.json",
        }

        filename = config_map.get(layer)
        if not filename:
            return False

        path = CONFIG_DIR / filename
        config = self._load_config_for_layer(layer)
        if not config:
            return False

        # 按路径修改
        parts = parameter_path.split(".")
        current = config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        key = parts[-1]
        current[key] = new_value

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            info("parameter_advisor", f"配置已更新: {layer}/{parameter_path} = {new_value}")
            return True
        except Exception as e:
            error("parameter_advisor", f"配置更新失败: {e}")
            return False

    # ── 保存与审批 ────────────────────────────────────────────

    def save_advice_report(self, advice: ParameterAdviceReport) -> str:
        """保存调参建议报告"""
        output_dir = REVIEW_OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"advice_{advice.review_id}.json"

        data = {
            "review_id": advice.review_id,
            "date": advice.date,
            "week_start": advice.week_start,
            "week_end": advice.week_end,
            "suggestions": [asdict(s) for s in advice.suggestions],
            "overall_confidence": advice.overall_confidence,
            "report_type": advice.report_type,
            "markets": advice.markets,
            "approved": advice.approved,
            "approved_by": advice.approved_by,
            "approved_at": advice.approved_at,
            "applied": advice.applied,
            "applied_at": advice.applied_at,
            "created_at": advice.created_at,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        info("parameter_advisor", f"调参建议已保存: {output_path}")
        return str(output_path)

    def get_pending_advice(
        self,
        report_type: Optional[str] = None
    ) -> List[ParameterAdviceReport]:
        """获取待审批的调参建议"""
        pending_dir = REVIEW_OUTPUT_DIR
        if not pending_dir.exists():
            return []

        pending = []
        for path in pending_dir.glob("advice_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if report_type and data.get("report_type") != report_type:
                    continue

                suggestions = [
                    ParameterSuggestion(**s) for s in data.get("suggestions", [])
                ]

                report = ParameterAdviceReport(
                    review_id=data.get("review_id", ""),
                    date=data.get("date", ""),
                    week_start=data.get("week_start"),
                    week_end=data.get("week_end"),
                    suggestions=suggestions,
                    overall_confidence=data.get("overall_confidence", 0.0),
                    report_type=data.get("report_type", "daily"),
                    markets=data.get("markets", []),
                    approved=data.get("approved", False),
                    approved_by=data.get("approved_by"),
                    approved_at=data.get("approved_at"),
                    applied=data.get("applied", False),
                    applied_at=data.get("applied_at"),
                    created_at=data.get("created_at", ""),
                )
                pending.append(report)
            except Exception as e:
                warn("parameter_advisor", f"加载建议文件失败 {path}: {e}")

        return pending

    def approve_advice(self, review_id: str, approved_by: str = "system") -> bool:
        """审批通过调参建议"""
        pending_dir = REVIEW_OUTPUT_DIR
        path = pending_dir / f"advice_{review_id}.json"

        if not path.exists():
            error("parameter_advisor", f"建议文件不存在: {review_id}")
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            data["approved"] = True
            data["approved_by"] = approved_by
            data["approved_at"] = datetime.now().isoformat()

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            info("parameter_advisor", f"建议已审批: {review_id} by {approved_by}")
            return True
        except Exception as e:
            error("parameter_advisor", f"审批失败: {e}")
            return False

    def apply_advice(self, review_id: str) -> bool:
        """将已审批的调参建议应用到实际配置文件"""
        pending_dir = REVIEW_OUTPUT_DIR
        path = pending_dir / f"advice_{review_id}.json"

        if not path.exists():
            error("parameter_advisor", f"建议文件不存在: {review_id}")
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not data.get("approved"):
                error("parameter_advisor", f"建议未审批: {review_id}")
                return False

            if data.get("applied"):
                warn("parameter_advisor", f"建议已应用: {review_id}")
                return False

            success = True
            for suggestion_data in data.get("suggestions", []):
                layer = suggestion_data.get("layer", "")
                param_path = suggestion_data.get("parameter_path", "")
                new_value = suggestion_data.get("suggested_value")

                if layer and param_path and new_value is not None:
                    ok = self._apply_parameter_change(layer, param_path, new_value)
                    if not ok:
                        success = False

            if success:
                data["applied"] = True
                data["applied_at"] = datetime.now().isoformat()
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                info("parameter_advisor", f"建议已应用: {review_id}")
            return success

        except Exception as e:
            error("parameter_advisor", f"应用建议失败: {e}")
            return False


# ─── CLI 自检 ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="L5 Parameter Advisor")
    parser.add_argument("--action", "-a", default="status",
                        choices=["status", "pending", "approve", "apply"],
                        help="执行动作")
    parser.add_argument("--market", "-m", default="CN",
                        choices=["CN", "HK", "US"],
                        help="市场标识")
    parser.add_argument("--review-id", "-r", default=None,
                        help="复盘ID（用于审批/应用）")
    parser.add_argument("--approved-by", "-b", default="system",
                        help="审批人")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    advisor = ParameterAdvisor(market=args.market)

    if args.action == "status":
        print(f"\n[{args.market}] Parameter Advisor 状态:")
        print(f"  待审批建议: {len(advisor.get_pending_advice())} 条")

    elif args.action == "pending":
        pending = advisor.get_pending_advice()
        print(f"\n待审批调参建议 ({len(pending)} 条):")
        for p in pending:
            print(f"  {p.review_id}: {len(p.suggestions)} 条建议,置信度 {p.overall_confidence:.2f}")

    elif args.action == "approve":
        if args.review_id:
            ok = advisor.approve_advice(args.review_id, args.approved_by)
            print(f"\n审批结果: {'成功' if ok else '失败'}")
        else:
            print("\n请指定 --review-id")

    elif args.action == "apply":
        if args.review_id:
            ok = advisor.apply_advice(args.review_id)
            print(f"\n应用结果: {'成功' if ok else '失败'}")
        else:
            print("\n请指定 --review-id")