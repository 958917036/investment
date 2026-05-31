#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 输入输出 — 复盘层数据对象

L5 是冷路径，不参与实时决策。负责：
- 决策记录（DecisionRecord）：由 L4 BUY 触发，写入 freeze_table
- 持仓结果追踪（OutcomeRecord）：跟踪持仓期间表现
- 交易记录（TradeRecord）：已平仓交易的完整记录
- 策略有效性指标（EffectivenessMetrics）：系统健康度
- CPCV 防过拟合验证（CPCVResult）：策略可信度
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .common import BaseContract, Decision


# ── 决策记录 ────────────────────────────────────────────────────────────

@dataclass
class DecisionRecord(BaseContract):
    """
    L4 决策记录 — 由 L4 BUY 触发写入 freeze_table

    对应 FreezeManager.record_buy_signal() 的写入数据。
    写入路径：main/freeze_table.json
    """
    decision_id: str                  # 唯一决策ID（UUID）
    code: str                          # 股票代码
    name: str                          # 股票名称
    decision: Decision = Decision.BUY  # 决策（BUY）
    judge_score: float = 0.0          # 裁判评分（0-1）
    date: str = ""                     # 决策日期 YYYY-MM-DD
    price: float = 0.0               # 决策价格
    stop_loss: float = 0.0           # 止损价格
    take_profit: float = 0.0         # 止盈价格
    kelly_fraction: float = 0.0       # 凯利仓位
    reason: str = ""                   # 决策原因（如 l4_judge:看多）

    # 附加信息
    market: str = "CN"               # 市场 CN/HK/US
    strategy: str = ""               # 来源策略
    five_score: float = 0.0           # 五维评分（原始）
    verdict: str = ""                # 辩论裁决

    def __post_init__(self):
        if isinstance(self.decision, str):
            try:
                self.decision = Decision(self.decision)
            except ValueError:
                self.decision = Decision.BUY


@dataclass
class OutcomeRecord(BaseContract):
    """
    持仓结果追踪 — 记录持仓期间的表现

    对应 ReviewEngine.evaluate_outcomes() 的记录数据。
    """
    decision_id: str            # 关联的 DecisionRecord ID
    code: str                    # 股票代码
    horizon: int = 0            # 持有天数
    return_pct: float = 0.0     # 收益率（%）
    hit: bool = False            # 是否盈利（return_pct > 0）
    closed: bool = False         # 是否已平仓
    entry_price: float = 0.0    # 入场价格
    exit_price: float = 0.0     # 出场价格（closed=True 时有效）
    max_gain_pct: float = 0.0    # 持仓期间最大浮盈（%）
    max_loss_pct: float = 0.0   # 持仓期间最大浮亏（%）


@dataclass
class TradeRecord(BaseContract):
    """
    交易记录 — 已平仓交易的完整记录

    对应 ReviewEngine 中平仓后的交易归档。
    """
    trade_id: str
    symbol: str                  # 股票代码
    entry_date: str             # 入场日期
    entry_price: float          # 入场价格
    exit_date: str = ""         # 出场日期
    exit_price: float = 0.0     # 出场价格
    return_pct: float = 0.0    # 收益率（%）
    holding_days: int = 0       # 持有天数
    decision_at_entry: str = ""  # BUY/WATCH
    confidence_at_entry: float = 0.0
    reason: str = ""            # 平仓原因（止损/止盈/手动）


# ── 有效性指标 ──────────────────────────────────────────────────────────

@dataclass
class EffectivenessMetrics(BaseContract):
    """
    策略有效性指标

    对应 ReviewEngine.get_effectiveness_report() 的输出。
    健康阈值：buy_hit_rate>55% / buy_avg_return>0% / win_loss_ratio>1.5x / pbo<15%
    """
    total_decisions: int = 0
    buy_count: int = 0
    watch_count: int = 0
    reject_count: int = 0

    # BUY 指标
    buy_hit_rate: float = 0.0     # BUY命中率（盈利BUY/总BUY），健康阈值>55%
    buy_avg_return: float = 0.0  # BUY平均收益，健康阈值>0%

    # WATCH 转化
    watch_to_buy_upgrade_rate: float = 0.0  # WATCH升级BUY后的收益
    watch_count_as_buy: int = 0            # WATCH后升级BUY的数量

    # REJECT 有效率
    reject_keep_dropping_rate: float = 0.0  # REJECT后继续下跌比例，健康阈值>70%

    # 综合指标
    sharpe_like: float = 0.0       # 模拟夏普比率，健康阈值>0
    win_loss_ratio: float = 0.0   # 盈亏比，健康阈值>1.5x

    # 持仓统计
    avg_holding_days: float = 0.0  # 平均持仓天数
    max_holding_days: int = 0     # 最长持仓天数


@dataclass
class CPCVResult(BaseContract):
    """
    CPCV 防过拟合验证结果

    对应 ReviewEngine.run_review() 中的 CPCV 验证模块。
    PBO < 15% 表示策略未过度优化。
    """
    n_trades: int = 0
    n_folds: int = 0
    avg_overfitting_ratio: float = 0.0
    pbo: float = 0.0              # Probability of Backtest Overfitting，健康阈值<15%
    hit_rate_train: float = 0.0   # 训练期命中率
    hit_rate_validate: float = 0.0  # 验证期命中率
    hit_rate_delta: float = 0.0    # 训练-验证期命中率差异，健康阈值<10%
    return_train_avg: float = 0.0   # 训练期平均收益
    return_validate_avg: float = 0.0  # 验证期平均收益
    return_delta: float = 0.0      # 训练-验证期收益差异，健康阈值<25%
    verdict: str = ""             # PASS/FAIL/WARNING
    notes: str = ""


# ── 冷冻管理 ────────────────────────────────────────────────────────────

@dataclass
class FreezeRecord(BaseContract):
    """
    冷冻记录 — 记录股票的冷冻状态

    对应 freeze_table.json 中的单条记录。
    """
    stock_code: str
    stock_name: str
    status: str = "frozen"         # frozen / observing / released
    freeze_type: str = ""          # 10days / 3months
    frozen_at: str = ""           # 冷冻开始日期
    frozen_until: str = ""        # 冷冻截止日期
    reason: List[str] = field(default_factory=list)  # 冷冻原因
    triggered_by: str = ""         # 触发源（如 "l4_judge" / "check_veto"）
    judge_score_at_freeze: float = 0.0  # 冷冻时的裁判评分
    price_at_freeze: float = 0.0   # 冷冻时的价格
    release_reason: str = ""      # 解冻原因（如 "手动解冻" / "到期自动解冻"）
    released_at: str = ""        # 解冻日期


@dataclass
class FreezeState(BaseContract):
    """
    冷冻状态汇总

    对应 freeze_table.json 的顶层结构。
    """
    freeze_records: List[FreezeRecord] = field(default_factory=list)
    observing_list: List[dict] = field(default_factory=list)  # 观察中的股票
    buy_signals: List[dict] = field(default_factory=list)  # 待处理的BUY信号
    last_updated: str = ""        # 最后更新时间