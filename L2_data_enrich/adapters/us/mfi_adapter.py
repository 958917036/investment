# -*- coding: utf-8 -*-
"""
美股 MFI 计算适配器
基于Yahoo Finance日线数据计算 MFI-14
"""

import sys, os
BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import log_start, log_end, log_fail, log_source, info

import logging
from datetime import datetime
from typing import Any, Dict

import pandas as pd
import yfinance as yf

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("L2.adapters.us")


class USMFICalcAdapter(DataSourceAdapter):
    """美股MFI计算适配器"""

    name = "美股MFI计算器"
    market = "US"
    description = "美股MFI-14计算（基于Yahoo Finance日线）"

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        days = kwargs.get("days", 90)
        return self._fetch_mfi(code, days)

    def _fetch_mfi(self, code: str, days: int = 90) -> Dict[str, Any]:
        """计算美股MFI-14"""
        log_source("mfi", "yahoo", "计算MFI", True, f"{code} ({days}d)")
        try:
            ticker = yf.Ticker(code)
            hist = ticker.history(period=f"{days}d")
            if hist is None or hist.empty or len(hist) < 20:
                log_source("mfi", "yahoo", "计算MFI", False, f"{code}: 数据不足")
                return self._fail()

            mfi = self._calc_mfi(hist)

            result = {
                "mfi": round(mfi, 2),
                "mfi_status": "流入" if mfi < 40 else ("流出" if mfi > 60 else "中性"),
                "_source": f"Yahoo Finance MFI({datetime.now().strftime('%Y-%m-%d')})",
            }
            log_source("mfi", "yahoo", "计算MFI", True, f"{code}: mfi={result['mfi']}")
            return result
        except Exception as e:
            log_source("mfi", "yahoo", "计算MFI", False, f"{code}: {e}")
            raise

    def _calc_mfi(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算MFI-14"""
        typical = (df['High'] + df['Low'] + df['Close']) / 3
        raw_money = typical * df['Volume']
        positive_flow = []
        negative_flow = []
        for i in range(1, len(typical)):
            if typical.iloc[i] > typical.iloc[i-1]:
                positive_flow.append(float(raw_money.iloc[i]))
                negative_flow.append(0)
            else:
                negative_flow.append(float(raw_money.iloc[i]))
                positive_flow.append(0)
        pos = sum(positive_flow[-period:])
        neg = sum(negative_flow[-period:])
        if neg == 0:
            return 50.0
        mr = pos / neg
        return 100 - (100 / (1 + mr))
