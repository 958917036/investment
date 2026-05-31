#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 输入输出 — 初筛层数据对象
"""
from dataclasses import dataclass, field, fields
from typing import Dict, List

from .common import BaseContract


@dataclass
class L1Candidate(BaseContract):
    """
    L1→L2：候选股票输出（每只股票的结构）

    对应 run_l1() 返回的 stocks[] 数组中的单个元素。
    """
    code: str                          # 股票代码
    name: str                          # 股票名称
    price: float                       # 当前价格（元）
    change_pct: float = 0.0            # 涨跌幅（%）
    market_cap: float = 0.0           # 市值（亿元）
    source: str = "腾讯行情"           # 数据来源
    strategy_matched: str = ""        # 命中的策略名称
    score: float = 0.0                 # 策略评分（0-1）

    def to_dict(self) -> dict:
        d = {}
        for f in fields(self):
            v = getattr(self, f.name)
            d[f.name] = v.value if hasattr(v, "value") else v
        return d


@dataclass
class L1Result(BaseContract):
    """
    L1 完整输出

    对应 run_l1() 的完整返回结构。
    """
    layer: str = "L1"
    run_date: str = ""                 # YYYY-MM-DD
    input_type: str = ""              # by_code/by_name/by_sector/by_strategy
    input_params: dict = field(default_factory=dict)
    stock_count: int = 0
    stocks: List[dict] = field(default_factory=list)  # List[L1Candidate.to_dict()]
    duration_ms: float = 0.0
    strategy_counts: Dict[str, int] = field(default_factory=dict)  # 各策略命中数
    filtered_by_freeze: int = 0       # 被freeze表过滤的数量
    frozen_stocks: List[str] = field(default_factory=list)  # 冻结的股票代码列表
    observing_stocks: List[str] = field(default_factory=list)  # 观察中的股票代码列表
    total_candidates: int = 0         # 候选股总数
    _symbol_mode: bool = False        # 是否为用户指定股票模式
    _fallback_mode: bool = False      # 是否为降级模式（使用昨日数据）