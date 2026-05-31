# -*- coding: utf-8 -*-
"""
腾讯行情适配器 — A股实时行情
数据源：腾讯行情API (qt.gtimg.cn)
返回：价格/PE/PB/外内盘/市值/换手率/52周范围
"""

import sys, os
BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import log_start, log_end, log_fail, log_source, info

import re
import subprocess
import logging
from typing import Any, Dict
from datetime import datetime

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("L2.adapters.cn")


# 腾讯API字段索引
QQ_PARTS = {
    "name": 1, "code": 2, "price": 3, "prev_close": 4, "open": 5,
    "volume": 6, "outer_disk": 7, "inner_disk": 8,
    "high": 33, "low": 34, "amount": 37, "turnover": 38,
    "pe": 39, "week52_high": 47, "week52_low": 48,
    "amplitude": 49, "pb": 46, "market_cap": 45,
}


def _to_qq_code(code: str) -> str:
    """转换为腾讯API格式：sh600320 / sz000858"""
    code = code.strip()
    if code.startswith(('sh.', 'sz.', 'hk.')):
        return code.lower().replace('.', '')
    if code.startswith(('sh', 'sz', 'hk')):
        return code.lower()
    if code.startswith(('6', '8')):
        return f"sh{code}"
    elif code.startswith(('0', '3')):
        return f"sz{code}"
    return code


class TencentCNAdapter(DataSourceAdapter):
    """A股腾讯行情适配器"""

    name = "腾讯行情API"
    market = "CN"
    description = "A股实时行情：价格/PE/PB/外内盘/市值/换手率/52周范围"

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        qq_code = _to_qq_code(code)
        url = f"http://qt.gtimg.cn/q={qq_code}"

        log_source("tencent", "curl", "获取腾讯行情", True, f"{qq_code}")
        try:
            r = subprocess.run(
                ['curl', '-s', '--max-time', '5', '-A', 'Mozilla/5.0', url],
                capture_output=True, timeout=10
            )
            raw = r.stdout.decode('gbk', errors='replace')
            log_source("tencent", "curl", "获取腾讯行情", True, f"{qq_code}")

            match = re.search(r'"([^"]+)"', raw)
            if not match:
                log_source("tencent", "curl", "获取腾讯行情", False, f"无数据返回: {code}")
                raise RuntimeError(f"腾讯API无数据返回: {code}")

            parts = match.group(1).split('~')
            if len(parts) < 50:
                log_source("tencent", "curl", "解析腾讯行情", False, f"字段不足({len(parts)}): {code}")
                raise RuntimeError(f"腾讯API字段不足({len(parts)}): {code}")

            def safe_float(idx, default=None):
                val = parts[idx] if idx < len(parts) else '-'
                if val and val != '-':
                    try:
                        return float(val)
                    except ValueError:
                        return default
                return default

            def safe_int(idx, default=0):
                val = parts[idx] if idx < len(parts) else '-'
                if val and val != '-':
                    try:
                        return int(float(val))
                    except ValueError:
                        return default
                return default

            price = safe_float(QQ_PARTS["price"])
            prev_close = safe_float(QQ_PARTS["prev_close"])
            change_pct = round((price - prev_close) / prev_close * 100, 2) \
                if (price and prev_close and prev_close > 0) else 0

            outer = safe_int(QQ_PARTS["outer_disk"])
            inner = safe_int(QQ_PARTS["inner_disk"])
            outer_inner_ratio = round(outer / inner, 2) if inner > 0 else 1.0
            raw_pb = safe_float(QQ_PARTS["pb"])
            pb = round(raw_pb, 4) if raw_pb is not None else None

            return {
                "price": price,
                "prev_close": prev_close,
                "change_pct": change_pct,
                "open": safe_float(QQ_PARTS["open"]),
                "high": safe_float(QQ_PARTS["high"]),
                "low": safe_float(QQ_PARTS["low"]),
                "volume": safe_int(QQ_PARTS["volume"]),
                "amount": safe_float(QQ_PARTS["amount"]),
                "pe": safe_float(QQ_PARTS["pe"]),
                "pb": pb,
                "market_cap": safe_float(QQ_PARTS["market_cap"]),
                "circulating_cap": safe_float(QQ_PARTS["market_cap"]),
                "turnover": safe_float(QQ_PARTS["turnover"]),
                "amplitude": safe_float(QQ_PARTS["amplitude"]),
                "week52_high": safe_float(QQ_PARTS["week52_high"]),
                "week52_low": safe_float(QQ_PARTS["week52_low"]),
                "outer_disk": outer,
                "inner_disk": inner,
                "outer_inner_ratio": outer_inner_ratio,
                "name": parts[QQ_PARTS["name"]] if QQ_PARTS["name"] < len(parts) else code,
                "_source": f"腾讯行情API({datetime.now().strftime('%H:%M')})",
                "_raw_fields": len(parts),
            }
        except Exception as e:
            log_source("tencent", "curl", "获取腾讯行情", False, f"{type(e).__name__}: {e}")
            raise
