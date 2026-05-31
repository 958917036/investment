#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2_data_enrich — 市场数据统一获取器

统一入口：fetch_market_data(code, market)
市场：CN(A股) | HK(港股) | US(美股)

数据质量设计：
  - 失败字段 → 字符串 "失败"
  - missing_fields → 本次获取失败的字段列表
  - quality → ok | degraded | fail
"""

import sys
import os
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

# ── 路径配置 ───────────────────────────────────────────────────────
BASE = os.path.expanduser('~/.hermes/investment')
for p in [BASE, os.path.join(BASE, 'L2_data_enrich')]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.hermes/.env"))

logger = logging.getLogger("L2.market_fetcher")

# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════

def _safe_float(val, default=None):
    """安全转浮点"""
    if val is None:
        return default
    try:
        v = float(val)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def _mark_missing(result: dict, fields: list, quality: str) -> dict:
    """将指定字段标记为失败，并填充 missing_fields"""
    result = dict(result)
    for f in fields:
        if f not in result or result[f] is None:
            result[f] = "失败"
    # 确保 missing_fields 在顶层
    if 'missing_fields' not in result:
        result['missing_fields'] = []
    result['missing_fields'] = list(set(result['missing_fields'] + fields))
    # 质量等级
    if quality:
        result['quality'] = quality
    return result


def _determine_quality(missing_fields: list, total_critical: int) -> str:
    """根据缺失字段比例判断质量"""
    if not missing_fields:
        return "ok"
    fail_ratio = len(missing_fields) / total_critical if total_critical > 0 else 1.0
    if fail_ratio >= 0.7:
        return "fail"
    elif fail_ratio >= 0.3:
        return "degraded"
    return "ok"


# ═══════════════════════════════════════════════════════════════════
# A股 (CN) 数据获取
# ═══════════════════════════════════════════════════════════════════

def _validate_cn_quality(data: dict, mf: dict, tech: dict, fund: dict,
                          sector: dict, event: dict) -> Tuple[dict, dict, dict, dict, dict]:
    """
    A股质量门禁：验证关键字段，发现数据问题立即上报，不允许拿"失败"继续分析。

    质量规则：
      - price > 0，否则 "fail"
      - roe 是有效数字（非None、非"失败"），否则 "fail"
      - pe 是有效数字（非None、非"失败"），否则 "fail"
      - 任何数据源全部失败导致 missing_fields 超过阈值 → "fail"
    """
    failures = []

    # 1. 腾讯行情价格必须有
    price = tech.get('price', 0)
    if not price or price <= 0:
        failures.append("price<=0")
        tech['price'] = "失败"
        tech['quality'] = 'fail'

    # 2. ROE 必须有效
    roe = fund.get('roe')
    if roe is None or roe == "失败" or (isinstance(roe, float) and roe != roe):
        failures.append("roe无效")
        fund['roe'] = "失败"
        fund['quality'] = 'fail'

    # 3. PE 必须有效
    pe = fund.get('pe')
    if pe is None or pe == "失败" or (isinstance(pe, float) and pe != pe):
        failures.append("pe无效")
        fund['pe'] = "失败"
        fund['quality'] = 'fail'

    # 4. 资金流数据如果全空，降级
    if not mf.get('main_net_flow_5d') and not mf.get('main_direction'):
        failures.append("资金流全空")
        mf['quality'] = 'fail'

    # 5. 板块数据如果 sector_count=0 且 sector_rank=50（未成功获取）
    if sector.get('sector_count', 0) == 0:
        failures.append("板块数据获取失败")

    # 6. 汇总质量等级
    critical_failures = sum(1 for f in failures if f in (
        "price<=0", "roe无效", "pe无效", "资金流全空"
    ))
    if critical_failures >= 2:
        mf['quality'] = 'fail'
        tech['quality'] = 'fail'
        fund['quality'] = 'fail'
        sector['quality'] = 'fail'
        event['quality'] = 'fail'

    return mf, tech, fund, sector, event


def fetch_cn(code: str) -> dict:
    """
    A股数据获取 — 复用现有 data_fetcher.py 的逻辑

    数据源：
      - 腾讯API：实时行情(价格/PE/PB/成交量)
      - 东方财富(EastMoney)：资金流向(主力净流入)
      - BaoStock：日线技术指标(MA/MACD/RSI/布林带)
      - AkShare：财务指标(ROE/毛利率/净利润增速)

    返回：L2 输出结构
    """
    from L2_data_enrich.core.data_fetcher import fetch_all

    start = time.time()
    try:
        data = fetch_all(code)
    except Exception as e:
        logger.warning(f"[CN] fetch_all({code}) 异常: {e}")
        data = {}

    # 解析各维度数据
    mf = data.get('moneyflow_data', {}) or {}
    tech = data.get('technical_data', {}) or {}
    fund = data.get('fundamental_data', {}) or {}
    sector = data.get('sector_data', {}) or {}
    event = data.get('event_data', {}) or {}

    # ── 资金流数据 ──────────────────────────────────────────────
    mf_critical = ['main_net_flow_5d', 'outer_inner_ratio', 'large_order_ratio']
    mf_missing = [f for f in mf_critical if mf.get(f) is None]
    mf_quality = _determine_quality(mf_missing, len(mf_critical))

    moneyflow_data = {
        "source": mf.get("_source", "腾讯API+东方财富"),
        "quality": mf_quality,
        "missing_fields": mf_missing,
        "main_net_flow_5d": mf.get('main_net_flow_5d') if mf.get('main_net_flow_5d') is not None else "失败",
        "outer_inner_ratio": mf.get('outer_inner_ratio', 1.0) if mf.get('outer_inner_ratio') is not None else 1.0,
        "large_order_ratio": mf.get('large_order_ratio', 0) if mf.get('large_order_ratio') is not None else 0,
        "main_direction": mf.get('main_direction', '未知'),
        "retail_direction": mf.get('retail_direction', '未知'),
        "daily_flows": mf.get('daily_flows', [])[:10],
        "stock_rank": mf.get('stock_rank', 9999),
    }

    # ── 技术数据 ────────────────────────────────────────────────
    tech_critical = ['ma_status', 'macd_status', 'rsi']
    tech_missing = [f for f in tech_critical if tech.get(f) is None or tech.get(f) == '']
    tech_quality = _determine_quality(tech_missing, len(tech_critical))

    technical_data = {
        "source": tech.get("_source", "BaoStock日线"),
        "quality": tech_quality,
        "missing_fields": tech_missing,
        "ma_status": tech.get('ma_status', 'neutral') or 'neutral',
        "macd_status": tech.get('macd_status', 'neutral') or 'neutral',
        "rsi": tech.get('rsi', 50) if tech.get('rsi') is not None else 50,
        "ma5": tech.get('ma5', 0),
        "ma10": tech.get('ma10', 0),
        "ma20": tech.get('ma20', 0),
        "ma60": tech.get('ma60', 0),
        "volume_status": tech.get('volume_status', '正常'),
        "volume_ratio": tech.get('volume_ratio', 1.0),
        "price": tech.get('price', 0),
        "change_pct": tech.get('change_pct', 0),
        "bb_upper": tech.get('bb_upper', 0),
        "bb_mid": tech.get('bb_mid', 0),
        "bb_lower": tech.get('bb_lower', 0),
        "bb_position": tech.get('bb_position', 0.5),
        "dif": tech.get('dif', 0),
        "dea": tech.get('dea', 0),
        "macd_hist": tech.get('macd_hist', 0),
    }

    # ── 基本面数据 ──────────────────────────────────────────────
    fund_critical = ['roe', 'pe']
    fund_missing = [f for f in fund_critical if fund.get(f) is None]
    fund_quality = _determine_quality(fund_missing, len(fund_critical))

    fundamental_data = {
        "source": fund.get("_source", "AkShare财务+腾讯API"),
        "quality": fund_quality,
        "missing_fields": fund_missing,
        "roe": fund.get('roe') if fund.get('roe') is not None else "失败",
        "pe": fund.get('pe') if fund.get('pe') is not None else "失败",
        "pb": fund.get('pb') if fund.get('pb') is not None else "失败",
        "net_profit_yoy": fund.get('net_profit_yoy'),
        "eps_growth_yoy": fund.get('eps_growth_yoy'),
        "gross_margin": fund.get('gross_margin'),
        "net_margin": fund.get('net_margin'),
        "revenue_growth": fund.get('revenue_growth'),
        "eps": fund.get('eps'),
        "debt_eq": fund.get('debt_eq'),
        "inst_ownership_pct": fund.get('inst_ownership_pct'),
        "inst_trans": fund.get('inst_trans'),
    }

    # ── 板块数据 ────────────────────────────────────────────────
    sector_data = {
        "source": sector.get("_source", "AkShare板块"),
        "quality": "ok" if sector.get('sector_count', 0) > 0 else "fail",
        "missing_fields": [] if sector.get('sector_count', 0) > 0 else ['sector_rank'],
        "sector_rank": sector.get('sector_rank', 50),
        "sector_fund_flow": sector.get('sector_fund_flow', 0),
        "sector_strength": sector.get('strength_label', 'unknown'),
        "related_sector": sector.get('related_sector', ''),
    }

    # ── 事件数据 ────────────────────────────────────────────────
    event_data = {
        "source": event.get("_source", "AkShare新闻"),
        "quality": "ok" if event.get('report_count_30d', 0) > 0 else "degraded",
        "missing_fields": [] if event.get('report_count_30d', 0) > 0 else ['positive_events'],
        "positive_events": event.get('positive_events', []),
        "analyst_rating": event.get('analyst_rating', 'neutral'),
        "report_count_30d": event.get('report_count_30d', 0),
    }

    # ── 质量门禁：关键字段失败检测 ─────────────────────────────
    mf, tech, fund, sector, event = _validate_cn_quality(
        data, mf, tech, fund, sector, event
    )

    return {
        "moneyflow_data": moneyflow_data,
        "technical_data": technical_data,
        "fundamental_data": fundamental_data,
        "sector_data": sector_data,
        "event_data": event_data,
        "_duration_ms": round((time.time() - start) * 1000, 1),
    }


# ═══════════════════════════════════════════════════════════════════
# 港股 (HK) 数据获取
# ═══════════════════════════════════════════════════════════════════

def _fetch_hk_realtime(code5: str) -> dict:
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
        price = _safe_float(parts[3])
        prev_close = _safe_float(parts[4])
        change_pct = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else 0
        outer = _safe_float(parts[7]) or 0
        inner = _safe_float(parts[8]) or 0
        outer_inner_ratio = round(outer / inner, 2) if inner > 0 else 1.0

        return {
            'name': parts[1],
            'code': parts[2],
            'price': price or 0,
            'prev_close': prev_close or 0,
            'change_pct': change_pct,
            'open': _safe_float(parts[5]) or 0,
            'high': _safe_float(parts[33]) or 0,
            'low': _safe_float(parts[34]) or 0,
            'volume': _safe_float(parts[6]) or 0,
            'amount': _safe_float(parts[37]) or 0,
            'turnover': _safe_float(parts[43]) or 0,
            'pe': _safe_float(parts[51]),
            'pb': _safe_float(parts[50]),
            'market_cap': _safe_float(parts[45]) or 0,
            'week52_high': _safe_float(parts[48]) or 0,
            'week52_low': _safe_float(parts[49]) or 0,
            'outer_disk': outer,
            'inner_disk': inner,
            'outer_inner_ratio': outer_inner_ratio,
        }
    except Exception:
        return {}


def _fetch_hk_daily(code5: str):
    """AkShare 港股日线"""
    import akshare as ak
    try:
        df = ak.stock_hk_daily(symbol=code5, adjust='qfq')
        if df is None or df.empty:
            return None
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception:
        return None


def _calc_hk_mfi(df) -> dict:
    """
    港股 MFI-14 计算（无逐笔资金流，用 MFI 估算方向）
    """
    import math

    if df is None or len(df) < 20:
        return {'mfi': 50.0, 'net_flow_5d': 0.0, 'daily_flows': []}

    typical = (df['high'] + df['low'] + df['close']) / 3.0
    raw_mf = typical * df['volume']
    positive_mf = raw_mf.where(df['close'] > df['close'].shift(1), 0)
    negative_mf = raw_mf.where(df['close'] < df['close'].shift(1), 0)
    mfi14 = 100 - (100 / (1 + positive_mf.rolling(14).sum() /
                          negative_mf.rolling(14).sum().replace(0, math.nan))).fillna(50)
    mfi14 = mfi14.fillna(50)

    n = min(10, len(df))
    daily_flows = []
    for i in range(len(df) - n, len(df)):
        row = df.iloc[i]
        date_str = str(row['date'])[:10] if 'date' in df.columns else ''
        amount_hkd = float(row.get('amount', 0) or 0)
        direction = '流入' if mfi14.iloc[i] > 50 else '流出'
        daily_flows.append({
            'date': date_str,
            'main_net': round(amount_hkd / 1e8, 3),
            'direction': direction,
        })

    mfi = float(mfi14.iloc[-1])
    amount_hkd = float(df['amount'].iloc[-1]) if 'amount' in df.columns else 0
    net_flow_hkd = amount_hkd * (mfi - 50) / 100

    return {
        'mfi': round(mfi, 1),
        'net_flow_5d': round(net_flow_hkd, 3),
        'daily_flows': daily_flows,
        'vol_ratio': round(float(df['volume'].iloc[-1]) / float(df['volume'].iloc[-5:].mean())
                          if len(df) >= 5 else 1.0, 2),
    }


def _calc_hk_technicals(df) -> dict:
    """基于日线 DataFrame 计算技术指标"""
    if df is None or df.empty:
        return {}

    import pandas as pd

    close = df['close'].values
    ma5  = float(pd.Series(close).rolling(5).mean().iloc[-1]) if len(close) >= 5 else close[-1]
    ma10 = float(pd.Series(close).rolling(10).mean().iloc[-1]) if len(close) >= 10 else close[-1]
    ma20 = float(pd.Series(close).rolling(20).mean().iloc[-1]) if len(close) >= 20 else close[-1]
    ma60 = float(pd.Series(close).rolling(60).mean().iloc[-1]) if len(close) >= 60 else close[-1]
    price = close[-1]

    if price > ma5 > ma10 > ma20:
        ma_status = 'bullish'
    elif price < ma5 < ma10 < ma20:
        ma_status = 'bearish'
    else:
        ma_status = 'neutral'

    delta = pd.Series(close).diff()
    gain = delta.clip(lower=0).rolling(14).mean().iloc[-1] if len(delta) >= 14 else 0
    loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1] if len(delta) >= 14 else 0
    rsi = float(gain / (gain + loss) * 100) if (gain + loss) > 0 else 50

    s = pd.Series(close)
    ema12 = float(s.ewm(span=12).mean().iloc[-1])
    ema26 = float(s.ewm(span=26).mean().iloc[-1])
    dif = ema12 - ema26
    dea = float(s.ewm(span=12).mean().ewm(span=9).mean().iloc[-1])
    macd_hist = (dif - dea) * 2
    macd_status = 'golden' if dif > dea and dif > 0 else 'death' if dif < dea else 'neutral'

    bb_mid = float(s.rolling(20).mean().iloc[-1])
    bb_std = float(s.rolling(20).std().iloc[-1])
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_pos = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5

    vol5_avg = float(df['volume'].iloc[-5:].mean())
    vol_ratio = float(df['volume'].iloc[-1]) / vol5_avg if vol5_avg > 0 else 1.0

    return {
        'ma5': round(ma5, 2), 'ma10': round(ma10, 2),
        'ma20': round(ma20, 2), 'ma60': round(ma60, 2),
        'ma_status': ma_status,
        'macd_status': macd_status,
        'dif': round(dif, 4), 'dea': round(dea, 4),
        'macd_hist': round(macd_hist, 4),
        'rsi': round(rsi, 1),
        'bb_upper': round(bb_upper, 2), 'bb_mid': round(bb_mid, 2),
        'bb_lower': round(bb_lower, 2),
        'bb_position': round(bb_pos, 4),
        'vol_ratio': round(vol_ratio, 2),
        'daily_30d': df['close'].iloc[-30:].tolist() if len(df) >= 30 else df['close'].tolist(),
    }


def _fetch_hk_financial(code5: str) -> dict:
    """AkShare 港股财务指标"""
    import akshare as ak
    try:
        df = ak.stock_financial_hk_analysis_indicator_em(symbol=code5)
        if df is None or df.empty:
            return {}
        latest = df.iloc[0]
        return {
            'roe': latest.get('ROE_AVG') or latest.get('ROE'),
            'net_profit_yoy': latest.get('HOLDER_PROFIT_YOY'),
            'revenue_growth': latest.get('OPERATE_INCOME_YOY'),
            'gross_profit_ratio': latest.get('GROSS_PROFIT_RATIO'),
            'eps': latest.get('BASIC_EPS') or latest.get('EPS'),
            'debt_asset': latest.get('DEBT_ASSET_RATIO'),
            'current_ratio': latest.get('CURRENT_RATIO'),
        }
    except Exception:
        return {}


def _fetch_hk_events(code5: str) -> dict:
    """AkShare 港股利润预测（券商评级/目标价）"""
    import akshare as ak
    import math

    result = {
        'positive_events': [],
        'analyst_rating': 'neutral',
        'report_count_30d': 0,
    }
    try:
        df = ak.stock_hk_profit_forecast_et(symbol=code5)
        if df is None or df.empty:
            return result
        result['report_count_30d'] = len(df)
        buy_count = 0
        for _, row in df.iterrows():
            rating = str(row.get('评级', ''))
            broker = str(row.get('证券商', ''))
            if '买' in rating or '跑赢' in rating or '强列' in rating:
                buy_count += 1
                result['positive_events'].append(f"券商[{broker}]给予买入评级")
        total = len(df)
        if total > 0:
            buy_ratio = buy_count / total
            if buy_ratio >= 0.7:
                result['analyst_rating'] = 'buy'
            elif buy_ratio >= 0.4:
                result['analyst_rating'] = 'neutral'
            else:
                result['analyst_rating'] = 'sell'
    except Exception:
        pass
    return result


def _fetch_hk_sector(code5: str) -> dict:
    """
    港股板块数据：行业分类 + 营收增速排名百分位

    数据源：
      - stock_hk_company_profile_em：行业分类
      - stock_hk_growth_comparison_em：营收增速排名百分位
    """
    import akshare as ak

    result = {
        '_source': 'AkShare company_profile+growth_comparison',
        'sector_rank': 50,
        'strength_label': 'unknown',
        'related_sector': '',
        'industry': '',
        'revenue_growth_rank': None,
        'total_stocks': 2751,
    }

    try:
        prof_df = ak.stock_hk_company_profile_em(symbol=code5)
        if prof_df is not None and not prof_df.empty:
            industry = str(prof_df.iloc[0].get('所属行业', '')).strip()
            result['related_sector'] = industry
            result['industry'] = industry
    except Exception:
        pass

    try:
        gr_df = ak.stock_hk_growth_comparison_em(symbol=code5)
        if gr_df is not None and not gr_df.empty:
            row = gr_df.iloc[0]
            rev_rank = row.get('营业收入同比增长率排名', 0) or 0
            eps_rank = row.get('基本每股收益同比增长率排名', 0) or 0
            total = result['total_stocks']
            rev_pct = max(0, min(100, (total - rev_rank) / total * 100))
            eps_pct = max(0, min(100, (total - eps_rank) / total * 100))
            sector_score = round(rev_pct * 0.7 + eps_pct * 0.3, 1)
            result['sector_rank'] = round(sector_score, 1)
            result['revenue_growth_rank'] = int(rev_rank)
            if sector_score >= 80:
                result['strength_label'] = '强势'
            elif sector_score >= 60:
                result['strength_label'] = '较强'
            elif sector_score >= 40:
                result['strength_label'] = '中性'
            elif sector_score >= 20:
                result['strength_label'] = '较弱'
            else:
                result['strength_label'] = '弱势'
    except Exception:
        pass

    return result


def fetch_hk(code: str) -> dict:
    """
    港股数据获取 — 从 L4_judge/hk_analysis.py 迁移数据获取逻辑

    数据源：
      - 腾讯API：港股实时行情(hk前缀)
      - AkShare stock_hk_daily：日线 + MFI计算
      - AkShare stock_hk_financial_indicator_em：财务指标

    返回：L2 输出结构
    """
    start = time.time()

    # 正规化代码
    code_raw = code.strip().upper().lstrip('HK').lstrip('0').zfill(5)

    # L2-1: 实时行情
    rt = _fetch_hk_realtime(code_raw)
    name = rt.get('name', code_raw)

    # L2-2: 日线
    df = _fetch_hk_daily(code_raw)
    daily_n = len(df) if df is not None else 0
    tech = _calc_hk_technicals(df)
    mfi_data = _calc_hk_mfi(df)

    # L2-3: 财务
    fin = _fetch_hk_financial(code_raw)

    # L2-4: 事件（券商评级）
    events = _fetch_hk_events(code_raw)

    # ── 资金流数据 ──────────────────────────────────────────────
    mf_missing = [] if mfi_data.get('mfi') else ['mfi']
    moneyflow_data = {
        "source": "AkShare stock_hk_daily MFI估算",
        "quality": "ok" if mfi_data.get('mfi') else "fail",
        "missing_fields": mf_missing,
        "main_net_flow_5d": mfi_data.get('net_flow_5d', 0),
        "outer_inner_ratio": rt.get('outer_inner_ratio', 1.0) or 1.0,
        "large_order_ratio": 0,  # 港股无逐笔
        "mfi": mfi_data.get('mfi', 50),
        "main_direction": '流入' if (mfi_data.get('mfi') or 50) > 50 else '流出',
        "retail_direction": 'unknown',
        "daily_flows": mfi_data.get('daily_flows', []),
        "vol_ratio": mfi_data.get('vol_ratio', 1.0),
    }

    # ── 技术数据 ────────────────────────────────────────────────
    tech_missing = [f for f in ['ma_status', 'macd_status'] if not tech.get(f)]
    technical_data = {
        "source": f"AkShare stock_hk_daily ({daily_n}条)",
        "quality": "ok" if daily_n >= 20 else "degraded",
        "missing_fields": tech_missing if daily_n < 20 else [],
        "ma_status": tech.get('ma_status', 'neutral') or 'neutral',
        "macd_status": tech.get('macd_status', 'neutral') or 'neutral',
        "rsi": tech.get('rsi', 50) or 50,
        "ma5": tech.get('ma5', 0),
        "ma10": tech.get('ma10', 0),
        "ma20": tech.get('ma20', 0),
        "ma60": tech.get('ma60', 0),
        "volume_status": '正常',
        "volume_ratio": tech.get('vol_ratio', 1.0),
        "price": rt.get('price', 0),
        "change_pct": rt.get('change_pct', 0),
        "bb_upper": tech.get('bb_upper', 0),
        "bb_mid": tech.get('bb_mid', 0),
        "bb_lower": tech.get('bb_lower', 0),
        "bb_position": tech.get('bb_position', 0.5),
        "dif": tech.get('dif', 0),
        "dea": tech.get('dea', 0),
        "macd_hist": tech.get('macd_hist', 0),
    }

    # ── 基本面数据 ──────────────────────────────────────────────
    fund_missing = [f for f in ['roe', 'pe'] if not fin.get(f)]
    fundamental_data = {
        "source": "AkShare stock_hk_financial_indicator_em",
        "quality": "ok" if not fund_missing else "degraded",
        "missing_fields": fund_missing,
        "roe": fin.get('roe') if fin.get('roe') is not None else "失败",
        "pe": rt.get('pe') if rt.get('pe') is not None else "失败",
        "pb": rt.get('pb') if rt.get('pb') is not None else "失败",
        "net_profit_yoy": fin.get('net_profit_yoy'),
        "revenue_growth": fin.get('revenue_growth'),
        "eps": fin.get('eps'),
        "gross_profit_ratio": fin.get('gross_profit_ratio'),
        "debt_eq": fin.get('debt_asset'),
        "current_ratio": fin.get('current_ratio'),
        "market_cap": rt.get('market_cap', 0),
    }

    # ── 板块数据（行业分类 + 营收增速排名）────────────────
    sector = _fetch_hk_sector(code_raw)
    sector_data = {
        "source": sector.get('_source', 'AkShare港股板块'),
        "quality": "ok" if sector.get('revenue_growth_rank') is not None else "degraded",
        "missing_fields": [] if sector.get('revenue_growth_rank') is not None else ['sector_rank'],
        "sector_rank": sector.get('sector_rank', 50),
        "sector_fund_flow": 0,
        "sector_strength": sector.get('strength_label', 'unknown'),
        "related_sector": sector.get('related_sector', ''),
        "industry": sector.get('industry', ''),
    }

    # ── 事件数据 ────────────────────────────────────────────────
    event_data = {
        "source": "AkShare stock_hk_profit_forecast_et",
        "quality": "ok" if events.get('report_count_30d', 0) > 0 else "degraded",
        "missing_fields": [] if events.get('report_count_30d', 0) > 0 else ['analyst_rating'],
        "positive_events": events.get('positive_events', []),
        "analyst_rating": events.get('analyst_rating', 'neutral'),
        "report_count_30d": events.get('report_count_30d', 0),
    }

    return {
        "moneyflow_data": moneyflow_data,
        "technical_data": technical_data,
        "fundamental_data": fundamental_data,
        "sector_data": sector_data,
        "event_data": event_data,
        "_duration_ms": round((time.time() - start) * 1000, 1),
    }


# ═══════════════════════════════════════════════════════════════════
# 美股 (US) 数据获取
# ═══════════════════════════════════════════════════════════════════

def fetch_us(code: str) -> dict:
    """
    美股数据获取 — 从 L4_judge/us_analysis.py 迁移 collect_data() 逻辑

    数据源：
      - 腾讯API (us前缀)：实时行情
      - Yahoo Finance Chart API：日K + 成交额 + MFI
      - AkShare stock_financial_us_analysis_indicator_em：财务指标
      - finviz.com：机构持仓/盈利能力（无需代理）

    返回：L2 输出结构
    """
    start = time.time()

    from L2_data_enrich.adapters.us.us_fetcher_adapter import fetch_us_data

    # 规范化 ticker（去除 .OQ/.NQ/.N 等后缀）
    normalized = code.strip().upper()
    for suffix in ('.OQ', '.NQ', '.SS', '.SZ', '.N', '.O', '.A', '.P'):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
            break

    try:
        raw = fetch_us_data(normalized)
    except Exception as e:
        logger.warning(f"[US] fetch_us_data({code}) 异常: {e}")
        raw = {}

    rt = raw.get('realtime', {}) or {}
    daily = raw.get('daily', {}) or {}
    tech = daily.get('technicals', {}) or {}
    fin = raw.get('financial', {}) or {}
    news = raw.get('news', {}) or {}
    fvx = raw.get('finviz', {}) or {}
    sec = raw.get('sector', {}) or {}
    mfi = raw.get('mfi', {}) or {}

    yf_returns = daily.get('returns', {}) or {}
    yf_week52 = daily.get('week52', {}) or {}

    # ── 资金流数据（MFI 替代逐笔资金流）──────────────────────
    mf_missing = [] if mfi.get('mfi14') else ['mfi14', 'net5']
    moneyflow_data = {
        "source": "Yahoo Finance Chart API + AkShare MFI计算",
        "quality": "ok" if mfi.get('mfi14') else "degraded",
        "missing_fields": mf_missing,
        "main_net_flow_5d": mfi.get('net5', 0) or 0,
        "outer_inner_ratio": 1.0,  # 美股无外内盘比
        "large_order_ratio": 0,
        "mfi14": mfi.get('mfi14'),
        "mfi5": mfi.get('mfi5'),
        "mfi10": mfi.get('mfi10'),
        "mfi20": mfi.get('mfi20'),
        "main_direction": '流入' if (mfi.get('mfi14') or 50) > 50 else '流出',
        "retail_direction": 'unknown',
        "amount_1d_b": daily.get('amount_1d_b', 0),
        "amount_20d_avg_b": daily.get('amount_20d_avg_b', 0),
        "vol_ratio": daily.get('vol_ratio', 1),
        "daily_flows": [],  # 近10日MFI方向（来自_mfi_adapter）
    }

    # ── 技术数据 ────────────────────────────────────────────────
    tech_missing = [f for f in ['ma_status', 'rsi'] if not tech.get(f)]
    technical_data = {
        "source": f"Yahoo Finance Chart API ({daily.get('data_points', 0)}条日线)",
        "quality": "ok" if tech.get('ma5') else "degraded",
        "missing_fields": tech_missing,
        "ma_status": 'bullish' if tech.get('ma_arrangement') == '多头排列' else
                     'bearish' if tech.get('ma_arrangement') == '空头排列' else 'neutral',
        "macd_status": 'golden' if tech.get('macd_status') == '金叉' else
                      'death' if tech.get('macd_status') == '死叉' else 'neutral',
        "rsi": tech.get('rsi_14', 50) or 50,
        "ma5": tech.get('ma5'),
        "ma10": tech.get('ma10'),
        "ma20": tech.get('ma20'),
        "ma60": tech.get('ma60'),
        "volume_status": '正常',
        "volume_ratio": tech.get('vol_ratio', daily.get('vol_ratio', 1)),
        "price": rt.get('price', 0),
        "change_pct": rt.get('change_pct', 0),
        "bb_upper": tech.get('bb_upper'),
        "bb_mid": tech.get('bb_mid'),
        "bb_lower": tech.get('bb_lower'),
        "bb_position": tech.get('bb_position'),
        "dif": tech.get('macd'),
        "dea": tech.get('macd_signal'),
        "macd_hist": tech.get('macd_hist'),
        "return_m1": yf_returns.get('m1'),
        "return_m3": yf_returns.get('m3'),
        "return_y1": yf_returns.get('y1'),
        "year_high": yf_week52.get('high', rt.get('week52_high')),
        "year_low": yf_week52.get('low', rt.get('week52_low')),
    }

    # ── 基本面数据 ──────────────────────────────────────────────
    fund_critical = ['pe', 'roe']
    fund_missing = [f for f in fund_critical
                    if (fvx.get('pe_ratio') is None and rt.get('pe') is None and f == 'pe') or
                       (fvx.get('roe') is None and fin.get('roe_avg') is None and rt.get('roe') is None and f == 'roe')]
    fundamental_data = {
        "source": "finviz.com + AkShare stock_financial_us_analysis_indicator_em",
        "quality": "ok" if not fund_missing else "degraded",
        "missing_fields": fund_missing,
        "pe": (fvx.get('pe_ratio') if fvx else None) or rt.get('pe'),
        "forward_pe": fvx.get('forward_pe') if fvx else None,
        "peg_ratio": fvx.get('peg_ratio') if fvx else None,
        "pb": rt.get('pb') if rt.get('pb') else None,
        "roe": (fvx.get('roe') if fvx else None) or fin.get('roe_avg') or rt.get('roe'),
        "gross_margin": fvx.get('gross_margin') if fvx else None,
        "operating_margin": fvx.get('operating_margin') if fvx else None,
        "profit_margin": fvx.get('profit_margin') if fvx else None,
        "eps_growth_yoy": fvx.get('eps_growth_yoy') if fvx else None,
        "eps_next_y": fvx.get('eps_next_y') if fvx else None,
        "eps_next_5y": fvx.get('eps_next_5y') if fvx else None,
        "revenue_growth": fin.get('operate_income_yoy') if fin else None,
        "inst_ownership_pct": fvx.get('inst_ownership_pct') if fvx else None,
        "inst_trans": fvx.get('inst_trans') if fvx else None,
        "insider_ownership_pct": fvx.get('insider_ownership_pct') if fvx else None,
        "insider_trans": fvx.get('insider_trans') if fvx else None,
        "beta": fvx.get('beta') if fvx else None,
        "market_cap": rt.get('market_cap'),
        "sector": fvx.get('sector') if fvx else None,
        "industry": fvx.get('industry') if fvx else None,
    }
    # 填充失败字段
    for f in fund_missing:
        if f in fundamental_data:
            fundamental_data[f] = "失败"

    # ── 板块数据 ────────────────────────────────────────────────
    sector_data = {
        "source": f"SPDR ETF ({sec.get('etf_ticker','N/A')})",
        "quality": "ok" if sec.get('etf_ticker') else "degraded",
        "missing_fields": [] if sec.get('etf_ticker') else ['sector_rank'],
        "sector_rank": sec.get('position_52w_pct', 50),
        "sector_strength": sec.get('strength_label', 'unknown'),
        "sector_etf": sec.get('etf_ticker'),
        "sector_fund_flow": sec.get('sector_fund_flow', 0),
    }

    # ── 事件数据 ────────────────────────────────────────────────
    positive_events = []
    for n in news.get('news_list', [])[:5]:
        positive_events.append(f"{n.get('source','')}: {n.get('title','')}")

    analyst_rating_map = {'positive': 'buy', 'negative': 'sell', 'neutral': 'neutral'}
    event_data = {
        "source": "Yahoo Finance Search + AkShare stock_news_em",
        "quality": "ok" if news.get('count_30d', 0) > 0 else "degraded",
        "missing_fields": [] if news.get('count_30d', 0) > 0 else ['positive_events'],
        "positive_events": positive_events,
        "analyst_rating": analyst_rating_map.get(news.get('sentiment', 'neutral'), 'neutral'),
        "report_count_30d": news.get('count_30d', 0),
        "sentiment": news.get('sentiment', 'neutral'),
        "insider_trans": fvx.get('insider_trans') if fvx else None,
    }

    return {
        "moneyflow_data": moneyflow_data,
        "technical_data": technical_data,
        "fundamental_data": fundamental_data,
        "sector_data": sector_data,
        "event_data": event_data,
        "_duration_ms": round((time.time() - start) * 1000, 1),
    }


# ═══════════════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════════════

def fetch_market_data(code: str, market: str) -> dict:
    """
    L2 统一入口

    Args:
        code: 股票代码
              CN: "600519" / "000858"（纯数字）
              HK: "3690" / "00700"（纯数字，自动补5位）
              US: "SMCI" / "NVDA" / "AAPL"（字母代码）
        market: "CN" | "HK" | "US"

    Returns: L2 输出结构
        {
            "layer": "L2",
            "code": ...,
            "market": ...,
            "run_date": "YYYY-MM-DD",
            "moneyflow_data": {...},
            "technical_data": {...},
            "fundamental_data": {...},
            "sector_data": {...},
            "event_data": {...},
            "duration_ms": ...
        }
    """
    market = market.upper().strip()
    if market not in ('CN', 'HK', 'US'):
        raise ValueError(f"Unsupported market: {market}. Must be CN | HK | US")

    code = code.strip()

    if market == 'CN':
        result = fetch_cn(code)
    elif market == 'HK':
        result = fetch_hk(code)
    elif market == 'US':
        result = fetch_us(code)
    else:
        raise ValueError(f"Unsupported market: {market}")

    # 统一包装
    return {
        "layer": "L2",
        "code": code,
        "market": market,
        "run_date": datetime.now().strftime('%Y-%m-%d'),
        **result,
        "duration_ms": result.pop("_duration_ms", 0),
    }


# ═══════════════════════════════════════════════════════════════════
# 入口脚本
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='L2 市场数据获取器')
    parser.add_argument('code', help='股票代码')
    parser.add_argument('market', choices=['CN', 'HK', 'US'], help='市场: CN | HK | US')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s [%(name)s] %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    import json
    result = fetch_market_data(args.code, args.market)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))