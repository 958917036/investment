#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L4 风险裁决层入口

run_risk_judgment(L3_quant, L3_persona, L2_data) -> dict
"""

import logging
import time
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional, List

from L4_judge.risk.risk_manager import RiskManager

logger = logging.getLogger("l4_runner")

# 决策标签映射
DECISION_LABELS = {
    "BUY": "建议买入",
    "WATCH": "谨慎观望",
    "REJECT": "不建议买入",
}

# 风险因子候选
RISK_FACTOR_TEMPLATES = {
    "high_pe": "PE偏高",
    "low_pe": "PE偏低",
    "high_rsi": "RSI偏高压70",
    "low_rsi": "RSI偏低压30",
    "bearish_ma": "均线空头排列",
    "bullish_ma": "均线多头排列",
    "death_cross": "MACD死叉",
    "golden_cross": "MACD金叉",
    "high_volatility": "波动率偏高",
    "low_volume": "成交量萎缩",
    "main_outflow": "主力资金流出",
    "sector_weak": "板块走势偏弱",
    "negative_event": "负面事件",
    "earnings_decline": "盈利下滑",
}


def _compute_judge_score(
    L3_quant: dict,
    L3_persona: dict,
    l4_weights: dict,
) -> dict:
    """
    计算 judge_score 及各组件

    judge_score = veto_score × 0.50 + debate_score × 0.25 + persona_score × 0.25
    """
    # 权重
    veto_w = l4_weights.get("veto_weight", 0.50)
    debate_w = l4_weights.get("debate_weight", 0.25)
    persona_w = l4_weights.get("persona_weight", 0.25)
    verdict_map = l4_weights.get("verdict_map", {
        "看多": 1.0,
        "谨慎看多": 0.6,
        "中性观望": 0.3,
        "谨慎看空": 0.1,
        "看空": 0.0,
    })
    thresholds = l4_weights.get("decision_thresholds", {
        "accept_min": 0.55,
        "watch_min": 0.35,
    })

    # 1. veto_score = five_score / 100.0
    score_data = L3_quant.get("score", {})
    five_score = score_data.get("five_score", 50)
    veto_score = five_score / 100.0

    # 2. debate_score = verdict映射 * (0.5 + 0.5 * confidence)
    debate_data = L3_quant.get("debate", {})
    verdict = debate_data.get("final_verdict", "中性观望")
    confidence = debate_data.get("confidence", 0.5)
    base_verdict = verdict_map.get(verdict, 0.3)
    confidence_adj = max(0.0, min(1.0, confidence))
    debate_score = round(base_verdict * (0.5 + 0.5 * confidence_adj), 3)

    # 3. persona_score = BUY票数 / 总大师数
    persona_status = L3_persona.get("_status", "") if isinstance(L3_persona, dict) else ""
    if persona_status in ("ok", "completed") and L3_persona.get("summary"):
        p_summary = L3_persona["summary"]
        total_agents = p_summary.get("agents_total", 12)
        buy_count = p_summary.get("buy_count", 0)
        persona_score = buy_count / total_agents if total_agents > 0 else 0.0
    else:
        persona_score = 0.0

    # 综合 judge_score
    judge_score = veto_score * veto_w + debate_score * debate_w + persona_score * persona_w

    # decision
    accept_min = thresholds.get("accept_min", 0.55)
    watch_min = thresholds.get("watch_min", 0.35)
    if judge_score >= accept_min:
        decision = "BUY"
    elif judge_score >= watch_min:
        decision = "WATCH"
    else:
        decision = "REJECT"

    return {
        "judge_score": round(judge_score, 3),
        "veto_score": veto_score,
        "debate_score": debate_score,
        "persona_score": persona_score,
        "veto_weight": veto_w,
        "debate_weight": debate_w,
        "persona_weight": persona_w,
        "decision": decision,
        "decision_label": DECISION_LABELS.get(decision, decision),
    }


def _extract_price(L2_data: dict) -> float:
    """从 L2_data 提取 price"""
    # 优先从 technical_data.price
    price = L2_data.get("technical_data", {}).get("price", None)
    if price is not None:
        return float(price)

    # fallback 到 moneyflow_data（如有）
    price = L2_data.get("moneyflow_data", {}).get("price", None)
    if price is not None:
        return float(price)

    # 最保底
    return 50.0


def _build_risk_factors(L3_quant: dict, L3_persona: dict, risk_assess) -> List[str]:
    """提取风险因子列表"""
    factors = []

    # 从五维评分提取风险维度
    score_data = L3_quant.get("score", {})
    scores = score_data.get("scores", {})

    # fundamental 维度
    fundamental = scores.get("fundamental", {})
    if isinstance(fundamental, dict):
        fund_score = fundamental.get("score", 50)
        if fund_score < 40:
            factors.append("PE偏高" if fund_score < 30 else "基本面偏弱")

    # technical 维度
    technical = scores.get("technical", {})
    if isinstance(technical, dict):
        tech_score = technical.get("score", 50)
        if tech_score < 40:
            factors.append("技术面偏弱")

    # 从 technical_data 提取 RSI
    rsi = L3_quant.get("technical_data", {}).get("rsi", None)
    if rsi is not None:
        if rsi > 70:
            factors.append("RSI偏高压70")
        elif rsi < 30:
            factors.append("RSI偏低压30")

    # 从 debate 提取辩论负面论点
    debate_data = L3_quant.get("debate", {})
    bear_args = debate_data.get("bear_arguments", [])
    if len(bear_args) >= 2:
        factors.append("负面论点过多")

    # 波动率过高
    if hasattr(risk_assess, "volatility") and risk_assess.volatility > 0.40:
        factors.append("波动率偏高")

    # 流动性预警
    if hasattr(risk_assess, "liquidity_alert"):
        if risk_assess.liquidity_alert == "red":
            factors.append("流动性风险")
        elif risk_assess.liquidity_alert == "yellow":
            factors.append("流动性预警")

    return factors[:5]  # 最多5个


def _determine_quality(L3_quant: dict, L3_persona: dict) -> str:
    """综合质量传播"""
    # 空字典视为质量失败
    if not L3_quant or not isinstance(L3_quant, dict) or "score" not in L3_quant:
        return "fail"
    if not L3_persona or not isinstance(L3_persona, dict):
        return "fail"

    q_quant = L3_quant.get("quality_overall", "ok")
    q_persona = L3_persona.get("quality_overall", "ok")

    if q_quant == "fail" or q_persona == "fail":
        return "fail"
    elif q_quant == "degraded" or q_persona == "degraded":
        return "degraded"
    return "ok"


def _validate_inputs(L3_quant: dict, L3_persona: dict, L2_data: dict) -> List[str]:
    """
    检查输入数据是否缺失关键字段。

    Returns:
        List of missing field descriptions. Empty list = 数据完整.
    """
    missing = []

    # L3_quant 关键字段
    if not L3_quant or not isinstance(L3_quant, dict):
        missing.append("L3_quant is empty")
        return missing

    score_data = L3_quant.get("score", {})
    if not score_data:
        missing.append("L3_quant.score is empty")
    else:
        if "five_score" not in score_data:
            missing.append("L3_quant.score.five_score missing")

    debate_data = L3_quant.get("debate", {})
    if not debate_data:
        missing.append("L3_quant.debate is empty")
    else:
        if "final_verdict" not in debate_data:
            missing.append("L3_quant.debate.final_verdict missing")

    # L3_persona 关键字段
    if not L3_persona or not isinstance(L3_persona, dict):
        missing.append("L3_persona is empty")
    elif L3_persona.get("_status") in ("ok", "completed"):
        if "summary" not in L3_persona:
            missing.append("L3_persona.summary missing")
        elif not L3_persona["summary"].get("agents_total"):
            missing.append("L3_persona.summary.agents_total missing")
    else:
        missing.append(f"L3_persona._status={L3_persona.get('_status')} (not ok/completed)")

    # L2_data 关键字段
    if not L2_data or not isinstance(L2_data, dict):
        missing.append("L2_data is empty")
    else:
        price = L2_data.get("technical_data", {}).get("price") or \
                L2_data.get("moneyflow_data", {}).get("price")
        if price is None:
            missing.append("L2_data price missing")

    return missing


class _ScoreWrapper:
    """适配 RiskManager 所需的 score_result 对象"""
    def __init__(self, score_data: dict):
        self.five_score = score_data.get("five_score", 50)
        self.grade = score_data.get("grade", "C")
        self.scores = score_data


def run_risk_judgment(
    L3_quant: dict,
    L3_persona: dict,
    L2_data: dict,
    l4_config: dict = None,
    l3_config: dict = None,
) -> dict:
    """
    L4 风险裁决入口

    入参:
        L3_quant: L3 量化结果 (L3_quantitative_output)
        L3_persona: L3 人格结果 (L3_persona_output)
        L2_data: L2 数据（用于获取 price）
        l4_config: 可选，从 PipelineContext.l4_risk_config 传入；若为 None 则自行加载
        l3_config: 可选，从 PipelineContext.l3_config 传入；若为 None 则自行加载

    出参:
        {
            "layer": "L4",
            "code": "600519",
            "run_date": "2026-05-30",

            "judge_score": 0.68,
            "decision": "BUY",       # BUY | WATCH | REJECT
            "decision_label": "建议买入",

            "risk_score": 35,
            "risk_level": "normal",      # normal | warning | high
            "volatility": 0.25,
            "kelly_fraction": 0.18,
            "recommended_weight": 0.15,
            "stop_loss_pct": -0.08,
            "take_profit_pct": 0.20,
            "risk_factors": ["PE偏高", "RSI偏高压70"],

            "quality_overall": "ok",
            "duration_ms": 150
        }
    """
    start = time.time()

    code = L3_quant.get("code", L2_data.get("code", "UNKNOWN"))
    run_date = datetime.now().strftime("%Y-%m-%d")

    # 数据完整性检查
    missing_fields = _validate_inputs(L3_quant, L3_persona, L2_data)
    if missing_fields:
        logger.warning(f"[L4] {code}: missing input fields: {missing_fields}")

    # 加载权重配置（必须从 PipelineContext 传入，不接受 fallback）
    if l4_config is None:
        raise ValueError("run_risk_judgment() 必须传入 l4_config 参数（从 PipelineContext.l4_risk_config 获取）")
    l4_weights = l4_config
    if l3_config is None:
        raise ValueError("run_risk_judgment() 必须传入 l3_config 参数（从 PipelineContext.l3_config 获取）")
    l3_cfg = l3_config

    # 计算 judge_score
    j = _compute_judge_score(L3_quant, L3_persona, l4_weights)
    judge_score = j["judge_score"]
    decision = j["decision"]
    decision_label = j["decision_label"]

    # 获取 price
    price = _extract_price(L2_data)

    # RiskManager 评估
    score_data = L3_quant.get("score", {})
    rm = RiskManager()
    risk_assess = rm.assess_stock_risk(
        stock_code=code,
        stock_name=L3_quant.get("name", L2_data.get("name", "")),
        current_price=price,
        score_result=_ScoreWrapper(score_data),
    )

    # risk_score（RiskManager 返回 0-100，越高越危险）
    risk_score = int(risk_assess.risk_score)

    # risk_level 映射
    if risk_assess.alert_level == "danger" or risk_score > 70:
        risk_level = "high"
    elif risk_assess.alert_level == "warning" or risk_score > 40:
        risk_level = "warning"
    else:
        risk_level = "normal"

    # 提取风险因子
    risk_factors = _build_risk_factors(L3_quant, L3_persona, risk_assess)

    # 计算百分比
    stop_loss_pct = -0.08  # 默认
    take_profit_pct = 0.20  # 默认
    if risk_assess.stop_loss_price > 0 and price > 0:
        stop_loss_pct = round((risk_assess.stop_loss_price - price) / price, 4)
    if risk_assess.take_profit_price > 0 and price > 0:
        take_profit_pct = round((risk_assess.take_profit_price - price) / price, 4)

    # 质量传播
    quality_overall = _determine_quality(L3_quant, L3_persona)

    # 数据缺失 → 强制 REJECT，永不给出买入信号
    has_missing = bool(missing_fields)
    if has_missing or quality_overall == "fail":
        judge_score = 0.0
        decision = "REJECT"
        decision_label = DECISION_LABELS["REJECT"]
    elif quality_overall == "degraded":
        judge_score = round(judge_score * 0.9, 3)
        # 重新计算 decision
        thresholds = l4_weights.get("decision_thresholds", {})
        accept_min = thresholds.get("accept_min", 0.55)
        watch_min = thresholds.get("watch_min", 0.35)
        if judge_score >= accept_min:
            decision = "BUY"
        elif judge_score >= watch_min:
            decision = "WATCH"
        else:
            decision = "REJECT"
        decision_label = DECISION_LABELS.get(decision, decision)

    duration_ms = int((time.time() - start) * 1000)

    result = {
        "layer": "L4",
        "code": code,
        "run_date": run_date,

        "judge_score": judge_score,
        "decision": decision,
        "decision_label": decision_label,

        "risk_score": risk_score,
        "risk_level": risk_level,
        "volatility": round(risk_assess.volatility, 4),
        "kelly_fraction": round(risk_assess.kelly_fraction, 4),
        "recommended_weight": round(risk_assess.recommended_weight, 4),
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "risk_factors": risk_factors,

        "quality_overall": quality_overall,
        "duration_ms": duration_ms,
        "missing_fields": missing_fields,

        # 调试用：保留组件详情
        "_judge_components": {
            "veto_score": j["veto_score"],
            "debate_score": j["debate_score"],
            "persona_score": j["persona_score"],
            "veto_weight": j["veto_weight"],
            "debate_weight": j["debate_weight"],
            "persona_weight": j["persona_weight"],
        },
    }

    logger.info(
        f"[L4] {code}: judge={judge_score:.3f}(veto={j['veto_score']:.3f}×{j['veto_weight']} "
        f"+ debate={j['debate_score']:.3f}×{j['debate_weight']} "
        f"+ persona={j['persona_score']:.3f}×{j['persona_weight']}) "
        f"→ {decision}, risk={risk_score}({risk_level})"
    )

    return result


def _mock_l3_quant(code: str = "600519") -> dict:
    """模拟 L3_quant 输出"""
    return {
        "layer": "L3_quantitative",
        "code": code,
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "score": {
            "five_score": 72,
            "grade": "B",
            "scores": {
                "moneyflow": {"score": 80, "weight": 0.35, "weighted_score": 28.0},
                "technical": {"score": 75, "weight": 0.35, "weighted_score": 26.25},
                "fundamental": {"score": 65, "weight": 0.10, "weighted_score": 6.5},
                "sector": {"score": 70, "weight": 0.10, "weighted_score": 7.0},
                "event": {"score": 55, "weight": 0.10, "weighted_score": 5.5},
            },
        },
        "debate": {
            "bull_arguments": ["业绩稳定增长", "行业龙头地位稳固"],
            "bear_arguments": ["估值偏高", "RSI进入超买区间"],
            "final_verdict": "谨慎看多",
            "confidence": 0.65,
        },
        "technical_data": {"rsi": 72},
        "quality_overall": "ok",
        "duration_ms": 850,
    }


def _mock_l3_persona(code: str = "600519") -> dict:
    """模拟 L3_persona 输出"""
    return {
        "layer": "L3_persona",
        "code": code,
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "perspectives": {
            "buffett": {"score": 0.7, "verdict": "买入", "rationale": "长期价值投资"},
            "lynch": {"score": 0.8, "verdict": "买入", "rationale": "增长型投资"},
            "druckenmiller": {"score": 0.65, "verdict": "谨慎看多", "rationale": "短期波动加大"},
        },
        "summary": {
            "buy_count": 2,
            "watch_count": 1,
            "reject_count": 0,
            "agents_total": 3,
            "avg_score": 0.72,
        },
        "_status": "ok",
        "quality_overall": "ok",
        "duration_ms": 2100,
    }


def _mock_l2_data(code: str = "600519") -> dict:
    """模拟 L2_data 输出"""
    return {
        "layer": "L2",
        "code": code,
        "market": "CN",
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "technical_data": {"price": 1850.0, "rsi": 72},
        "moneyflow_data": {"main_net_flow_5d": 123456789},
        "duration_ms": 1200,
    }


def check_portfolio_triggers(
    code: str,
    L4_data: dict,
    current_price: float,
    position: dict,
    freeze_status: str = "normal",
) -> dict:
    """
    L4 持仓触发检查入口（原 L5 功能整合）

    入参:
        code: 股票代码
        L4_data: L4 裁决结果（含 stop_loss_pct, take_profit_pct, trend_direction）
        current_price: 当前价格
        position: 持仓信息 {"shares": 100, "avg_cost": 1750.0}
        freeze_status: 冷冻状态（默认 "normal"）

    出参:
        {
            "action": "HOLD" | "STOP_LOSS" | "SELL" | "ADD",
            "action_reason": str,
            "freeze_status": str,
            "price_change_pct": float,
            "duration_ms": int
        }
    """
    import time
    start = time.time()

    rm = RiskManager()
    result = rm.check_position_triggers(
        stock_code=code,
        current_price=current_price,
        avg_cost=position.get("avg_cost", 0.0),
        shares=position.get("shares", 0),
        stop_loss_pct=L4_data.get("stop_loss_pct", -0.08),
        take_profit_pct=L4_data.get("take_profit_pct", 0.20),
        trend_direction=L4_data.get("trend_direction"),
        freeze_status=freeze_status,
    )

    result["layer"] = "L4"
    result["code"] = code
    result["run_date"] = datetime.now().strftime("%Y-%m-%d")
    result["duration_ms"] = int((time.time() - start) * 1000)

    return result


def test_run_risk_judgment():
    """测试 run_risk_judgment"""
    l3_quant = _mock_l3_quant()
    l3_persona = _mock_l3_persona()
    l2_data = _mock_l2_data()

    result = run_risk_judgment(l3_quant, l3_persona, l2_data)

    print("=" * 60)
    print("L4 风险裁决测试结果")
    print("=" * 60)
    for k, v in result.items():
        if k != "_judge_components":
            print(f"  {k}: {v}")
    print("\n  _judge_components:")
    for k, v in result["_judge_components"].items():
        print(f"    {k}: {v}")
    print("\n测试通过!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_run_risk_judgment()