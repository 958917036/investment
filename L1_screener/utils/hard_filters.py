# -*- coding: utf-8 -*-
"""
L1 硬约束过滤器 — 来自 delegate.md 的规范实现

所有策略共享的前置过滤器，在策略评分之前执行。
任何一条触发即排除，不进入策略评分。

硬约束（delegate.md §硬约束）：
1. 资金面否决：主力3日连续净流出，或近20日净流出>10亿
2. 技术面极度负面：均线全部空头排列 + MACD死叉 + RSI<30
3. 市值不足：< 30亿（流动性风险）
4. 基本面亏损：近1年净利润为负
5. ST/*ST：直接排除
6. 冷冻表在期：直接跳过
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("l1.hard_filters")


@dataclass
class HardFilterResult:
    """硬约束过滤结果"""
    passed: bool
    reason: str          # 未通过的原因
    violated_rules: List[str]  # 触发的规则列表


def check_hard_filters(
    stock_code: str,
    stock_name: str,
    moneyflow_data: Optional[dict] = None,
    technical_data: Optional[dict] = None,
    fundamental_data: Optional[dict] = None,
    is_st: bool = False,
    is_frozen: bool = False,
) -> HardFilterResult:
    """
    检查所有硬约束

    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        moneyflow_data: 资金流数据（来自 L2），含 main_net_flow_5d 等
        technical_data: 技术数据，含 ma_status/macd_status/rsi 等
        fundamental_data: 基本数据，含 net_profit_yoy 等
        is_st: 是否 ST/*ST
        is_frozen: 是否在冷冻表中

    Returns:
        HardFilterResult: passed=True 表示通过所有硬约束
    """
    violated = []

    # ── 规则1：ST/*ST ────────────────────────────────────────
    if is_st:
        violated.append("ST/*ST排除")

    # ── 规则6：冷冻表 ────────────────────────────────────────
    if is_frozen:
        violated.append("冷冻表在期，跳过")

    # ── 规则3：市值不足 ─────────────────────────────────────
    if fundamental_data:
        mcap = fundamental_data.get("total_market_cap", 0)  # 单位：元
        if mcap > 0 and mcap < 30_000_000_000:  # 30亿
            violated.append(f"市值不足30亿（实际{mcap/1e8:.1f}亿）")

    # ── 规则4：基本面亏损 ─────────────────────────────────────
    if fundamental_data:
        net_profit_yoy = fundamental_data.get("net_profit_yoy")
        if net_profit_yoy is not None and net_profit_yoy < 0:
            violated.append(f"净利润负增长{net_profit_yoy:.1%}")

    # ── 规则1：资金面否决 ─────────────────────────────────────
    if moneyflow_data:
        main_net_flow_5d = moneyflow_data.get("main_net_flow_5d", 0)  # 亿元
        main_net_flow_20d = moneyflow_data.get("main_net_flow_20d", 0)

        # 主力近20日净流出 > 10亿 → 否决
        if main_net_flow_20d < -10:
            violated.append(f"主力20日净流出{-main_net_flow_20d:.1f}亿>10亿，资金面否定")

        # 主力近5日连续净流出（5日均为负）→ 否决
        daily_flows = moneyflow_data.get("daily_net_flows", [])
        if len(daily_flows) >= 3:
            if all(f < 0 for f in daily_flows[-3:]):
                violated.append("主力3日连续净流出，资金面否定")

    # ── 规则2：技术面极度负面 ─────────────────────────────────
    # 需同时满足：均线全部空头排列 + MACD死叉 + RSI<30
    if technical_data:
        ma_status = technical_data.get("ma_status", "")
        macd_status = technical_data.get("macd_status", "")
        rsi = technical_data.get("rsi", 50)

        technical_violations = []
        if ma_status == "bearish":
            technical_violations.append("均线空头排列")
        if macd_status == "death":
            technical_violations.append("MACD死叉")
        if rsi < 30:
            technical_violations.append(f"RSI={rsi:.1f}<30")

        if len(technical_violations) >= 2:
            violated.append(f"技术面极度负面：{'+'.join(technical_violations)}")

    if violated:
        reason = "; ".join(violated)
        logger.debug(f"[L1 HardFilter] {stock_code} 硬约束未通过: {reason}")
        return HardFilterResult(passed=False, reason=reason, violated_rules=violated)

    return HardFilterResult(passed=True, reason="", violated_rules=[])


def apply_hard_filters_to_candidates(
    candidates: List[dict],
    moneyflow_map: Dict[str, dict],
    technical_map: Dict[str, dict],
    fundamental_map: Dict[str, dict],
    frozen_codes: set,
) -> Tuple[List[dict], List[dict]]:
    """
    对候选列表批量应用硬约束过滤。

    Args:
        candidates: 候选股票列表，每项含 code/name
        moneyflow_map: {code: moneyflow_data}
        technical_map: {code: technical_data}
        fundamental_map: {code: fundamental_data}
        frozen_codes: 冷冻股票代码集合

    Returns:
        (passed_list, rejected_list)
    """
    passed = []
    rejected = []

    for cand in candidates:
        code = cand.get("code", "")
        name = cand.get("name", "")

        result = check_hard_filters(
            stock_code=code,
            stock_name=name,
            moneyflow_data=moneyflow_map.get(code),
            technical_data=technical_map.get(code),
            fundamental_data=fundamental_map.get(code),
            is_frozen=code in frozen_codes,
        )

        if result.passed:
            passed.append(cand)
        else:
            cand["reject_reason"] = result.reason
            cand["violated_rules"] = result.violated_rules
            rejected.append(cand)

    logger.info(f"[L1 HardFilter] 硬约束过滤: {len(passed)}/{len(candidates)} 通过, "
                f"{len(rejected)} 排除")
    return passed, rejected
