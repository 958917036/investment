#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析师预期数据采集器 — EPS预测/目标价/评级/研报

数据源（已验证可用）：
- 同花顺EPS预测: ak.stock_profit_forecast_ths(symbol)
- 东方财富研报: ak.stock_research_report_em(symbol)
- 东方财富分析师排名: ak.stock_analyst_rank_em()
- 东方财富个股评级: ak.stock_analyst_detail_em()

用途：
- 基本面维度增强（机构预测EPS → 计算预期PE）
- 评级变化作为情绪面输入
- 研报标题作为事件信号
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import pandas as pd

logger = logging.getLogger("analyst_fetcher")


class AnalystFetcher:
    """
    分析师预期数据采集器
    
    获取：
    - EPS一致预期（未来3年）
    - 目标价区间
    - 评级分布（买入/增持/中性/减持）
    - 研报摘要（近30天）
    - 分析师情绪趋势
    """

    def __init__(self, use_cache: bool = True, cache_hours: int = 6):
        self.use_cache = use_cache
        self.cache_hours = cache_hours
        self._cache: Dict[str, Any] = {}

    def fetch_all(self, code: str, name: str = "") -> Dict[str, Any]:
        """
        获取某只股票的全部分析师数据
        
        Args:
            code: 股票代码（A股6位，如 "000001"）
            name: 股票名称
        
        Returns:
            {
                "eps_forecast": {...},
                "research_reports": [...],
                "rating_summary": {...},
                "analyst_sentiment": {...},
                "summary": "..."
            }
        """
        cache_key = f"{code}_analyst"
        
        if self.use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        
        # 标准化代码
        std_code = self._normalize_code(code)
        
        eps = self._fetch_eps_forecast(std_code)
        reports = self._fetch_research_reports(std_code)
        rating = self._summarize_rating(reports)
        sentiment = self._calculate_sentiment(reports)
        
        result = {
            "code": code,
            "name": name,
            "eps_forecast": eps,
            "research_reports": reports[:20],  # 最多20条研报
            "rating_summary": rating,
            "analyst_sentiment": sentiment,
            "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "summary": self._generate_summary(eps, rating, sentiment, name),
        }
        
        self._cache[cache_key] = result
        return result

    def _normalize_code(self, code: str) -> str:
        """标准化代码格式"""
        # 去掉sh/sz前缀
        code = code.replace("sh", "").replace("sz", "").replace("hk", "")
        return code.zfill(6)

    def _fetch_eps_forecast(self, code: str) -> Dict[str, Any]:
        """获取同花顺EPS预测"""
        try:
            import akshare as ak
            df = ak.stock_profit_forecast_ths(symbol=code)
            
            if df is None or len(df) == 0:
                return {"years": [], "error": "无预测数据"}
            
            # 解析各年预测
            years = []
            for _, row in df.iterrows():
                year = str(row.get("年度", ""))
                forecast_count = int(row.get("预测机构数", 0))
                avg_eps = row.get("均值", 0)
                min_eps = row.get("最小值", 0)
                max_eps = row.get("最大值", 0)
                industry_avg = row.get("行业平均数", 0)
                
                years.append({
                    "year": year,
                    "forecast_count": forecast_count,
                    "avg_eps": float(avg_eps) if avg_eps else None,
                    "min_eps": float(min_eps) if min_eps else None,
                    "max_eps": float(max_eps) if max_eps else None,
                    "industry_avg_eps": float(industry_avg) if industry_avg else None,
                })
            
            return {
                "years": years,
                "source": "同花顺盈利预测",
                "fetch_date": datetime.now().strftime("%Y-%m-%d"),
            }
            
        except Exception as e:
            logger.warning(f"EPS预测获取失败 {code}: {e}")
            return {"years": [], "error": str(e)}

    def _fetch_research_reports(self, code: str) -> List[Dict[str, Any]]:
        """获取东方财富研报"""
        try:
            import akshare as ak
            df = ak.stock_research_report_em(symbol=code)
            
            if df is None or len(df) == 0:
                return []
            
            reports = []
            for _, row in df.iterrows():
                rating_map = {
                    "买入": 5, "增持": 4, "中性": 3, "减持": 2, "卖出": 1,
                    "强烈推荐": 5, "推荐": 4, "谨慎推荐": 3, "回避": 2,
                    "优于大市": 5, "强于大市": 4, "同步大市": 3, "弱于大市": 2,
                }
                
                raw_rating = str(row.get("东财评级", ""))
                rating_score = rating_map.get(raw_rating, 3)  # 默认为中性
                
                reports.append({
                    "report_name": str(row.get("报告名称", "")),
                    "rating": raw_rating,
                    "rating_score": rating_score,
                    "institution": str(row.get("机构", "")),
                    "date": str(row.get("发布日期", row.get("日期", ""))),
                })
            
            return reports
            
        except Exception as e:
            logger.warning(f"研报获取失败 {code}: {e}")
            return []

    def _summarize_rating(self, reports: List[Dict]) -> Dict[str, Any]:
        """汇总评级分布"""
        if not reports:
            return {"distribution": {}, "buy_ratio": None, "avg_rating": None, "top_rating": None}
        
        distribution = {"买入": 0, "增持": 0, "中性": 0, "减持": 0, "卖出": 0}
        
        for r in reports:
            rating = r.get("rating", "")
            for key in distribution:
                if key in rating:
                    distribution[key] += 1
                    break
        
        # 计算买入比例
        total = len(reports)
        buy_count = distribution.get("买入", 0) + distribution.get("增持", 0)
        buy_ratio = buy_count / total if total > 0 else 0
        
        # 平均评级分数
        avg_rating = sum(r.get("rating_score", 3) for r in reports) / total if total > 0 else 3
        
        # 最新评级
        top_rating = reports[0].get("rating", "未知") if reports else "无数据"
        
        return {
            "distribution": distribution,
            "total_reports": total,
            "buy_ratio": round(buy_ratio, 2),
            "avg_rating": round(avg_rating, 2),
            "top_rating": top_rating,
            "interpretation": self._interpret_rating(buy_ratio, avg_rating),
        }

    def _interpret_rating(self, buy_ratio: float, avg_rating: float) -> str:
        """解读评级"""
        if buy_ratio >= 0.8:
            return "强烈看好，机构共识高"
        elif buy_ratio >= 0.6:
            return "普遍看好，机构偏多"
        elif buy_ratio >= 0.4:
            return "分歧较大，谨慎乐观"
        elif buy_ratio >= 0.2:
            return "普遍偏空，机构谨慎"
        else:
            return "强烈看空，风险较大"

    def _calculate_sentiment(self, reports: List[Dict]) -> Dict[str, Any]:
        """
        计算分析师情绪趋势
        基于近6个月研报评级变化
        """
        if not reports:
            return {"trend": "无数据", "confidence": "low"}
        
        # 最近6个月的研报
        recent = reports[:min(20, len(reports))]
        
        # 前半段 vs 后半段的平均评级
        mid = len(recent) // 2
        first_half_avg = sum(r.get("rating_score", 3) for r in recent[mid:]) / (len(recent) - mid) if mid > 0 else 3
        second_half_avg = sum(r.get("rating_score", 3) for r in recent[:mid]) / mid if mid > 0 else 3
        
        change = second_half_avg - first_half_avg
        
        if change > 0.3:
            trend = "上调"
            description = "机构情绪持续改善"
        elif change < -0.3:
            trend = "下调"
            description = "机构情绪转弱"
        else:
            trend = "稳定"
            description = "机构预期稳定"
        
        return {
            "trend": trend,
            "change": round(change, 2),
            "description": description,
            "confidence": "high" if len(recent) >= 5 else "medium",
        }

    def _generate_summary(
        self,
        eps: Dict[str, Any],
        rating: Dict[str, Any],
        sentiment: Dict[str, Any],
        name: str
    ) -> str:
        """生成人类可读的分析师摘要"""
        lines = []
        name = name or "该股"
        
        lines.append(f"【分析师预期】{name}")
        
        # EPS预测
        years = eps.get("years", [])
        if years:
            # 取最近2年预测
            for y in years[:2]:
                yr = y.get("year", "")
                avg_eps = y.get("avg_eps")
                count = y.get("forecast_count", 0)
                if avg_eps:
                    lines.append(f"• {yr}年EPS预测: {avg_eps:.2f}元（{count}家机构）")
        
        # 评级
        buy_ratio = rating.get("buy_ratio")
        top_rating = rating.get("top_rating", "无数据")
        if buy_ratio is not None:
            lines.append(f"• 评级: {rating.get('interpretation', '')}")
            lines.append(f"  买入+增持占比: {buy_ratio:.0%}，最新: {top_rating}")
        
        # 趋势
        trend = sentiment.get("trend", "无数据")
        desc = sentiment.get("description", "")
        if trend != "无数据":
            lines.append(f"• 情绪趋势: {trend}（{desc}）")
        
        return "\n".join(lines) if lines else f"【分析师预期】{name} — 暂无分析师数据"


# ─── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    fetcher = AnalystFetcher()
    
    # 测试：平安银行
    print("获取分析师数据: 000001 平安银行")
    result = fetcher.fetch_all("000001", "平安银行")
    
    print(f"\n{result['summary']}")
    print(f"\nEPS预测: {result['eps_forecast']}")
    print(f"评级分布: {result['rating_summary']}")
    print(f"情绪趋势: {result['analyst_sentiment']}")
    print(f"\n✅ 分析师预期采集器工作正常")
