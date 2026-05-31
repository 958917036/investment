#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 输入输出 — 数据充实层核心对象

L2 是跨层数据传输最密集的层：stocks[]._data 包含5个维度的完整数据。
这里定义所有5个维度的 dataclass，以及跨层传输的核心结构 L2StockData。
"""
from dataclasses import dataclass, field, fields, asdict
from typing import Any, Dict, List, Optional

from .common import BaseContract, QualityLevel


# ── 五维度数据对象 ────────────────────────────────────────────────────────

@dataclass
class MoneyflowData(BaseContract):
    """
    资金流数据（五维度之一）

    描述主力资金、散户资金的流向和强度。
    数据来源：东方财富+BaoStock估算 / 腾讯API / MFI指标
    """
    _source: str = ""                  # 数据来源描述
    _quality: QualityLevel = QualityLevel.OK  # 数据质量
    _missing_fields: List[str] = field(default_factory=list)  # 缺失字段列表

    # 核心字段
    main_net_flow_5d: float = 0.0      # 近5日主力净流入（元），正=流入
    main_direction: str = "未知"        # 流入/流出/未知
    retail_direction: str = "未知"       # 散户方向（与主力反向）
    outer_inner_ratio: float = 1.0     # 外盘/内盘比，>1=主力强，<0.9=散户接盘
    large_order_ratio: float = 0.0       # 大单成交占比，>5%=机构参与
    daily_flows: List[dict] = field(default_factory=list)  # 每日资金流 [{date, flow, direction}, ...]
    stock_rank: int = 9999              # 主力资金排名（9999=未上榜）

    # 扩展字段
    latest_main_flow: float = 0.0     # 最新单日主力净流入（元）
    super_large_flow: float = 0.0     # 超大单净流入（元）
    small_order_flow: float = 0.0       # 小单净流入（散户代理，元）
    hsgt_hold_ratio: float = 0.0        # 北向持股比例（HSGT，%）
    hsgt_add_ratio: float = 0.0         # 北向增持比例（%）
    net_flow_1d_yuan: int = 0          # 单日净流入金额（元）
    latest_main_ratio: float = 0.0     # 最新主力净流入占总成交比

    def __post_init__(self):
        if isinstance(self._quality, str):
            self._quality = QualityLevel(self._quality)


@dataclass
class TechnicalData(BaseContract):
    """
    技术面数据（五维度之一）

    描述价格走势、均线系统、技术指标。
    数据来源：BaoStock日线 / AkShare日线 / Yahoo Finance
    """
    _source: str = ""
    _quality: QualityLevel = QualityLevel.OK
    _missing_fields: List[str] = field(default_factory=list)

    # 价格与涨跌
    price: float = 0.0                 # 当前价格（元/港币/美元）
    change_pct: float = 0.0            # 涨跌幅（%）

    # 均线系统
    ma5: float = 0.0                   # 5日均线
    ma10: float = 0.0                 # 10日均线
    ma20: float = 0.0                 # 20日均线
    ma60: float = 0.0                  # 60日均线
    ma_status: str = "neutral"          # 均线状态：bullish/bearish/neutral

    # MACD
    dif: float = 0.0                   # DIF 快线
    dea: float = 0.0                  # DEA 慢线
    macd_hist: float = 0.0             # MACD 柱状图（DIF-DEA）
    macd_status: str = "neutral"        # MACD信号：golden/death/neutral/golden_cross/death_cross

    # RSI
    rsi: float = 50.0                 # RSI(14)，>70超买/<30超卖，40-70健康区间

    # 成交量
    volume_status: str = "正常"         # 放量上涨/缩量/正常
    volume_ratio: float = 1.0          # 量比（相对20日均量），>1.5=放量

    # 布林带
    bb_upper: float = 0.0              # 布林上轨
    bb_mid: float = 0.0                # 布林中轨
    bb_lower: float = 0.0              # 布林下轨
    bb_position: float = 0.5           # 布林位置，>0.8接近上轨/<0.2接近下轨

    # 美股特有扩展
    return_m1: float = 0.0            # 近1月收益率（%）
    return_m3: float = 0.0            # 近3月收益率（%）
    return_y1: float = 0.0           # 近1年收益率（%）
    year_high: float = 0.0             # 年内高点
    year_low: float = 0.0             # 年内低点

    def __post_init__(self):
        if isinstance(self._quality, str):
            self._quality = QualityLevel(self._quality)


@dataclass
class FundamentalData(BaseContract):
    """
    基本面数据（五维度之一）

    描述估值、盈利、成长、财务结构。
    数据来源：AkShare财务 / 腾讯API / finviz / BaoStock
    """
    _source: str = ""
    _quality: QualityLevel = QualityLevel.OK
    _missing_fields: List[str] = field(default_factory=list)

    # 估值
    pe: float = 0.0                    # 市盈率（倍），<15低估/>30高估
    pb: float = 0.0                   # 市净率（倍），制造业均值约2.5x
    forward_pe: float = 0.0           # 前瞻PE（美股）
    peg_ratio: float = 0.0             # PEG（市盈率/增速），<1合理

    # 盈利能力
    roe: float = 0.0                   # 净资产收益率（%），>15%=优秀
    eps: float = 0.0                  # 每股收益（元）
    gross_margin: float = 0.0         # 毛利率（%）
    net_margin: float = 0.0           # 净利率（%）

    # 成长性
    net_profit_yoy: float = 0.0         # 净利润同比增速（%）
    revenue_growth: float = 0.0        # 营收增速（%）
    eps_growth_yoy: float = 0.0      # EPS增速（%）
    eps_next_y: float = 0.0           # 明年EPS预期增速（美股）
    eps_next_5y: float = 0.0          # 未来5年EPS增速预期（美股）

    # 财务结构
    debt_eq: float = 0.0              # 负债股权比（%）
    asset_liability_ratio: float = 0.0 # 资产负债率（%），>75%为高负债
    inst_ownership_pct: float = 0.0    # 机构持股比例（%）
    inst_trans: float = 0.0           # 机构持股变动（%）
    insider_ownership_pct: float = 0.0 # 内部人持股比例（美股）
    insider_trans: float = 0.0         # 内部人交易（美股）

    # 美股特有
    operating_margin: float = 0.0      # 营业利润率
    profit_margin: float = 0.0         # 净利润率
    beta: float = 0.0                 # Beta（波动率相对市场）
    market_cap: float = 0.0           # 市值（亿美元）
    sector: str = ""                   # 行业
    industry: str = ""                 # 子行业

    def __post_init__(self):
        if isinstance(self._quality, str):
            self._quality = QualityLevel(self._quality)


@dataclass
class SectorData(BaseContract):
    """
    板块数据（五维度之一）

    描述个股所在板块的资金流和强度排名。
    数据来源：AkShare板块
    """
    _source: str = ""
    _quality: QualityLevel = QualityLevel.OK
    _missing_fields: List[str] = field(default_factory=list)

    sector_rank: int = 50             # 板块排名（1-100），越高越强
    sector_fund_flow: float = 0.0     # 板块资金流（元），正=净流入
    sector_strength: str = "unknown"  # 板块强度：强势/弱势/unknown
    related_sector: str = ""           # 关联板块名称
    sector_etf: str = ""              # 对应ETF代码（美股）
    sector_count: int = 0             # 成分股数量（0=获取失败）

    def __post_init__(self):
        if isinstance(self._quality, str):
            self._quality = QualityLevel(self._quality)


@dataclass
class EventData(BaseContract):
    """
    事件数据（五维度之一）

    描述利好/利空事件、分析师评级、研报覆盖。
    数据来源：AkShare新闻 / AkShare舆情
    """
    _source: str = ""
    _quality: QualityLevel = QualityLevel.OK
    _missing_fields: List[str] = field(default_factory=list)

    positive_events: List[str] = field(default_factory=list)  # 利好事件列表
    analyst_rating: str = ""        # 分析师评级：buy/neutral/sell
    report_count_30d: int = 0       # 近30天研报数量
    news_count: int = 0             # 新闻数量
    negative_event_count: int = 0     # 负面事件数量
    positive_event_count: int = 0      # 正面事件数量

    # 美股特有
    sentiment: str = ""             # 市场情绪
    insider_trans: float = 0.0      # 内部人交易量（美股）

    def __post_init__(self):
        if isinstance(self._quality, str):
            self._quality = QualityLevel(self._quality)


# ── 核心跨层结构 ──────────────────────────────────────────────────────────

@dataclass
class L2StockData(BaseContract):
    """
    L2→L3 跨层传输的核心数据结构：单只股票的5维度市场数据

    这是 L2 层输出的核心单元。对应 run_L2() 返回的 stocks[] 数组中
    每个元素的 _data 字段。

    使用 to_dict() 序列化后与现有 dict 结构完全兼容。
    """
    # 股票身份
    code: str = ""
    name: str = ""

    # 五维度数据（每个都是独立 dataclass）
    moneyflow_data: MoneyflowData = field(default_factory=MoneyflowData)
    technical_data: TechnicalData = field(default_factory=TechnicalData)
    fundamental_data: FundamentalData = field(default_factory=FundamentalData)
    sector_data: SectorData = field(default_factory=SectorData)
    event_data: EventData = field(default_factory=EventData)

    def to_dict(self) -> dict:
        """序列化为普通 dict，用于 JSON 存储和跨层传输"""
        d = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, BaseContract):
                sub = v.to_dict()
                # _quality 枚举转字符串
                if "_quality" in sub and isinstance(sub["_quality"], QualityLevel):
                    sub["_quality"] = sub["_quality"].value
                d[f.name] = sub
            else:
                d[f.name] = v
        return d

    @classmethod
    def from_dict(cls, d: dict):
        """从普通 dict 反序列化（宽松加载，忽略未知字段）"""
        identity = {k: d[k] for k in ["code", "name"] if k in d}

        sub_fields = {
            "moneyflow_data": MoneyflowData,
            "technical_data": TechnicalData,
            "fundamental_data": FundamentalData,
            "sector_data": SectorData,
            "event_data": EventData,
        }
        parsed = {}
        for sub_name, sub_cls in sub_fields.items():
            if sub_name in d and isinstance(d[sub_name], dict):
                try:
                    parsed[sub_name] = sub_cls.from_dict(d[sub_name])
                except (TypeError, ValueError):
                    known = {f.name for f in fields(sub_cls)}
                    filtered = {k: v for k, v in d[sub_name].items() if k in known}
                    try:
                        parsed[sub_name] = sub_cls.from_dict(filtered)
                    except Exception:
                        parsed[sub_name] = sub_cls()
            else:
                parsed[sub_name] = sub_cls()

        return cls(**identity, **parsed)


@dataclass
class L2Result(BaseContract):
    """
    L2 完整输出

    对应 run_L2() 的完整返回结构。
    """
    layer: str = "L2"
    run_date: str = ""                 # YYYY-MM-DD
    stock_count: int = 0
    stocks: List[dict] = field(default_factory=list)  # List[L2StockData.to_dict()]
    duration_s: float = 0.0

    # 特殊标记（用于整日数据质量告警）
    _DATA_CRITICAL_FAILURE: bool = False  # True=资金流数据严重缺失，整日中止
    _moneyflow_valid_pct: float = 0.0      # 有效资金流占比（%）
    _has_moneyflow_count: int = 0         # 有有效资金流的股票数
    _batch_health: dict = field(default_factory=dict)  # 批次健康度详情