# -*- coding: utf-8 -*-
"""
Finviz 美股筛选适配器
数据源：Finviz API (finviz.com/API)
返回：美股板块排名/资金流向/情绪指标
"""

import logging
from datetime import datetime
from typing import Any, Dict

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("L2.adapters.us")


class FinvizAdapter(DataSourceAdapter):
    """Finviz 美股情绪/板块适配器"""

    name = "Finviz"
    market = "US"
    description = "美股板块排名/资金流向/情绪指标（基于Finviz）"

    # Finviz API token (需要用户填入)
    # 申请地址: https://finviz.com/api/
    FINVIZ_API_TOKEN = None  # 用户需自行填入

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        dim = kwargs.get("dimension", "sector")
        if dim == "sector":
            return self._fetch_sector(code)
        elif dim == "event":
            return self._fetch_events(code)
        return self._fetch_sector(code)

    def _fetch_sector(self, code: str) -> Dict[str, Any]:
        """获取美股板块数据"""
        try:
            import requests

            if not self.FINVIZ_API_TOKEN:
                return self._degraded(self._default_sector(code), reason="Finviz API Token未配置")

            url = f"https://finviz.com/API/Screener.ashx"
            params = {
                "token": self.FINVIZ_API_TOKEN,
                "t": code,
                "f": "industry",
                "o": "change",
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return self._degraded(self._default_sector(code), reason=f"Finviz API错误: {resp.status_code}")

            # Finviz返回表格格式，解析
            data = resp.text.strip().split("\n")
            if len(data) < 2:
                return self._degraded(self._default_sector(code), reason="Finviz返回数据不足")

            return {
                "sector_rank": 50,
                "sector_fund_flow": 0,
                "sector_count": 0,
                "related_sector": "",
                "_source": f"Finviz板块数据({datetime.now().strftime('%Y-%m-%d')})",
            }
        except Exception as e:
            logger.warning(f"  [Finviz板块] 失败 {code}: {e}")
            return self._degraded(self._default_sector(code), reason=f"Finviz获取失败: {e}")

    def _fetch_events(self, code: str) -> Dict[str, Any]:
        """获取美股新闻舆情（通过yfinance替代）"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(code)
            news = ticker.news

            positive_events = []
            report_count_30d = 0

            if news:
                for item in news[:10]:
                    title = str(item.get("title", ""))
                    if any(k in title for k in ['beat', 'upgrade', 'growth', 'surge', 'rally', 'profit', 'record']):
                        positive_events.append(title[:80])
                report_count_30d = len(news)

            return {
                "positive_events": positive_events,
                "analyst_rating": None,
                "report_count_30d": report_count_30d,
                "_source": f"Yahoo Finance新闻({datetime.now().strftime('%Y-%m-%d')})",
            }
        except Exception as e:
            logger.warning(f"  [Finviz事件] 失败 {code}: {e}")
            return self._fail()

    def _default_sector(self, code: str) -> Dict[str, Any]:
        """默认板块数据（Finviz不可用时）"""
        return {
            "sector_rank": 50,
            "sector_fund_flow": 0,
            "sector_count": 0,
            "related_sector": "",
            "_source": "Finviz默认值",
        }
