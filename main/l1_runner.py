#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 Runner — 统一入口

调用现有 L1_screener/l1_runner.run_l1()，将结果写入 context.l1_result。
"""
import sys
import os
import time

BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))

from logger import log_start, log_end, log_fail, info

from main.contracts import PipelineContext, L1Result
from main.contracts.common import Market


def run_l1(ctx: PipelineContext) -> PipelineContext:
    """
    L1 选股

    入口：ctx.l1_config（dict）
    出口：ctx.l1_result = L1Result
    """
    t0 = time.time()
    info("l1_runner", f"开始L1选股 market={ctx.market.value}")

    try:
        # 构建 L1 入参
        input_type = "by_strategy"
        test_limit = ctx.l1_config.get("test_limit")
        params = {
            "strategy": "all",
            "pool": ctx.l1_config.get("pool", "index800"),
            "market": ctx.market.value.lower(),
        }
        if test_limit is not None:
            params["test_limit"] = test_limit

        # _force_mode 支持直接指定查询模式（--symbols 入口）
        # by_code:   code列表 → 按代码精确查
        # by_name:   name 关键字 → 按名称模糊查
        # by_sector: sector 关键字 → 按板块查
        # by_strategy: strategy名称 → 按策略查（breakout/growth_momentum/garp/pullback/quality_value）
        force_mode = ctx.l1_config.get("_force_mode")
        if force_mode:
            input_type = force_mode
            symbols = ctx.l1_config.get("_force_symbols", [])
            if force_mode == "by_code":
                params = {"codes": symbols, "market": ctx.market.value.lower()}
            elif force_mode == "by_name":
                params = {"name": symbols[0] if symbols else "", "market": ctx.market.value.lower()}
            elif force_mode == "by_sector":
                params = {"sector": symbols[0] if symbols else "", "market": ctx.market.value.lower()}
            elif force_mode == "by_strategy":
                params = {"strategy": symbols[0] if symbols else "all",
                          "pool": ctx.l1_config.get("pool", "index800"),
                          "market": ctx.market.value.lower()}
                if test_limit is not None:
                    params["test_limit"] = test_limit
            # 清空 force 参数，避免影响后续层
            ctx.l1_config.pop("_force_mode", None)
            ctx.l1_config.pop("_force_symbols", None)

        # 调用底层 runner（传入 context 中的 config）
        from L1_screener.l1_runner import run_l1 as _run_l1

        raw = _run_l1(input_type, params, config=ctx.l1_config)

        # 转换 dict → L1Result
        stocks = [L1Candidate(**s) for s in raw.get("stocks", [])]

        ctx.l1_result = L1Result(
            layer="L1",
            run_date=raw.get("run_date", ctx.run_date),
            input_type=raw.get("input_type", input_type),
            input_params=raw.get("input_params", params),
            stock_count=raw.get("stock_count", len(stocks)),
            stocks=stocks,
            duration_ms=raw.get("duration_ms", 0.0),
            strategy_counts=raw.get("strategy_counts", {}),
            filtered_by_freeze=raw.get("filtered_by_freeze", 0),
            frozen_stocks=raw.get("frozen_stocks", []),
            total_candidates=raw.get("total_candidates", 0),
        )

        info("l1_runner", f"L1选股完成: {ctx.l1_result.stock_count} 只候选股票")
        return ctx

    except Exception as e:
        log_fail("l1_runner", "L1选股异常", str(e))
        ctx.add_error("L1", "", str(e))
        return ctx


# 内部导入，避免循环依赖
from main.contracts.l1 import L1Candidate