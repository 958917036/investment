#!/usr/bin/env python3
"""
Buffett Quality Value Screener (L1策略)
筛选核心：ROE≥15% + PE≤25 + 护城河稳定
输出：候选股票列表（得分降序），写入 records/
"""

import json
import os
import sys
import time
import requests
from datetime import datetime

import sys, os
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, info

# === 路径 ===
BASE_DIR = os.path.expanduser("~/.hermes/investment")
MAIN_DIR = os.path.join(BASE_DIR, "main")
RECORDS_DIR = os.path.join(MAIN_DIR, "records")
FREEZE_FILE = os.path.join(MAIN_DIR, "freeze_table.json")
SCREENER_DIR = os.path.join(BASE_DIR, "L1_screener/quality_value")
CONFIG_FILE = os.path.join(MAIN_DIR, "config", "l1_config.json")

STRATEGY_NAME = "quality_value"

# === 配置加载 ===
def load_l1_config():
    """从配置文件加载L1参数"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_l1_config = None
def get_l1_config():
    global _l1_config
    if _l1_config is None:
        _l1_config = load_l1_config()
    return _l1_config

# === 工具函数 ===

def load_freezes():
    """加载冷冻表，返回 frozen_codes set 和 observing dict"""
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
    """获取股票列表
    scope="all" → 全市场5500只（慢）
    scope="full" → 全市场+粗筛（排除ST/退市/市值<5亿/日均成交<500万）
    scope="hs300" → 沪深300（快，推荐默认）
    scope="zz500" → 中证500
    """
    import akshare as ak
    if scope == "hs300":
        try:
            df = ak.index_stock_cons_csindex("000300")
            info("quality_value", f"  沪深300成分股: {len(df)}")
            return df.rename(columns={'成分券代码': 'code', '成分券名称': 'name'})
        except:
            info("quality_value", "  沪深300获取失败，回退全市场")
    elif scope == "zz500":
        try:
            df = ak.index_stock_cons_csindex("000905")
            info("quality_value", f"  中证500成分股: {len(df)}")
            return df.rename(columns={'成分券代码': 'code', '成分券名称': 'name'})
        except:
            info("quality_value", "  中证500获取失败，回退全市场")
    
    # 全市场模式
    df = ak.stock_info_a_code_name()
    df = df[~df['name'].str.match(r'^\*?ST')]
    
    if scope == "full":
        info("quality_value", f"  全市场基础列表: {len(df)} 只（已排除ST），正在粗筛...")
        # 批量获取腾讯行情做粗筛（只需price/市值/成交额）
        codes = [f"{'sh' if c.startswith(('6','8')) else 'sz'}{c}" for c in df['code'].tolist()]
        quotes = batch_fetch_quotes(codes)
        info("quality_value", f"  腾讯行情获取: {len(quotes)} 只")
        # 粗筛：价格>0, 市值≥5亿, 日均成交额≥500万
        # 腾讯字段: parts[16]=成交额(万), 用该字段作为日均成交额代理
        filtered_codes = []
        for code_str, q in quotes.items():
            price = q['price']
            mcap = q['mcap_100m']  # 亿
            vol_amount = q.get('amount', 0)  # 万（成交额）
            if price > 0 and mcap >= 5 and vol_amount >= 500:
                filtered_codes.append(code_str)
        df = df[df['code'].isin(filtered_codes)]
        info("quality_value", f"  粗筛后保留: {len(df)} 只（价>0, 市值≥5亿, 日均成交≥500万）")
    
    return df

def batch_fetch_quotes(codes):
    """批量获取腾讯实时行情"""
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
            r = requests.get(url, timeout=request_timeout)
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
                    amount = float(parts[16]) if parts[16] else 0  # 成交额(万)
                except (ValueError, IndexError):
                    continue
                results[code] = {
                    'code': code, 'name': name, 'price': price,
                    'pe': pe, 'pb': pb, 'mcap_100m': mcap,
                    'high': high, 'low': low, 'amount': amount
                }
        except Exception as e:
            info("quality_value", f"  [WARN] Batch fetch error: {e}")
        if i + batch_size < len(codes):
            time.sleep(request_interval)
    return results

# === 筛选逻辑 ===

def pre_filter(quote):
    """前置过滤器：所有策略共享"""
    cfg = get_l1_config()
    pf = cfg.get("prefilter", {})
    min_mcap = pf.get("min_market_cap_yuan", 30000000000) / 100000000  # 转换为亿
    max_pe = pf.get("max_pe", 50)

    # ST已在前面排除
    # 市值 < 30亿
    if quote['mcap_100m'] < min_mcap:
        return False, f"市值不足{min_mcap}亿"
    # PE > 50（过高）
    if quote['pe'] > max_pe and quote['pe'] > 0:
        return False, f"PE={quote['pe']}过高"
    return True, ""

def score_buffett(quote):
    """
    Buffett Quality Value Scoring
    综合得分 = (盈利能力分 + 估值分 + 护城河分 + 财务分) / 4
    由于无法实时获取全部财务数据，基于可用字段近似评分
    """
    score = 0.0
    reasons = []
    
    price = quote['price']
    pe = quote['pe']
    pb = quote['pb']
    mcap = quote['mcap_100m']
    
    # === 估值分 (25%) ===
    val_score = 0.0
    # PE评分：0-30之间越低估越好
    if 0 < pe <= 25:
        val_score += 0.25 * (1 - pe/25 * 0.8)
        reasons.append(f"PE={pe:.1f}合理")
    elif 25 < pe <= 35:
        val_score += 0.25 * 0.3
        reasons.append(f"PE={pe:.1f}偏高")
    elif pe == 0:
        val_score += 0.0
        reasons.append("PE为负/零")
    
    # PB评分
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
    
    # === 盈利能力分 (35%) 近似 ===
    earn_score = 0.0
    # PE的倒数≈盈利收益率，越高越好
    if pe > 0:
        earnings_yield = 1.0 / pe  # E/P
        earn_score = 0.35 * min(earnings_yield * 8, 1.0)  # 8%≈满分
    else:
        earn_score = 0.0
    
    # === 护城河分 (25%) 近似 ===
    moat_score = 0.0
    # PB低说明资产价格合理，大市值公司护城河更强
    if mcap > 200:
        moat_score += 0.15  # 大市值加分
        reasons.append("大盘股")
    if pb > 0 and pb < 2:
        moat_score += 0.10  # 极低PB
        reasons.append("低PB")
    
    # === 综合 ===
    total = val_score + earn_score + moat_score
    # 归一化到signal（从配置读取阈值）
    cfg = get_l1_config()
    sig_cfg = cfg.get("signals", {}).get("buffett", {})
    thresholds = sig_cfg.get("thresholds", [0.3, 0.45, 0.65])

    if total >= thresholds[2]:  # 0.65
        signal = 1.0
    elif total >= thresholds[1]:  # 0.45
        signal = 0.6
    elif total >= thresholds[0]:  # 0.3
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

# === 主流程 ===

def main(pool='index800'):
    os.makedirs(RECORDS_DIR, exist_ok=True)

    log_start("quality_value", "run_screener", f"pool={pool}")
    info("quality_value", f"股票池: {'全市场(粗筛)' if pool == 'full' else '沪深300+中证500'}")

    # Step 1: 加载冷冻表
    frozen_codes, observing = load_freezes()
    info("quality_value", f"冷冻表: {len(frozen_codes)} 只冻结, {len(observing)} 只观察")

    # Step 2: 获取股票列表
    if pool == 'full':
        info("quality_value", "获取全市场股票列表(粗筛过滤)...")
        all_stocks = get_all_a_stocks("full")
        info("quality_value", f"全市场粗筛后: {len(all_stocks)} 只")
    else:
        info("quality_value", "获取股票列表(沪深300+中证500)...")
        hs300 = get_all_a_stocks("hs300")
        zz500 = get_all_a_stocks("zz500")
        import pandas as pd
        all_stocks = pd.concat([hs300, zz500]).drop_duplicates(subset=['code'])
        info("quality_value", f"合并去重后: {len(all_stocks)} 只")

    # Step 3: 批量获取实时行情
    info("quality_value", "批量获取实时行情...")
    codes = [f"{'sh' if c.startswith(('6','8')) else 'sz'}{c}" for c in all_stocks['code'].tolist()]
    quotes = batch_fetch_quotes(codes)
    info("quality_value", f"成功获取: {len(quotes)} 只行情")

    # Step 4: 前置过滤
    candidates = []
    for code, q in quotes.items():
        if code in frozen_codes:
            continue
        ok, reason = pre_filter(q)
        if ok:
            candidates.append(q)

    info("quality_value", f"前置过滤通过: {len(candidates)} 只")

    # Step 5: 策略评分
    results = []
    for q in candidates:
        s = score_buffett(q)
        cfg = get_l1_config()
        sig_cfg = cfg.get("signals", {}).get("buffett", {})
        thresholds = sig_cfg.get("thresholds", [0.3, 0.45, 0.65])
        min_signal = thresholds[0]  # 使用配置中的最低阈值
        if s['signal'] >= min_signal:
            results.append({
                'code': q['code'],
                'name': q['name'],
                'price': q['price'],
                'pe': q['pe'],
                'pb': q['pb'],
                'mcap_100m': q['mcap_100m'],
                'signal': s['signal'],
                'score': s['score'],
                'breakdown': s['breakdown'],
                'reasons': '; '.join(s['reasons']),
                'strategy': STRATEGY_NAME,
                'timestamp': datetime.now().isoformat()
            })

    # Step 6: 排序输出
    results.sort(key=lambda x: x['score'], reverse=True)
    cfg = get_l1_config()
    per_strategy_limit = cfg.get("cn", {}).get("per_strategy_limit", 200)
    top = results[:per_strategy_limit]

    # 输出结果
    info("quality_value", f"\n策略通过: {len(results)} 只, Top 10:")
    print("-" * 70)
    for r in top[:10]:
        print(f"  {r['code']} {r['name']:8s} | 价:{r['price']:>8.2f} | PE:{r['pe']:>6.1f} | PB:{r['pb']:>5.2f} | 信号:{r['signal']:.1f} | 分:{r['score']:.3f}")
    info("quality_value", f"\n(共{len(results)}只通过, 显示Top10)")

    # Step 7: 保存结果
    output = {
        'strategy': STRATEGY_NAME,
        'timestamp': datetime.now().isoformat(),
        'total_stocks': len(all_stocks),
        'frozen': len(frozen_codes),
        'after_prefilter': len(candidates),
        'passed': len(results),
        'top200': top
    }

    date_str = datetime.now().strftime('%Y%m%d')
    outfile = os.path.join(RECORDS_DIR, f"{STRATEGY_NAME}_{date_str}.json")
    with open(outfile, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log_end("quality_value", "run_screener", f"saved={outfile}")

    return output

if __name__ == '__main__':
    pool = 'index800'
    for i, arg in enumerate(sys.argv):
        if arg in ('--pool', '-p') and i + 1 < len(sys.argv):
            pool = sys.argv[i + 1]
    main(pool=pool)
