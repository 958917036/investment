#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票身份 — 所有层的基石对象
"""
from dataclasses import dataclass, asdict, fields
from typing import Optional

from .common import BaseContract, Market


@dataclass
class StockIdentity(BaseContract):
    """
    股票身份标识，所有层共享。

    用于标记一笔数据的股票归属，不含业务字段。
    三市场代码格式：
    - A股 CN：纯数字，如 "600519"
    - 港股 HK：5位，如 "00700"
    - 美股 US：字母，如 "SMCI"
    """
    code: str                          # 股票代码
    name: str                          # 股票名称
    market: Market = Market.CN         # 市场（默认A股）

    def __post_init__(self):
        if isinstance(self.market, str):
            self.market = Market(self.market)

    @classmethod
    def from_dict(cls, d: dict):
        allowed = {"code", "name", "market"}
        filtered = {k: v for k, v in d.items() if k in allowed}
        if "market" in filtered and isinstance(filtered["market"], str):
            filtered["market"] = Market(filtered["market"])
        return cls(**filtered)