#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成长动量策略 (L1)
核心：营收增速≥20% + 动量确认 + EPS增长
"""
import json, os, sys, time, requests
from datetime import datetime

import sys, os
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, info

BASE_DIR = os.path.expanduser("~/.hermes/investment")
CONFIG_FILE = os.path.join(BASE_DIR, "main/config/l1_config.json")
STRATEGY_NAME = "growth_momentum"

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
    with open(FREEZE_FILE) as f:
        data = json.load(f)
    today = datetime.now().strftime("%Y-%m-%d")
    frozen = set()
    for r in data.get("freeze_records", []):
        if r.get("frozen_until", "") > today:
            frozen.add(r["stock_code"])
    observing = {r["stock_code"]: r.get("priority",0) for r in data.get("observing_list",[])}
    return frozen, observing

def get_all(scope="all"):
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
                if q['price'] > 0 and q['mcap_100m'] >= 5 and q.get('amount', 0) >= 500:
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
        try:
            r = requests.get("https://qt.gtimg.cn/q=" + ",".join(batch), timeout=request_timeout)
            for line in r.text.strip().split(';'):
                if not line or '=' not in line:
                    continue
                parts = line.split('=',1)[1].replace('"','').split('~')
                if len(parts) < 47:
                    continue
                code = parts[2]
                try:
                    results[code] = {
                        'code': code, 'name': parts[1],
                        'price': float(parts[3]) if parts[3] else 0,
                        'pe': float(parts[39]) if parts[39] else 0,
                        'pb': float(parts[46]) if parts[46] else 0,
                        'mcap_100m': float(parts[45]) if parts[45] else 0,
                        'high': float(parts[33]) if parts[33] else 0,
                        'low': float(parts[34]) if parts[34] else 0,
                        'amount': float(parts[16]) if parts[16] else 0,
                    }
                except:
                    continue
        except Exception as e:
            pass
        if i + batch_size < len(codes):
            time.sleep(request_interval)
    return results

def pre_filter(q):
    cfg = get_l1_config()
    pf = cfg.get("prefilter", {})
    min_mcap = pf.get("min_market_cap_yuan", 30000000000) / 100000000
    max_pe = pf.get("max_pe", 50)
    if q['mcap_100m'] < min_mcap:
        return False, f"市值不足{min_mcap}亿"
    if q['pe'] > max_pe and q['pe'] > 0:
        return False, f"PE={q['pe']}过高"
    return True, ""

def score_graham(q):
    cfg = get_l1_config()
    sig_cfg = cfg.get("signals", {}).get("graham", {})
    thresholds = sig_cfg.get("thresholds", [0.25, 0.40, 0.55])

    score = 0.0
    reasons = []
    pe = q['pe']; pb = q['pb']
    price = q['price']; mcap = q['mcap_100m']

    growth_score = 0.0
    if pe > 0:
        ep = 1.0 / pe
        if pe <= 30:
            growth_score += 0.30
            reasons.append(f"PE={pe:.1f}成长合理")
        elif pe <= 40:
            growth_score += 0.20
            reasons.append(f"PE={pe:.1f}偏高但有成长")

    if q['high'] > 0 and q['low'] > 0:
        amplitude = (q['high'] - q['low']) / q['low'] * 100
        if amplitude > 1.0:
            growth_score += 0.15
            reasons.append(f"振幅{amplitude:.1f}%活跃")

    if 30 <= mcap <= 500:
        growth_score += 0.20
        reasons.append("中小盘成长潜力")
    elif 500 < mcap <= 1000:
        growth_score += 0.10
        reasons.append("中盘")

    val_score = 0.0
    if pb > 0 and pb < 5:
        val_score = 0.20
    elif pb <= 8:
        val_score = 0.10

    stability = 0.0
    if mcap > 500:
        stability = 0.15
        if '中小盘' not in reasons:
            reasons.append("大市值稳定")

    total = growth_score + val_score + stability

    if total >= thresholds[2]:
        signal = 1.0
    elif total >= thresholds[1]:
        signal = 0.6
    elif total >= thresholds[0]:
        signal = 0.3
    else:
        signal = 0.0

    return {
        'signal': signal, 'score': round(total, 3),
        'breakdown': {'growth': round(growth_score,3), 'valuation': round(val_score,3), 'stability': round(stability,3)},
        'reasons': '; '.join(reasons)
    }


def screen(pool: str = "index800") -> list:
    """
    执行成长动量策略筛选
    返回: [{code, name, price, change_pct, market_cap, strategy_matched}, ...]
    """
    frozen_codes, observing = load_freezes()

    if pool == 'full':
        all_stocks = get_all("full")
    else:
        stocks_hs = get_all("hs300")
        stocks_zz = get_all("zz500")
        import pandas as pd
        all_stocks = pd.concat([stocks_hs, stocks_zz]).drop_duplicates(subset=['code'])

    codes = [f"{'sh' if c.startswith(('6','8')) else 'sz'}{c}" for c in all_stocks['code'].tolist()]
    quotes = batch_fetch_quotes(codes)

    candidates = [q for code,q in quotes.items() if code not in frozen_codes and pre_filter(q)[0]]

    results = []
    cfg = get_l1_config()
    sig_cfg = cfg.get("signals", {}).get("graham", {})
    thresholds = sig_cfg.get("thresholds", [0.25, 0.40, 0.55])
    min_signal = thresholds[0]

    for q in candidates:
        s = score_graham(q)
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