#!/usr/bin/env python3
"""
HK Stock Screener (L1策略)
适用于港股标的筛选，验证股票代码有效性并获取基础行情。

两种模式：
1. codes=None（默认）：动态筛选模式 — 调用 AkShare stock_hk_spot_em()
   按成交额排序，取 top_n 只（成交额>1000万HKD，排除ETF/基金）
2. codes!=None：用户指定代码模式 — 腾讯API验证可获取即通过
"""

import os
import sys

import sys, os
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, info

BASE_DIR = os.path.expanduser("~/.hermes/investment")
SCRIPTS_DIR = os.path.join(BASE_DIR, "L1_screener", "scripts")

STRATEGY_NAME = "hk_screener"


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
            'turnover':  float(parts[37]) if parts[37] else 0,   # 成交额(HKD)
            'pe':        float(parts[51]) if parts[51] else None,
            'pb':        float(parts[50]) if parts[50] else None,
            'market_cap': float(parts[45]) if parts[45] else 0,  # 市值(HKD)
        }
    except Exception:
        return {}


def _dynamic_screening(top_n: int = 100) -> list:
    """
    动态筛选：获取港股热门人气榜 top_n 只（不走 push2.eastmoney.com）。
    
    实现：
    1. emappdata.eastmoney.com（直连）→ 获取100只热门股票代码
    2. 腾讯 qt.gtimg.cn（直连）→ 批量获取这100只的实时行情+总市值
    3. 按总市值降序，取 top_n，排除 ETF/基金/信托
    
    绕过 push2.eastmoney.com（Clash 代理不支持该域名）。
    """
    import requests
    import pandas as pd

    # Step 1: 获取热门股票列表（直连 emappdata，代理不影响）
    # 注意：emappdata 单次上限 pageSize=100，需分页
    url_rank = "https://emappdata.eastmoney.com/stockrank/getAllCurrHkUsList"
    raw_list = []
    page_size = 100
    for page_no in range(1, 10):  # 最多取 9 页 = 900 只
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

    # 提取代码列表
    codes_5d = []
    for item in raw_list:
        sc = item.get("sc", "")
        if "|" in sc:
            code = sc.split("|")[1].lstrip("0").zfill(5)
            codes_5d.append(code)

    # Step 2: 腾讯批量行情补全（直连 qt.gtimg.cn）
    quotes = {}
    BATCH = 30
    for i in range(0, len(codes_5d), BATCH):
        batch = codes_5d[i : i + BATCH]
        hk_batch = ["hk" + c for c in batch]
        qurl = "https://qt.gtimg.cn/q=" + ",".join(hk_batch)
        try:
            qr = requests.get(qurl, timeout=8)
            for line in qr.text.strip().split("\n"):
                if "~" not in line:
                    continue
                parts = line.split("~")
                raw_key = parts[0].replace("v_", "").replace('"', "").split("=")[0]
                if not raw_key.startswith("hk"):
                    continue
                code5 = raw_key.replace("hk", "")
                try:
                    price = float(parts[3]) if parts[3] else 0
                    mktcap = float(parts[45]) if parts[45] else 0  # 亿元HKD
                    change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else 0
                except (ValueError, IndexError):
                    price = 0
                    mktcap = 0
                    change_pct = 0
                quotes[code5] = {
                    "name": parts[1] if len(parts) > 1 else "",
                    "price": price,
                    "mktcap_bn": mktcap,
                    "change_pct": change_pct,
                }
        except Exception:
            continue

    # Step 3: 合并，按市值降序
    rows = []
    for code5 in codes_5d:
        q = quotes.get(code5, {})
        if not q.get("price") or q["price"] <= 0:
            continue
        rows.append(
            {
                "code5": code5,
                "name": q["name"],
                "price": q["price"],
                "mktcap_bn": q["mktcap_bn"],
                "change_pct": q["change_pct"],
            }
        )

    if not rows:
        return []

    df = pd.DataFrame(rows)

    # 排除 ETF/基金/信托（名称关键词）
    etf_pattern = (
        "ETF|指数|恒生|南方|安硕|iShares|Direxion|"
        "XL(?![a-zA-Z])|XI(?!-)|FL |FI |杠杆|反向|2x|3x|倍鹏|"
        "基金|信托|Reits|鹏信|华兴"
    )
    df_filtered = df[~df["name"].str.contains(etf_pattern, regex=True, na=False)]

    # 按市值降序
    df_sorted = df_filtered.sort_values("mktcap_bn", ascending=False)
    top = df_sorted.head(top_n)

    return top["code5"].tolist()


def screen_stocks(codes: list = None, top_n: int = 100) -> list:
    """
    港股L1筛选。

    Args:
        codes: 股票代码列表。若为 None，则动态筛选（按成交额取 top_n）。
        top_n: 动态筛选时返回的股票数量（默认 100）

    Returns:
        候选股票列表，每项含 code/name/price/turnover 等字段
    """
    # ── 动态筛选模式 ──────────────────────────────
    if codes is None:
        codes = _dynamic_screening(top_n=top_n)

    # ── 用户指定代码模式 ─────────────────────────
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
        candidates.append({
            'code': rt['code'],
            'name': rt['name'],
            'price': rt['price'],
            'change_pct': rt.get('change_pct', 0),
            'pe': rt.get('pe'),
            'pb': rt.get('pb'),
            'market_cap': rt.get('market_cap', 0),
            'turnover': rt.get('turnover', 0),
            'score': 50.0,
            'strategy': STRATEGY_NAME,
        })
    return candidates


def main():
    log_start("hk_screener", "run_screener")
    import argparse
    parser = argparse.ArgumentParser(description='HK L1 Screener')
    parser.add_argument('--codes', '-c', help='港股代码，逗号分隔，如: 3690,00700,9988（省略则动态筛选）')
    parser.add_argument('--top-n', '-n', type=int, default=100, help='动态筛选时返回的股票数量（默认100）')
    parser.add_argument('--output', '-o', help='输出JSON文件路径')
    args = parser.parse_args()

    codes = [c.strip() for c in args.codes.split(',')] if args.codes else None
    results = screen_stocks(codes=codes, top_n=args.top_n)

    import json
    from datetime import datetime
    output = {
        'strategy': STRATEGY_NAME,
        'timestamp': datetime.now().isoformat(),
        'total_input': len(codes) if codes else 0,
        'candidates': results,
    }

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        info("hk_screener", f"结果已保存: {args.output}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))

    log_end("hk_screener", "run_screener", f"candidates={len(results)}")
    return output


if __name__ == '__main__':
    main()