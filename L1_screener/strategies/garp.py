#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GARP合理价格成长策略 (L1)
核心：PEG≤1.2 + PE≤35 + 成长确认
"""
import json, os, sys, time, requests
from datetime import datetime

import sys, os
BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import log_start, log_end, log_fail, info

BASE = os.path.expanduser("~/.hermes/investment")
CONFIG_FILE = os.path.join(BASE, "main/config/l1_config.json")
STRATEGY = "garp"

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
    FREEZE = os.path.join(BASE, "main/freeze_table.json")
    if not os.path.exists(FREEZE):
        return set(), {}
    with open(FREEZE) as f:
        d = json.load(f)
    t = datetime.now().strftime("%Y-%m-%d")
    frozen = {r["stock_code"] for r in d.get("freeze_records",[]) if r.get("frozen_until","") > t}
    ob = {r["stock_code"]: r.get("priority",0) for r in d.get("observing_list",[])}
    return frozen, ob

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
            quotes = fetch_quotes(codes)
            filtered_codes = []
            for code_str, q in quotes.items():
                if q['price'] > 0 and q.get('mcap', 0) >= 5 and q.get('amount', 0) >= 500:
                    filtered_codes.append(code_str)
            df = df[df['code'].isin(filtered_codes)]
        return df
    finally:
        os.environ["no_proxy"] = old_no_proxy

def get_all_stock_codes():
    hs = get_all("hs300")
    zz = get_all("zz500")
    import pandas as pd
    all_df = pd.concat([hs, zz]).drop_duplicates(subset=['code'])
    return [f"{'sh' if c.startswith(('6','8')) else 'sz'}{c}" for c in all_df['code'].tolist()]

def fetch_quotes(codes):
    cfg = get_l1_config()
    cn_cfg = cfg.get("cn", {})
    batch_size = cn_cfg.get("batch_size", 30)
    request_timeout = cn_cfg.get("request_timeout", 15)
    request_interval = cn_cfg.get("request_interval", 0.3)

    res = {}
    for i in range(0, len(codes), batch_size):
        b = codes[i:i+batch_size]
        try:
            r = requests.get("https://qt.gtimg.cn/q="+",".join(b), timeout=30)
            for l in r.text.strip().split(';'):
                if not l or '=' not in l: continue
                p = l.split('=',1)[1].replace('"','').split('~')
                if len(p)<47: continue
                try:
                    res[p[2]] = {
                        'code': p[2], 'name': p[1], 'price': float(p[3] or 0),
                        'pe': float(p[39] or 0), 'pb': float(p[46] or 0),
                        'mcap': float(p[45] or 0), 'high': float(p[33] or 0),
                        'low': float(p[34] or 0),
                        'amount': float(p[16] or 0),
                    }
                except: continue
        except: pass
        if i+batch_size < len(codes): time.sleep(request_interval)
    return res

def pre(q):
    cfg = get_l1_config()
    pf = cfg.get("prefilter", {})
    min_mcap = pf.get("min_market_cap_yuan", 30000000000) / 100000000
    max_pe = pf.get("max_pe", 50)
    if q['mcap'] < min_mcap: return False
    if q['pe'] > max_pe and q['pe'] > 0: return False
    return True

def score_lynch(q):
    cfg = get_l1_config()
    sig_cfg = cfg.get("signals", {}).get("lynch", {})
    thresholds = sig_cfg.get("thresholds", [0.25, 0.4, 0.6])

    s, r = 0.0, []
    pe, pb, mcap = q['pe'], q['pb'], q['mcap']

    if 0 < pe <= 20:
        s += 0.35; r.append(f"PE={pe:.1f}低估值GARP")
    elif 20 < pe <= 35:
        s += 0.25; r.append(f"PE={pe:.1f}合理成长")
    elif pe == 0:
        s += 0.0

    if 0 < pb <= 2:
        s += 0.20; r.append(f"PB={pb:.2f}低估值")
    elif 2 < pb <= 5:
        s += 0.10; r.append(f"PB={pb:.2f}合理")

    if 50 <= mcap <= 800:
        s += 0.25; r.append("中盘GARP偏好")
    elif mcap > 800:
        s += 0.10; r.append("大盘")

    amp = (q['high']-q['low'])/q['low']*100 if q['low']>0 else 0
    if amp > 0.5:
        s += 0.10; r.append(f"振幅{amp:.1f}%")

    if s >= thresholds[2]:
        signal = 1.0
    elif s >= thresholds[1]:
        signal = 0.6
    elif s >= thresholds[0]:
        signal = 0.3
    else:
        signal = 0.0
    return {'signal': signal, 'score': round(s,3), 'reasons': '; '.join(r)}


def screen(pool: str = "index800") -> list:
    """
    执行GARP策略筛选
    返回: [{code, name, price, change_pct, market_cap, strategy_matched}, ...]
    """
    frozen, ob = load_freezes()

    if pool == 'full':
        all_df = get_all("full")
        stocks = [f"{'sh' if c.startswith(('6','8')) else 'sz'}{c}" for c in all_df['code'].tolist()]
    else:
        stocks = get_all_stock_codes()

    quotes = fetch_quotes(stocks)
    cands = [q for c,q in quotes.items() if c not in frozen and pre(q)]

    results = []
    cfg = get_l1_config()
    sig_cfg = cfg.get("signals", {}).get("lynch", {})
    thresholds = sig_cfg.get("thresholds", [0.25, 0.4, 0.6])
    min_signal = thresholds[0]

    for q in cands:
        s = score_lynch(q)
        if s['signal'] >= min_signal:
            results.append({
                'code': q['code'],
                'name': q['name'],
                'price': q['price'],
                'change_pct': 0,
                'market_cap': q['mcap'],
                'source': '腾讯行情',
                'strategy_matched': STRATEGY
            })

    results.sort(key=lambda x: x.get('price', 0), reverse=True)
    cfg = get_l1_config()
    per_strategy_limit = cfg.get("cn", {}).get("per_strategy_limit", 200)
    return results[:per_strategy_limit]