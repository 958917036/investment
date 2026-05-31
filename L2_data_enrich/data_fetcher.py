#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 Data Fetcher — 统一导出层

shennong.py 等外部调用方使用:
    from L2_data_enrich.data_fetcher import fetch_batch, fetch_all, fetch_one_stock

实际实现在 core/data_fetcher.py。
"""
from L2_data_enrich.core.data_fetcher import fetch_batch, fetch_all, fetch_one_stock

__all__ = ["fetch_batch", "fetch_all", "fetch_one_stock"]