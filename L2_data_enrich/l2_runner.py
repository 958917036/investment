#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2_data_enrich — 单一入口脚本

对外暴露：
    fetch_market_data(code: str, market: str) -> dict

使用示例：
    from L2_data_enrich.l2_runner import fetch_market_data

    # A股
    data = fetch_market_data("600519", "CN")

    # 港股
    data = fetch_market_data("00700", "HK")

    # 美股
    data = fetch_market_data("SMCI", "US")
"""

from L2_data_enrich.core.market_fetcher import fetch_market_data

__all__ = ['fetch_market_data']