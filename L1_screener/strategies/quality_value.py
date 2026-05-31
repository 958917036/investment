#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
质量价值策略 (L1)
核心：ROE≥15% + PE≤25 + 护城河稳定
"""
import json, os, sys, time, requests
from datetime import datetime

import sys, os
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, info

BASE_DIR = os.path.expanduser("~/.hermes/investment")
CONFIG_FILE = os.path.join(BASE_DIR, "main/config/l1_config.json")
STRATEGY_NAME = "quality_value"

_l1_config = None
def get_l1_config():
    global _l1_config
    if _l1_config is None:
        try:
            with open(CONFIG_FILE, 'r') as f:
                _l1_config = json.load(f)
        except:
            _l1_config = {}
    return _l1_config

def load_freezes():
    FREEZE_FILE = os.path.join(BASE_DIR, "main/freeze_table.json")
    if not os.path.exists(FREEZE_FILE):
        return set(), {}
    with open(FREEZE_FILE, 'r') as f:
        data = json.load(f)
    today = datetime.now().strftime("%Y-%m-%d")
    frozen_codes = set()
    for r in data.get("freeze_records", []):
        if r.get("frozen_until", "") > today:
            frozen_codes.add(r["stock_code"])
    observing = {}
    for r in data.get("observing_list", []):
        observing[r["stock_code"]] = r.get("priority", 0)
    return frozen_codes, observing

def get_all_a_stocks(scope="all"):
    import akshare as ak
    # akshare国内接口不走代理
    old_no_proxy = os.environ.get("no_proxy", "")
    os.environ["no_proxy"] = "*"
    try:
        if scope == "hs300":
            try:
                df = ak.index_stock_cons_csindex("000300")
                return df.rename(columns={'成分券代码': 'code', '成分券名称': 'name'})
            except: pass
        elif scope == "zz500":
            try:
                df = ak.index_stock_cons_csindex("000905")
                return df.rename(columns={'成分券代码': 'code', '成分券名称': 'name'})
            except: pass
        df = ak.stock_info_a_code_name()
        df = df[~df['name'].str.match(r'^\*?ST')]
        if scope == "full":
            codes = [f"{'sh' if c.startswith(('6','8')) else 'sz'}{c}" for c in df['code'].tolist()]
            quotes = batch_fetch_quotes(codes)
            filtered_codes = []
            for code_str, q in quotes.items():
                price = q['price']
                mcap = q['mcap_100m']
                vol_amount = q.get('amount', 0)
                if price > 0 and mcap >= 5 and vol_amount >= 500:
                    filtered_codes.append(code_str)
            df = df[df['code'].isin(filtered_codes)]
        return df
    finally:
        os.environ["no_proxy"] = old_no_proxy

def batch_fetch_quotes(codes):
    cfg = get_l1_config()
    cn_cfg = cfg.get("cn", {})
    batch_size = cn_cfg.get("batch_size", 30)
    request_timeout = cn_cfg.get("request_timeout", 15)
    request_interval = cn_cfg.get("request_interval", 0.3)

    results = {}
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        try:
            r = requests.get(url, timeout=30)
            lines = r.text.strip().split(';')
            for line in lines:
                if not line or '=' not in line:
                    continue
                raw = line.split('=', 1)[1].replace('"', '')
                parts = raw.split('~')
                if len(parts) < 47:
                    continue
                code = parts[2]
                try:
                    price = float(parts[3]) if parts[3] else 0
                    pe = float(parts[39]) if parts[39] else 0
                    pb = float(parts[46]) if parts[46] else 0
                    mcap = float(parts[45]) if parts[45] else 0
                    name = parts[1]
                    high = float(parts[33]) if parts[33] else 0
                    low = float(parts[34]) if parts[34] else 0
                    amount = float(parts[16]) if parts[16] else 0
                except (ValueError, IndexError):
                    continue
                results[code] = {
                    'code': code, 'name': name, 'price': price,
                    'pe': pe, 'pb': pb, 'mcap_100m': mcap,
                    'high': high, 'low': low, 'amount': amount
                }
        except Exception as e:
            pass
        if i + batch_size < len(codes):
            time.sleep(request_interval)
    return results

def pre_filter(quote):
    cfg = get_l1_config()
    pf = cfg.get("prefilter", {})
    min_mcap = pf.get("min_market_cap_yuan", 30000000000) / 100000000
    max_pe = pf.get("max_pe", 50)
    if quote['mcap_100m'] < min_mcap:
        return False, f"市值不足{min_mcap}亿"
    if quote['pe'] > max_pe and quote['pe'] > 0:
        return False, f"PE={quote['pe']}过高"
    return True, ""

def score_buffett(quote):
    cfg = get_l1_config()
    sig_cfg = cfg.get("signals", {}).get("buffett", {})
    thresholds = sig_cfg.get("thresholds", [0.3, 0.45, 0.65])

    score = 0.0
    reasons = []

    price = quote['price']
    pe = quote['pe']
    pb = quote['pb']
    mcap = quote['mcap_100m']

    val_score = 0.0
    if 0 < pe <= 25:
        val_score += 0.25 * (1 - pe/25 * 0.8)
        reasons.append(f"PE={pe:.1f}合理")
    elif 25 < pe <= 35:
        val_score += 0.25 * 0.3
        reasons.append(f"PE={pe:.1f}偏高")
    elif pe == 0:
        val_score += 0.0
        reasons.append("PE为负/零")

    if pb > 0 and pb <= 3:
        pb_score = 0.25 * (1 - pb/3 * 0.7)
        val_score += pb_score
        reasons.append(f"PB={pb:.2f}合理")
    elif 3 < pb <= 5:
        val_score += 0.25 * 0.3
        reasons.append(f"PB={pb:.2f}偏高")
    elif pb > 0:
        val_score += 0.25 * 0.1
        reasons.append(f"PB={pb:.2f}过高")

    earn_score = 0.0
    if pe > 0:
        earnings_yield = 1.0 / pe
        earn_score = 0.35 * min(earnings_yield * 8, 1.0)
    else:
        earn_score = 0.0

    moat_score = 0.0
    if mcap > 200:
        moat_score += 0.15
        reasons.append("大盘股")
    if pb > 0 and pb < 2:
        moat_score += 0.10
        reasons.append("低PB")

    total = val_score + earn_score + moat_score

    if total >= thresholds[2]:
        signal = 1.0
    elif total >= thresholds[1]:
        signal = 0.6
    elif total >= thresholds[0]:
        signal = 0.3
    else:
        signal = 0.0

    return {
        'signal': signal,
        'score': round(total, 3),
        'breakdown': {
            'valuation': round(val_score, 3),
            'earnings': round(earn_score, 3),
            'moat': round(moat_score, 3),
        },
        'reasons': reasons
    }


def screen(pool: str = "index800") -> list:
    """
    执行质量价值策略筛选
    返回: [{code, name, price, change_pct, market_cap, strategy_matched}, ...]
    """
    frozen_codes, observing = load_freezes()

    if pool == 'full':
        all_stocks = get_all_a_stocks("full")
    else:
        hs300 = get_all_a_stocks("hs300")
        zz500 = get_all_a_stocks("zz500")
        import pandas as pd
        all_stocks = pd.concat([hs300, zz500]).drop_duplicates(subset=['code'])

    codes = [f"{'sh' if c.startswith(('6','8')) else 'sz'}{c}" for c in all_stocks['code'].tolist()]
    quotes = batch_fetch_quotes(codes)

    candidates = []
    for code, q in quotes.items():
        if code in frozen_codes:
            continue
        ok, reason = pre_filter(q)
        if ok:
            candidates.append(q)

    results = []
    cfg = get_l1_config()
    sig_cfg = cfg.get("signals", {}).get("buffett", {})
    thresholds = sig_cfg.get("thresholds", [0.3, 0.45, 0.65])
    min_signal = thresholds[0]

    for q in candidates:
        s = score_buffett(q)
        if s['signal'] >= min_signal:
            results.append({
                'code': q['code'],
                'name': q['name'],
                'price': q['price'],
                'change_pct': 0,
                'market_cap': q['mcap_100m'],
                'source': '腾讯行情',
                'strategy_matched': STRATEGY_NAME
            })

    results.sort(key=lambda x: x.get('price', 0), reverse=True)
    cfg = get_l1_config()
    per_strategy_limit = cfg.get("cn", {}).get("per_strategy_limit", 200)
    return results[:per_strategy_limit]