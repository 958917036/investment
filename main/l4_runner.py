#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L4 Runner — 统一入口

调用现有 L4_judge/l4_runner.run_risk_judgment()，
将结果写入 context.l4_result。
"""
import sys
import os
import time

BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))

from logger import log_start, log_end, info

from main.contracts import PipelineContext, L4Result
from main.contracts.l4 import L4Decision, Decision as L4DecisionEnum


def run_l4(ctx: PipelineContext) -> PipelineContext:
    """
    L4 风险裁决

    入口：ctx.l3_result.results[] + ctx.l2_result.stocks[]
    出口：ctx.l4_result = L4Result
    """
    t0 = time.time()
    info("l4_runner", f"开始L4风险裁决: {ctx.l3_result.stock_count} 只股票")

    if ctx.l3_result is None or ctx.l3_result.stock_count == 0:
        info("l4_runner", "L3无数据，跳过L4")
        ctx.l4_result = L4Result(layer="L4", run_date=ctx.run_date, stock_count=0, decisions=[])
        return ctx

    try:
        from L4_judge.l4_runner import run_risk_judgment

        decisions = []
        for l3_stock in ctx.l3_result.results:
            code = l3_stock.code
            name = l3_stock.name

            # 构建 L2 data dict（从 ctx.l2_result 查找）
            l2_data = {}
            if ctx.l2_result:
                for s in ctx.l2_result.stocks:
                    if s.get("code") == code:
                        l2_data = s
                        break

            # 构建 L3_quant（score + debate）
            l3_quant = {
                "score": l3_stock.score,
                "debate": l3_stock.debate,
            }

            # 构建 L3_persona
            l3_persona = l3_stock.persona if l3_stock.persona else {}

            # 调用 L4（传入 l4_config + l3_config）
            try:
                l4_raw = run_risk_judgment(
                    l3_quant, l3_persona, l2_data,
                    l4_config=ctx.l4_risk_config,
                    l3_config=ctx.l3_config,
                )
            except Exception as e:
                info("l4_runner", f"L4裁决异常 {code}: {e}")
                ctx.add_error("L4", code, str(e))
                continue

            # 转换 dict → L4Decision
            decision_str = l4_raw.get("decision", "Reject")
            # 兼容旧 Accept/Watch/Reject → 映射到 BUY/WATCH/REJECT
            _map = {"Accept": "BUY", "Watch": "WATCH", "Reject": "REJECT"}
            decision = L4DecisionEnum(_map.get(decision_str, decision_str))

            l4d = L4Decision(
                code=code,
                name=name,
                price=l2_data.get("technical_data", {}).get("price", 0.0),
                judge_score=l4_raw.get("judge_score", 0.0),
                decision=decision,
                verdict=l4_raw.get("decision_label", ""),
                confidence=0.0,
                risk_score=l4_raw.get("risk_score", 50.0),
                kelly_fraction=l4_raw.get("kelly_fraction", 0.0),
                recommended_weight=l4_raw.get("recommended_weight", 0.0),
                volatility=l4_raw.get("volatility", 0.0),
                stop_loss=l4_raw.get("stop_loss_pct", 0.0),
                take_profit=l4_raw.get("take_profit_pct", 0.0),
                _judge_components=l4_raw.get("_judge_components", {}),
                _five_score=0.0,
            )
            decisions.append(l4d)

        elapsed = time.time() - t0
        buy_count = sum(1 for d in decisions if d.decision == L4DecisionEnum.BUY)

        ctx.l4_result = L4Result(
            layer="L4",
            run_date=ctx.run_date,
            stock_count=len(decisions),
            buy_count=buy_count,
            decisions=decisions,
            duration_s=elapsed,
        )

        info("l4_runner", f"L4风险裁决完成: {len(decisions)} 只，BUY={buy_count}，耗时{elapsed:.1f}s")
        return ctx

    except Exception as e:
        info("l4_runner", f"L4风险裁决异常: {e}")
        ctx.add_error("L4", "", str(e))
        return ctx