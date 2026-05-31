#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.contracts — 神农系统跨层数据实体类

所有层使用统一的 dataclass 定义输入输出，配合 to_dict()/from_dict()
保持与现有 dict 结构的完全兼容。
"""
from .common import (
    BaseContract,
    QualityLevel,
    Market,
    Decision,
    Verdict,
    Grade,
    _safe_enum,
)

from .stock import StockIdentity

from .l1 import L1Candidate, L1Result

from .l2 import (
    MoneyflowData,
    TechnicalData,
    FundamentalData,
    SectorData,
    EventData,
    L2StockData,
    L2Result,
)

from .l3 import (
    ScoreDimension,
    FiveScore,
    Argument,
    DebateRound,
    DebateResult,
    PersonaResult,
    L3StockResult,
    L3Result,
)

from .l4 import (
    JudgeComponents,
    L4Decision,
    PortfolioRisk,
    L4Result,
)

from .l5 import (
    DecisionRecord,
    OutcomeRecord,
    TradeRecord,
    EffectivenessMetrics,
    CPCVResult,
    FreezeRecord,
    FreezeState,
)

from .context import PipelineContext, L5Result, load_all_config

__all__ = [
    # common
    "BaseContract",
    "QualityLevel",
    "Market",
    "Decision",
    "Verdict",
    "Grade",
    "_safe_enum",
    # stock
    "StockIdentity",
    # l1
    "L1Candidate",
    "L1Result",
    # l2
    "MoneyflowData",
    "TechnicalData",
    "FundamentalData",
    "SectorData",
    "EventData",
    "L2StockData",
    "L2Result",
    # l3
    "ScoreDimension",
    "FiveScore",
    "Argument",
    "DebateRound",
    "DebateResult",
    "PersonaResult",
    "L3StockResult",
    "L3Result",
    # l4
    "JudgeComponents",
    "L4Decision",
    "PortfolioRisk",
    "L4Result",
    # l5
    "DecisionRecord",
    "OutcomeRecord",
    "TradeRecord",
    "EffectivenessMetrics",
    "CPCVResult",
    "FreezeRecord",
    "FreezeState",
    # context
    "PipelineContext",
    "L5Result",
    "load_all_config",
]