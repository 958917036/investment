#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3 输入输出 — 量化分析层数据对象

L3 有两条并行路径：
- 量化轨：FiveScore（五维评分）+ DebateResult（辩论裁决）
- 人格轨：PersonaResult（LLM大师投票）
"""
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List

from .common import BaseContract, Grade, Verdict


# ── 量化轨对象 ────────────────────────────────────────────────────────────

@dataclass
class ScoreDimension(BaseContract):
    """
    五维评分中单个维度的得分详情

    对应 five_dimension_scorer.StockScoreResult.scores[key]
    """
    dimension_name: str                # 维度中文名（如"资金面"）
    score: float = 0.0               # 维度得分（0-100）
    weight: float = 0.0              # 配置权重（加总=1）
    weighted_score: float = 0.0      # 加权得分（score × weight）
    detail: Dict[str, Any] = field(default_factory=dict)  # 子项得分明细
    data_source: str = ""             # 数据来源描述


@dataclass
class FiveScore(BaseContract):
    """
    五维评分结果 — L3量化轨的核心输出

    对应 five_dimension_scorer.StockScoreResult 的序列化结构。
    """
    stock_code: str = ""
    stock_name: str = ""
    score_date: str = ""              # YYYY-MM-DD
    five_score: float = 0.0           # 综合评分（0-100），>80=A/65-79=B/50-64=C/<50=D
    grade: Grade = Grade.D
    scores: Dict[str, ScoreDimension] = field(default_factory=dict)  # 五维度详情
    calculation_time_ms: float = 0.0  # 计算耗时（毫秒）

    def __post_init__(self):
        if isinstance(self.grade, str):
            self.grade = Grade(self.grade) if self.grade else Grade.D


@dataclass
class Argument(BaseContract):
    """
    辩论论点

    对应 debate_engine.DebateRound 中的单个论点。
    """
    side: str                          # "bull" / "bear"
    title: str                         # 论点标题
    evidence: List[str] = field(default_factory=list)  # 证据列表
    strength: float = 0.0             # 论点强度（0-1）
    source: str = ""                   # 数据来源维度


@dataclass
class DebateRound(BaseContract):
    """
    辩论回合

    对应 debate_engine.DebateResult.rounds 中单个回合。
    """
    round_number: int = 0              # 回合数（1-indexed）
    bull_arguments: List[Argument] = field(default_factory=list)
    bear_arguments: List[Argument] = field(default_factory=list)
    bull_score: float = 0.0           # 多头得分
    bear_score: float = 0.0           # 空头得分
    verdict: str = ""                 # 本轮裁决


@dataclass
class DebateResult(BaseContract):
    """
    辩论引擎输出 — L3量化轨的双轨之一

    对应 debate_engine.DebateResult 的序列化结构。
    """
    stock_code: str = ""
    stock_name: str = ""
    debate_date: str = ""
    rounds: List[DebateRound] = field(default_factory=list)
    final_verdict: Verdict = Verdict.中性观望
    confidence: float = 0.5           # 置信度（0-1）
    bull_total_score: float = 0.0       # 多头总分
    bear_total_score: float = 0.0      # 空头总分
    key_opportunities: List[str] = field(default_factory=list)  # 关键机会（最多8条）
    key_risks: List[str] = field(default_factory=list)          # 关键风险（最多8条）
    debate_duration_ms: float = 0.0
    bull_arguments: List[str] = field(default_factory=list)    # 兼容旧字段
    bear_arguments: List[str] = field(default_factory=list)    # 兼容旧字段

    def __post_init__(self):
        if isinstance(self.final_verdict, str):
            try:
                self.final_verdict = Verdict(self.final_verdict)
            except ValueError:
                self.final_verdict = Verdict.中性观望


# ── 人格轨对象 ────────────────────────────────────────────────────────────

@dataclass
class PersonaResult(BaseContract):
    """
    人格分析输出 — L3人格轨的输出（LLM大师投票）

    对应 persona_runner.run_persona_analysis 的返回结构。
    当 LLM 不可用时，_status="skipped"。
    """
    _status: str = "skipped"          # ok / skipped / error
    perspectives: Dict[str, dict] = field(default_factory=dict)  # 大师视角 {name: {score, verdict, rationale, grade}}
    summary: Dict[str, Any] = field(default_factory=dict)  # 汇总 {buy_count, watch_count, reject_count, hold_count, agents_total, avg_score}
    duration_ms: float = 0.0


# ── L3 输出结构 ─────────────────────────────────────────────────────────

@dataclass
class L3StockResult(BaseContract):
    """
    L3 单只股票分析结果 — 对应 l3_result["results"] 的单个元素

    L3 有双轨输出：量化（score/debate）和人格（persona）。
    """
    code: str                          # 股票代码
    name: str                          # 股票名称
    score: dict = field(default_factory=dict)        # FiveScore.to_dict()
    debate: dict = field(default_factory=dict)      # DebateResult.to_dict()
    persona: dict = field(default_factory=dict)    # PersonaResult（已序列化）
    price: float = 0.0                # 当前价格（从L2传入，用于人格分析）

    # 内部状态标记（不用于跨层传输）
    _status: str = ""                  # 空/ok/skip/error


@dataclass
class L3Result(BaseContract):
    """
    L3 完整输出

    对应 run_L3() 的完整返回结构。
    """
    layer: str = "L3"
    run_date: str = ""                 # YYYY-MM-DD
    stock_count: int = 0
    results: List[L3StockResult] = field(default_factory=list)
    duration_s: float = 0.0
    _skipped_no_data: int = 0         # 因moneyflow_data缺失跳过的股票数
    _from_queue: bool = False         # 是否来自queue批处理
    _batch_start: int = 0             # 本批起始下标