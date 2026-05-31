#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L4 输入输出 — 风险裁决层数据对象

L4 是决策层，接收 L3 的双轨输出，输出最终投资决策 + 风控参数。
"""
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional

from .common import BaseContract, Decision


# ── 评分组成 ────────────────────────────────────────────────────────────

@dataclass
class JudgeComponents(BaseContract):
    """
    JudgeScore 的三个组成部分及权重

    judge_score = veto_score × veto_weight + debate_score × debate_weight + persona_score × persona_weight
    """
    veto_score: float = 0.0           # 五维分（five_score/100）
    debate_score: float = 0.0         # 辩论分（verdict映射×置信度）
    persona_score: float = 0.0       # 人格分（BUY票数/总大师数）
    veto_weight: float = 0.50        # 权重：veto（五维分）
    debate_weight: float = 0.25       # 权重：辩论裁决
    persona_weight: float = 0.25    # 权重：人格大师


# ── 单只决策 ────────────────────────────────────────────────────────────

@dataclass
class L4Decision(BaseContract):
    """
    L4 单只股票决策 — 对应 l4_result["decisions"] 的单个元素

    这是 L4 的核心输出，包含完整的投资决策和风控参数。
    """
    code: str                          # 股票代码
    name: str                          # 股票名称
    price: float = 0.0                 # 当前价格

    # 核心评分
    judge_score: float = 0.0         # 综合裁决分（0-1），≥0.55=BUY/≥0.35=WATCH/<0.35=REJECT
    decision: Decision = Decision.REJECT  # BUY/WATCH/REJECT

    # 评分来源
    grade: str = ""                    # 五维评分等级 A/B/C/D
    verdict: str = ""                  # 辩论裁决（看多/谨慎看多/中性观望/谨慎看空/看空）
    confidence: float = 0.0          # 辩论置信度（0-1）

    # 风控参数
    risk_score: float = 50.0           # 风险评分（0-100），>70=高风险
    kelly_fraction: float = 0.0       # 凯利仓位（fraction），(bp-q)/b
    recommended_weight: float = 0.0  # 建议仓位（综合）
    volatility: float = 0.0           # 30日年化波动率
    stop_loss: float = 0.0            # 止损价格
    take_profit: float = 0.0         # 止盈价格

    # 扩展参数
    stop_loss_pct: float = -0.08      # 止损百分比（默认-8%）
    take_profit_pct: float = 0.20     # 止盈百分比（默认+20%）

    # 评分详情（用于报告展示）
    _judge_components: dict = field(default_factory=dict)  # JudgeComponents.to_dict()
    _five_score: float = 0.0          # 五维总分（原始，0-100）

    def __post_init__(self):
        if isinstance(self.decision, str):
            try:
                self.decision = Decision(self.decision)
            except ValueError:
                self.decision = Decision.REJECT


# ── 组合风控 ────────────────────────────────────────────────────────────

@dataclass
class PortfolioRisk(BaseContract):
    """
    组合风控结果

    对应 RiskManager.assess_portfolio() 的输出。
    """
    total_capital: float = 0.0
    used_capital: float = 0.0
    available_capital: float = 0.0
    positions_count: int = 0
    top_holding_pct: float = 0.0       # 最大持仓占比
    top_3_holding_pct: float = 0.0    # 前三持仓占比
    sector_concentration: Dict = field(default_factory=dict)  # 行业集中度
    avg_correlation: float = 0.0       # 平均持仓相关性
    max_correlation: float = 0.0      # 最大持仓相关性
    correlation_matrix: dict = field(default_factory=dict)  # 相关性矩阵
    portfolio_volatility: float = 0.0  # 组合波动率
    portfolio_var_95: float = 0.0    # 组合VaR（95%）
    sortino_ratio: float = 0.0        # Sortino比率
    calmar_ratio: float = 0.0        # Calmar比率
    concentration_warning: bool = False  # 集中度警告
    margin_call_risk: bool = False     # 保证金风险
    overall_alert: str = "green"      # 整体告警：green/yellow/red
    real_covariance_var_95: float = 0.0  # 真实协方差VaR
    portfolio_beta: float = 0.0      # 组合Beta


# ── L4 输出结构 ────────────────────────────────────────────────────────

@dataclass
class L4Result(BaseContract):
    """
    L4 完整输出

    对应 run_L4() / _run_L4_for_batch() 的完整返回结构。
    """
    layer: str = "L4"
    run_date: str = ""                 # YYYY-MM-DD
    stock_count: int = 0
    buy_count: int = 0                 # BUY决策数量
    decisions: List[L4Decision] = field(default_factory=list)
    portfolio_risk: Optional[PortfolioRisk] = None  # 组合风控（可选）
    duration_s: float = 0.0

    # 扩展标记
    _from_queue: bool = False          # 是否来自queue批处理
    _aborted: str = ""                # 中止原因（如 queue_empty）