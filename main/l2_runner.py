#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 Runner — 统一入口

调用现有 L2_data_enrich.core.market_fetcher.fetch_batch()，将结果写入 context.l2_result。
"""
import sys
import os
import time

BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))

from logger import log_start, log_end, info

from main.contracts import PipelineContext, L2Result
from main.contracts.l2 import L2StockData


def run_l2(ctx: PipelineContext) -> PipelineContext:
    """
    L2 数据充实

    入口：ctx.l1_result.stocks[]
    出口：ctx.l2_result = L2Result
    """
    t0 = time.time()
    info("l2_runner", f"开始L2数据充实: {ctx.l1_result.stock_count} 只股票")

    if ctx.l1_result is None or ctx.l1_result.stock_count == 0:
        info("l2_runner", "L1无候选股票，跳过L2")
        ctx.l2_result = L2Result(layer="L2", run_date=ctx.run_date, stock_count=0, stocks=[])
        return ctx

    try:
        # 构建 fetch_batch 入参
        stocks_input = [
            {"code": s.code, "name": s.name}
            for s in ctx.l1_result.stocks
        ]

        # 测试模式限制：从 config 获取 test_limit 限制股票数量
        test_limit = ctx.l2_config.get("test_limit") if ctx.l2_config else None

        # 市场路由：CN 用 fetch_batch，HK/US 用 market_fetcher
        market = ctx.market.value.upper()
        if market == "CN":
            from L2_data_enrich.core.data_fetcher import fetch_batch
            results = fetch_batch(stocks_input, max_stocks=test_limit)
        else:
            from L2_data_enrich.core.market_fetcher import fetch_market_data
            results = []
            for s in stocks_input[:test_limit]:
                data = fetch_market_data(s["code"], market)
                results.append({"code": s["code"], "name": s["name"], "data": data})

        # 转换 dict → L2StockData → L2Result
        l2_stocks = []
        for r in results:
            code = r.get("code", "")
            name = r.get("name", "")
            data = r.get("data", {})

            if data:
                l2_sd = L2StockData.from_dict({"code": code, "name": name, **data})
            else:
                l2_sd = L2StockData(code=code, name=name)

            l2_stocks.append(l2_sd)

        elapsed = time.time() - t0
        ctx.l2_result = L2Result(
            layer="L2",
            run_date=ctx.run_date,
            stock_count=len(l2_stocks),
            stocks=[s.to_dict() for s in l2_stocks],
            duration_s=elapsed,
        )

        info("l2_runner", f"L2数据充实完成: {ctx.l2_result.stock_count} 只股票，耗时{elapsed:.1f}s")
        return ctx

    except Exception as e:
        info("l2_runner", f"L2数据充实异常: {e}")
        ctx.add_error("L2", "", str(e))
        return ctx