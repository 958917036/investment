# -*- coding: utf-8 -*-
"""
因子研究模块

提供 A 股因子库、IC 分析、分层回测功能。
"""

from L3_quant_analysis.factor.factor_library import Factor, FactorLibrary
from L3_quant_analysis.factor.factor_computer import FactorComputer
from L3_quant_analysis.factor.ic_analyzer import ICAnalyzer
from L3_quant_analysis.factor.quantile_backtest import QuantileBacktester
from L3_quant_analysis.factor.factor_researcher import FactorResearcher

__all__ = [
    "Factor",
    "FactorLibrary",
    "FactorComputer",
    "ICAnalyzer",
    "QuantileBacktester",
    "FactorResearcher",
]
