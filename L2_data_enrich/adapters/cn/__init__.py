# -*- coding: utf-8 -*-
"""
A股数据适配器
"""

from L2_data_enrich.adapters.cn.tencent_adapter import TencentCNAdapter
from L2_data_enrich.adapters.cn.baostock_adapter import BaoStockAdapter
from L2_data_enrich.adapters.cn.eastmoney_adapter import EastMoneyAdapter
from L2_data_enrich.adapters.cn.akshare_cn_adapter import AkShareCNAdapter

__all__ = [
    "TencentCNAdapter",
    "BaoStockAdapter",
    "EastMoneyAdapter",
    "AkShareCNAdapter",
]
