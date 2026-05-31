# -*- coding: utf-8 -*-
"""
AkShare港股适配器 — 日线技术指标 + 财务数据 + 机构持仓
数据源：AkShare SDK (stock_hk_hist + stock_hk_financial_indicator_em)
返回：港股日线数据（用于MA/MACD/RSI计算）+ 财务指标 + 机构持仓
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import akshare as ak
import pandas as pd

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("L2.adapters.hk")


class AkShareHKAdapter(DataSourceAdapter):
    """港股AkShare适配器（技术指标 + 财务数据 + 机构持仓）"""

    name = "AkShare港股"
    market = "HK"
    description = "港股日线(MACD/RSI/MA) + 财务指标(ROE/营收增速) + 机构持仓"

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        dim = kwargs.get("dimension", "technical")
        if dim == "fundamental":
            return self._fetch_financial(code)
        elif dim == "institution":
            return self._fetch_institution(code)
        return self._fetch_technical(code)

    def _fetch_technical(self, code: str) -> Dict[str, Any]:
        """获取港股日线技术指标（使用stock_hk_daily，不支持start/end参数需本地过滤）"""
        code5 = code.strip().lstrip('hkHK').zfill(5)
        try:
            df = ak.stock_hk_daily(symbol=code5, adjust="qfq")
            if df is None or df.empty or len(df) < 20:
                raise RuntimeError(f"港股日线数据不足: {code}")

            # 过滤近120天数据
            cutoff = pd.to_datetime(datetime.now() - timedelta(days=120))
            df['date'] = pd.to_datetime(df['date'])
            df = df[df['date'] >= cutoff].copy()
            if len(df) < 20:
                raise RuntimeError(f"港股日线数据不足: {code}")

            df = df.tail(90).reset_index(drop=True).copy()
            # stock_hk_daily columns: ['date','open','high','low','close','volume','amount']
            # (no rename needed, columns already match)

            close = df['close'].values.astype(float)
            volume = df['volume'].values.astype(float)

            # MA
            ma5 = float(close[-5:].mean())
            ma10 = float(close[-10:].mean()) if len(close) >= 10 else ma5
            ma20 = float(close[-20:].mean()) if len(close) >= 20 else ma10
            ma60 = float(close[-60:].mean()) if len(close) >= 60 else ma20
            current_price = float(close[-1])

            if current_price > ma5 > ma10 > ma20:
                ma_status = "bullish"
            elif current_price < ma5 < ma10 < ma20:
                ma_status = "bearish"
            else:
                ma_status = "neutral"

            # MFI-14
            mfi = self._calc_mfi(df)
            # RSI-14
            rsi = self._calc_rsi(close)

            # MACD
            ema12 = self._ema(close, 12)
            ema26 = self._ema(close, 26)
            dif = ema12 - ema26
            dea = self._ema(dif, 9) if len(dif) >= 9 else 0
            macd_hist = 2 * (dif[-1] - dea[-1]) if len(dif) >= 9 else 0
            macd_status = "golden" if macd_hist > 0 else "death"

            # 成交量
            vol_avg_5 = float(volume[-5:].mean())
            vol_now = float(volume[-1])
            volume_ratio = round(vol_now / vol_avg_5, 2) if vol_avg_5 > 0 else 1.0

            return {
                "price": current_price,
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "ma20": round(ma20, 2),
                "ma60": round(ma60, 2),
                "ma_status": ma_status,
                "macd_status": macd_status,
                "dif": round(float(dif[-1]), 3),
                "dea": round(float(dea[-1]), 3) if len(dif) >= 9 else 0,
                "macd_hist": round(float(macd_hist), 3),
                "rsi": round(rsi, 2),
                "mfi": round(mfi, 2),
                "volume_ratio": volume_ratio,
                "volume_status": "放量" if volume_ratio > 1.5 else ("缩量" if volume_ratio < 0.5 else "正常"),
                "_source": f"AkShare港股日线({datetime.now().strftime('%Y-%m-%d')})",
            }
        except Exception as e:
            raise RuntimeError(f"[AkShare港股技术] stock_hk_daily失败 {code}: {e}") from e

    def _fetch_financial(self, code: str) -> Dict[str, Any]:
        """获取港股财务指标"""
        code5 = code.strip().lstrip('hkHK').zfill(5)
        try:
            df = ak.stock_hk_financial_indicator_em(symbol=code5)
            if df is None or df.empty:
                raise RuntimeError(f"港股财务数据为空: {code}")

            latest = df.iloc[-1]

            def get_val(col_name):
                """从列名模糊匹配获取最新值"""
                for col in df.columns:
                    if col_name in str(col):
                        val = latest[col]
                        try:
                            v = float(val)
                            if v != v:  # NaN check
                                return None
                            return v
                        except (TypeError, ValueError):
                            return None
                return None

            return {
                "roe": get_val("股东权益回报率"),
                "revenue_growth": get_val("营业总收入滚动环比增长"),
                "net_profit_yoy": get_val("净利润滚动环比增长"),
                "gross_margin": get_val("销售净利率"),  # HK uses 销售净利率 as margin proxy
                "net_margin": get_val("销售净利率"),
                "pe": get_val("市盈率"),
                "pb": get_val("市净率"),
                "market_cap_hkd": get_val("总市值"),
                "dividend_yield": get_val("股息率"),
                "_source": f"AkShare港股财务({datetime.now().strftime('%Y-%m-%d')})",
            }
        except Exception as e:
            raise RuntimeError(f"[AkShare港股财务] stock_hk_financial_indicator_em失败 {code}: {e}") from e

    def _fetch_institution(self, code: str) -> Dict[str, Any]:
        """获取港股机构持仓数据（通过stock_hk_financial_indicator_em总股本估算）"""
        code5 = code.strip().lstrip('hkHK').zfill(5)
        try:
            df = ak.stock_hk_financial_indicator_em(symbol=code5)
            if df is None or df.empty:
                raise RuntimeError(f"港股财务数据为空: {code}")

            latest = df.iloc[-1]

            def get_val(col_name):
                for col in df.columns:
                    if col_name in str(col):
                        val = latest[col]
                        try:
                            v = float(val)
                            if v != v:
                                return None
                            return v
                        except (TypeError, ValueError):
                            return None
                return None

            # 估算机构持股比例：总市值(HKD) / 股数
            total_shares = get_val("已发行股本")
            market_cap_hkd = get_val("总市值")
            if total_shares and total_shares > 0 and market_cap_hkd:
                # 每股价格估算
                price_est = market_cap_hkd / total_shares if total_shares else None
            else:
                price_est = None

            return {
                "inst_ownership_pct": None,  # 港股无直接机构持仓数据源（需付费Bloomberg/路透）
                "total_shares": total_shares,
                "free_float_shares": get_val("已发行股本-H股"),  # H股比例可作为外资持股代理
                "market_cap_hkd": market_cap_hkd,
                "price_estimate_hkd": price_est,
                "dividend_yield": get_val("股息率TTM"),
                "institution_note": "港股机构持仓数据受限，Baidu/Eniu等免费API已失效，需Bloomberg/路透付费数据",
                "_source": f"AkShare港股机构数据({datetime.now().strftime('%Y-%m-%d')})",
            }
        except Exception as e:
            raise RuntimeError(f"[AkShare港股机构持仓] stock_hk_financial_indicator_em失败 {code}: {e}") from e

    def _calc_mfi(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算MFI-14"""
        typical = df['high'] + df['low'] + df['close']
        raw_money = typical * df['volume']
        positive_flow = []
        negative_flow = []
        for i in range(1, len(typical)):
            tp_curr = float(typical.iloc[i])
            tp_prev = float(typical.iloc[i-1])
            if tp_curr > tp_prev:
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

    def _calc_rsi(self, close_arr, period: int = 14) -> float:
        """计算RSI-14"""
        delta = [close_arr[i] - close_arr[i-1] for i in range(1, len(close_arr))]
        gain = [d if d > 0 else 0 for d in delta]
        loss = [-d if d < 0 else 0 for d in delta]
        avg_gain = sum(gain[-period:]) / period
        avg_loss = sum(loss[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _ema(self, arr, period: int):
        """计算EMA"""
        import numpy as np
        data = np.array(arr)
        alpha = 2 / (period + 1)
        ema = [data[0]]
        for i in range(1, len(data)):
            ema.append(alpha * data[i] + (1 - alpha) * ema[-1])
        return np.array(ema)
