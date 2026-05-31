"""SQLAlchemy models for the stock analysis platform.

Database Design: Single main table (analysis_records) + 4 auxiliary tables

Main Table:
- analysis_records: 全链路分析记录 (L1→L2→L3→L4)
  - Core fields as direct columns (indexable, queryable)
  - Raw JSON blobs (l1_data~l4_data) for complete data flexibility
  - Key metrics expanded as direct columns for fast queries

Auxiliary Tables:
- stock_profiles: 股票库索引表
- reflections: 反思记录表
- portfolios: 持仓管理表
- watchlists: 关注列表表

Migration note: Add columns via ALTER TABLE, don't drop existing ones.
"""
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, String, Integer, Float, DateTime, Text, Enum as SQLEnum
from database import Base


class Market(str, Enum):
    CN = "CN"
    HK = "HK"
    US = "US"


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Decision(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WATCH = "WATCH"
    REJECT = "REJECT"


class Priority(int, Enum):
    """任务优先级: 1=人工触发, 3=定时调度"""
    MANUAL = 1
    SCHEDULED = 3


class Step(str, Enum):
    """分析阶段: L1→L2→veto→L3→L4"""
    L1 = "L1"
    L2 = "L2"
    VETO = "veto"
    L3 = "L3"
    L4 = "L4"


class AnalysisRecord(Base):
    """
    分析记录表 — 核心数据表，存储 L1/L2/L3/L4 全链路结果。

    调度逻辑:
    - WorkerPool 按 priority ASC 拉取 PENDING 状态记录
    - priority=1 优先于 priority=3
    - force_refresh=True 时跳过缓存强制刷新
    """
    __tablename__ = "analysis_records"

    # ── 身份 ─────────────────────────────────────────────
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    stock_code = Column(String, nullable=False, index=True)
    stock_name = Column(String, nullable=True)
    market = Column(SQLEnum(Market), default=Market.CN)
    run_date = Column(String, nullable=True, index=True)  # YYYY-MM-DD，运行日期

    # ── 执行控制 ─────────────────────────────────────────
    task_id = Column(String, nullable=True, index=True)
    step = Column(SQLEnum(Step), default=Step.L1)
    parent_record_id = Column(String, nullable=True)
    priority = Column(Integer, default=Priority.SCHEDULED.value, index=True)
    status = Column(SQLEnum(Status), default=Status.PENDING, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # ── 缓存控制 ─────────────────────────────────────────
    cache_key = Column(String, nullable=True)
    cached_at = Column(DateTime, nullable=True)
    force_refresh = Column(Integer, default=0)

    # ── L1 核心指标 ──────────────────────────────────────
    l1_strategy_counts = Column(Text, nullable=True)  # JSON: {breakout: 5, growth: 3, ...}
    l1_candidate_count = Column(Integer, default=0)
    l1_filtered_count = Column(Integer, default=0)    # 被冻结过滤的数量
    l1_total_scanned = Column(Integer, default=0)
    l1_source = Column(String, nullable=True)          # 数据来源描述
    l1_price = Column(Float, nullable=True)            # 当前价格
    l1_change_pct = Column(Float, nullable=True)       # 涨跌幅%
    l1_market_cap = Column(Float, nullable=True)       # 市值（亿元）

    # ── L2 核心指标（技术面）──────────────────────────────
    l2_price = Column(Float, nullable=True)
    l2_pe = Column(Float, nullable=True)
    l2_pb = Column(Float, nullable=True)
    l2_roe = Column(Float, nullable=True)
    l2_eps = Column(Float, nullable=True)
    l2_market_cap = Column(Float, nullable=True)
    l2_main_net_flow_5d = Column(Float, nullable=True)  # 主力净流入5日（元）
    l2_rsi = Column(Float, nullable=True)
    l2_ma_status = Column(String, nullable=True)       # bullish/bearish/neutral
    l2_macd_status = Column(String, nullable=True)     # golden/death/neutral
    l2_data_quality = Column(String, nullable=True)    # ok/degraded/fail

    # ── L3 核心指标（五维评分）───────────────────────────
    l3_five_score = Column(Float, nullable=True)        # 综合评分 0-100
    l3_grade = Column(String, nullable=True)            # A/B/C/D
    l3_score_technical = Column(Float, nullable=True)   # 技术面得分
    l3_score_fundamental = Column(Float, nullable=True)  # 基本面得分
    l3_score_moneyflow = Column(Float, nullable=True)  # 资金面得分
    l3_score_sector = Column(Float, nullable=True)     # 板块面得分
    l3_score_event = Column(Float, nullable=True)      # 事件面得分
    l3_debate_verdict = Column(String, nullable=True)   # 辩论裁决
    l3_debate_confidence = Column(Float, nullable=True)
    l3_persona_verdict = Column(String, nullable=True) # 人格裁决
    l3_persona_avg_score = Column(Float, nullable=True)

    # ── L4 核心指标（决策）───────────────────────────────
    l4_judge_score = Column(Float, nullable=True)      # 综合裁决分 0-1
    l4_decision = Column(SQLEnum(Decision), nullable=True)
    l4_risk_score = Column(Float, nullable=True)
    l4_volatility = Column(Float, nullable=True)
    l4_kelly_fraction = Column(Float, nullable=True)
    l4_recommended_weight = Column(Float, nullable=True)
    l4_stop_loss = Column(Float, nullable=True)
    l4_take_profit = Column(Float, nullable=True)

    # ── 完整原始数据（JSON）───────────────────────────────
    l1_data = Column(Text, nullable=True)  # 完整 L1 结果 JSON
    l2_data = Column(Text, nullable=True)  # 完整 L2 结果 JSON
    l3_data = Column(Text, nullable=True)  # 完整 L3 结果 JSON
    l4_data = Column(Text, nullable=True)  # 完整 L4 结果 JSON

    # ── 错误与重试 ───────────────────────────────────────
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)

    # ── 聚合字段 ────────────────────────────────────────
    analysis_count = Column(Integer, default=0)
    last_analysis_date = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "market": self.market.value if self.market else None,
            "run_date": self.run_date,
            "task_id": self.task_id,
            "step": self.step.value if self.step else None,
            "parent_record_id": self.parent_record_id,
            "priority": self.priority,
            "status": self.status.value if self.status else None,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "l3_five_score": self.l3_five_score,
            "l4_decision": self.l4_decision.value if self.l4_decision else None,
            "l4_judge_score": self.l4_judge_score,
            "cached_at": self.cached_at.isoformat() if self.cached_at else None,
            "force_refresh": bool(self.force_refresh),
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }


class StockProfile(Base):
    """股票库索引表 — 汇总每只股票的分析概况。"""
    __tablename__ = "stock_profiles"

    stock_code = Column(String, primary_key=True)
    stock_name = Column(String, nullable=True)
    market = Column(SQLEnum(Market), default=Market.CN)
    sector = Column(String, nullable=True)           # 行业
    industry = Column(String, nullable=True)         # 子行业

    analysis_count = Column(Integer, default=0)
    last_analysis_date = Column(DateTime, nullable=True)
    latest_record_id = Column(String, nullable=True)
    latest_decision = Column(SQLEnum(Decision), nullable=True)
    latest_judge_score = Column(Float, nullable=True)
    latest_price = Column(Float, nullable=True)


class Reflection(Base):
    """反思记录表 — 记录错误分析并进行反思。"""
    __tablename__ = "reflections"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_id = Column(String, nullable=False)
    wrong_analysis = Column(String, nullable=False)  # 'A' or 'B'
    reflection_text = Column(Text, nullable=False)
    error_tags = Column(Text, nullable=True)  # JSON array

    correct_analysis_id = Column(String, nullable=True)


class PositionType(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Portfolio(Base):
    """持仓管理表。"""
    __tablename__ = "portfolios"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    stock_code = Column(String, nullable=False, index=True)
    stock_name = Column(String, nullable=True)
    market = Column(SQLEnum(Market), default=Market.CN)
    position_type = Column(SQLEnum(PositionType), default=PositionType.LONG)

    quantity = Column(Float, default=0)
    avg_cost = Column(Float, default=0.0)
    current_price = Column(Float, nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Watchlist(Base):
    """关注列表表。"""
    __tablename__ = "watchlists"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    stock_code = Column(String, nullable=False, index=True)
    stock_name = Column(String, nullable=True)
    market = Column(SQLEnum(Market), default=Market.CN)

    reason = Column(Text, nullable=True)
    target_price = Column(Float, nullable=True)

    added_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)