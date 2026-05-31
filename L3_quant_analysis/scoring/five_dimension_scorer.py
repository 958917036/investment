#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
五维评分引擎 — 融合KHunter评分体系设计思想
核心创新：可配置权重 + 多数据源降级

权重配置（默认，可动态调整）：
- 资金面：35% （数据 > 叙事，核心决策力）
- 技术面：35% （趋势跟踪）
- 基本面：10% （长期质量）
- 板块强度：10% （行业轮动）
- 事件驱动：10% （催化剂）

评分范围：0-100，>70 强势推荐，50-70 关注，<50 观望
"""

import json
import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("five_dimension_scorer")

# ======================== 数据模型 ========================

@dataclass
class ScoreDetail:
    """五维评分详情"""
    dimension_name: str
    score: float                    # 维度得分 0-100
    weight: float                   # 配置权重
    weighted_score: float           # 加权后得分
    detail: Dict[str, Any] = field(default_factory=dict)  # 子项得分明细
    data_source: str = ""           # 数据来源说明

    def to_dict(self):
        return asdict(self)

@dataclass
class StockScoreResult:
    """个股综合评分结果"""
    stock_code: str
    stock_name: str
    score_date: str
    five_score: float = 0.0         # 五维度综合评分 0-100
    grade: str = ""                 # A/B/C/D
    scores: Dict[str, ScoreDetail] = field(default_factory=dict)
    calculation_time_ms: float = 0.0

    def to_dict(self):
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "score_date": self.score_date,
            "five_score": round(self.five_score, 2),
            "grade": self.grade,
            "scores": {k: v.to_dict() for k, v in self.scores.items()},
            "calculation_time_ms": round(self.calculation_time_ms, 1)
        }

# ======================== 评分配置 ========================

DEFAULT_WEIGHTS = {
    "moneyflow": 0.35,      # 资金面 35%
    "technical": 0.35,      # 技术面 35%
    "fundamental": 0.10,    # 基本面 10%
    "sector": 0.10,         # 板块强度 10%
    "event": 0.10,          # 事件驱动 10%
}

# 配置加载
import os as _os

_CONFIG_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
    "main", "config", "l3_config.json"
)

def _load_l3_config() -> dict:
    """从配置文件加载L3参数"""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def get_default_weights() -> dict:
    """从配置加载默认权重，失败时使用硬编码默认值"""
    cfg = _load_l3_config()
    fw = cfg.get("five_dimension_weights")
    if fw:
        return fw
    return DEFAULT_WEIGHTS.copy()

# ======================== 五维评分引擎 ========================

class FiveDimensionScorer:
    """
    五维评分引擎 — 投资决策的核心量化器
    
    设计思想：
    1. 可配置权重：默认35/35/10/10/10，可根据市场环境动态调整
    2. 数据源降级：一个API失败，自动切换到备用数据源
    3. 细粒度子维度：每个维度下有2-4个子评分项，更精细
    """

    def __init__(self, weights: Dict[str, float] = None):
        self.weights = weights or get_default_weights()
        # 验证权重总和为1.0
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.001:
            logger.warning(f"权重总和为{total}，自动归一化")
            for k in self.weights:
                self.weights[k] /= total
        logger.info(f"五维评分引擎初始化，权重: {self.weights}")

    def score_stock(self, stock_code: str, stock_name: str = "",
                    data: Dict[str, Any] = None) -> StockScoreResult:
        """
        对单只股票进行五维评分
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            data: 预获取的数据字典，含各维度所需数据
                  如果为None，引擎内部会尝试自行获取
        
        Returns:
            StockScoreResult 综合评分结果
        """
        start_time = time.time()
        score_date = datetime.now().strftime("%Y-%m-%d")
        
        result = StockScoreResult(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            score_date=score_date,
        )

        # 五维度评分
        dimensions = [
            ("moneyflow", "资金面", self._score_moneyflow, "moneyflow_data"),
            ("technical", "技术面", self._score_technical, "technical_data"),
            ("fundamental", "基本面", self._score_fundamental, "fundamental_data"),
            ("sector", "板块强度", self._score_sector, "sector_data"),
            ("event", "事件驱动", self._score_event, "event_data"),
        ]

        for key, name, scorer, data_key in dimensions:
            dim_data = data.get(data_key) or {} if data else {}

            # 评分（包含降级处理）
            score, detail_dict = scorer(dim_data, stock_code)

            # 缺失子维度归一化：moneyflow的_sub_max<100时，score是子维度原始之和，非百分制
            # 修复：score<=detail_dict["_sub_max"] 说明有子维度缺失，需要归一化到100分制
            # 注意：score==sub_max 也是 degraded 状态（如 moneyflow 只有north缺失，score=80/80 不是满分100）
            sub_max = detail_dict.get("_sub_max", 100)
            weight = self.weights.get(key, 0.1)
            if score <= sub_max and sub_max < 100:
                # 归一化：(实际分/实际满分) × 100 × 权重
                normalized = (score / sub_max) * 100.0 * weight
            else:
                # 满分或技术/基本面等维度（sub_max始终100），直接乘权重
                normalized = score * weight

            detail = ScoreDetail(
                dimension_name=name,
                score=score,
                weight=weight,
                weighted_score=round(normalized, 4),
                detail=detail_dict,
                data_source=dim_data.get("_source", ""),
            )
            result.scores[key] = detail

        # 正常加权求和
        total = sum(d.weighted_score for d in result.scores.values())
        result.five_score = min(100.0, max(0.0, total))
        result.grade = self._get_grade(result.five_score)

        result.calculation_time_ms = (time.time() - start_time) * 1000
        return result

    def batch_score(self, stocks: List[Dict[str, Any]],
                    data_provider=None) -> List[StockScoreResult]:
        """
        批量评分 — 支持并行计算
        
        Args:
            stocks: [{"code": "600519", "name": "茅台"}, ...]
            data_provider: 数据提供者回调函数
        
        Returns:
            评分结果列表（已排序：高分在前）
        """
        results = []
        for stock in stocks:
            code = stock.get("code", stock.get("stock_code", ""))
            name = stock.get("name", stock.get("stock_name", ""))
            data = {}
            if data_provider:
                try:
                    data = data_provider(code)
                except Exception as e:
                    logger.warning(f"数据获取失败 {code}: {e}")
            
            result = self.score_stock(code, name, data)
            results.append(result)

        # 按综合分降序排列
        results.sort(key=lambda r: r.five_score, reverse=True)
        return results

    # ==================== 各维度评分器 ====================

    def _score_moneyflow(self, data: Dict, stock_code: str) -> Tuple[float, Dict]:
        """
        资金面评分（35%权重 — 最核心维度）

        子维度（2026-04-28重构，数据源降级后的评分策略）：
        - 主力资金流（全市场排名+净额）：40分
          * 2026-04-28: ranking被封，降级用BaoStock日线估算+腾讯外内盘
        - 千股千评综合得分：25分
          * 2026-04-28: comment被封，降级用外内盘比+龙虎榜信号
        - 北向资金（沪深港通增持比例）：20分
          * 2026-04-28: HSGT被封，降级用龙虎榜机构席位数估算
        - 北向大盘资金流向：15分
          * 2026-04-28: north_net_buy被封，降级用5日估算净额方向
        """
        detail = {}

        # ── 提取资金数据（兼容新旧两种数据格式）───────────────
        main_net_flow = data.get("main_net_flow_5d", 0)        # BaoStock估算5日净流入（元）
        stock_rank = data.get("stock_rank", 9999)               # 全市场排名（封了=9999）
        comprehensive_score = data.get("comprehensive_score")   # 千股千评（封了=None）
        main_cost = data.get("main_cost")
        institution_participation = data.get("institution_participation")
        attention_index = data.get("newspaper_reaction", None)
        hsgt_hold_ratio = data.get("hsgt_hold_ratio")            # 北向持股（封了=None）
        hsgt_add_shares = data.get("hsgt_add_shares")
        north_net_buy = data.get("north_net_buy_today", 0)       # 北向净买额（封了=0）
        price_change_pct = data.get("price_change_pct", 0) or 0

        # 2026-04-28新增字段（来自三源架构）
        net_flow_1d_yuan = data.get("net_flow_1d_yuan", 0) or 0  # 腾讯单日净流入估算（元）
        outer_inner_ratio = data.get("outer_inner_ratio", 1.0)    # 腾讯外内盘比
        billboard_net_amt = data.get("billboard_net_amt", None)  # 龙虎榜净流入额（元）
        net_flow_score = data.get("net_flow_score", 10)          # BaoStock估算净额评分

        # 换算
        main_net_flow_yi = main_net_flow / 1e8 if main_net_flow else 0
        net_flow_1d_yi = net_flow_1d_yuan / 1e8

        # --- 子维度1: 主力资金流（全市场排名，40分）---
        # 2026-04-28: ranking=9999时，用BaoStock估算净额降级评分
        if stock_rank <= 10:
            flow_score = 40
        elif stock_rank <= 50:
            flow_score = 35
        elif stock_rank <= 200:
            flow_score = 28
        elif stock_rank <= 500:
            flow_score = 20
        elif stock_rank <= 1000:
            flow_score = 12
        elif main_net_flow_yi >= 5:            # BaoStock估算>=5亿
            flow_score = 22
        elif main_net_flow_yi >= 1:            # BaoStock估算>=1亿
            flow_score = 18
        elif main_net_flow_yi >= 0.5:          # BaoStock估算>=5000万（2026-04-29细化）
            flow_score = 15
        elif main_net_flow_yi >= 0.1:          # BaoStock估算>=1000万（2026-04-29细化）
            flow_score = 13
        elif main_net_flow_yi > 0:             # BaoStock估算正净额（<1000万）
            flow_score = 12
        elif main_net_flow_yi <= -5:           # BaoStock估算<=-5亿
            flow_score = 3
        elif main_net_flow_yi <= -1:           # BaoStock估算<=-1亿（2026-04-29细化）
            flow_score = 5
        elif main_net_flow_yi < 0:            # BaoStock估算负净额（>-1亿）
            flow_score = 7
        else:
            # rank=9999且净额≈0 → 用腾讯外内盘比降级
            if outer_inner_ratio and outer_inner_ratio > 1.1:
                flow_score = 14   # 外盘>内盘，主力偏强
            elif outer_inner_ratio and outer_inner_ratio < 0.9:
                flow_score = 6    # 外盘<内盘，主力偏弱
            else:
                flow_score = 10   # 中性

        detail["stock_rank"] = stock_rank
        detail["main_net_flow_5d_yuan"] = int(main_net_flow)
        detail["main_net_flow_yi"] = round(main_net_flow_yi, 2)
        detail["main_net_flow_score"] = flow_score

        # --- 子维度2: 千股千评综合得分（25分）---
        # 2026-04-28: comment被封，降级用龙虎榜+外内盘估算
        if comprehensive_score is not None:
            if comprehensive_score >= 85: comment_score = 25
            elif comprehensive_score >= 75: comment_score = 20
            elif comprehensive_score >= 65: comment_score = 15
            elif comprehensive_score >= 50: comment_score = 8
            else: comment_score = 3
        elif billboard_net_amt is not None and abs(billboard_net_amt) > 1000_0000:
            # 龙虎榜净流入>1000万，机构参与
            if billboard_net_amt > 1_0000_0000:  # >1亿
                comment_score = 20
            elif billboard_net_amt > 1000_0000:  # >1000万
                comment_score = 15
            else:
                comment_score = 10
        elif outer_inner_ratio:
            # 外内盘比估算主力行为
            if outer_inner_ratio > 1.15: comment_score = 15
            elif outer_inner_ratio > 1.05: comment_score = 12
            elif outer_inner_ratio < 0.85: comment_score = 5
            elif outer_inner_ratio < 0.95: comment_score = 8
            else: comment_score = 10
        else:
            comment_score = 10  # 中性分

        detail["comprehensive_score"] = round(comprehensive_score, 2) if comprehensive_score else None
        detail["main_cost"] = round(main_cost, 2) if main_cost else None
        detail["institution_participation"] = round(institution_participation, 4) if institution_participation else None
        detail["outer_inner_ratio"] = round(outer_inner_ratio, 3) if outer_inner_ratio else None
        detail["net_flow_1d_yuan"] = int(net_flow_1d_yuan) if net_flow_1d_yuan else 0
        detail["billboard_net_amt"] = int(billboard_net_amt) if billboard_net_amt is not None else None  # 龙虎榜净流入额（元），透传用于报告
        detail["comment_score"] = comment_score

        # --- 子维度3: 北向资金（沪深港通增持，20分）---
        # 数据质量标记：hsgt有真实数据才参与汇总，否则为None（EM被封时不造假中性分）
        if hsgt_hold_ratio is not None:
            if hsgt_hold_ratio >= 0.10: hsgt_score = 20
            elif hsgt_hold_ratio >= 0.05: hsgt_score = 16
            elif hsgt_hold_ratio >= 0.02: hsgt_score = 12
            elif hsgt_add_shares and hsgt_add_shares > 0: hsgt_score = 10
            else: hsgt_score = 6
        else:
            hsgt_score = None  # 不写死！EM被封时从评分移除，不参与汇总
        detail["hsgt_hold_ratio"] = round(hsgt_hold_ratio, 4) if hsgt_hold_ratio else None
        detail["hsgt_add_shares"] = int(hsgt_add_shares) if hsgt_add_shares else 0
        detail["_hsgt_data_source"] = "em_hsgt" if hsgt_hold_ratio is not None else "blocked"
        detail["_hsgt_score"] = hsgt_score

        # --- 子维度4: 北向大盘资金流向（15分）---
        # 腾讯单日净流入是真实数据（外内盘×价格），不是EM写死值
        # EM north被封时：用腾讯净流入估算替代（这是真实市场数据，不是造假）
        north_net_buy_yi = north_net_buy / 1e8 if north_net_buy else 0
        net_flow_1d_yi = net_flow_1d_yuan / 1e8 if net_flow_1d_yuan else 0
        
        # 判断north_score数据来源
        if north_net_buy_yi != 0:
            # EM北向数据真实可用
            if north_net_buy_yi > 10: north_score = 15
            elif north_net_buy_yi > 5: north_score = 12
            elif north_net_buy_yi > 0: north_score = 10
            elif north_net_buy_yi > -5: north_score = 6
            else: north_score = 3
            detail["_north_data_source"] = "em_north"
        elif abs(net_flow_1d_yi) > 0.05:  # 腾讯净流入有意义信号（>500万）
            # EM被封，用腾讯日净流入替代（真实市场数据，不是写死）
            if net_flow_1d_yi > 1: north_score = 15
            elif net_flow_1d_yi > 0.5: north_score = 12
            elif net_flow_1d_yi > 0.1: north_score = 10
            elif net_flow_1d_yi > -0.5: north_score = 6
            else: north_score = 3
            detail["_north_data_source"] = "tencent_flow"
        else:
            # EM被封且腾讯净流入≈0，无有效数据 → 不造假，设为None
            north_score = None
            detail["_north_data_source"] = "no_data"

        detail["north_net_buy_yi"] = round(north_net_buy_yi, 2)
        detail["net_flow_1d_yi"] = round(net_flow_1d_yi, 4)
        detail["_north_score"] = north_score
        detail["_north_data_source"] = ("em_north" if north_net_buy_yi != 0
                                       else "tencent_flow" if abs(net_flow_1d_yi) > 0.05
                                       else "no_data")

        # 资金面总分：只汇总有真实数据的子维度（EM被封的子维度=None，不参与）
        # 子维度满分子集：flow(40) + comment(25) + hsgt(20) + north(15) = 100
        # EM被封时该维度分项为None，实际满分变为 80（无hsgt）或 85（无north）等
        _sub_scores = [s for s in [flow_score, comment_score, hsgt_score, north_score] if s is not None]
        if _sub_scores:
            total = sum(_sub_scores)
        else:
            total = 0  # 完全没有有效数据
        # 实际参与子维度满分之和（用于judge动态归一化）
        _sub_max = sum([
            40 if flow_score is not None else 0,
            25 if comment_score is not None else 0,
            20 if hsgt_score is not None else 0,
            15 if north_score is not None else 0,
        ])
        detail["_sub_scores"] = _sub_scores
        detail["_sub_max"] = _sub_max              # 实际满分，如65/80/85/100
        detail["_sub_max_weighted"] = _sub_max * 0.35  # weighted满分，如22.75/28/29.75/35
        detail["_hsgt_score"] = hsgt_score
        detail["_north_score"] = north_score
        return total, detail

    def _score_technical(self, data: Dict, stock_code: str) -> Tuple[float, Dict]:
        """
        技术面评分（35%权重）
        
        子维度：
        - 均线形态：40分
        - MACD信号：30分
        - 成交量验证：30分
        """
        score = 50.0
        detail = {}

        # 类型安全：数值字段做类型校验，非 number 则用默认值
        def _safe_float(val, default):
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        ma_status = data.get("ma_status", "neutral")        # bullish/bearish/neutral
        macd_status = data.get("macd_status", "neutral")     # golden/death/neutral
        volume_status = data.get("volume_status", "neutral") # 放量/缩量/正常
        rsi_value = _safe_float(data.get("rsi", 50), 50)

        # --- 子维度1: 均线形态（40分）---
        if ma_status == "bullish":
            ma_score = 40
        elif ma_status == "neutral":
            ma_score = 20
        else:  # bearish
            ma_score = 5

        # RSI辅助（超卖加分，超买减分）
        if rsi_value < 30:
            ma_score = min(ma_score + 10, 40)  # 超卖反弹机会
        elif rsi_value > 70:
            ma_score = max(ma_score - 10, 0)   # 超买风险

        detail["ma_status"] = ma_status
        detail["rsi"] = rsi_value
        detail["ma_score"] = ma_score

        # --- 子维度2: MACD信号（30分）---
        if macd_status == "golden":
            macd_score = 30
        elif macd_status == "neutral":
            macd_score = 15
        else:  # death
            macd_score = 0

        detail["macd_status"] = macd_status
        detail["macd_score"] = macd_score

        # --- 子维度3: 成交量验证（30分）---
        if volume_status == "放量上涨":
            vol_score = 30
        elif volume_status == "放量":
            vol_score = 20
        elif volume_status == "正常":
            vol_score = 15
        elif volume_status == "缩量":
            vol_score = 10
        else:
            vol_score = 5

        detail["volume_status"] = volume_status
        detail["volume_score"] = vol_score

        total = ma_score + macd_score + vol_score
        return total, detail

    def _score_fundamental(self, data: Dict, stock_code: str) -> Tuple[float, Dict]:
        """
        基本面评分（10%权重）

        2026-04-26 升级：全面接入 finviz 爬虫数据
        - finviz 机构持仓率（15%评级基准，比A股更权威）
        - finviz 盈利能力（Gross/Oper/Net Margin）
        - finviz 成长性（EPS YoY/未来增速/QoQ）
        - finviz 财务结构（Debt/Eq, Current/Quick Ratio）
        - finviz 估值（PE/Forward PE/PEG）

        子维度：
        - 机构持仓质量：25分  ← 新增（finviz权威数据）
        - 盈利能力：25分     ← 升级（Gross+Oper+Net Margin）
        - 成长性：25分       ← 升级（EPS YoY + 未来增速）
        - 财务结构：15分     ← 升级（Debt/Eq + 流动性比率）
        - 估值：10分         ← 升级（PE分位 + Forward PE + PEG）
        """
        detail = {}

        # ── finviz 数据提取（A股兼容）──
        # 2026-05-01 修复：AkShare使用 net_margin（≠profit_margin）和 gross_profit_margin（≠gross_margin）
        inst_pct    = data.get('inst_ownership_pct') or data.get('hsgt_hold_ratio')  # 机构持仓率（%）
        inst_trans  = data.get('inst_trans') or data.get('hsgt_add_ratio')          # 机构净买入率（%）
        gross_m     = data.get('gross_profit_margin') or data.get('gross_margin')   # 毛利率（%）
        oper_m      = data.get('operating_margin')       # 营益率（%）
        profit_m    = data.get('net_margin')             # 净利率（AkShare字段）
        eps_yoy     = data.get('eps_growth_yoy')         # EPS同比增速（%）
        eps_next_y  = data.get('eps_next_y')             # EPS预期增速（%，未来1年）
        eps_next_5y = data.get('eps_next_5y')            # EPS预期增速（%，未来5年）
        eps_qoq     = data.get('eps_qoq')                # EPS季环比（%）
        sales_qoq   = data.get('sales_qoq')              # 营收季环比（%）
        roe         = data.get('roe')                   # ROE（%）
        roa         = data.get('roa')                   # ROA（%）
        roic        = data.get('roic')                   # ROIC（%）
        debt_eq     = data.get('debt_eq')                # 负债率
        curr_ratio  = data.get('current_ratio')          # 流动比率
        quick_ratio = data.get('quick_ratio')            # 速动比率
        pe          = data.get('pe')                    # 市盈率TTM
        fwd_pe      = data.get('forward_pe')             # 前瞻PE
        peg         = data.get('peg_ratio')               # PEG
        beta        = data.get('beta')                   # Beta

        # ── 子维度1: 机构持仓质量（25分）──────────────────
        # 2026-05-01 修复：AkShare返回十进制小数(0.0655=6.55%)，阈值是百分位(5=5%)，需×100转换
        inst_pct_raw = data.get('inst_ownership_pct') or data.get('hsgt_hold_ratio')
        inst_pct_pct = (inst_pct_raw * 100) if inst_pct_raw is not None else None

        if inst_pct_pct is not None:
            if inst_pct_pct >= 60:      inst_score = 25
            elif inst_pct_pct >= 40:    inst_score = 22
            elif inst_pct_pct >= 25:    inst_score = 18
            elif inst_pct_pct >= 15:    inst_score = 15
            elif inst_pct_pct >= 5:     inst_score = 10
            else:                       inst_score = 5
        else:
            inst_score = 5
            detail["_inst_data_missing"] = True

        # 机构动向（净买入加分，净卖出减分）
        inst_trans = data.get('inst_trans') or data.get('hsgt_add_ratio')
        if inst_trans is not None:
            if inst_trans >= 5:        inst_score = min(inst_score + 5, 25)
            elif inst_trans >= 1:     inst_score = min(inst_score + 3, 25)
            elif inst_trans <= -5:     inst_score = max(inst_score - 8, 0)
            elif inst_trans <= -1:     inst_score = max(inst_score - 4, 0)

        detail['inst_ownership_pct'] = inst_pct_raw
        detail['inst_trans'] = inst_trans
        detail['inst_score'] = inst_score

        # ── 子维度2: 盈利能力（25分）─────────────────────
        # 三率综合评分：毛利率+营益率+净利率，取最高者
        # 2026-05-30修复：_valid() 需要过滤 "失败" 字符串（来自 L2 数据富化层）
        def _valid(v):
            if v is None: return False
            if isinstance(v, float) and v != v:  # NaN 自真检测
                return False
            if v == "失败":  # L2 层赋值为字符串 "失败" 的字段
                return False
            return True
        margins = [v for v in [gross_m, oper_m, profit_m] if _valid(v)]
        best_margin = max(margins) if margins else None

        if best_margin is not None:
            if best_margin >= 40:       margin_score = 25
            elif best_margin >= 25:     margin_score = 20
            elif best_margin >= 15:    margin_score = 15
            elif best_margin >= 5:     margin_score = 8
            else:                       margin_score = 3
        else:
            margin_score = 2   # null数据降权：毛利率数据不可得，极低分
            detail["_margin_data_missing"] = True

        # ROE/ROA/ROIC 加成（反映资本效率）
        roe_family = [v for v in [roe, roa, roic] if _valid(v)]
        best_roe = max(roe_family) if roe_family else None
        if best_roe is not None:
            if best_roe >= 30:         margin_score = min(margin_score + 5, 25)
            elif best_roe >= 20:       margin_score = min(margin_score + 3, 25)
            elif best_roe >= 10:       margin_score = min(margin_score + 1, 25)

        detail['gross_margin'] = gross_m
        detail['operating_margin'] = oper_m
        detail['profit_margin'] = profit_m
        detail['roe'] = roe
        detail['roa'] = roa
        detail['roic'] = roic
        detail['margin_score'] = margin_score

        # ── 子维度3: 成长性（25分）────────────────────────
        # 综合增速：EPS YoY(权重0.5) + 预期1年增速(权重0.3) + 5年预期(权重0.2)
        # 2026-05-30修复：使用 _valid() 过滤 "失败" 字符串
        growth_score = None
        if _valid(eps_yoy) or _valid(eps_next_y) or _valid(eps_next_5y):
            weighted = 0.0
            total_w = 0.0
            if _valid(eps_yoy):
                w = 0.5
                # cap at 100% for scoring purposes
                weighted += min(eps_yoy, 100) * w
                total_w += w
            if _valid(eps_next_y):
                w = 0.3
                weighted += min(eps_next_y, 100) * w
                total_w += w
            if _valid(eps_next_5y):
                w = 0.2
                # 5年化增速转年化
                annualised = (pow(1 + eps_next_5y / 100, 1/5) - 1) * 100 if eps_next_5y > -100 else -100
                weighted += min(annualised, 100) * w
                total_w += w
            growth_score = (weighted / total_w) if total_w > 0 else None

        if growth_score is not None:
            if growth_score >= 30:      profit_score = 25
            elif growth_score >= 20:    profit_score = 20
            elif growth_score >= 10:    profit_score = 15
            elif growth_score >= 5:     profit_score = 10
            elif growth_score >= 0:     profit_score = 6
            else:                       profit_score = 0
        else:
            profit_score = 2   # null数据降权：成长性数据不可得，极低分
            detail["_growth_data_missing"] = True

        # QoQ 验证（季环比趋势确认）
        if _valid(eps_qoq) and eps_qoq > 10:
            profit_score = min(profit_score + 3, 25)
        if _valid(sales_qoq) and sales_qoq > 10:
            profit_score = min(profit_score + 2, 25)

        detail['eps_growth_yoy'] = eps_yoy
        detail['eps_next_y'] = eps_next_y
        detail['eps_next_5y'] = eps_next_5y
        detail['eps_qoq'] = eps_qoq
        detail['sales_qoq'] = sales_qoq
        detail['growth_composite'] = round(growth_score, 2) if growth_score is not None else None
        detail['growth_score'] = profit_score

        # ── 子维度4: 财务结构（15分）──────────────────────
        # 负债率 + 流动性比率综合
        debt_score = None
        if _valid(debt_eq):
            if debt_eq <= 0.2:          debt_score = 10
            elif debt_eq <= 0.5:         debt_score = 7
            elif debt_eq <= 1.0:         debt_score = 4
            else:                         debt_score = 1

        liq_score = None
        if _valid(curr_ratio) or _valid(quick_ratio):
            best_liq = max(v for v in [curr_ratio, quick_ratio] if _valid(v))
            if best_liq >= 2.0:         liq_score = 5
            elif best_liq >= 1.5:        liq_score = 4
            elif best_liq >= 1.0:        liq_score = 3
            else:                         liq_score = 1

        fin_score = 0
        if debt_score is not None: fin_score += debt_score
        if liq_score is not None: fin_score += liq_score
        # 负债率和流动性比率各有权重
        if debt_score is not None and liq_score is not None:
            fin_score = debt_score * 0.6 + liq_score * 0.4
            fin_score = round(fin_score)
        elif debt_score is None and liq_score is None:
            fin_score = 2   # null数据降权：财务结构数据不可得，极低分
            detail["_fin_data_missing"] = True

        detail['debt_eq'] = debt_eq
        detail['current_ratio'] = curr_ratio
        detail['quick_ratio'] = quick_ratio
        detail['financial_score'] = fin_score

        # ── 子维度5: 估值（10分）────────────────────────────
        # Forward PE 为主，PEG 辅助
        val_score = None
        if _valid(fwd_pe) and fwd_pe > 0:
            # 半导体行业合理 Forward PE 15-30x
            if fwd_pe <= 15:            val_score = 10
            elif fwd_pe <= 20:          val_score = 8
            elif fwd_pe <= 25:          val_score = 6
            elif fwd_pe <= 30:          val_score = 4
            elif fwd_pe <= 40:          val_score = 2
            else:                        val_score = 0
        elif _valid(pe) and pe > 0:
            if pe <= 20:                val_score = 8
            elif pe <= 30:              val_score = 6
            elif pe <= 40:              val_score = 3
            else:                        val_score = 1

        # PEG 辅助判断成长估值匹配度
        if _valid(peg) and peg > 0 and val_score is not None:
            if peg <= 1.0:             val_score = min(val_score + 2, 10)
            elif peg > 2.0:             val_score = max(val_score - 2, 0)

        if val_score is None:
            val_score = 1   # null数据降权：估值数据不可得，极低分
            detail["_val_data_missing"] = True

        detail['pe'] = pe
        detail['forward_pe'] = fwd_pe
        detail['peg_ratio'] = peg
        detail['valuation_score'] = val_score

        total = inst_score + margin_score + profit_score + fin_score + val_score

        # _sub_max: 实际满分（只有数据完整的子维度才计入）
        # 5个子维度: inst(25) + margin(25) + growth(25) + fin(15) + val(10) = 100
        _sub_max = 100
        if '_inst_data_missing' in detail:   _sub_max -= 25
        if '_margin_data_missing' in detail: _sub_max -= 25
        if '_growth_data_missing' in detail: _sub_max -= 25
        if '_fin_data_missing' in detail:    _sub_max -= 15
        if '_val_data_missing' in detail:    _sub_max -= 10
        detail['_sub_max'] = _sub_max

        return total, detail

    def _score_sector(self, data: Dict, stock_code: str) -> Tuple[float, Dict]:
        """
        板块强度评分（10%权重）

        子维度：
        - 板块涨跌幅排名：50分
        - 板块资金流入：50分
        """
        detail = {}

        # ── 数据真实性检查 ──────────────────────────────────────
        sector_rank = data.get("sector_rank", 50)
        # 2026-04-26增强：若sector_rank=50（默认中性）但rank_position有真实数据，用rank_position换算
        rank_position = data.get("rank_position")
        if sector_rank == 50 and rank_position and rank_position != 9999 and rank_position > 0:
            # rank_position=6（第6名/5179）→ 百分位 = (1 - 6/5179)*100 = 99.88
            sector_count_for_pct = data.get("sector_count", 5179)
            sector_rank = round((1 - rank_position / max(sector_count_for_pct, 1)) * 100, 1)
        sector_flow = data.get("sector_fund_flow", 0)
        sector_count = data.get("sector_count", 0) or 0  # None → 0
        sector_strength = data.get("sector_strength", None)
        data_source = data.get("_source", "")

        # 判断是否"数据实质缺失"（2026-04-29修复：同时处理None和0）
        # 条件：sector_count in (None,0) 表示没有真实的板块排名/资金流数据
        # 注：BaoStock行业分类只提供"该股票属于哪个行业"，不提供"行业今日涨跌排名"
        # 因此sector_rank=55 + sector_count=None 实质也是数据缺失
        # 2026-05-06修复：strength_label='unknown' 也视为数据缺失（港股行业数据获取不稳定）
        is_data_missing = (sector_count in (None, 0) and not sector_strength) or (sector_strength == 'unknown')

        if is_data_missing:
            # 数据实质缺失：不给中性分，只给基准分10分（低于中性的20分）
            # 不触发否决，但明确标注数据不可用
            rank_score = 5       # 降权
            flow_score = 5       # 降权
            detail["_data_missing"] = True
            detail["_data_missing_warning"] = "板块数据不可得，评分降权处理"
            detail["sector_rank_percentile"] = sector_rank
            detail["sector_rank_score"] = rank_score
            detail["sector_fund_flow"] = sector_flow
            detail["sector_fund_flow_score"] = flow_score
            total = rank_score + flow_score
            detail["_sub_max"] = 10  # rank(5) + flow(5) = 10，实际满分10分
            return total, detail
        # ── 正常评分 ───────────────────────────────────────────

        # 板块排名评分（A股用rank_pct，美股用sector_strength标签）
        if sector_strength:
            # 美股 SPDR ETF 标签评分（sector_rank 传入的是52w位置pct，但用strength标签更直接）
            strength_upper = sector_strength.upper()
            if '强势' in sector_strength or 'STRONG' in strength_upper:
                rank_score = 40
            elif '中性' in sector_strength or 'NEUTRAL' in strength_upper:
                rank_score = 20
            elif '弱势' in sector_strength or 'WEAK' in strength_upper:
                rank_score = 10
            else:
                rank_score = 20  # 未知标签默认为中性
        elif sector_rank >= 90:
            rank_score = 50
        elif sector_rank >= 70:
            rank_score = 35
        elif sector_rank >= 50:
            rank_score = 20
        else:
            rank_score = 10

        # 板块资金评分
        if sector_flow > 1_000_000_000:
            flow_score = 50
        elif sector_flow > 100_000_000:
            flow_score = 35
        elif sector_flow > 0:
            flow_score = 20
        else:
            flow_score = 5

        detail["sector_rank_percentile"] = sector_rank
        detail["sector_rank_score"] = rank_score
        detail["sector_fund_flow"] = sector_flow
        detail["sector_fund_flow_score"] = flow_score

        total = rank_score + flow_score
        return total, detail

    def _score_event(self, data: Dict, stock_code: str) -> Tuple[float, Dict]:
        """
        事件驱动评分（10%权重）

        子维度：
        - 利好事件：60分（业绩预告/订单/政策）
        - 机构关注度：40分（研报数量/评级上调）
        """
        detail = {}

        positive_events = data.get("positive_events", [])
        analyst_rating = data.get("analyst_rating", "neutral")  # buy/neutral/sell
        report_count = data.get("report_count_30d", 0)

        # ── 过滤全市场统计事件（2026-04-29修复）────────────────────
        # 全市场统计事件示例："今日369只个股突破五日均线"、"A股三大指数集体上涨"
        # 这类事件描述的是全市场/板块整体状态，不是该个股特有的催化剂
        generic_patterns = [
            "只个股", "今日", "市场", "大盘", "全市", "整体上涨", "整体下跌",
            "指数", "板块", "行业", "集体", "普遍", "涨停", "跌停", "飘红", "飘绿",
            "成交额", "换手率", "北向资金", "主力资金", "超大单", "大单", "中单", "小单",
            "突破五日", "突破十日", "MACD", "KDJ", "RSI", "boll", "BOLL",
        ]
        def is_stock_specific(event: str) -> bool:
            """判断事件是否是个股特有事件（非全市场统计）"""
            if not event or not isinstance(event, str):
                return False
            event_lower = event.lower()
            # 明确标记为个股事件的模式
            specific_patterns = ["中标", "签约", "合同", "订单", "业绩", "分红", "回购",
                                "增持", "减持", "收购", "重组", "资产", "新产品", "新技术",
                                "政策", "批文", "许可", "认证", "专利", "研发",
                                "评级上调", "评级下调", "目标价", "研报", "券商",
                                "分红预案", "利润分配", "送转", "配股"]
            for p in specific_patterns:
                if p in event_lower:
                    return True
            # 排除全市场统计模式
            for p in generic_patterns:
                if p in event:
                    return False
            # 不包含通用模式，但也不包含明确个股模式 → 保守处理，保留
            return True

        filtered_events = [e for e in positive_events if is_stock_specific(e)]
        detail["_event_filtered"] = len(positive_events) - len(filtered_events)
        detail["_event_filtered_examples"] = [
            e for e in positive_events if not is_stock_specific(e)
        ][:3]  # 保留最多3个被过滤的例子用于调试
        positive_events = filtered_events
        # ── 过滤完成 ────────────────────────────────────────────

        # 利好事件评分
        event_count = len(positive_events)
        if event_count >= 3:
            event_score = 60
        elif event_count == 2:
            event_score = 45
        elif event_count == 1:
            event_score = 25
        else:
            event_score = 5

        detail["positive_event_count"] = event_count
        detail["positive_events"] = positive_events[:5] if positive_events else []
        detail["event_score"] = event_score

        # 机构关注度评分
        if analyst_rating == "buy" and report_count >= 5:
            analyst_score = 40
        elif analyst_rating == "buy":
            analyst_score = 30
        elif analyst_rating == "neutral":
            analyst_score = 15
        else:
            analyst_score = 0

        detail["analyst_rating"] = analyst_rating
        detail["report_count_30d"] = report_count
        detail["analyst_score"] = analyst_score

        total = event_score + analyst_score
        return total, detail

    # ==================== 辅助方法 ====================

    def _get_grade(self, score: float) -> str:
        """根据综合评分给出等级"""
        if score >= 80:
            return "A"  # 强力推荐
        elif score >= 65:
            return "B"  # 关注
        elif score >= 50:
            return "C"  # 观望
        else:
            return "D"  # 回避

    def update_weights(self, new_weights: Dict[str, float]):
        """运行时更新权重配置"""
        total = sum(new_weights.values())
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"权重总和应为1.0，当前{total}")
        self.weights = new_weights
        logger.info(f"权重已更新: {self.weights}")

    def score_from_api(self, code: str, name: str = "") -> StockScoreResult:
        """
        从实时数据源获取数据并评分 — 一键评分入口
        
        Args:
            code: 股票代码（如 "600519", "002594"）
            name: 股票名称（可选）
        
        Returns:
            StockScoreResult 综合评分结果
        
        数据流：
            fetch_all(code, name) 
            → data dict (moneyflow/technical/fundamental/sector/event)
            → score_stock(code, name, data)
        """
        try:
            from data.realtime_data_fetcher import fetch_all
            data = fetch_all(code, name)
            result = self.score_stock(code, name or code, data)
            result.calculation_time_ms = round(result.calculation_time_ms, 1)
            return result
        except ImportError:
            logger.error("realtime_data_fetcher 未安装，请确保 data/ 目录在 PYTHONPATH 中")
            raise
        except Exception as e:
            logger.error(f"实时评分失败 {code}: {e}")
            raise

    def batch_score_from_api(self, stock_list: List[Dict[str, str]]) -> List[StockScoreResult]:
        """
        批量实时评分 — 从API获取数据后评分并排序
        
        Args:
            stock_list: [{"code": "600519", "name": "贵州茅台"}, ...]
        
        Returns:
            按综合分降序排列的评分结果列表
        """
        results = []
        total = len(stock_list)
        for i, stock in enumerate(stock_list):
            code = stock.get("code", "")
            name = stock.get("name", "")
            logger.info(f"[{i+1}/{total}] 评分 {name} ({code})...")
            try:
                result = self.score_from_api(code, name)
                results.append(result)
            except Exception as e:
                logger.error(f"评分失败 {code}: {e}")
                # 即使失败也返回一个默认结果，保证批量不会中断
                from datetime import datetime
                result = StockScoreResult(
                    stock_code=code,
                    stock_name=name or code,
                    score_date=datetime.now().strftime("%Y-%m-%d"),
                    five_score=0.0,
                    grade="D",
                )
                results.append(result)
        
        results.sort(key=lambda r: r.five_score, reverse=True)
        return results

# ======================== 测试入口 ========================

def test_scorer():
    """用模拟数据测试五维评分引擎"""
    scorer = FiveDimensionScorer()
    
    test_data = {
        "moneyflow_data": {
            "main_net_flow_5d": 80_000_000,   # 8000万净流入
            "large_order_ratio": 0.25,
            "main_direction": "流入",
            "retail_direction": "流出",
            "daily_flows": [20_000_000, 30_000_000, 30_000_000],
            "_source": "AkShare(模拟数据)",
        },
        "technical_data": {
            "ma_status": "bullish",
            "macd_status": "golden",
            "volume_status": "放量上涨",
            "rsi": 45,
            "_source": "BaoStock(模拟数据)",
        },
        "fundamental_data": {
            "roe": 18.5,
            "net_profit_yoy": 22.3,
            "pb": 1.8,
            "_source": "腾讯行情API(模拟数据)",
        },
        "sector_data": {
            "sector_rank": 85,
            "sector_fund_flow": 500_000_000,
            "_source": "AkShare(模拟数据)",
        },
        "event_data": {
            "positive_events": ["业绩预增50%", "中标大单", "政策利好"],
            "analyst_rating": "buy",
            "report_count_30d": 8,
            "_source": "东方财富(模拟数据)",
        },
    }
    
    result = scorer.score_stock("600519", "贵州茅台", test_data)
    
    print("=" * 60)
    print("五维评分测试结果")
    print("=" * 60)
    print(f"股票: {result.stock_name} ({result.stock_code})")
    print(f"日期: {result.score_date}")
    print(f"五维度评分: {result.five_score:.1f} | 等级: {result.grade}")
    print(f"计算耗时: {result.calculation_time_ms:.1f}ms")
    print()
    
    for key, detail in result.scores.items():
        print(f"  [{key}] {detail.dimension_name}: {detail.score:.1f} × {detail.weight:.0%} = {detail.weighted_score:.1f}")
        for k, v in detail.detail.items():
            print(f"    └ {k}: {v}")
    
    print()
    print("测试通过！五维评分引擎可正常使用。")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_scorer()
