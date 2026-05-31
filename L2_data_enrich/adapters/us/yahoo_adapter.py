# -*- coding: utf-8 -*-
"""
Yahoo Finance 美股适配器
数据源：Yahoo Finance (yfinance)
返回：美股实时价格/PE/PB/市值/50日均价/52周范围
"""

import sys, os
BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import log_start, log_end, log_fail, log_source, info

import logging
from datetime import datetime
from typing import Any, Dict

import yfinance as yf

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("L2.adapters.us")


class YahooFinanceAdapter(DataSourceAdapter):
    """Yahoo Finance 美股行情适配器"""

    name = "Yahoo Finance"
    market = "US"
    description = "美股实时行情：价格/PE/PB/市值/50日均价/52周范围"

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        return self._fetch_realtime(code)

    def _fetch_realtime(self, code: str) -> Dict[str, Any]:
        """获取美股实时行情"""
        log_source("yahoo", "yahoo", "获取实时行情", True, code)
        try:
            ticker = yf.Ticker(code)
            info = ticker.fast_info

            price = info.last_price or 0
            prev_close = info.previous_close or 0
            market_cap = info.market_cap or 0
            pe = info.pe or None
            pb = info.pb_ratio or None
            week52_high = info.fifty_two_week_high or 0
            week52_low = info.fifty_two_week_low or 0

            # 50日均价（通过history计算）
            hist_50d = ticker.history(period="50d")
            ma50 = float(hist_50d['Close'].mean()) if len(hist_50d) >= 50 else price

            # 换手率（来自info或估算）
            try:
                turn_rate = float(ticker.info.get('averageVolume10Day', 0)) or 0
            except:
                turn_rate = 0

            change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

            result = {
                'name': ticker.info.get('shortName', code),
                'code': code,
                'price': round(price, 2),
                'prev_close': round(prev_close, 2),
                'change_pct': round(change_pct, 2),
                'open': round(info.open or prev_close, 2),
                'high': round(info.day_high or price, 2),
                'low': round(info.day_low or price, 2),
                'volume': info.last_volume or 0,
                'market_cap': market_cap,
                'pe': round(pe, 2) if pe else None,
                'pb': round(pb, 2) if pb else None,
                'week52_high': round(week52_high, 2),
                'week52_low': round(week52_low, 2),
                'ma50': round(ma50, 2),
                'turn_rate': turn_rate,
                'outer_disk': None,
                'inner_disk': None,
                'outer_inner_ratio': None,
                '_source': f"Yahoo Finance({datetime.now().strftime('%H:%M')})",
            }
            log_source("yahoo", "yahoo", "获取实时行情", True, code)
            return result
        except Exception as e:
            log_source("yahoo", "yahoo", "获取实时行情", False, f"{code}: {e}")
            raise
