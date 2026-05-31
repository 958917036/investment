# -*- coding: utf-8 -*-
"""
期货/外汇数据适配器 — R4 多资产支持

数据来源：BaoStock 期货日线 + AkShare 外汇数据

期货代码示例（郑商所/大商所/上期所/中金所）：
    IF2506 → 沪深300指数期货
    IC2506 → 中证500指数期货
    IM2506 → 中证1000指数期货
    IH2506 → 上证50指数期货
    T2506   → 10年期国债期货
    RU2506  → 橡胶期货
    FG2506  → 玻璃期货
    SR2506  → 白糖期货

外汇代码示例（ AkShare）：
    USD.CNY → 美元/人民币
    EUR.CNY → 欧元/人民币
    GBP.CNY → 英镑/人民币
    JPY.CNY → 日元/人民币
"""

from __future__ import annotations

import logging
from typing import Optional
import pandas as pd
import numpy as np

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("adapter.futures")


# ======================== 期货数据适配器 ========================

class FuturesAdapter(DataSourceAdapter):
    """
    BaoStock 期货日线数据适配器。

    支持国内商品期货、金融期货（指数/国债）。

    使用方式：
        adapter = FuturesAdapter()
        data = adapter.fetch("RU2506")  # 橡胶期货
        data = adapter.fetch("IF2506")   # 沪深300期货
    """

    name = "BaoStock 期货"
    market = "FUTURES"

    # BaoStock 期货代码前缀映射
    FUTURES_EXCHANGE_MAP = {
        "IF": "CFFEX",   # 沪深300指数期货
        "IC": "CFFEX",   # 中证500指数期货
        "IM": "CFFEX",   # 中证1000指数期货
        "IH": "CFFEX",   # 上证50指数期货
        "T": "CFFEX",    # 国债期货
        "TF": "CFFEX",   # 5年期国债期货
        "TS": "CFFEX",   # 2年期国债期货
        "RU": "SHFE",    # 橡胶
        "RB": "SHFE",    # 螺纹钢
        "HC": "SHFE",    # 热卷
        "FG": "CZCE",    # 玻璃
        "SA": "CZCE",    # 纯碱
        "SR": "CZCE",    # 白糖
        "CF": "CZCE",    # 棉花
        "TA": "CZCE",    # PTA
        "MA": "CZCE",    # 甲醇
        "V": "DCE",      # PVC
        "PP": "DCE",     # 聚丙烯
        "L": "DCE",      # 塑料
        "J": "DCE",      # 焦炭
        "JM": "DCE",     # 焦煤
        "I": "DCE",      # 铁矿石
    }

    def _to_bs_code(self, code: str) -> str:
        """转换为 BaoStock 格式（如 RU2506 → fu.RU2506）"""
        code = code.upper().strip()
        if "." in code:
            return code.lower()
        return f"fu.{code}"

    def _fetch(self, code: str, **kwargs) -> dict:
        """从 BaoStock 获取期货日线数据"""
        import baostock as bs

        bs_code = self._to_bs_code(code)
        start_date = kwargs.get("start_date", "2020-01-01")
        end_date = kwargs.get("end_date", "2025-12-31")

        bs.login()
        rs = bs.query_future_daily_data(
            bs_code,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )

        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())

        bs.logout()

        if not rows:
            return self._fail_result(f"No data for {code}")

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"])
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["close"])
        df = df.sort_values("date").reset_index(drop=True)

        # 计算收益率
        df["daily_return"] = df["close"].pct_change()

        return self._ok_result({
            "date": df["date"].tolist(),
            "open": df["open"].tolist(),
            "high": df["high"].tolist(),
            "low": df["low"].tolist(),
            "close": df["close"].tolist(),
            "volume": df["volume"].tolist(),
            "amount": df["amount"].tolist(),
            "daily_return": df["daily_return"].tolist(),
            "settlement": kwargs.get("margin_rate", 0.10),  # 默认保证金10%
        })


# ======================== 外汇数据适配器 ========================

class FXAdapter(DataSourceAdapter):
    """
    AkShare 外汇数据适配器。

    支持主要外汇对（USD/CNY, EUR/CNY 等）。

    使用方式：
        adapter = FXAdapter()
        data = adapter.fetch("USD.CNY")  # 美元/人民币
    """

    name = "AkShare 外汇"
    market = "FX"

    def _fetch(self, code: str, **kwargs) -> dict:
        """从 AkShare 获取外汇数据"""
        import akshare as ak

        start_date = kwargs.get("start_date", "2020-01-01")
        end_date = kwargs.get("end_date", "2025-12-31")

        try:
            # AkShare 外汇牌价
            fx_df = ak.currency_hist(
                symbol=code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
            )
            if fx_df is None or fx_df.empty:
                return self._fail_result(f"No FX data for {code}")

            fx_df = fx_df.sort_values("date").reset_index(drop=True)
            fx_df.columns = [c.lower() for c in fx_df.columns]

            return self._ok_result({
                "date": fx_df["date"].tolist(),
                "open": fx_df.get("open", fx_df["close"]).tolist(),
                "high": fx_df.get("high", fx_df["close"]).tolist(),
                "low": fx_df.get("low", fx_df["close"]).tolist(),
                "close": fx_df["close"].tolist(),
                "volume": fx_df.get("volume", [0] * len(fx_df)).tolist(),
                "amount": fx_df.get("amount", [0] * len(fx_df)).tolist(),
                "daily_return": fx_df["close"].pct_change().fillna(0).tolist(),
            })

        except Exception as e:
            return self._fail_result(f"AkShare FX error for {code}: {e}")


# ======================== 工厂函数 ========================

def create_futures_adapter() -> FuturesAdapter:
    return FuturesAdapter()


def create_fx_adapter() -> FXAdapter:
    return FXAdapter()
