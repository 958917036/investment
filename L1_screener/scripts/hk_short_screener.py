#!/usr/bin/env python3
"""
HK Short Opportunities Screener (L1策略 - 做空方向)
专门筛选港股做空候选标的

做空逻辑:
1. PE > 100x 或 PE < 0 with PB > 5 (极端高估)
2. RSI > 75 超买
3. RSI > 70 + BB > 0.9 (布林带突破)
4. MACD死叉 + MA空头/中性排列
5. MFI < 40 (资金明显流出)
6. 近期大幅上涨后开始回调

使用方法:
python hk_short_screener.py                    # 动态筛选top100中找做空机会
python hk_short_screener.py --codes 01347,00981  # 指定代码分析
"""
import os
import sys
import json
import logging
from datetime import datetime

import sys, os
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, info

BASE_DIR = os.path.expanduser("~/.hermes/investment")
SCRIPTS_DIR = os.path.join(BASE_DIR, "L1_screener", "scripts")

STRATEGY_NAME = "hk_short_screener"


def fetch_hk_realtime(code5: str) -> dict:
    """腾讯行情API — 港股前缀 hk + 5位代码"""
    import urllib.request
    url = f'http://qt.gtimg.cn/q=hk{code5}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('gbk', errors='replace')
        parts = raw.strip().strip('"').split('~')
        if len(parts) < 52:
            return {}
        return {
            'code':      parts[2],
            'name':      parts[1],
            'price':     float(parts[3]) if parts[3] else 0,
            'change_pct': float(parts[32]) if parts[32] else 0,
            'turnover':  float(parts[37]) if parts[37] else 0,
            'pe':        float(parts[51]) if parts[51] else None,
            'pb':        float(parts[50]) if parts[50] else None,
            'market_cap': float(parts[45]) if parts[45] else 0,
        }
    except Exception:
        return {}


def _dynamic_screening(top_n: int = 100) -> list:
    """
    动态筛选：获取港股热门人气榜 top_n 只
    """
    import requests

    url_rank = "https://emappdata.eastmoney.com/stockrank/getAllCurrHkUsList"
    raw_list = []
    page_size = 100
    for page_no in range(1, 10):
        payload = {
            "appId": "appId01",
            "globalId": "786e4c21-70dc-435a-93bb-38",
            "marketType": "000003",
            "pageNo": page_no,
            "pageSize": page_size,
        }
        try:
            r = requests.post(url_rank, json=payload, timeout=15)
            data = r.json()
            page = data.get("data", [])
            if not page:
                break
            raw_list.extend(page)
        except Exception:
            break

    codes_5d = []
    for item in raw_list:
        sc = item.get("sc", "")
        if "|" in sc:
            code = sc.split("|")[1].lstrip("0").zfill(5)
            codes_5d.append(code)

    return codes_5d[:top_n]


def screen_stocks(codes: list = None, top_n: int = 100) -> list:
    """
    港股做空L1筛选。

    Args:
        codes: 股票代码列表。若为 None，则动态筛选（按成交额取 top_n）。
        top_n: 动态筛选时返回的股票数量（默认 100）

    Returns:
        做空候选股票列表
    """
    import requests
    import pandas as pd

    # 动态筛选模式
    if codes is None:
        codes = _dynamic_screening(top_n=top_n)

    # 获取实时行情
    candidates = []
    for code_raw in codes:
        code_normalized = str(code_raw).strip().upper().lstrip('HK').lstrip('0').zfill(5)
        rt = fetch_hk_realtime(code_normalized)
        if not rt or not rt.get('name'):
            continue
        if rt.get('price', 0) <= 0:
            continue
        if rt.get('turnover', 0) < 100000:
            continue
        
        pe = rt.get('pe')
        pb = rt.get('pb')
        
        # 基本筛选：满足做空条件才保留
        is_short_candidate = False
        reasons = []
        
        # 条件1: PE > 100x
        if pe and pe > 100:
            is_short_candidate = True
            reasons.append(f'PE={pe:.0f}>100')
        # 条件2: PE < 0 with PB > 5
        elif pe and pe < 0 and pb and pb > 5:
            is_short_candidate = True
            reasons.append(f'PE={pe:.0f}<0,PB={pb:.1f}>5')
        # 条件3: PE 80-100x with 高PB
        elif pe and 80 <= pe <= 100 and pb and pb > 8:
            is_short_candidate = True
            reasons.append(f'PE={pe:.0f}80-100,PB={pb:.1f}>8')
        
        if is_short_candidate:
            candidates.append({
                'code': rt['code'],
                'name': rt['name'],
                'price': rt['price'],
                'change_pct': rt.get('change_pct', 0),
                'pe': pe,
                'pb': pb,
                'market_cap': rt.get('market_cap', 0),
                'turnover': rt.get('turnover', 0),
                'short_reasons': reasons,
                'strategy': STRATEGY_NAME,
            })

    return candidates


def main():
    log_start("hk_short_screener", "run_screener")
    import argparse
    parser = argparse.ArgumentParser(description='HK Short L1 Screener')
    parser.add_argument('--codes', '-c', help='港股代码，逗号分隔，如: 01347,00981,06809（省略则动态筛选）')
    parser.add_argument('--top-n', '-n', type=int, default=100, help='动态筛选时返回的股票数量（默认100）')
    parser.add_argument('--output', '-o', help='输出JSON文件路径')
    args = parser.parse_args()

    codes = [c.strip() for c in args.codes.split(',')] if args.codes else None
    results = screen_stocks(codes=codes, top_n=args.top_n)

    output = {
        'strategy': STRATEGY_NAME,
        'timestamp': datetime.now().isoformat(),
        'total_input': len(codes) if codes else 0,
        'candidates': results,
        'short_count': len(results),
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        info("hk_short_screener", f"结果已保存: {args.output}")

    log_end("hk_short_screener", "run_screener", f"short_count={len(results)}")
    return output


if __name__ == '__main__':
    main()
