# -*- coding: utf-8 -*-
"""
港股/美股 MFI 计算适配器
基于AkShare日线数据计算 MFI-14
用于替代 EastMoney（港股/美股不支持）
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import akshare as ak
import pandas as pd

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("L2.adapters.hk")


class MFICalcAdapter(DataSourceAdapter):
    """MFI计算适配器（港股/美股）"""

    name = "MFI计算器"
    market = "HK"  # HK/US 共用
    description = "MFI-14计算（基于AkShare日线）"

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        market = kwargs.get("market", "HK")
        days = kwargs.get("days", 90)

        if market == "US":
            return self._fetch_us_mfi(code, days)
        return self._fetch_hk_mfi(code, days)

    def _fetch_hk_mfi(self, code: str, days: int = 90) -> Dict[str, Any]:
        """港股MFI计算（使用stock_hk_daily，不支持start/end参数需本地过滤）"""
        code5 = code.strip().lstrip('hkHK').zfill(5)
        try:
            df = ak.stock_hk_daily(symbol=code5, adjust="qfq")
            if df is None or df.empty or len(df) < 20:
                return self._fail()

            # 过滤近(days+30)天数据
            cutoff = pd.to_datetime(datetime.now() - timedelta(days=days + 30))
            df['date'] = pd.to_datetime(df['date'])
            df = df[df['date'] >= cutoff].copy()
            if len(df) < 20:
                return self._fail()

            df = df.tail(days).copy()
            # stock_hk_daily columns: ['date','open','high','low','close','volume','amount']
            # (no rename needed, columns already match)

            mfi = self._calc_mfi(df)

            return {
                "mfi": round(mfi, 2),
                "mfi_status": "流入" if mfi < 40 else ("流出" if mfi > 60 else "中性"),
                "_source": f"AkShare港股MFI({datetime.now().strftime('%Y-%m-%d')})",
            }
        except Exception as e:
            logger.warning(f"  [MFI港股] 失败 {code}: {e}")
            return self._fail()

    def _fetch_us_mfi(self, code: str, days: int = 90) -> Dict[str, Any]:
        """美股MFI计算（通过AkShare美股期货/指数日线模拟）"""
        # AkShare 不直接支持美股个股日线MFI，使用股票报价接口
        try:
            df = ak.stock_us_em_daily(symbol=code)
            if df is None or df.empty or len(df) < 20:
                return self._fail()

            df = df.tail(days)
            mfi = self._calc_mfi(df)

            return {
                "mfi": round(mfi, 2),
                "mfi_status": "流入" if mfi < 40 else ("流出" if mfi > 60 else "中性"),
                "_source": f"AkShare美股MFI({datetime.now().strftime('%Y-%m-%d')})",
            }
        except Exception as e:
            logger.warning(f"  [MFI美股] 失败 {code}: {e}")
            return self._fail()

    def _calc_mfi(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算MFI-14"""
        typical = (df['high'] + df['low'] + df['close']) / 3
        raw_money = typical * df['volume']
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
