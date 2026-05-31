#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票分类引擎 — 价值股/增长股/短线股/困境反转识别

基于财务指标 + 技术指标 + 资金流 进行股票分类
为动态权重配置和持仓管理提供基础

分类逻辑：
- 价值股(Value): 低估值 + 高股息 + 稳定盈利
- 增长股(Growth): 高营收增速 + 毛利提升 + 行业空间
- 短线股(Momentum): 题材驱动 + 放量 + 趋势确认
- 困境反转(Turnaround): ROE触底 + 行业拐点 + 负债改善
"""

import sys, os
BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import log_start, log_end, log_fail, info

import logging
from typing import Dict, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger("stock_classifier")


class StockType(Enum):
    VALUE = "价值股"      # 低估值高股息，长期持有
    GROWTH = "增长股"     # 高成长性，中期持有
    MOMENTUM = "短线股"   # 题材动量，短期持有
    TURNAROUND = "困境反转"  # 困境反转，中期持有
    UNCLASSIFIED = "未分类"


@dataclass
class ClassificationResult:
    stock_type: StockType
    confidence: float  # 0-1，分类置信度
    reasoning: str     # 分类理由
    key_metrics: Dict[str, float]  # 关键指标
    position_guide: Dict[str, Any]  # 持仓指引
    subtypes: Dict[str, float]  # 各类型匹配度


# ─── 持仓指引配置 ─────────────────────────────────────────
POSITION_GUIDES = {
    StockType.VALUE: {
        "holding_period": "6-12个月",
        "stop_loss": -0.25,
        "target_return": 0.30,
        "weight_recommended": 0.10,
        "review_frequency": "每月",
        "key_metrics": ["PE", "股息率", "ROE", "PB"],
    },
    StockType.GROWTH: {
        "holding_period": "3-6个月",
        "stop_loss": -0.20,
        "target_return": 0.40,
        "weight_recommended": 0.08,
        "review_frequency": "每周",
        "key_metrics": ["营收增速", "毛利趋势", "行业空间", "研发费用"],
    },
    StockType.MOMENTUM: {
        "holding_period": "1-4周",
        "stop_loss": -0.15,
        "target_return": 0.20,
        "weight_recommended": 0.05,
        "review_frequency": "每日",
        "key_metrics": ["题材匹配", "量比", "MACD", "RSI"],
    },
    StockType.TURNAROUND: {
        "holding_period": "3-9个月",
        "stop_loss": -0.20,
        "target_return": 0.50,
        "weight_recommended": 0.08,
        "review_frequency": "每两周",
        "key_metrics": ["ROE触底", "行业景气", "负债率", "现金流"],
    },
}


# ─── 分类器 ───────────────────────────────────────────────
class StockClassifier:
    """
    股票分类引擎
    
    输入：五维评分数据（含基本面/技术面/资金面/情绪面）
    输出：StockType + 置信度 + 持仓指引
    """

    def classify(self, data: Dict[str, Any], code: str = "", name: str = "") -> ClassificationResult:
        """
        对单只股票进行分类
        
        Args:
            data: 五维评分数据，包含 fundamental_data, technical_data, moneyflow_data, sector_data, event_data
            code: 股票代码
            name: 股票名称
        
        Returns:
            ClassificationResult
        """
        fundamental = data.get("fundamental_data", {})
        technical = data.get("technical_data", {})
        moneyflow = data.get("moneyflow_data", {})
        sector = data.get("sector_data", {})
        event = data.get("event_data", {})
        
        # 计算各类型匹配度
        value_score = self._score_value(fundamental, sector)
        growth_score = self._score_growth(fundamental)
        momentum_score = self._score_momentum(technical, moneyflow, event)
        turnaround_score = self._score_turnaround(fundamental, sector)
        
        subtypes = {
            "价值股": value_score,
            "增长股": growth_score,
            "短线股": momentum_score,
            "困境反转": turnaround_score,
        }
        
        # 确定最高匹配类型
        best_type = max(subtypes, key=subtypes.get)
        best_score = subtypes[best_type]
        
        # 计算置信度（最高分 - 次高分的差距 + 绝对值归一化）
        sorted_scores = sorted(subtypes.values(), reverse=True)
        margin = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]
        confidence = min(0.95, max(0.3, best_score - margin * 0.3 + 0.1))
        
        # 特殊规则覆盖
        type_enum, override_reason = self._apply_rules(
            best_type, fundamental, technical, moneyflow, event, subtypes
        )
        
        # 生成理由
        reasoning = self._generate_reasoning(
            type_enum, subtypes, fundamental, technical, event
        )
        
        # 持仓指引
        guide = POSITION_GUIDES[type_enum].copy()
        guide["override_reason"] = override_reason
        
        return ClassificationResult(
            stock_type=type_enum,
            confidence=round(confidence, 2),
            reasoning=reasoning,
            key_metrics={
                "value_score": round(value_score, 2),
                "growth_score": round(growth_score, 2),
                "momentum_score": round(momentum_score, 2),
                "turnaround_score": round(turnaround_score, 2),
            },
            position_guide=guide,
            subtypes=subtypes,
        )

    def _score_value(self, fundamental: Dict, sector: Dict) -> float:
        """
        价值股评分：低估值 + 高股息 + 稳定盈利
        """
        score = 0.0
        metrics = {}
        
        # PE评分（越低越好）
        pe = fundamental.get("pe_ttm") or fundamental.get("pe")
        if pe and pe > 0:
            if pe < 10:
                score += 0.35
                metrics["pe"] = pe
            elif pe < 15:
                score += 0.25
                metrics["pe"] = pe
            elif pe < 20:
                score += 0.15
                metrics["pe"] = pe
            elif pe < 30:
                score += 0.05
                metrics["pe"] = pe
            # PE<0 为亏损，不加分
        
        # 股息率评分（越高越好）
        dividend_yield = fundamental.get("dividend_yield") or 0.0
        if dividend_yield > 5:
            score += 0.30
            metrics["dividend_yield"] = dividend_yield
        elif dividend_yield > 3:
            score += 0.20
            metrics["dividend_yield"] = dividend_yield
        elif dividend_yield > 1:
            score += 0.10
            metrics["dividend_yield"] = dividend_yield
        
        # ROE评分（越高越稳定）
        roe = fundamental.get("roe") or 0.0
        if roe > 20:
            score += 0.25
            metrics["roe"] = roe
        elif roe > 15:
            score += 0.20
            metrics["roe"] = roe
        elif roe > 10:
            score += 0.10
            metrics["roe"] = roe
        
        # PB评分（越低越好）
        pb = fundamental.get("pb")
        if pb and pb > 0:
            if pb < 1.5:
                score += 0.10
                metrics["pb"] = pb
            elif pb < 3:
                score += 0.05
                metrics["pb"] = pb
        
        return min(1.0, score)

    def _score_growth(self, fundamental: Dict) -> float:
        """
        增长股评分：高营收增速 + 毛利提升
        """
        score = 0.0
        
        # 营收增速（核心指标）
        revenue_growth = fundamental.get("revenue_growth") or fundamental.get("营收增速") or 0.0
        if revenue_growth > 50:
            score += 0.40
        elif revenue_growth > 30:
            score += 0.30
        elif revenue_growth > 20:
            score += 0.20
        elif revenue_growth > 10:
            score += 0.10
        
        # 毛利趋势（连续提升为佳）
        gross_margin = fundamental.get("gross_margin") or 0.0
        if gross_margin > 50:
            score += 0.30
        elif gross_margin > 30:
            score += 0.20
        elif gross_margin > 15:
            score += 0.10
        
        # 净利润增速
        net_profit_growth = fundamental.get("net_profit_growth") or fundamental.get("净利润增速") or 0.0
        if net_profit_growth > 30:
            score += 0.20
        elif net_profit_growth > 15:
            score += 0.10
        
        # 研发费用占比（科创属性）
        rd_expense_ratio = fundamental.get("rd_ratio") or 0.0
        if rd_expense_ratio > 10:
            score += 0.10
        elif rd_expense_ratio > 5:
            score += 0.05
        
        return min(1.0, score)

    def _score_momentum(self, technical: Dict, moneyflow: Dict, event: Dict) -> float:
        """
        短线股评分：题材 + 放量 + 趋势
        """
        score = 0.0
        
        # 题材/事件驱动（最重要）
        positive_events = event.get("positive_events", [])
        event_count = event.get("news_count", 0) or len(positive_events)
        if event_count >= 5:
            score += 0.30
        elif event_count >= 3:
            score += 0.20
        elif event_count >= 1:
            score += 0.10
        
        # 成交量放大（量比）
        volume_ratio = technical.get("volume_ratio") or 0.0
        if volume_ratio > 2.0:
            score += 0.30
        elif volume_ratio > 1.5:
            score += 0.20
        elif volume_ratio > 1.2:
            score += 0.10
        
        # MACD金叉
        macd_signal = technical.get("macd_signal") or technical.get("macd")
        if macd_signal == "golden_cross":
            score += 0.20
        elif macd_signal == "bullish":
            score += 0.10
        
        # 资金流入
        main_net_inflow = moneyflow.get("main_net_inflow") or 0.0
        if main_net_inflow > 1_000_000_000:  # 10亿
            score += 0.20
        elif main_net_inflow > 500_000_000:  # 5亿
            score += 0.10
        
        return min(1.0, score)

    def _score_turnaround(self, fundamental: Dict, sector: Dict) -> float:
        """
        困境反转评分：ROE触底 + 行业拐点
        """
        score = 0.0
        
        # ROE触底回升信号
        roe = fundamental.get("roe") or 0.0
        roe_trend = fundamental.get("roe_trend") or "unknown"
        if roe_trend == "recovering" or roe_trend == "触底回升":
            score += 0.35
        elif roe_trend == "declining":
            score += 0.15  # 困境中，触底后有反转可能
        
        # 行业景气度触底
        sector_momentum = sector.get("sector_momentum") or sector.get("板块动量") or 0.0
        if sector_momentum > 0:
            score += 0.25  # 行业开始回升
        elif sector_momentum < -0.1:
            score += 0.15  # 行业低谷，可能反转
        
        # 负债率下降趋势
        debt_ratio = fundamental.get("debt_ratio") or 0.0
        debt_trend = fundamental.get("debt_trend") or "unknown"
        if debt_trend == "declining" and debt_ratio > 50:
            score += 0.20
        
        # 现金流改善
        operating_cashflow = fundamental.get("operating_cashflow") or 0.0
        if operating_cashflow > 0:
            score += 0.20
        
        return min(1.0, score)

    def _apply_rules(
        self,
        best_type: str,
        fundamental: Dict,
        technical: Dict,
        moneyflow: Dict,
        event: Dict,
        subtypes: Dict
    ) -> Tuple[StockType, str]:
        """
        特殊规则覆盖：某些指标直接决定类型
        """
        # 规则1: PE<0（亏损）不能是价值股
        pe = fundamental.get("pe_ttm") or fundamental.get("pe")
        if best_type == "价值股" and pe is not None and pe < 0:
            # 亏损股降级为增长股（如果有增长）或短线股
            if subtypes["增长股"] > 0.3:
                return StockType.GROWTH, "PE<0，亏损，不能归类为价值股"
            elif subtypes["短线股"] > 0.3:
                return StockType.MOMENTUM, "PE<0，亏损，转为短线题材"
        
        # 规则2: 强烈事件驱动的，优先短线股
        strong_event_count = len(event.get("positive_events", []))
        if strong_event_count >= 5 and subtypes.get("短线股", 0) >= 0.3:
            if subtypes["短线股"] >= subtypes.get("增长股", 0):
                return StockType.MOMENTUM, f"强烈事件驱动({strong_event_count}条利好)"
        
        # 规则3: 极度高增长(营收>100%)归类为增长股
        revenue_growth = fundamental.get("revenue_growth") or 0.0
        if revenue_growth > 100:
            return StockType.GROWTH, f"营收增速{revenue_growth:.0f}%，超强成长"
        
        # 规则4: 稳定高分红(>5%)优先价值股
        dividend_yield = fundamental.get("dividend_yield") or 0.0
        if dividend_yield > 5 and subtypes.get("价值股", 0) >= 0.2:
            return StockType.VALUE, f"高股息{dividend_yield:.1f}%，稳定收益"
        
        return StockType(best_type), ""

    def _generate_reasoning(
        self,
        stock_type: StockType,
        subtypes: Dict[str, float],
        fundamental: Dict,
        technical: Dict,
        event: Dict
    ) -> str:
        """生成人类可读的分类理由"""
        type_names = {
            StockType.VALUE: "价值股",
            StockType.GROWTH: "增长股",
            StockType.MOMENTUM: "短线股",
            StockType.TURNAROUND: "困境反转",
            StockType.UNCLASSIFIED: "未分类",
        }
        
        reason = f"【{type_names[stock_type]}】"
        
        if stock_type == StockType.VALUE:
            pe = fundamental.get("pe_ttm") or fundamental.get("pe")
            roe = fundamental.get("roe", 0)
            div = fundamental.get("dividend_yield", 0)
            if pe: reason += f"PE={pe:.1f}"
            if roe: reason += f"，ROE={roe:.1f}%"
            if div: reason += f"，股息率={div:.1f}%"
        
        elif stock_type == StockType.GROWTH:
            rev = fundamental.get("revenue_growth", 0)
            gm = fundamental.get("gross_margin", 0)
            if rev: reason += f"营收增速={rev:.1f}%"
            if gm: reason += f"，毛利率={gm:.1f}%"
        
        elif stock_type == StockType.MOMENTUM:
            events = len(event.get("positive_events", []))
            vr = technical.get("volume_ratio", 0)
            if events: reason += f"事件驱动({events}条利好)"
            if vr: reason += f"，量比={vr:.1f}"
        
        elif stock_type == StockType.TURNAROUND:
            roe_trend = fundamental.get("roe_trend", "未知")
            reason += f"ROE趋势={roe_trend}"
        
        # 添加次高类型作为参考
        sorted_types = sorted(subtypes.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_types) > 1:
            second = sorted_types[1]
            reason += f"（次选：{second[0]} {second[1]:.0%}）"
        
        return reason


# ─── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    # 简单测试
    classifier = StockClassifier()

    # 模拟价值股数据
    log_start("stock_classifier", "test", "模拟价值股")
    value_data = {
        "fundamental_data": {"pe": 8.5, "roe": 18.0, "dividend_yield": 4.2, "pb": 1.2},
        "technical_data": {},
        "moneyflow_data": {},
        "sector_data": {},
        "event_data": {},
    }

    result = classifier.classify(value_data, "600519", "贵州茅台")
    log_end("stock_classifier", "test", f"贵州茅台: {result.stock_type.value}")
    print(f"\n模拟价值股测试:")
    print(f"  类型: {result.stock_type.value}")
    print(f"  置信度: {result.confidence:.0%}")
    print(f"  理由: {result.reasoning}")
    print(f"  各类型得分: {result.key_metrics}")
    print(f"  持仓指引: {result.position_guide}")
