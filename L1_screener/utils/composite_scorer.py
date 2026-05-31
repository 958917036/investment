# -*- coding: utf-8 -*-
"""
L1 综合评分器 — 来自 delegate.md 的规范实现

合并多策略候选池，去重后按综合得分排序。
delegate.md §汇总逻辑：
    Step 1: 各策略独立筛选，得分归一化到[-1, +1]
    Step 2: 去重（同一股票多策略推荐，只保留一次）
    Step 3: 综合得分 = 各策略得分等权平均
    Step 4: 硬约束过滤（已由 hard_filters.py 处理）
    Step 5: 按综合得分降序，输出前N只
    Step 6: 写入执行记录（供L5读取更新冷冻表）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger("l1.composite")


@dataclass
class ScoredCandidate:
    """综合评分后的候选股票"""
    code: str
    name: str
    composite_score: float       # 综合得分 [0, 1]
    strategy_scores: Dict[str, float]  # 各策略原始得分
    primary_strategy: str        # 得分最高的策略
    violations: List[str] = None  # 硬约束违反（已过滤的不在此）
    watch_conditions: List[str] = None  # 观察条件


def normalize_score(raw: float, min_val: float, max_val: float) -> float:
    """将原始得分归一化到 [0, 1]"""
    if max_val <= min_val:
        return 0.5
    return (raw - min_val) / (max_val - min_val)


def merge_and_score(
    strategy_results: Dict[str, List[dict]],
    top_n: int = 30,
) -> List[ScoredCandidate]:
    """
    合并多策略结果，进行综合评分。

    Args:
        strategy_results: {
            "quality_value": [{code, name, signal, ...}, ...],
            "growth_momentum": [...],
            "garp": [...],
            "breakout": [...],
            "pullback": [...],
        }
        top_n: 返回前 N 只

    Returns:
        List[ScoredCandidate]，按 composite_score 降序
    """
    # ── Step 1 & 2: 收集 + 去重 ──────────────────────────────
    code_to_name: Dict[str, str] = {}
    code_to_scores: Dict[str, Dict[str, float]] = {}

    for strategy, candidates in strategy_results.items():
        for cand in candidates:
            code = cand.get("code") or cand.get("symbol", "")
            name = cand.get("name", code)
            signal = cand.get("signal", 0.0)

            if not code:
                continue

            code_to_name[code] = name
            if code not in code_to_scores:
                code_to_scores[code] = {}
            code_to_scores[code][strategy] = signal

    # ── Step 3: 计算综合得分（等权平均） ──────────────────────
    scored = []
    for code, scores in code_to_scores.items():
        if not scores:
            continue

        avg = sum(scores.values()) / len(scores)
        primary = max(scores, key=scores.get)

        scored.append(ScoredCandidate(
            code=code,
            name=code_to_name[code],
            composite_score=round(avg, 4),
            strategy_scores={k: round(v, 4) for k, v in scores.items()},
            primary_strategy=primary,
        ))

    # ── Step 5: 降序排列 ───────────────────────────────────
    scored.sort(key=lambda x: x.composite_score, reverse=True)

    result = scored[:top_n]

    logger.info(f"[L1 Composite] 合并{len(strategy_results)}个策略，"
                f"{len(code_to_scores)}只去重，综合评分后返回前{top_n}只")
    for i, c in enumerate(result[:5]):
        logger.debug(f"  #{i+1} {c.code} {c.name} score={c.composite_score:.3f} "
                     f"({c.primary_strategy})")

    return result


def build_composite_output(
    scored: List[ScoredCandidate],
    market: str = "CN",
    date: str = "",
) -> dict:
    """
    将 ScoredCandidate 列表构建为统一输出格式（delegate.md §输出格式）

    Returns:
        dict，匹配 delegate.md 定义的 L1 输出结构
    """
    candidates = []
    for c in scored:
        candidates.append({
            "symbol": f"{c.code}.SH" if c.code.startswith("6") else f"{c.code}.SZ",
            "name": c.name,
            "composite_signal": c.composite_score,
            "graham_signal": c.strategy_scores.get("quality_value", 0),
            "buffett_signal": c.strategy_scores.get("quality_value", 0),
            "lynch_signal": c.strategy_scores.get("growth_momentum", 0),
            "momentum_signal": c.strategy_scores.get("breakout", 0),
            "mean_reversion_signal": c.strategy_scores.get("pullback", 0),
            "status": "CANDIDATE",
            "primary_strategy": c.primary_strategy,
            "violations": c.violations or [],
            "watch_conditions": c.watch_conditions or [],
            "from_freeze_table": False,
        })

    return {
        "layer": "L1",
        "date": date,
        "total_candidates": len(scored),
        "strategies_used": list({s for c in scored for s in c.strategy_scores}),
        "candidates": candidates,
        "freeze_summary": {
            "skipped_frozen": 0,
            "observing_priority": 0,
            "buy_signals": 0,
        },
        "recommendation": "proceed_to_l2",
    }
