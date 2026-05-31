#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按板块查询 (L1)
调用AkShare板块查询，返回板块内所有股票
"""
import requests
import os
import re
from datetime import datetime

import sys, os
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, log_source, info

def search_by_sector(sector: str, market: str = "cn") -> list:
    """
    按行业板块查询所有成分股

    Args:
        sector: 板块名称关键字，如 "白酒"、"医药"、"银行"
        market: "cn" | "hk" | "us"

    Returns:
        [{code, name, price, change_pct, market_cap, source, strategy_matched}, ...]
    """
    if not sector or len(sector) < 1:
        return []

    if market == "hk":
        return _search_by_sector_hk(sector)
    elif market == "us":
        return _search_by_sector_us(sector)
    else:
        return _search_by_sector_cn(sector)


def _search_by_sector_cn(sector: str) -> list:
    """A股板块查询"""
    results = []
    try:
        import akshare as ak
    except ImportError:
        return []

    old_no_proxy = os.environ.get("no_proxy", "")
    os.environ["no_proxy"] = "*"

    try:
        sector_df = ak.stock_board_industry_name_em()
        if sector_df is None or sector_df.empty:
            log_source("by_sector", "akshare", "获取A股板块列表", False, "空数据")
            return []

        name_col = None
        for c in ['板块名称', '名称', '行业']:
            if c in sector_df.columns:
                name_col = c
                break
        if name_col is None:
            name_col = sector_df.columns[0]

        mask = sector_df[name_col].str.contains(sector, na=False)
        matched_sectors = sector_df[mask]
        if matched_sectors.empty:
            return []

        target_sector = matched_sectors.iloc[0][name_col]
        stock_df = ak.stock_board_industry_cons_em(symbol=target_sector)
        log_source("by_sector", "akshare", "获取A股板块成分股", True, f"{target_sector}: {len(stock_df) if stock_df is not None else 0} 条")
        if stock_df is None or stock_df.empty:
            return []

        codes = []
        for col in ['代码', '股票代码', 'code', '股票代码']:
            if col in stock_df.columns:
                codes = stock_df[col].tolist()
                break
        if not codes:
            return []

        os.environ["no_proxy"] = old_no_proxy

        qq_codes = []
        for c in codes:
            c = str(c).strip()
            if c.startswith(('6', '8')):
                qq_codes.append(f"sh{c}")
            elif c.startswith(('0', '3')):
                qq_codes.append(f"sz{c}")
            else:
                qq_codes.append(c)

        if not qq_codes:
            return []

        url = f"http://qt.gtimg.cn/q={','.join(qq_codes)}"
        try:
            r = requests.get(url, timeout=30)
            log_source("by_sector", "tencent", "批量获取A股行情", True, f"{len(qq_codes)} 只")
        except Exception as e:
            log_source("by_sector", "tencent", "批量获取A股行情", False, f"{type(e).__name__}: {e}")
            return []
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
            code_ret = parts[2] if len(parts) > 2 else ""
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
                    'code': code_ret,
                    'name': name_ret,
                    'price': price,
                    'change_pct': change_pct,
                    'market_cap': mcap,
                    'source': '腾讯行情',
                    'strategy_matched': 'by_sector'
                })
    except Exception as e:
        log_source("by_sector", "akshare", "A股板块查询", False, f"{type(e).__name__}: {e}")
    finally:
        os.environ["no_proxy"] = old_no_proxy

    return results


def _search_by_sector_hk(sector: str) -> list:
    """港股板块查询"""
    results = []
    try:
        import akshare as ak
    except ImportError:
        return []

    old_no_proxy = os.environ.get("no_proxy", "")
    os.environ["no_proxy"] = "*"

    try:
        try:
            sector_df = ak.stock_board_hk_industry_name_em()
        except Exception as e:
            log_source("by_sector", "akshare", "获取港股板块列表", False, f"{type(e).__name__}: {e}")
            return []

        if sector_df is None or sector_df.empty:
            log_source("by_sector", "akshare", "获取港股板块列表", False, "空数据")
            return []

        name_col = None
        for c in ['板块名称', '名称', '行业', '行业名称']:
            if c in sector_df.columns:
                name_col = c
                break
        if name_col is None:
            name_col = sector_df.columns[0]

        mask = sector_df[name_col].str.contains(sector, na=False)
        matched_sectors = sector_df[mask]
        if matched_sectors.empty:
            return []

        target_sector = matched_sectors.iloc[0][name_col]

        try:
            stock_df = ak.stock_board_hk_industry_cons_em(symbol=target_sector)
        except Exception as e:
            log_source("by_sector", "akshare", "获取港股板块成分股", False, f"{type(e).__name__}: {e}")
            return []

        log_source("by_sector", "akshare", "获取港股板块成分股", True, f"{target_sector}: {len(stock_df) if stock_df is not None else 0} 条")
        if stock_df is None or stock_df.empty:
            return []

        codes = []
        for col in ['代码', '股票代码', 'code', '股票代码', 'symbol']:
            if col in stock_df.columns:
                codes = stock_df[col].tolist()
                break
        if not codes:
            return []

        os.environ["no_proxy"] = old_no_proxy

        qq_codes = [f"hk{int(c):05d}" for c in codes]

        if not qq_codes:
            return []

        url = f"http://qt.gtimg.cn/q={','.join(qq_codes)}"
        try:
            r = requests.get(url, timeout=30)
            log_source("by_sector", "tencent", "批量获取港股行情", True, f"{len(qq_codes)} 只")
        except Exception as e:
            log_source("by_sector", "tencent", "批量获取港股行情", False, f"{type(e).__name__}: {e}")
            return []
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
            code_ret = parts[2] if len(parts) > 2 else ""
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
                    'code': code_ret,
                    'name': name_ret,
                    'price': price,
                    'change_pct': change_pct,
                    'market_cap': mcap,
                    'source': '腾讯行情',
                    'strategy_matched': 'by_sector'
                })
    except Exception as e:
        log_source("by_sector", "akshare", "港股板块查询", False, f"{type(e).__name__}: {e}")
    finally:
        os.environ["no_proxy"] = old_no_proxy

    return results


def _search_by_sector_us(sector: str) -> list:
    """美股板块查询 - 返回空（美股板块概念不同）"""
    return []