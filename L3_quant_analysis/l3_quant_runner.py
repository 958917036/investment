#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3 量化分析层入口 — v4.0 统一接口

入口函数: run_quantitative(L2_data: dict) -> dict

设计原则：
1. 单一入口：L3 量化分析只通过此脚本提供
2. 层间解耦：输入 L2 输出，输出量化结果（score + debate + quality）
3. 失败可识别：L2 中赋值为 "失败" 的字段，该维度得 0 分，failed_dimensions 记录
4. 不调用 L4/L5：只做量化分析，不做风险裁决

输出结构：
{
    "layer": "L3_quantitative",
    "code": "600519",
    "run_date": "2026-05-30",
    "score": {...},
    "debate": {...},
    "quality_overall": "ok" | "degraded" | "fail",
    "failed_dimensions": [],
    "duration_ms": 850
}
"""

import json
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("l3_quant_runner")

# ======================== 入口函数 ========================

def run_quantitative(L2_data: dict, config: dict = None) -> dict:
    """
    L3 量化分析入口 — 五维评分 + 多空辩论

    入参:
        L2_data: L2 输出（整个 dict）
        config: 可选，从 PipelineContext.l3_config 传入；若为 None 则自行加载

    出参: {score, debate, quality_overall, failed_dimensions}

    L2 数据质量处理：
    - 如果某维度数据块 quality == "fail"，该维度得 0 分
    - 如果某字段值为字符串 "失败"，该子维度得 0 分
    - quality_overall = 最差的维度质量（ok / degraded / fail）
    - failed_dimensions = 失败的维度列表（用于下游 L4/L5 判断置信度）
    """
    start_time = time.time()
    run_date = datetime.now().strftime("%Y-%m-%d")

    code = L2_data.get("code", "")
    name = L2_data.get("name", code)

    # ── 1. 配置（必须从 PipelineContext 传入，不接受 fallback）───
    if config is None:
        raise ValueError("run_quantitative() 必须传入 config 参数（从 PipelineContext.l3_config 获取）")
    l3_cfg = config
    five_dim_weights = l3_cfg.get("five_dimension_weights", None)

    # ── 2. 五维评分 ─────────────────────────────────────────────
    scorer = _get_scorer(weights=five_dim_weights)
    data = _extract_data_for_scorer(L2_data)

    # 检测哪些维度有失败字段
    failed_dims, data_with_quality = _detect_failed_dimensions(L2_data, data)

    # 评分（识别失败字段，得 0 分）
    score_result = scorer.score_stock(code, name, data_with_quality)

    # ── 3. 多空辩论 ─────────────────────────────────────────────
    debate_max_rounds = l3_cfg.get("debate", {}).get("max_rounds", 1)
    debater = _get_debate_engine(max_rounds=debate_max_rounds)

    # 辩论（无论分数高低都跑辩论，gate 在 L4 层处理）
    debate_result = debater.debate(
        code, name,
        score_result=score_result,
        raw_data=L2_data
    )

    # ── 4. 质量传播 ─────────────────────────────────────────────
    quality_overall = _compute_quality_overall(L2_data, failed_dims)

    # ── 5. 组装输出 ─────────────────────────────────────────────
    result = {
        "layer": "L3_quantitative",
        "code": code,
        "run_date": run_date,
        "score": _serialize_score(score_result),
        "debate": _serialize_debate(debate_result),
        "quality_overall": quality_overall,
        "failed_dimensions": failed_dims,
        "duration_ms": round((time.time() - start_time) * 1000, 1),
    }

    logger.info(
        f"L3量化: {name}({code}) | 五维={score_result.five_score:.1f}({score_result.grade}) "
        f"| 辩论={debate_result.final_verdict} | quality={quality_overall} "
        f"| failed={failed_dims} | {result['duration_ms']}ms"
    )

    return result


# ======================== 内部实现 ========================

_scorer_instance = None

def _get_scorer(weights=None):
    """获取五维评分器单例"""
    global _scorer_instance
    if _scorer_instance is None:
        from L3_quant_analysis.scoring.five_dimension_scorer import FiveDimensionScorer
        _scorer_instance = FiveDimensionScorer(weights=weights)
    return _scorer_instance


_debate_instance = None

def _get_debate_engine(max_rounds: int = 1):
    """获取辩论引擎单例"""
    global _debate_instance
    if _debate_instance is None or _debate_instance.max_rounds != max_rounds:
        from L3_quant_analysis.debate.debate_engine import DebateEngine
        _debate_instance = DebateEngine(max_rounds=max_rounds)
    return _debate_instance


def _extract_data_for_scorer(L2_data: dict) -> dict:
    """
    从 L2 数据中提取五维评分所需的数据结构

    兼容 L2 输出的新旧两种格式：
    - 新格式：moneyflow_data / technical_data / fundamental_data / sector_data / event_data
    - 旧格式：raw_data 内嵌结构
    """
    return {
        "moneyflow_data": L2_data.get("moneyflow_data", {}),
        "technical_data": L2_data.get("technical_data", L2_data),
        "fundamental_data": L2_data.get("fundamental_data", L2_data),
        "sector_data": L2_data.get("sector_data", {}),
        "event_data": L2_data.get("event_data", {}),
    }


def _detect_failed_dimensions(L2_data: dict, data: dict) -> tuple:
    """
    检测 L2 数据中哪些维度存在 "失败" 字段

    Returns:
        (failed_dimensions: list, data_with_quality: dict)
        failed_dimensions: ["fundamental", ...]
        data_with_quality: 原始 data 副本（不修改输入）
    """
    failed_dims = []

    # 检查各维度数据块的 quality 字段
    dimension_map = [
        ("moneyflow_data", "moneyflow"),
        ("technical_data", "technical"),
        ("fundamental_data", "fundamental"),
        ("sector_data", "sector"),
        ("event_data", "event"),
    ]

    import copy
    data_copy = copy.deepcopy(data)

    for data_key, dim_name in dimension_map:
        dim_data = L2_data.get(data_key, {})

        # 数据块整体 quality="fail" → 该维度失败
        if dim_data.get("quality") == "fail":
            if dim_name not in failed_dims:
                failed_dims.append(dim_name)
            # 标记该维度数据为失败
            data_copy[data_key] = {**_mark_all_as_fail(dim_data)}

        # 逐字段检查 "失败" 字符串
        _fail_fields = []
        for k, v in dim_data.items():
            if v == "失败":
                _fail_fields.append(k)

        if _fail_fields:
            if dim_name not in failed_dims:
                failed_dims.append(dim_name)
            logger.debug(f"维度 {dim_name} 存在失败字段: {_fail_fields}")

    # 检查 missing_fields：字段实质缺失 → 该维度降级
    for data_key, dim_name in dimension_map:
        dim_data = L2_data.get(data_key, {})
        missing = dim_data.get("missing_fields", [])
        if isinstance(missing, list) and missing:
            if dim_name not in failed_dims:
                failed_dims.append(dim_name)
            logger.debug(f"维度 {dim_name} 存在缺失字段: {missing}")

        # 数据块完全为空（除了可能存在的 quality/missing_fields，无实际数据字段）→ 该维度实质缺失
        real_keys = [k for k in dim_data.keys() if k not in ("quality", "missing_fields", "_source")]
        if not real_keys:
            if dim_name not in failed_dims:
                failed_dims.append(dim_name)
            logger.debug(f"维度 {dim_name} 数据块为空，无实际字段")

    return failed_dims, data_copy


def _mark_all_as_fail(dim_data: dict) -> dict:
    """将维度数据中非元数据字段全部标记为失败"""
    result = {}
    for k, v in dim_data.items():
        if k.startswith("_") or k in ("quality", "source", "missing_fields"):
            result[k] = v
        else:
            result[k] = "失败"
    return result


def _compute_quality_overall(L2_data: dict, failed_dims: list) -> str:
    """
    计算综合质量等级

    规则：
    - 任意维度 quality="fail" → "fail"
    - 任意维度有 "失败" 字段 → "degraded"
    - 任意维度 missing_fields 非空 → "degraded"（字段实质缺失）
    - 全部正常 → "ok"

    优先级：fail > degraded > ok
    """
    # 检查整体 quality 字段
    for data_key in ["moneyflow_data", "technical_data", "fundamental_data",
                     "sector_data", "event_data"]:
        dim_data = L2_data.get(data_key, {})
        if dim_data.get("quality") == "fail":
            return "fail"

    # 有失败字段 → degraded
    if failed_dims:
        return "degraded"

    # 检查 missing_fields：字段实质缺失 → degraded
    for data_key in ["moneyflow_data", "technical_data", "fundamental_data",
                     "sector_data", "event_data"]:
        dim_data = L2_data.get(data_key, {})
        missing = dim_data.get("missing_fields", [])
        if isinstance(missing, list) and missing:
            return "degraded"

    return "ok"


def _serialize_score(score_result) -> dict:
    """将 StockScoreResult 序列化为可 JSON 化的 dict"""
    if score_result is None:
        return {}
    if hasattr(score_result, "to_dict"):
        d = score_result.to_dict()
    else:
        d = dict(score_result)

    # 移除不可序列化的对象
    for k, v in list(d.get("scores", {}).items()):
        if hasattr(v, "to_dict"):
            d["scores"][k] = v.to_dict()

    return d


def _serialize_debate(debate_result) -> dict:
    """将 DebateResult 序列化为可 JSON 化的 dict"""
    if debate_result is None:
        return {}
    if hasattr(debate_result, "to_dict"):
        d = debate_result.to_dict()
    else:
        d = dict(debate_result)

    # 提取顶层的 bull/bear arguments + final_verdict + confidence
    # 用于 v4 接口规范输出
    return {
        "bull_arguments": d.get("key_opportunities", []),
        "bear_arguments": d.get("key_risks", []),
        "final_verdict": d.get("final_verdict", "中性观望"),
        "confidence": d.get("confidence", 0.5),
        # 保留完整结构供调试
        "_raw": d,
    }