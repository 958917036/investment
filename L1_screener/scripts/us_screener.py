#!/usr/bin/env python3
"""
US Stock Screener (L1策略)
适用于美股标的筛选，验证股票代码有效性并获取基础行情。

两种模式：
1. tickers=None（默认）：从 Wikipedia S&P 500 列表获取候选（约504只），腾讯API验证
2. tickers!=None：用户指定 ticker 模式 — 腾讯API验证即可通过
"""

import os
import sys

import sys, os
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, info

BASE_DIR = os.path.expanduser("~/.hermes/investment")
SCRIPTS_DIR = os.path.join(BASE_DIR, "L1_screener", "scripts")

STRATEGY_NAME = "us_screener"

# 备用硬编码列表（当 Wikipedia 不可用时）
_US_MAJOR_TICKERS_FALLBACK = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "BRK.B", "LLY", "AVGO",
    "JPM", "V", "MA", "HD", "COST", "JNJ", "PG", "UNH", "ABBV", "MRK",
    "CRM", "CVX", "KO", "PEP", "BAC", "WMT", "TMO", "ACN", "ADBE", "NFLX",
    "AMD", "INTC", "QCOM", "TXN", "AMAT", "ASML", "MU", "LRCX",
    "GS", "MS", "AXP", "BLK", "SCHW", "USB", "PNC", "TFC", "COF",
    "NOW", "INTU", "DASH", "UBER", "SQ", "SHOP", "PYPL",
    "DIS", "CMCSA", "VZ", "T", "TMUS",
    "NEE", "SO", "DUK", "D", "AEP", "EXC", "XEL",
    "BMY", "PFE", "AMGN", "GILD", "BIIB", "VRTX",
    "CAT", "DE", "CMI", "ROK", "EMR", "HON", "GE", "MMM", "ITW", "ETN",
    "SPGI", "MCO", "NDAQ", "ICE", "CME", "COIN", "MSTR",
    "RIVN", "LCID", "PLTR", "SNOW", "DDOG", "CRWD", "NET", "ZS", "OKTA",
    "TSM", "GOLD", "NVO", "BABA", "PDD", "BIDU", "NTES", "JD",
    "AMC", "GME", "BB",
]


def fetch_sp500_from_wikipedia() -> list:
    """从 Wikipedia S&P 500 页面抓取成分股列表（约504只）"""
    import urllib.request
    import re

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")
    except Exception:
        return _US_MAJOR_TICKERS_FALLBACK

    # 在 wikitable 区域查找所有 ticker
    start = html.find("wikitable sortable")
    if start == -1:
        start = html.find("wikitable")
    end = min(start + 500000, len(html)) if start != -1 else len(html)
    section = html[start:end] if start != -1 else html

    # 提取所有 <a>TICKER</a> 模式（A-Z 1-5字符）
    bad = {"GICS", "CIK", "SEC", "ETF", "ETFs", "NASDAQ", "NYSE", "AMEX",
           "SPDR", "S&P", "PDF", "FORM", "FILE", "HTTP", "HTTPS", "WWW"}
    tickers = re.findall(r'<a[^>]*>([A-Z]{2,5})</a>', section)
    tickers = sorted(set([t for t in tickers
                          if len(t) >= 2 and len(t) <= 5
                          and t.isalpha()
                          and t not in bad]))
    return tickers if len(tickers) >= 100 else _US_MAJOR_TICKERS_FALLBACK


def fetch_us_realtime(ticker: str) -> dict:
    """腾讯行情API — 美股前缀 us + ticker"""
    import urllib.request
    url = f'http://qt.gtimg.cn/q=us{ticker}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('gbk', errors='replace')
        parts = raw.strip().strip('"').split('~')
        if len(parts) < 50:
            return {}
        return {
            'code':      parts[2].split('.')[0] if '.' in parts[2] else parts[2],  # "NVDA.OQ" → "NVDA"
            'name':      parts[1],
            'price':     float(parts[3]) if parts[3] else 0,
            'change_pct': float(parts[32]) if parts[32] else 0,
            'pe':        float(parts[39]) if parts[39] else None,
            'market_cap': float(parts[44]) if parts[44] else 0,  # 亿美元
            'volume':    float(parts[6]) if parts[6] else 0,
        }
    except Exception:
        return {}


def _dynamic_screening(top_n: int = 500) -> list:
    """
    从 Wikipedia S&P 500 列表获取候选（约504只），腾讯API验证有效性。
    不依赖 AkShare，彻底绕过 eastmoney 代理封锁问题。
    """
    import urllib.request

    candidates = fetch_sp500_from_wikipedia()
    validated = []
    batch_size = 40

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        symbols = ",".join(f"us{t}" for t in batch)
        url = f"http://qt.gtimg.cn/q={symbols}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gbk", errors="replace")
            lines = raw.strip().split("\n")
            for line in lines:
                parts = line.strip().strip('"').split("~")
                if len(parts) < 10:
                    continue
                try:
                    price = float(parts[3]) if parts[3] else 0
                    volume = float(parts[6]) if parts[6] else 0
                    ticker_raw = parts[2]  # "NVDA.OQ"
                    ticker = ticker_raw.split('.')[0]  # "NVDA"
                    if price > 5 and volume > 1_000_000 and ticker:
                        validated.append(ticker)
                except (ValueError, IndexError):
                    continue
        except Exception:
            pass

    return validated[:top_n]


def screen_stocks(tickers: list = None, top_n: int = 100) -> list:
    """
    美股L1筛选。

    Args:
        tickers: ticker 列表。若为 None，则动态筛选（按成交量取 top_n）。
        top_n: 动态筛选时返回的股票数量（默认 100）

    Returns:
        候选股票列表
    """
    # ── 动态筛选模式 ──────────────────────────────
    if tickers is None:
        tickers = _dynamic_screening(top_n=top_n)

    # ── 用户指定 ticker 模式 ─────────────────────
    candidates = []
    for ticker_raw in tickers:
        ticker = str(ticker_raw).strip().upper()
        if not ticker:
            continue
        rt = fetch_us_realtime(ticker)
        if not rt or not rt.get('name'):
            continue
        if rt.get('price', 0) <= 0:
            continue
        if rt.get('volume', 0) < 10000:
            continue
        candidates.append({
            'code': rt['code'],
            'name': rt['name'],
            'price': rt['price'],
            'change_pct': rt.get('change_pct', 0),
            'pe': rt.get('pe'),
            'market_cap': rt.get('market_cap', 0),
            'volume': rt.get('volume', 0),
            'score': 50.0,
            'strategy': STRATEGY_NAME,
        })
    return candidates


def main():
    log_start("us_screener", "run_screener")
    import argparse
    parser = argparse.ArgumentParser(description='US L1 Screener')
    parser.add_argument('--tickers', '-t', help='美股代码，逗号分隔，如: SMCI,NVDA,AAPL（省略则动态筛选）')
    parser.add_argument('--top-n', '-n', type=int, default=100, help='动态筛选时返回的股票数量（默认100）')
    parser.add_argument('--output', '-o', help='输出JSON文件路径')
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(',')] if args.tickers else None
    results = screen_stocks(tickers=tickers, top_n=args.top_n)

    import json
    from datetime import datetime
    output = {
        'strategy': STRATEGY_NAME,
        'timestamp': datetime.now().isoformat(),
        'total_input': len(tickers) if tickers else 0,
        'candidates': results,
    }

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        info("us_screener", f"结果已保存: {args.output}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))

    log_end("us_screener", "run_screener", f"candidates={len(results)}")
    return output


if __name__ == '__main__':
    main()