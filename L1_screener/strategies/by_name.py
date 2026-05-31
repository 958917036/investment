#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按股票名称查询 (L1)
调用腾讯API，名称模糊匹配
"""
import subprocess, re, requests, os, pandas as pd
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
    if market == "hk":
        return f"hk{int(code):05d}"
    if market == "us":
        return f"us{code.upper()}"
    if code.startswith(('6', '8')):
        return f"sh{code}"
    elif code.startswith(('0', '3')):
        return f"sz{code}"
    return code

def search_by_name(name: str, market: str = "cn") -> list:
    """
    按股票名称模糊查询腾讯行情

    Args:
        name: 股票名称或关键字，如 "茅台"
        market: "cn" | "hk" | "us"

    Returns:
        [{code, name, price, change_pct, market_cap, source, strategy_matched}, ...]
    """
    if not name or len(name) < 1:
        return []

    try:
        import akshare as ak
        old_no_proxy = os.environ.get("no_proxy", "")
        os.environ["no_proxy"] = "*"
        try:
            if market == "hk":
                df = ak.stock_info_hk_name_code()
                log_source("by_name", "akshare", "港股名称模糊搜索", True, f"{len(df)} 条")
                mask = df['name'].str.contains(name, na=False)
            elif market == "us":
                df = ak.stock_us_spot_em()
                log_source("by_name", "akshare", "美股名称模糊搜索", True, f"{len(df) if df is not None else 0} 条")
                if df is None or df.empty:
                    return []
                mask = df['name'].str.contains(name, na=False) if 'name' in df.columns else pd.Series([False] * len(df))
            else:
                df = ak.stock_info_a_code_name()
                log_source("by_name", "akshare", "A股名称模糊搜索", True, f"{len(df)} 条")
                mask = df['name'].str.contains(name, na=False)
            matched = df[mask]
            if matched.empty:
                return []
            codes = matched['code'].tolist()
        finally:
            os.environ["no_proxy"] = old_no_proxy
    except Exception as e:
        log_source("by_name", "akshare", "名称模糊搜索", False, f"{type(e).__name__}: {e}")
        return []

    if not codes:
        return []

    # 批量查询腾讯行情
    qq_codes = [_to_qq_code(c, market) for c in codes]
    url = f"{QQ_API}{','.join(qq_codes)}"

    results = []
    try:
        r = requests.get(url, timeout=30)
        log_source("by_name", "tencent", "批量获取行情", True, f"{len(codes)} 只")
    except Exception as e:
        log_source("by_name", "tencent", "批量获取行情", False, f"{type(e).__name__}: {e}")
        return []

    try:
        raw = r.text.strip()
        lines = raw.split(';')
        for line in lines:
            if not line or '=' not in line:
                continue
            match = re.search(r'"([^"]+)"', line)
            if not match:
                continue
            parts = match.group(1).split('~')
            if len(parts) < 47:
                continue
            code = parts[2] if len(parts) > 2 else ""
            name_ret = parts[1] if len(parts) > 1 else ""
            try:
                price = float(parts[3]) if parts[3] else 0
                prev_close = float(parts[4]) if parts[4] else 0
                change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                mcap = float(parts[45]) if parts[45] else 0
            except (ValueError, IndexError):
                continue
            if price > 0:
                results.append({
                    'code': code,
                    'name': name_ret,
                    'price': price,
                    'change_pct': change_pct,
                    'market_cap': mcap,
                    'source': '腾讯行情',
                    'strategy_matched': 'by_name'
                })
    except Exception as e:
        pass

    return results