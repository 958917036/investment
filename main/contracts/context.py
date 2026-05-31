#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PipelineContext — 贯穿 L1→L2→L3→L4→L5 的唯一执行上下文

所有控制逻辑集中在 main 组装，runner 只消费 context 读配置，写结果。
"""
from dataclasses import dataclass, field
from typing import List, Optional

from .common import Market
from .l1 import L1Result
from .l2 import L2Result
from .l3 import L3Result
from .l4 import L4Result


@dataclass
class L5Result:
    """L5 终审结果（扩展后）"""
    layer: str = "L5"
    run_date: str = ""
    review_count: int = 0
    decisions_recorded: int = 0
    freeze_updated: bool = False
    effectiveness: dict = field(default_factory=dict) # EffectivenessMetrics.to_dict()
    cpcv: dict = field(default_factory=dict)            # CPCVResult.to_dict()
    freeze_state: dict = field(default_factory=dict)     # {expired[], upgraded[], unfrozen[]}
    duration_s: float = 0.0
    # L5 扩展字段
    position_summary: dict = field(default_factory=dict)      # PositionStatus.to_dict()
    trigger_results: dict = field(default_factory=dict)       # {stop_loss[], take_profit[], expired[], unchanged[]}
    report_path: Optional[str] = None                        # GeneratedReport.file_path
    parameter_advice: List[dict] = field(default_factory=list)  # ParameterSuggestion.to_dict()
    errors: List[dict] = field(default_factory=list)         # [{"module": "...", "error": "..."}]


@dataclass
class PipelineContext:
    """
    贯穿 L1→L2→L3→L4→L5 的唯一执行上下文

    使用方式：
        ctx = PipelineContext(run_date="2026-05-31", market=Market.CN, mode="full")
        ctx = run_pipeline(ctx)  # 内部循环调用各层 runner
        print(ctx.l4_result.buy_count)
    """
    # 基础信息
    run_date: str = ""                      # YYYY-MM-DD
    market: Market = Market.CN              # CN/HK/US
    mode: str = "full"                      # full / L2 / L3 / L4 / L5 / quick

    # ── 配置（全部从 config/ 加载到此）───────────────────────
    l1_config: dict = field(default_factory=dict)
    l2_config: dict = field(default_factory=dict)
    l3_config: dict = field(default_factory=dict)
    l3_persona_config: dict = field(default_factory=dict)
    l4_risk_config: dict = field(default_factory=dict)
    l4_batch_config: dict = field(default_factory=dict)
    model_config: dict = field(default_factory=dict)

    # ── 各层结果（层层累积）───────────────────────────────
    l1_result: Optional[L1Result] = None
    l2_result: Optional[L2Result] = None
    l3_result: Optional[L3Result] = None
    l4_result: Optional[L4Result] = None
    l5_result: Optional[L5Result] = None

    # ── 执行状态 ────────────────────────────────────────
    errors: List[dict] = field(default_factory=list)  # [{"layer": "L2", "code": "600519", "error": "..."}]
    duration_s: float = 0.0

    # ── 辅助方法 ────────────────────────────────────────
    def add_error(self, layer: str, code: str, error: str):
        self.errors.append({"layer": layer, "code": code, "error": error})

    def has_errors(self) -> bool:
        return len(self.errors) > 0


def load_all_config(ctx: PipelineContext) -> PipelineContext:
    """将所有 config/*.json 加载到 context"""
    import json
    import os

    base = os.path.expanduser("~/.hermes/investment/main/config")

    def load(name: str) -> dict:
        path = os.path.join(base, name)
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    ctx.l1_config = load("l1_config.json")
    ctx.l2_config = load("l2_config.json")
    ctx.l3_config = load("l3_config.json")
    ctx.l3_persona_config = load("l3_persona_config.json")
    ctx.l4_risk_config = load("l4_risk_config.json")
    ctx.l4_batch_config = load("l4_batch_config.json")
    ctx.model_config = load("model_config.json")
    return ctx