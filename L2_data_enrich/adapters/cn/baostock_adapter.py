# -*- coding: utf-8 -*-
"""
BaoStock适配器 — A股技术指标
数据源：BaoStock日线
返回：MA/MACD/RSI/布林带/成交量
"""

import sys, os
BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import log_start, log_end, log_fail, log_source, info

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import baostock as bs
import pandas as pd
import numpy as np

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("L2.adapters.cn")


def _to_baostock_code(code: str) -> str:
    """转换为BaoStock格式：sh.600519 或 sz.000858"""
    code = code.strip().lower()
    if code.startswith(('sh.', 'sz.')):
        return code
    if code.startswith(('sh', 'sz')):
        return f"{code[:2]}.{code[2:]}"
    if code.startswith(('6', '8')):
        return f"sh.{code}"
    elif code.startswith(('0', '3')):
        return f"sz.{code}"
    return code


class BaoStockAdapter(DataSourceAdapter):
    """A股BaoStock技术指标适配器"""

    name = "BaoStock日线"
    market = "CN"
    description = "A股技术指标：MA/MACD/RSI/布林带/成交量"

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        bs_code = _to_baostock_code(code)

        log_source("baostock", "baostock", "登录", True, bs_code)
        lg = bs.login()
        if lg.error_code != '0':
            log_source("baostock", "baostock", "登录", False, lg.error_msg)
            raise RuntimeError(f"BaoStock登录失败: {lg.error_msg}")
        log_source("baostock", "baostock", "登录", True, "success")

        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

            log_source("baostock", "baostock", "查询K线", True, f"{bs_code}: {len(df)}行")
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,volume",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2"  # 前复权
            )
            df = rs.get_data()
            log_source("baostock", "baostock", "查询K线", True, f"{bs_code}: {len(df)}行")

            if df.empty or len(df) < 20:
                raise RuntimeError(f"技术数据不足({len(df)}行): {code}")

            for col in ['close', 'high', 'low', 'open', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            close = df['close'].values
            volume = df['volume'].values

            # MA计算
            ma5 = np.mean(close[-5:]) if len(close) >= 5 else close[-1]
            ma10 = np.mean(close[-10:]) if len(close) >= 10 else close[-1]
            ma20 = np.mean(close[-20:]) if len(close) >= 20 else close[-1]
            ma60 = np.mean(close[-60:]) if len(close) >= 60 else close[-1]
            current_price = close[-1]

            # 均线形态
            if current_price > ma5 > ma10 > ma20:
                ma_status = "bullish"
            elif current_price < ma5 < ma10 < ma20:
                ma_status = "bearish"
            else:
                ma_status = "neutral"

            # MACD计算
            def calc_ema(data, period):
                alpha = 2 / (period + 1)
                ema_arr = [data[0]]
                for i in range(1, len(data)):
                    ema_arr.append(alpha * data[i] + (1 - alpha) * ema_arr[-1])
                return np.array(ema_arr)

            ema12 = calc_ema(close, 12)
            ema26 = calc_ema(close, 26)
            dif = ema12 - ema26
            dea = calc_ema(dif, 9)
            macd_hist = 2 * (dif - dea)
            dif_val = dif[-1]
            dea_val = dea[-1]
            macd_val = macd_hist[-1]

            if macd_val > 0 and dif_val > dea_val:
                macd_status = "golden"
            elif macd_val < 0 and dif_val < dea_val:
                macd_status = "death"
            else:
                macd_status = "neutral"

            # RSI
            delta = np.diff(close)
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_gain = np.mean(gain[-14:]) if len(gain) >= 14 else np.mean(gain)
            avg_loss = np.mean(loss[-14:]) if len(loss) >= 14 else np.mean(loss)
            rs_val = avg_gain / avg_loss if avg_loss > 0 else 100
            rsi = round(100 - 100 / (1 + rs_val), 2) if avg_loss > 0 else 50

            # 成交量状态
            vol_avg_5 = np.mean(volume[-5:]) if len(volume) >= 5 else np.mean(volume)
            vol_now = volume[-1] if len(volume) > 0 else 0
            volume_ratio = round(vol_now / vol_avg_5, 2) if vol_avg_5 > 0 else 1.0
            volume_status = "放量" if volume_ratio > 1.5 else ("缩量" if volume_ratio < 0.5 else "正常")

            # 布林带
            bb_mid = np.mean(close[-20:]) if len(close) >= 20 else close[-1]
            bb_std = np.std(close[-20:]) if len(close) >= 20 else 0
            bb_upper = round(bb_mid + 2 * bb_std, 2)
            bb_lower = round(bb_mid - 2 * bb_std, 2)
            bb_position = round((current_price - bb_lower) / (bb_upper - bb_lower) * 100, 2) \
                if bb_upper > bb_lower else 50

            return {
                "price": current_price,
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "ma20": round(ma20, 2),
                "ma60": round(ma60, 2),
                "ma_status": ma_status,
                "dif": round(dif_val, 3),
                "dea": round(dea_val, 3),
                "macd_hist": round(macd_val, 3),
                "macd_status": macd_status,
                "rsi": rsi,
                "volume_ratio": volume_ratio,
                "volume_status": volume_status,
                "bb_upper": bb_upper,
                "bb_mid": round(bb_mid, 2),
                "bb_lower": bb_lower,
                "bb_position": bb_position,
                "_source": "BaoStock日线",
            }

        except Exception as e:
            log_source("baostock", "baostock", "查询K线", False, f"{code}: {e}")
            raise
        finally:
            log_source("baostock", "baostock", "登出", True, bs_code)
            bs.logout()
            log_source("baostock", "baostock", "登出", True, "success")
