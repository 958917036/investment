#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3 Runner — 统一入口

调用现有 L3_quant_analysis/l3_quant_runner.run_quantitative() 和
L3_llm_perspectives/persona_runner.run_persona()，
将结果写入 context.l3_result。
"""
import sys
import os
import time

BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))

from logger import log_start, log_end, info

from main.contracts import PipelineContext, L3Result
from main.contracts.l2 import L2StockData


def run_l3(ctx: PipelineContext, skip_persona: bool = False) -> PipelineContext:
    """
    L3 量化分析（双轨：量化 + 人格）

    入口：ctx.l2_result.stocks[]
    出口：ctx.l3_result = L3Result
    """
    t0 = time.time()
    info("l3_runner", f"开始L3量化分析: {ctx.l2_result.stock_count} 只股票")

    if ctx.l2_result is None or ctx.l2_result.stock_count == 0:
        info("l3_runner", "L2无数据，跳过L3")
        ctx.l3_result = L3Result(layer="L3", run_date=ctx.run_date, stock_count=0, results=[])
        return ctx

    try:
        from main.contracts.l3 import L3StockResult

        results = []
        for stock_dict in ctx.l2_result.stocks:
            code = stock_dict.get("code", "")
            name = stock_dict.get("name", "")
            price = stock_dict.get("technical_data", {}).get("price", 0.0)

            # 量化轨（传入 l3_config）
            from L3_quant_analysis.l3_quant_runner import run_quantitative

            quant_raw = run_quantitative(stock_dict, config=ctx.l3_config)

            # 人格轨（传入 l3_persona_config + model_config）
            persona_raw = {}
            if not skip_persona:
                try:
                    from L3_llm_perspectives.persona_runner import run_persona

                    persona_raw = run_persona(
                        stock_dict,
                        l3_persona_config=ctx.l3_persona_config,
                        model_config=ctx.model_config,
                    )
                except Exception as e:
                    info("l3_runner", f"人格分析异常 {code}: {e}")

            # 构建 L3StockResult
            l3sr = L3StockResult(
                code=code,
                name=name,
                price=price,
                score=quant_raw.get("score", {}),
                debate=quant_raw.get("debate", {}),
                persona=persona_raw if persona_raw else {},
            )
            l3sr._status = quant_raw.get("quality_overall", "ok")
            results.append(l3sr)

        elapsed = time.time() - t0
        ctx.l3_result = L3Result(
            layer="L3",
            run_date=ctx.run_date,
            stock_count=len(results),
            results=results,
            duration_s=elapsed,
        )

        info("l3_runner", f"L3量化分析完成: {ctx.l3_result.stock_count} 只股票，耗时{elapsed:.1f}s")
        return ctx

    except Exception as e:
        info("l3_runner", f"L3量化分析异常: {e}")
        ctx.add_error("L3", "", str(e))
        return ctx