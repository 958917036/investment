# -*- coding: utf-8 -*-
"""
东方财富适配器 — A股资金流向
数据源：东方财富直连API (push2his.eastmoney.com)
返回：主力/超大单/大单/中单/小单近20日净流入
备份：BaoStock日线估算
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import requests
import pandas as pd

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("L2.adapters.cn")

_EM_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"
_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}


def _to_eastmoney_secid(code: str) -> str:
    """转换为东方财富secid格式：sh.600519 → 1.600519"""
    import re
    c = code.strip()
    if '.' in c:
        market_char, digits = c.split('.', 1)
        market_char = market_char.lower()
    elif c.startswith('sh'):
        market_char, digits = 'sh', c[2:]
    elif c.startswith('sz'):
        market_char, digits = 'sz', c[2:]
    elif c.startswith('bj'):
        market_char, digits = 'bj', c[2:]
    else:
        digits = re.sub(r'[^0-9]', '', c)

    if market_char in ('sh', 'bj'):
        return f"1.{digits}"
    return f"0.{digits}"


class EastMoneyAdapter(DataSourceAdapter):
    """
    A股东方财富资金流向适配器。
    主数据源：东方财富直连API（主力资金近20日）
    备份数据源：BaoStock日线估算
    """

    name = "东方财富EM"
    market = "CN"
    description = "A股主力资金流向（超大单/大单/中单/小单近20日）"

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        days = kwargs.get("days", 20)
        result = self._fetch_eastmoney(code, days)
        if result:
            return result

        # 降级：尝试BaoStock估算
        logger.info(f"  [EM资金流] 东财失败，使用BaoStock备份估算: {code}")
        result_fallback = self._fetch_baostock_fallback(code, days)
        if result_fallback:
            return self._degraded(result_fallback, reason="BaoStock日线估算")

        return self._fail()

    def _fetch_eastmoney(self, code: str, days: int) -> Dict[str, Any]:
        """东方财富直连API（主力资金流）"""
        secid = _to_eastmoney_secid(code)
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "klt": "101",
            "lmt": str(days),
        }
        try:
            resp = requests.get(
                _EM_URL, params=params,
                headers=_EM_HEADERS, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug(f"  [EM资金流] 东财API失败 {code}: {e}")
            return None

        if not data or data.get("rc", 1) != 0:
            logger.debug(f"  [EM资金流] 东财响应异常 {code}: rc={data.get('rc', 'N/A')}")
            return None

        klines = (data.get("data") or {}).get("klines") or []
        if not klines:
            logger.debug(f"  [EM资金流] 东财无kline数据 {code}")
            return None

        daily_entries = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 6:
                daily_entries.append({
                    "date": parts[0],
                    "main_net": float(parts[1]) if parts[1] else 0,
                    "small_net": float(parts[2]) if parts[2] else 0,
                    "mid_net": float(parts[3]) if parts[3] else 0,
                    "large_net": float(parts[4]) if parts[4] else 0,
                    "super_large_net": float(parts[5]) if parts[5] else 0,
                })

        if not daily_entries:
            return None

        latest = daily_entries[-1]
        daily_flows = [e["main_net"] for e in daily_entries]
        main_net_flow_5d = sum(daily_flows[-5:]) if len(daily_flows) >= 5 else sum(daily_flows)

        recent_main = daily_flows[-5:] if len(daily_flows) >= 5 else daily_flows
        main_direction = "流入" if sum(recent_main) >= 0 else "流出"
        retail_direction = "流入" if latest["small_net"] >= 0 else "流出"

        total_abs = abs(latest["large_net"]) + abs(latest["small_net"])
        large_ratio = abs(latest["large_net"]) / total_abs if total_abs > 0 else 0

        result = {
            "main_net_flow_5d": main_net_flow_5d,
            "daily_flows": daily_flows,
            "latest_main_flow": latest["main_net"],
            "latest_main_ratio": large_ratio,
            "large_order_ratio": large_ratio,
            "super_large_flow": latest["super_large_net"],
            "small_order_flow": latest["small_net"],
            "main_direction": main_direction,
            "retail_direction": retail_direction,
            "data_rows": len(daily_entries),
            "_source": f"东方财富资金流向API({datetime.now().strftime('%Y-%m-%d')})",
        }

        # 补充沪深港通
        try:
            import akshare as ak
            code_clean = code.lstrip("shszSHZS")
            df_hsgt = ak.stock_hsgt_individual_em(symbol=code_clean)
            if df_hsgt is not None and not df_hsgt.empty:
                latest_hsgt = df_hsgt.iloc[-1]
                result["hsgt_hold_ratio"] = (
                    float(latest_hsgt['持股数量占A股百分比']) / 100
                    if pd.notna(latest_hsgt.get('持股数量占A股百分比')) else None
                )
                result["hsgt_add_shares"] = (
                    float(latest_hsgt['今日增持股数'])
                    if pd.notna(latest_hsgt.get('今日增持股数')) else None
                )
                result["hsgt_add_ratio"] = (
                    float(latest_hsgt.get('增持占A股百分比', 0)) / 100
                    if pd.notna(latest_hsgt.get('增持占A股百分比')) else None
                )
        except Exception as e:
            logger.debug(f"  [沪深港通] 补充失败 {code}: {e}")

        return result

    def _fetch_baostock_fallback(self, code: str, days: int) -> Dict[str, Any]:
        """BaoStock日线备份估算（通过成交额×外内盘比估算资金流向）"""
        from L2_data_enrich.adapters.cn.baostock_adapter import _to_baostock_code
        import baostock as bs

        bs_code = _to_baostock_code(code)
        lg = bs.login()
        if lg.error_code != '0':
            return None
        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=min(days, 60))).strftime('%Y-%m-%d')
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",
            )
            df = rs.get_data()
            if df.empty or len(df) < 5:
                return None

            for col in ['close', 'volume', 'amount']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            daily_flows = df['amount'].tolist()[-days:]
            main_net_flow_5d = sum(daily_flows[-5:]) if len(daily_flows) >= 5 else sum(daily_flows)

            return {
                "main_net_flow_5d": main_net_flow_5d,
                "daily_flows": daily_flows,
                "latest_main_flow": daily_flows[-1] if daily_flows else 0,
                "latest_main_ratio": 0.5,
                "large_order_ratio": 0.5,
                "super_large_flow": 0,
                "small_order_flow": 0,
                "main_direction": "未知",
                "retail_direction": "未知",
                "data_rows": len(daily_flows),
                "_source": f"BaoStock日线估算({datetime.now().strftime('%Y-%m-%d')})",
            }
        finally:
            bs.logout()


from datetime import timedelta
