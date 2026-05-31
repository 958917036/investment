#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按股票代码精确查询 (L1)
调用腾讯API，精确查询单只股票
"""
import re, requests
from datetime import datetime

import sys, os
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, log_source, info

QQ_API = "http://qt.gtimg.cn/q="

def _to_qq_code(code: str, market: str = "cn") -> str:
    """转换为腾讯API格式"""
    code = code.strip()
    if code.startswith(('sh.', 'sz.', 'hk.', 'us.')):
        return code.lower().replace('.', '')
    if code.startswith(('sh', 'sz')) and market == "cn":
        return code.lower()
    if code.startswith(('hk')) and market == "hk":
        return code.lower()
    if code.startswith(('us')) and market == "us":
        return code.lower()
    # A股
    if market == "hk":
        return f"hk{int(code):05d}"
    if market == "us":
        return f"us{code.upper()}"
    if code.startswith(('6', '8')):
        return f"sh{code}"
    elif code.startswith(('0', '3')):
        return f"sz{code}"
    return code

def query_by_code(code: str, market: str = "cn") -> list:
    """
    按股票代码精确查询腾讯行情

    Args:
        code: 股票代码，如 "600519"（A股）、"00700"（港股）、"TSLA"（美股）
        market: "cn" | "hk" | "us"

    Returns:
        [{code, name, price, change_pct, market_cap, source, strategy_matched}, ...]
        找不到时返回空列表（不抛异常）
    """
    if not code or len(code) < 1:
        return []

    qq_code = _to_qq_code(code, market)
    url = f"{QQ_API}{qq_code}"

    try:
        r = requests.get(url, timeout=30)
        raw = r.text.strip()
    except Exception as e:
        log_source("by_code", "tencent", "精确查询行情", False, f"{type(e).__name__}: {e}")
        return []

    if not raw or '=' not in raw:
        log_source("by_code", "tencent", "精确查询行情", False, "空响应")
        return []

    match = re.search(r'"([^"]+)"', raw)
    if not match:
        log_source("by_code", "tencent", "精确查询行情", False, "解析失败")
        return []

    parts = match.group(1).split('~')
    if len(parts) < 47:
        log_source("by_code", "tencent", "精确查询行情", False, f"字段不足({len(parts)})")
        return []

    code_ret = parts[2] if len(parts) > 2 else code
    name_ret = parts[1] if len(parts) > 1 else ""

    try:
        price = float(parts[3]) if parts[3] else 0
        prev_close = float(parts[4]) if parts[4] else 0
        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
        mcap = float(parts[45]) if parts[45] else 0
    except (ValueError, IndexError):
        log_source("by_code", "tencent", "精确查询行情", False, "字段解析失败")
        return []

    if price <= 0:
        log_source("by_code", "tencent", "精确查询行情", False, f"价格异常: {price}")
        return []

    log_source("by_code", "tencent", "精确查询行情", True, f"code={qq_code}")

    return [{
        'code': code_ret,
        'name': name_ret,
        'price': price,
        'change_pct': change_pct,
        'market_cap': mcap,
        'source': '腾讯行情',
        'strategy_matched': 'by_code'
    }]