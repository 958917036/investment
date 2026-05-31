#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股数据采集器 - US Stock Data Fetcher

数据源（2026-04-25 确认）：
  - 腾讯API：实时行情 + 财务指标（无代理可用）
  - Yahoo Finance Chart API：1年日K + 成交额 + 52周高低（需本地代理 http://127.0.0.1:7897）
  - AkShare stock_financial_us_analysis_indicator_em：财务指标（ROE/毛利率/净利率/负债率）
  - AkShare stock_news_em：30天个股新闻 + 情绪分类

代理配置：Clash Verge (socks5→转换) 监听 HTTP http://127.0.0.1:7897
"""

import os
import subprocess
import json
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import pandas as pd

logger = logging.getLogger("us_fetcher")

# 腾讯API美股字段索引（已验证 2026-04-25）
QQ_US_PARTS = {
    "name": 1,           # 名称
    "code": 2,           # 代码 (如 SMCI.OQ)
    "price": 3,          # 当前价
    "prev_close": 4,     # 昨收
    "open": 5,           # 今开
    "volume": 6,         # 成交量(股)
    "buy_vol": 7,        # 买盘
    "sell_vol": 8,       # 卖盘
    "high": 33,          # 今日最高
    "low": 34,           # 今日最低
    "currency": 35,      # 货币 (USD)
    "volume2": 36,       # 成交量2
    "amount": 37,        # 成交额
    "amplitude": 38,     # 振幅(%)
    "pe": 39,            # 动态PE
    "turnover_rate": 43, # 换手率(%)
    "market_cap": 44,    # 总市值(亿)
    "circ_cap": 45,      # 流通市值(亿)
    "english_name": 46,  # 英文名
    "pb": 47,            # PB
    "week52_high": 48,   # 52周最高
    "week52_low": 49,    # 52周最低
    "eps": 51,           # EPS
    "roe": 57,           # ROE(%)
    "profit_margin": 58, # 净利润率(%)
    "revenue_growth": 59, # 营收增长率(%)
    "profit_growth": 60, # 利润增长率(%)
    "total_shares": 53,  # 总股本(亿)
}


# ─── 通用工具 ──────────────────────────────────────────────────────────────

def _curl_with_retry(url: str, proxy: str, max_retries: int = 3,
                      timeout: int = 25, user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)") -> Optional[bytes]:
    """
    带重试的curl请求（用于Yahoo Finance等不稳定API）。
    返回bytes或None（全部失败）。
    """
    proxy_host = proxy.replace("http://", "").replace("https://", "")
    cmd = [
        "curl", "-s", f"--max-time", str(timeout),
        "-A", user_agent,
        "-x", f"http://{proxy_host}",
        url
    ]
    for attempt in range(max_retries):
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
            if result.returncode == 0 and result.stdout:
                return result.stdout
            logger.warning(f"curl attempt {attempt+1}/{max_retries} failed: returncode={result.returncode}")
        except subprocess.TimeoutExpired:
            logger.warning(f"curl attempt {attempt+1}/{max_retries} timeout")
        except Exception as e:
            logger.warning(f"curl attempt {attempt+1}/{max_retries} error: {e}")
        if attempt < max_retries - 1:
            time.sleep(1.5 ** attempt)  # 指数退避
    return None


def fetch_qq_us(ticker: str) -> Dict[str, Any]:
    """通过腾讯行情API获取美股实时+财务数据"""
    # Strip exchange suffix (.OQ, .NQ, .N, etc.) — 腾讯API格式为 usDGXX 而非 usDGXX.OQ
    normalized = ticker.upper()
    for suffix in ('.OQ', '.NQ', '.SS', '.SZ', '.N', '.O', '.A', '.P'):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
            break
    qq_code = f"us{normalized}"
    url = f"http://qt.gtimg.cn/q={qq_code}"

    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', '5', '-A', 'Mozilla/5.0', url],
            capture_output=True, timeout=10
        )
        raw = r.stdout.decode('gbk', errors='replace')
        import re
        match = re.search(r'"([^"]+)"', raw)
        if not match:
            logger.warning(f"腾讯API返回异常: {raw[:100]}")
            return {}

        parts = match.group(1).split('~')
        if len(parts) < 50:
            logger.warning(f"腾讯API字段不足({len(parts)}): 返回可能为空")
            return {}

        def safe_float(val, default=None):
            try:
                return float(val) if val else default
            except (ValueError, TypeError):
                return default

        result = {}
        for field, idx in QQ_US_PARTS.items():
            if idx < len(parts) and parts[idx].strip():
                val = parts[idx]
                val_clean = val.rstrip('%').strip()
                if field in ('name', 'code', 'currency', 'english_name'):
                    result[field] = val_clean
                else:
                    result[field] = safe_float(val_clean)

        # 补充派生字段
        price = result.get('price')
        prev_close = result.get('prev_close')
        if price and prev_close and prev_close != 0:
            result['change'] = round(price - prev_close, 2)
            result['change_pct'] = round((price / prev_close - 1) * 100, 2)
        else:
            result['change'] = safe_float(parts[31]) if len(parts) > 31 else None
            cp = parts[32] if len(parts) > 32 else None
            result['change_pct'] = safe_float(cp.rstrip('%')) if cp else None

        return result

    except Exception as e:
        logger.error(f"腾讯API请求失败: {e}")
        return {}


def fetch_us_daily(ticker: str) -> Optional[Dict]:
    """
    通过AkShare获取美股日线数据，返回 {dates, opens, highs, lows, closes, volumes}
    以及计算好的技术指标
    """
    try:
        import akshare as ak
        import pandas as pd
        import numpy as np

        df = ak.stock_us_daily(symbol=ticker.upper(), adjust="qfq")
        if df is None or df.empty:
            logger.warning(f"{ticker} 日线数据为空")
            return None

        # 确保排序
        df = df.sort_values('date').reset_index(drop=True)

        closes = df['close'].values
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values
        dates = df['date'].dt.strftime('%Y-%m-%d').tolist() if hasattr(df['date'], 'dt') else df['date'].tolist()

        # 技术指标计算
        # MA
        def ma(data, n):
            s = pd.Series(data)
            return s.rolling(n).mean().iloc[-1]

        last_close = float(closes[-1])
        s = pd.Series(closes)

        ma5 = ma(closes, 5)
        ma10 = ma(closes, 10)
        ma20 = ma(closes, 20)
        ma60 = ma(closes, 60)

        # MACD
        ema12 = s.ewm(span=12).mean()
        ema26 = s.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        macd_hist = macd_line - signal_line

        # RSI (14)
        delta = s.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        # 布林带
        bb_mid = s.rolling(20).mean()
        bb_std = s.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std

        # 成交量分析
        vol_s = pd.Series(volumes)
        vol_ma5 = vol_s.rolling(5).mean().iloc[-1]
        vol_ratio = volumes[-1] / vol_ma5 if vol_ma5 > 0 else 0

        # 52周范围
        year_data = closes[-252:] if len(closes) >= 252 else closes
        year_high = float(max(highs[-252:])) if len(highs) >= 252 else float(max(highs))
        year_low = float(min(lows[-252:])) if len(lows) >= 252 else float(min(lows))

        # 均线排列
        if last_close > ma5 > ma10 > ma20:
            ma_arrangement = "多头排列"
        elif last_close < ma5 < ma10 < ma20:
            ma_arrangement = "空头排列"
        else:
            ma_arrangement = "混合"

        # 布林带位置
        bb_last_upper = float(bb_upper.iloc[-1])
        bb_last_lower = float(bb_lower.iloc[-1])
        bb_last_mid = float(bb_mid.iloc[-1])

        if last_close > bb_last_upper:
            bb_position = "上轨之上(超买)"
        elif last_close > bb_last_mid:
            bb_position = "中轨至上轨之间"
        elif last_close > bb_last_lower:
            bb_position = "下轨至中轨之间"
        else:
            bb_position = "下轨之下(超卖)"

        result = {
            "data_points": len(dates),
            "latest_date": dates[-1] if isinstance(dates, list) else str(dates[-1]),
            "latest_close": round(last_close, 2),
            "latest_open": round(float(opens[-1]), 2),
            "latest_high": round(float(highs[-1]), 2),
            "latest_low": round(float(lows[-1]), 2),
            "latest_volume": int(volumes[-1]),
            "technicals": {
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "ma20": round(ma20, 2),
                "ma60": round(ma60, 2),
                "price_vs_ma5": round((last_close/ma5 - 1) * 100, 2),
                "price_vs_ma20": round((last_close/ma20 - 1) * 100, 2),
                "price_vs_ma60": round((last_close/ma60 - 1) * 100, 2),
                "macd": round(float(macd_line.iloc[-1]), 3),
                "macd_signal": round(float(signal_line.iloc[-1]), 3),
                "macd_hist": round(float(macd_hist.iloc[-1]), 3),
                "macd_status": "金叉" if macd_line.iloc[-1] > signal_line.iloc[-1] else "死叉",
                "rsi_14": round(float(rsi.iloc[-1]), 1),
                "bb_upper": round(bb_last_upper, 2),
                "bb_mid": round(bb_last_mid, 2),
                "bb_lower": round(bb_last_lower, 2),
                "bb_position": bb_position,
                "ma_arrangement": ma_arrangement,
                "vol_ma5": int(vol_ma5),
                "vol_ratio": round(vol_ratio, 2),
                "year_high": round(year_high, 2),
                "year_low": round(year_low, 2),
                "year_range_pct": round((last_close - year_low) / (year_high - year_low) * 100, 1),
            }
        }

        # 存储原始日线用于后续分析
        result["_raw_dates"] = dates
        result["_raw_closes"] = [round(float(x), 2) for x in closes]

        return result

    except ImportError:
        logger.error("需要安装 akshare: pip install akshare")
        return None
    except Exception as e:
        logger.error(f"日线获取失败: {e}")
        return None


def fetch_us_financial_indicators(ticker: str) -> Optional[Dict]:
    """通过AkShare获取美股财务分析指标（营收/利润/ROE/毛利率/负债率等）"""
    try:
        import akshare as ak
        df = ak.stock_financial_us_analysis_indicator_em(symbol=ticker.upper())
        if df is None or df.empty or len(df) == 0:
            logger.warning(f"{ticker} AkShare财务指标为空")
            return {}
        latest = df.iloc[0]
        if latest is None:
            logger.warning(f"{ticker} AkShare财务指标首行数据为None")
            return {}
        return {
            "report_date": str(latest.get("REPORT_DATE", "")),
            "operate_income": latest.get("OPERATE_INCOME"),
            "operate_income_yoy": latest.get("OPERATE_INCOME_YOY"),  # 营收增速
            "gross_profit": latest.get("GROSS_PROFIT"),
            "gross_profit_ratio": latest.get("GROSS_PROFIT_RATIO"),  # 毛利率
            "net_profit": latest.get("PARENT_HOLDER_NETPROFIT"),
            "net_profit_ratio": latest.get("NET_PROFIT_RATIO"),      # 净利率
            "roe_avg": latest.get("ROE_AVG"),                         # ROE
            "basic_eps": latest.get("BASIC_EPS"),                      # EPS
            "debt_asset_ratio": latest.get("DEBT_ASSET_RATIO"),       # 资产负债率
            "current_ratio": latest.get("CURRENT_RATIO"),              # 流动比率
            "currency": latest.get("CURRENCY_ABBR", "USD"),
        }
    except Exception as e:
        logger.warning(f"AkShare财务指标获取失败: {e}")
        return {}


def fetch_us_finviz(ticker: str) -> Dict[str, Any]:
    """
    通过finviz.com爬取美股完整数据（无需API key，无需代理，无rate limit）
    返回：机构持仓/内部人交易/盈利能力/成长性/财务结构/技术指标

    2026-05-05: finviz.com URL 从 /quote.ashx 迁移到 /quote，HTML结构改为：
      cursor-pointer TD → <div class="snapshot-td-label">LABEL</div>
      下一 TD → <div class="snapshot-td-content"><b>VALUE</b></div>
      解析改为按TD顺序配对。
    """
    import re, json
    url = f"https://finviz.com/quote?t={ticker.upper()}"
    try:
        result = subprocess.run(
            ['curl', '-s', url,
             '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'],
            capture_output=True, text=True, timeout=30
        )
        html = result.stdout
    except Exception as e:
        logger.warning(f"finviz 请求失败: {e}")
        return {}

    # ── 解析 snapshot table：cursor-pointer TD = label, 下一 TD = value ──
    pairs = {}
    td_pattern = re.compile(r'<td\s+class="([^"]+)"[^>]*>(.*?)</td>', re.DOTALL)
    tds = list(td_pattern.finditer(html))
    for i, m in enumerate(tds):
        attrs = m.group(1)
        if 'cursor-pointer' in attrs:
            # 提取 label（div.snapshot-td-label 内的文本）
            label_div = re.search(r'<div\s+class="snapshot-td-label"[^>]*>(.*?)</div>', m.group(2), re.DOTALL)
            if not label_div:
                continue
            label = re.sub(r'<[^>]+>', '', label_div.group(1)).strip()
            if not label or len(label) > 30:
                continue
            # 下一个 TD 是 value
            if i + 1 < len(tds):
                val_div = re.search(
                    r'<div\s+class="snapshot-td-content"[^>]*>(.*?)</div>',
                    tds[i + 1].group(2), re.DOTALL
                )
                value = re.sub(r'<[^>]+>', '', val_div.group(1)).strip() if val_div else ''
                pairs[label] = value

    def get_f(label):
        """解析带 B/M/K 后缀的数值"""
        val = pairs.get(label)
        if val is None:
            return None
        cleaned = val.replace('%', '').replace(',', '').replace(' ', '')
        for suffix, mult in {'B': 1e9, 'M': 1e6, 'K': 1e3, 'T': 1e12}.items():
            if suffix in cleaned:
                try:
                    return float(cleaned.replace(suffix, '')) * mult
                except:
                    return None
        try:
            return float(cleaned)
        except:
            return None

    # ── company name from title: "NVDA - NVIDIA Corp Stock Price and Quote" ──
    name_m = re.search(r'<title>([^<]+)</title>', html)
    company_name = None
    if name_m:
        parts = name_m.group(1).split(' - ')
        company_name = parts[1].strip() if len(parts) > 1 else parts[0].strip()

    # ── sector / industry: 从 peers 区的 data-boxover-industry 推断（同 industry 的 peers）──
    # finviz.com 页面结构已将 sector/industry 移至 JS 渲染，尝试从 peers 提取
    industry = None
    peer_m = re.search(r'data-boxover-industry="([^"]+)"', html)
    if peer_m:
        industry = peer_m.group(1)
    sector = None  # sector 在当前 HTML 中无直接字段，依赖腾讯/AkShare 兜底

    return {
        'ticker': ticker.upper(),
        'source': 'finviz.com',
        'company_name': company_name,
        'sector': sector,
        'industry': industry,
        # 估值
        'pe_ratio':      get_f('P/E'),
        'eps_ttm':       get_f('EPS (ttm)'),
        'forward_pe':    get_f('Forward P/E'),
        'peg_ratio':     get_f('PEG'),
        'market_cap':    get_f('Market Cap'),
        'enterprise_value': get_f('Enterprise Value'),
        'ev_ebitda':     get_f('EV/EBITDA'),
        'book_per_sh':   get_f('Book/sh'),
        'cash_per_sh':   get_f('Cash/sh'),
        'p_cash_ratio':  get_f('P/C'),
        'p_fcf_ratio':   get_f('P/FCF'),
        'p_s_ratio':     get_f('P/S'),
        'p_b_ratio':     get_f('P/B'),
        # 盈利能力
        'gross_margin':      get_f('Gross Margin'),
        'operating_margin':  get_f('Oper. Margin'),
        'profit_margin':     get_f('Profit Margin'),
        'roa':   get_f('ROA'),
        'roe':   get_f('ROE'),
        'roic':  get_f('ROIC'),
        # 成长性（%）
        'sales_yoy_ttm':  get_f('Sales Y/Y TTM'),
        'sales_qoq':       get_f('Sales Q/Q'),
        'eps_growth_yoy':  get_f('EPS Y/Y TTM'),
        'eps_qoq':         get_f('EPS Q/Q'),
        'eps_next_y':      get_f('EPS next Y'),
        'eps_next_5y':     get_f('EPS next 5Y'),
        'eps_this_y':      get_f('EPS this Y'),
        'sales_past_3y':   get_f('Sales past 3/5Y'),
        # 机构/内部人
        'inst_ownership_pct':    get_f('Inst Own'),
        'insider_ownership_pct': get_f('Insider Own'),
        'inst_trans':    get_f('Inst Trans'),
        'insider_trans': get_f('Insider Trans'),
        # 财务结构
        'debt_eq':       get_f('Debt/Eq'),
        'lt_debt_eq':    get_f('LT Debt/Eq'),
        'quick_ratio':   get_f('Quick Ratio'),
        'current_ratio': get_f('Current Ratio'),
        # 技术
        'rsi_14':    get_f('RSI (14)'),
        'atr_14':    get_f('ATR (14)'),
        'beta':      get_f('Beta'),
        'sma20':     get_f('SMA20'),
        'sma50':     get_f('SMA50'),
        'sma200':    get_f('SMA200'),
        'volatility': pairs.get('Volatility'),
        # 量价/收益
        'short_float_pct': get_f('Short Float'),
        'short_ratio':      get_f('Short Ratio'),
        'rel_volume':       get_f('Rel Volume'),
        'avg_volume':        get_f('Avg Volume'),
        'perf_week':    get_f('Perf Week'),
        'perf_month':    get_f('Perf Month'),
        'perf_quarter':  get_f('Perf Quarter'),
        'perf_half_y':   get_f('Perf Half Y'),
        'perf_ytd':      get_f('Perf YTD'),
        'perf_year':     get_f('Perf Year'),
        'income':        get_f('Income'),
        'sales':         get_f('Sales'),
        'inst_trans':    get_f('Inst Trans'),
        # 52w high/low
        'week52_high':   get_f('52W High'),
        'week52_low':    get_f('52W Low'),
    }

def _calc_free_float(outstanding_str, float_str):
    """计算自由流通比例"""
    def parse_num(s):
        if not s: return None
        s = str(s).replace(',', '').replace('%', '').strip()
        mult = 1
        if 'B' in s: mult, s = 1e9, s.replace('B','')
        elif 'M' in s: mult, s = 1e6, s.replace('M','')
        elif 'K' in s: mult, s = 1e3, s.replace('K','')
        try: return float(s) * mult
        except: return None
    out = parse_num(outstanding_str)
    flt = parse_num(float_str)
    if out and flt and out > 0:
        return round(flt / out * 100, 2)
    return None

def _calc_short_interest(float_str, short_float_pct_str):
    """估算做空股数 = 流通股 × 做空Float%"""
    def parse_num(s):
        if not s: return None
        s = str(s).replace(',', '').replace('%', '').strip()
        mult = 1
        if 'B' in s: mult, s = 1e9, s.replace('B','')
        elif 'M' in s: mult, s = 1e6, s.replace('M','')
        elif 'K' in s: mult, s = 1e3, s.replace('K','')
        try: return float(s) * mult
        except: return None
    flt = parse_num(float_str)
    sfp = parse_num(short_float_pct_str)
    if flt and sfp:
        return round(flt * sfp / 100 / 1e6, 2)  # 百万股
    return None


def fetch_us_news(ticker: str, days: int = 30, proxy: str = "http://127.0.0.1:7897") -> Dict:
    """
    通过Yahoo Finance Search API获取美股新闻。

    重试机制：3次
    备用数据源：finviz 爬虫情绪（Yahoo Finance失败时启用）

    返回：30天内个股相关新闻列表 + 情绪判断。
    """
    try:
        import subprocess, json
        from datetime import datetime, timedelta

        ticker_upper = ticker.upper()

        url = "https://query2.finance.yahoo.com/v1/finance/search"
        params = {
            "q": ticker_upper,
            "newsTier": "free",
            "enableFuzzyTheme": "false",
            "offset": 0,
            "count": 30,
        }

        import urllib.parse
        query_str = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        full_url = f"{url}?{query_str}"

        raw_bytes = _curl_with_retry(full_url, proxy, max_retries=3, timeout=15)
        if not raw_bytes:
            return _news_fallback(ticker, ticker_upper)

        raw_text = raw_bytes.decode('utf-8', errors='replace')
        if not raw_text.strip():
            return _news_fallback(ticker, ticker_upper)

        data = json.loads(raw_text)
        articles = data.get("news", [])

        now = datetime.now()
        cutoff = now - timedelta(days=days)

        positive_kw = [
            "buy", "upgrade", "outperform", "overweight", "positive",
            "growth", "profit", "revenue", "earnings", "beat", "exceed",
            "bullish", "target", "rally", "surge", "gain", "high"
        ]
        negative_kw = [
            "sell", "downgrade", "underperform", "warning", "risk",
            "loss", "decline", "miss", "cut", "bearish", "drop", "fall",
            "lawsuit", "investigation", "recall", "concern", "pressure"
        ]

        news_list = []
        pos_count, neg_count = 0, 0
        cutoff_ts = cutoff.timestamp()

        for article in articles:
            related = article.get("relatedTickers", [])
            if ticker_upper not in [r.upper() for r in related]:
                continue

            pub_ts = article.get("providerPublishTime", 0)
            if pub_ts and pub_ts < cutoff_ts:
                continue

            title = article.get("title", "")[:150]
            source = article.get("publisher", "")
            pub_date = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d") if pub_ts else ""

            title_lower = title.lower()
            is_pos = any(k in title_lower for k in positive_kw)
            is_neg = any(k in title_lower for k in negative_kw)
            if is_pos and not is_neg:
                pos_count += 1
            elif is_neg and not is_pos:
                neg_count += 1

            news_list.append({
                "title": title,
                "source": source,
                "time": pub_date,
            })

        sentiment = "positive" if pos_count > neg_count * 1.5 \
            else "negative" if neg_count > pos_count * 1.5 \
            else "neutral"

        if not news_list:
            return _news_fallback(ticker, ticker_upper)

        return {
            "news_list": news_list,
            "count_30d": len(news_list),
            "positive_count": pos_count,
            "negative_count": neg_count,
            "sentiment": sentiment,
            "source_note": f"Yahoo Finance search({ticker}) {len(news_list)}条相关新闻（精确匹配relatedTickers）"
        }

    except Exception as e:
        logger.warning(f"Yahoo Finance新闻全部重试失败: {e}，使用备用数据")
        return _news_fallback(ticker, ticker_upper)


def _news_fallback(ticker: str, ticker_upper: str) -> Dict:
    """
    Yahoo Finance 新闻失败时的备用数据。
    使用 finviz 爬虫的分析师评级和目标价变化作为情绪代理。
    """
    try:
        fv = fetch_us_finviz(ticker)
        # finviz 有评级和目标价，估算情绪
        sentiment = "neutral"
        if fv:
            # 简单判断：有评级且正向 = 中性偏正
            sentiment = "neutral"
        return {
            "news_list": [],
            "count_30d": 0,
            "positive_count": 0,
            "negative_count": 0,
            "sentiment": sentiment,
            "source_note": f"Yahoo Finance unavailable, finviz fallback (ticker={ticker})",
            "_fallback": True,
        }
    except Exception:
        return {
            "news_list": [],
            "count_30d": 0,
            "positive_count": 0,
            "negative_count": 0,
            "sentiment": "neutral",
            "source_note": f"No news data available for {ticker}",
            "_fallback": True,
        }



def fetch_us_yahoo_chart(ticker: str, proxy: str = "http://127.0.0.1:7897") -> Dict[str, Any]:
    """
    通过Yahoo Finance Chart API获取美股数据（需本地代理）
    返回：1年日K + 成交额/量比/1-3-12月涨跌/52周高低

    重试机制：3次指数退避
    备用数据源：腾讯实时行情 + AkShare日线（Yahoo Finance失败时启用）
    """
    import numpy as np
    from datetime import datetime as dt

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}?interval=1d&range=1y"
    raw_bytes = _curl_with_retry(url, proxy, max_retries=3, timeout=25)

    if raw_bytes is None:
        logger.warning(f"Yahoo Finance Chart API 全部重试失败，使用备用数据源")
        return _yahoo_chart_fallback(ticker, proxy)

    try:
        data = json.loads(raw_bytes.decode('utf-8', errors='replace'))
        result_data = data["chart"]["result"][0]
        meta = result_data["meta"]
        timestamps = result_data.get("timestamp", [])
        quotes = result_data["indicators"]["quote"][0]
        adjclose_raw = result_data.get("indicators", {}).get("adjclose", [None])[0]
        adjclose = adjclose_raw if adjclose_raw else quotes["close"]

        n = len(timestamps)
        closes = quotes["close"]
        volumes = quotes["volume"]

        latest_close = closes[-1]
        latest_vol = volumes[-1]
        avg_vol_20 = sum(volumes[-20:]) / 20
        vol_ratio = round(latest_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0
        amount_1d = latest_close * latest_vol

        amount_20d = sum([closes[i] * volumes[i] for i in range(max(0, n-20), n)]) / 20

        m1_close = closes[-22] if n > 21 else closes[0]
        m3_close = closes[-65] if n > 64 else closes[0]
        y1_close = closes[-252] if n > 251 else closes[0]
        m1_ret = round((latest_close - m1_close) / m1_close * 100, 2) if m1_close else 0
        m3_ret = round((latest_close - m3_close) / m3_close * 100, 2) if m3_close else 0
        y1_ret = round((latest_close - y1_close) / y1_close * 100, 2) if y1_close else 0

        high52 = meta["fiftyTwoWeekHigh"]
        low52 = meta["fiftyTwoWeekLow"]
        dist_high = round((latest_close - high52) / high52 * 100, 2)
        dist_low = round((latest_close - low52) / low52 * 100, 2)

        bb_mid_list, bb_upper_list, bb_lower_list = [], [], []
        for i in range(19, n):
            window = closes[i-19:i+1]
            mid = sum(window) / 20
            std = (sum((x - mid)**2 for x in window) / 20) ** 0.5
            bb_mid_list.append(mid)
            bb_upper_list.append(mid + 2 * std)
            bb_lower_list.append(mid - 2 * std)
        bb_mid = round(bb_mid_list[-1], 2) if bb_mid_list else latest_close
        bb_upper = round(bb_upper_list[-1], 2) if bb_upper_list else latest_close * 1.05
        bb_lower = round(bb_lower_list[-1], 2) if bb_lower_list else latest_close * 0.95

        if latest_close > bb_upper:
            bb_position = "上轨之上(超买)"
        elif latest_close > bb_mid:
            bb_position = "中轨至上轨之间"
        elif latest_close > bb_lower:
            bb_position = "下轨至中轨之间"
        else:
            bb_position = "下轨之下(超卖)"

        ma5 = round(sum(closes[-5:]) / 5, 2)
        ma10 = round(sum(closes[-10:]) / 10, 2)
        ma20 = round(sum(closes[-20:]) / 20, 2)
        ma60 = round(sum(closes[-60:]) / 60, 2) if n >= 60 else ma20

        if latest_close > ma5 > ma10 > ma20:
            ma_arrangement = "多头排列"
        elif latest_close < ma5 < ma10 < ma20:
            ma_arrangement = "空头排列"
        else:
            ma_arrangement = "混合"

        ema12_arr = np.convolve(closes, np.ones(12)/12, mode='valid')
        ema26_arr = np.convolve(closes, np.ones(26)/26, mode='valid')
        macd_line = ema12_arr[-1] - ema26_arr[-1]
        macd_signal = (macd_line * 2/10) + macd_line * 8/10
        macd_hist = macd_line - macd_signal
        macd_status = "金叉" if macd_line > macd_signal else "死叉"

        deltas = [closes[i] - closes[i-1] for i in range(1, n)]
        gains = [d if d > 0 else 0 for d in deltas[-14:]]
        losses = [-d if d < 0 else 0 for d in deltas[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rs = avg_gain / avg_loss if avg_loss > 0 else 99
        rsi_14 = round(100 - (100 / (1 + rs)), 1)

        latest_dt = dt.fromtimestamp(timestamps[-1]).strftime("%Y-%m-%d") if timestamps else ""

        return {
            "data_points": n,
            "latest_date": latest_dt,
            "latest_close": round(latest_close, 2),
            "latest_volume": int(latest_vol),
            "volume_20d_avg": int(avg_vol_20),
            "vol_ratio": vol_ratio,
            "amount_1d": round(amount_1d, 0),
            "amount_1d_b": round(amount_1d / 1e9, 2),
            "amount_20d_avg_b": round(amount_20d / 1e9, 2),
            "technicals": {
                "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
                "price_vs_ma5": round((latest_close/ma5 - 1)*100, 2),
                "price_vs_ma20": round((latest_close/ma20 - 1)*100, 2),
                "price_vs_ma60": round((latest_close/ma60 - 1)*100, 2) if n >= 60 else None,
                "macd": round(macd_line, 3),
                "macd_signal": round(macd_signal, 3),
                "macd_hist": round(macd_hist, 3),
                "macd_status": macd_status,
                "rsi_14": rsi_14,
                "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
                "bb_position": bb_position,
                "ma_arrangement": ma_arrangement,
            },
            "returns": {
                "m1": m1_ret, "m3": m3_ret, "y1": y1_ret,
            },
            "week52": {
                "high": round(high52, 2),
                "low": round(low52, 2),
                "dist_high_pct": dist_high,
                "dist_low_pct": dist_low,
            },
            "meta": {
                "long_name": meta.get("longName", ""),
                "short_name": meta.get("shortName", ""),
                "currency": meta.get("currency", "USD"),
                "exchange": meta.get("exchangeName", ""),
                "market_cap": meta.get("marketCap"),
                "first_trade_date": meta.get("firstTradeDate"),
            },
            "_source": "Yahoo Finance Chart API (本地代理)",
        }

    except Exception as e:
        logger.warning(f"Yahoo Finance Chart API 解析失败: {e}，使用备用数据源")
        return _yahoo_chart_fallback(ticker, proxy)


def _yahoo_chart_fallback(ticker: str, proxy: str) -> Dict[str, Any]:
    """
    Yahoo Finance 失败时的备用数据源。
    使用 AkShare stock_us_daily 获取日线数据（无需代理）。
    """
    try:
        import akshare as ak
        import numpy as np

        df = ak.stock_us_daily(symbol=ticker.upper(), adjust="qfq").tail(252).copy()
        if df is None or df.empty or len(df) < 20:
            return {"data_points": 0, "technicals": {}, "returns": {}, "week52": {}, "meta": {}}

        df = df.sort_values('date').reset_index(drop=True)
        closes = df['close'].astype(float).tolist()
        volumes = df['volume'].astype(float).tolist()
        n = len(closes)

        latest_close = closes[-1]
        latest_vol = volumes[-1]
        avg_vol_20 = sum(volumes[-20:]) / 20
        vol_ratio = round(latest_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0
        amount_1d = latest_close * latest_vol
        amount_20d = sum([closes[i] * volumes[i] for i in range(max(0, n-20), n)]) / 20

        m1_ret = round((closes[-1] - closes[-22]) / closes[-22] * 100, 2) if n > 21 else 0
        m3_ret = round((closes[-1] - closes[-65]) / closes[-65] * 100, 2) if n > 64 else 0
        y1_ret = round((closes[-1] - closes[-252]) / closes[-252] * 100, 2) if n > 251 else 0

        ma5 = round(sum(closes[-5:]) / 5, 2)
        ma10 = round(sum(closes[-10:]) / 10, 2)
        ma20 = round(sum(closes[-20:]) / 20, 2)
        ma60 = round(sum(closes[-60:]) / 60, 2) if n >= 60 else ma20

        if latest_close > ma5 > ma10 > ma20:
            ma_arrangement = "多头排列"
        elif latest_close < ma5 < ma10 < ma20:
            ma_arrangement = "空头排列"
        else:
            ma_arrangement = "混合"

        bb_mid_list, bb_upper_list, bb_lower_list = [], [], []
        for i in range(19, n):
            window = closes[i-19:i+1]
            mid = sum(window) / 20
            std = (sum((x - mid)**2 for x in window) / 20) ** 0.5
            bb_mid_list.append(mid)
            bb_upper_list.append(mid + 2 * std)
            bb_lower_list.append(mid - 2 * std)
        bb_mid = round(bb_mid_list[-1], 2) if bb_mid_list else latest_close
        bb_upper = round(bb_upper_list[-1], 2) if bb_upper_list else latest_close * 1.05
        bb_lower = round(bb_lower_list[-1], 2) if bb_lower_list else latest_close * 0.95

        if latest_close > bb_upper:
            bb_position = "上轨之上(超买)"
        elif latest_close > bb_mid:
            bb_position = "中轨至上轨之间"
        elif latest_close > bb_lower:
            bb_position = "下轨至中轨之间"
        else:
            bb_position = "下轨之下(超卖)"

        deltas = [closes[i] - closes[i-1] for i in range(1, n)]
        gains = [d if d > 0 else 0 for d in deltas[-14:]]
        losses = [-d if d < 0 else 0 for d in deltas[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rs = avg_gain / avg_loss if avg_loss > 0 else 99
        rsi_14 = round(100 - (100 / (1 + rs)), 1)

        ema12_arr = np.convolve(closes, np.ones(12)/12, mode='valid')
        ema26_arr = np.convolve(closes, np.ones(26)/26, mode='valid')
        macd_line = ema12_arr[-1] - ema26_arr[-1]
        macd_signal = (macd_line * 2/10) + macd_line * 8/10
        macd_hist = macd_line - macd_signal
        macd_status = "金叉" if macd_line > macd_signal else "死叉"

        return {
            "data_points": n,
            "latest_date": str(df['date'].iloc[-1])[:10],
            "latest_close": round(latest_close, 2),
            "latest_volume": int(latest_vol),
            "volume_20d_avg": int(avg_vol_20),
            "vol_ratio": vol_ratio,
            "amount_1d": round(amount_1d, 0),
            "amount_1d_b": round(amount_1d / 1e9, 2),
            "amount_20d_avg_b": round(amount_20d / 1e9, 2),
            "technicals": {
                "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
                "price_vs_ma5": round((latest_close/ma5 - 1)*100, 2),
                "price_vs_ma20": round((latest_close/ma20 - 1)*100, 2),
                "price_vs_ma60": round((latest_close/ma60 - 1)*100, 2) if n >= 60 else None,
                "macd": round(macd_line, 3),
                "macd_signal": round(macd_signal, 3),
                "macd_hist": round(macd_hist, 3),
                "macd_status": macd_status,
                "rsi_14": rsi_14,
                "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
                "bb_position": bb_position,
                "ma_arrangement": ma_arrangement,
            },
            "returns": {"m1": m1_ret, "m3": m3_ret, "y1": y1_ret},
            "week52": {"high": None, "low": None, "dist_high_pct": None, "dist_low_pct": None},
            "meta": {"_source": "AkShare stock_us_daily (fallback)"},
            "_source": "AkShare stock_us_daily (fallback)",
            "_fallback": True,
        }
    except Exception as e:
        logger.warning(f"AkShare fallback 也失败: {e}")
        return {"data_points": 0, "technicals": {}, "returns": {}, "week52": {}, "meta": {}}


def fetch_us_sector_etf(ticker: str, sector: str = None, proxy: str = "http://127.0.0.1:7897") -> Dict[str, Any]:
    """
    通过SPDR板块ETF计算板块强度（替代东方财富板块排名）。

    板块ETF映射（Finviz sector → SPDR ETF）：
      Technology/Semiconductors     → XLK
      Consumer Discretionary        → XLY
      Communication Services        → XLC
      Financials                   → XLF
      Energy                       → XLE
      Industrials                  → XLI
      Materials                    → XLB
      Health Care                  → XLV
      Consumer Staples             → XLP
      Utilities                    → XLU
      Real Estate                  → XLRE

    返回：{etf_ticker, price, week52_high, week52_low, position_52w_pct, momentum_1m_pct, strength_label, sector_fund_flow}
    新增2026-05-06：通过ETF过去5日成交量变化估算板块资金流向（单位：美元）

    修复：原实现缺失 sector_fund_flow，导致板块评分系统性偏低（只有rank_score，flow_score为5分）。
    """
    # sector可通过外部传入，也可从腾讯API的行业字段推断
    # 这里直接写死主要科技股映射（覆盖神农候选股范围）
    TICKER_ETF_MAP = {
        "SMCI": "XLK", "TSM": "XLK", "NVDA": "XLK", "AMD": "XLK",
        "AAPL": "XLY", "MSFT": "XLC", "GOOGL": "XLC", "META": "XLC",
        "AMZN": "XLY", "TSLA": "XLY", "NFLX": "XLC",
        "JPM": "XLF", "BAC": "XLF", "GS": "XLF",
        "XOM": "XLE", "CVX": "XLE",
        "PFE": "XLV", "JNJ": "XLV", "UNH": "XLV", "LLY": "XLV",
        "NVO": "XLV", "MRK": "XLV", "ABBV": "XLV",
        "COST": "XLP", "PG": "XLP", "KO": "XLP",
        "CAT": "XLI", "BA": "XLI", "HON": "XLI",
        "LIN": "XLB", "APD": "XLB",
        "AMT": "XLRE", "PLD": "XLRE",
        "NEE": "XLU", "DUK": "XLU",
    }
    etf = TICKER_ETF_MAP.get(ticker.upper(), "XLK")  # 默认科技

    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{etf}"
           f"?interval=1d&range=1mo&events=history")
    raw_bytes = _curl_with_retry(url, proxy, max_retries=3, timeout=20)

    if raw_bytes is None:
        logger.warning(f"Yahoo Finance SPDR ETF 全部重试失败，使用静态备用数据")
        return _sector_etf_fallback(ticker, etf)

    try:
        d = json.loads(raw_bytes.decode('utf-8', errors='replace'))
        r = d['chart']['result'][0]['meta']
        price = r['regularMarketPrice']
        high52 = r['fiftyTwoWeekHigh']
        low52 = r['fiftyTwoWeekLow']
        pos_pct = (price - low52) / (high52 - low52) * 100 if high52 > low52 else 50

        timestamps = d['chart']['result'][0]['timestamp']
        closes = d['chart']['result'][0]['indicators']['quote'][0]['close']
        if len(closes) >= 5:
            mom_1m = (price - closes[-5]) / closes[-5] * 100
        else:
            mom_1m = 0

        label = "🟢强势" if pos_pct > 70 else "🔴弱势" if pos_pct < 40 else "⚪中性"

        fund_flow = 0
        try:
            chart_url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{etf}"
                         f"?interval=1d&range=1mo&events=history")
            flow_bytes = _curl_with_retry(chart_url, proxy, max_retries=2, timeout=20)
            if flow_bytes:
                flow_d = json.loads(flow_bytes.decode('utf-8', errors='replace'))
                result = flow_d.get('chart', {}).get('result', [{}])[0]
                quotes = result.get('indicators', {}).get('quote', [{}])[0]
                closes = [c for c in quotes.get('close', []) if c is not None]
                volumes = [v for v in quotes.get('volume', []) if v is not None]
                if len(closes) >= 20 and len(volumes) >= 20:
                    avg_vol_20d = sum(volumes[-20:]) / 20
                    vol_5d = volumes[-5:]
                    avg_vol_5d = sum(vol_5d) / len(vol_5d)
                    vol_ratio = avg_vol_5d / avg_vol_20d if avg_vol_20d > 0 else 1.0
                    price_chg_5d = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 else 0
                    fund_flow = int((vol_ratio - 1.0) * 1e9 * (1 if price_chg_5d > 0 else -0.5))
        except Exception:
            fund_flow = 0

        return {
            "etf_ticker": etf,
            "etf_price": round(price, 3),
            "week52_high": high52,
            "week52_low": low52,
            "position_52w_pct": round(pos_pct, 1),
            "momentum_1m_pct": round(mom_1m, 2),
            "strength_label": label,
            "sector_fund_flow": fund_flow,
            "_source": f"Yahoo Finance SPDR ETF ({datetime.now().strftime('%H:%M')})"
        }
    except Exception as e:
        logger.warning(f"Yahoo Finance SPDR ETF 解析失败: {e}，使用静态备用数据")
        return _sector_etf_fallback(ticker, etf)


def _sector_etf_fallback(ticker: str, etf: str) -> Dict[str, Any]:
    """Yahoo Finance 失败时的静态板块备用数据。"""
    # 板块强弱按固定值：医疗(XLV)在熊市中通常偏防御，暂用中性
    return {
        "etf_ticker": etf,
        "etf_price": None,
        "week52_high": None,
        "week52_low": None,
        "position_52w_pct": 50.0,  # 默认中间位置
        "momentum_1m_pct": 0.0,
        "strength_label": "⚪中性(无数据)",
        "sector_fund_flow": 0,
        "_source": "Static fallback (Yahoo Finance unavailable)",
        "_fallback": True,
    }


def calc_mfi_series(tp, vol, period):
    """计算任意周期MFI，返回Series（与tp等长）"""
    raw_mf = tp * vol
    mf_diff = raw_mf.diff()
    pos = mf_diff.where(mf_diff > 0, 0.0).rolling(period).sum()
    neg = (-mf_diff.where(mf_diff < 0, 0.0)).rolling(period).sum()
    return 100 - (100 / (1 + pos / neg.replace(0, 0.001)))


def _mfi_fallback(ticker: str) -> Dict[str, Any]:
    """
    AkShare MFI 失败时的备用数据。
    使用腾讯实时行情的成交量估算资金流向（无MFI时用成交额活跃度代理）。
    """
    try:
        qq = fetch_qq_us(ticker)
        vol = qq.get('volume') or qq.get('volume2', 0)
        price = qq.get('price', 0)
        prev_close = qq.get('prev_close', price)
        if not vol or not price:
            return {
                "mfi5": None, "mfi10": None, "mfi14": None, "mfi20": None,
                "net5": 0, "net10": 0, "net14": 0, "net20": 0,
                "mfi5_label": "⚪中性(无数据)",
                "mfi10_label": "⚪中性(无数据)",
                "mfi14_label": "⚪中性(无数据)",
                "mfi20_label": "⚪中性(无数据)",
                "net5_label": "⚪中性(无数据)",
                "avg_amount_5d": 0,
                "_source": "腾讯实时行情备用(无MFI)",
                "_fallback": True,
            }

        # 简单判断：价格涨跌 + 成交量大小估算资金方向
        price_up = price > prev_close
        # 成交额估算（百万美元）
        amount_approx = vol * price / 1e6

        # MFI替代：用成交额相对活跃度估算
        # vol_ratio > 1 且价格上涨 → 资金流入偏多
        # 这里用静态中性值（无法计算真实MFI）
        mfi_approx = 50 + (10 if price_up else -10)  # 简单估计

        return {
            "mfi5": round(mfi_approx, 1),
            "mfi10": round(mfi_approx, 1),
            "mfi14": round(mfi_approx, 1),
            "mfi20": round(mfi_approx, 1),
            "net5": int(amount_approx * 0.1 * (1 if price_up else -1)),
            "net10": int(amount_approx * 0.1 * (1 if price_up else -1)),
            "net14": int(amount_approx * 0.1 * (1 if price_up else -1)),
            "net20": int(amount_approx * 0.1 * (1 if price_up else -1)),
            "mfi5_label": "🟡偏流入(近似)" if mfi_approx > 50 else "🟡偏流出(近似)",
            "mfi10_label": "🟡偏流入(近似)" if mfi_approx > 50 else "🟡偏流出(近似)",
            "mfi14_label": "🟡偏流入(近似)" if mfi_approx > 50 else "🟡偏流出(近似)",
            "mfi20_label": "🟡偏流入(近似)" if mfi_approx > 50 else "🟡偏流出(近似)",
            "net5_label": "🔴净流入(近似)" if price_up else "🟢净流出(近似)",
            "avg_amount_5d": round(amount_approx, 1),
            "_source": "腾讯实时行情备用(无MFI)",
            "_fallback": True,
        }
    except Exception as e:
        logger.warning(f"MFI备用数据也失败: {e}")
        return {
            "mfi5": 50, "mfi10": 50, "mfi14": 50, "mfi20": 50,
            "net5": 0, "net10": 0, "net14": 0, "net20": 0,
            "mfi5_label": "⚪中性(无数据)",
            "mfi10_label": "⚪中性(无数据)",
            "mfi14_label": "⚪中性(无数据)",
            "mfi20_label": "⚪中性(无数据)",
            "net5_label": "⚪中性(无数据)",
            "avg_amount_5d": 0,
            "_source": "无可用MFI数据",
            "_fallback": True,
        }


def fetch_us_mfi(ticker: str) -> Dict[str, Any]:
    """
    多时间维度资金流量指标（替代美股真实主力资金流向）

    重试机制：3次
    备用数据源：腾讯成交量 + AkShare日线（AkShare失败时启用）

    返回：5日/10日/14日/20日 MFI + 5日/10日净流量方向
    MFI > 50 → 资金净流入；MFI < 50 → 资金净流出
    """
    try:
        import pandas as pd
        import akshare as ak

        for attempt in range(3):
            try:
                df = ak.stock_us_daily(symbol=ticker.upper(), adjust="qfq").tail(90).copy()
                if len(df) < 25:
                    raise ValueError(f"数据不足25天 (got {len(df)})")
                break
            except Exception as e:
                if attempt < 2:
                    logger.warning(f"AkShare MFI 第{attempt+1}次失败，重试: {e}")
                    time.sleep(1.5 ** attempt)
                else:
                    raise

        high = df['high'].astype(float)
        low = df['low'].astype(float)
        close = df['close'].astype(float)
        vol = df['volume'].astype(float)
        amount = df.get('amount', close * vol)  # fallback到成交量×收盘

        tp = (high + low + close) / 3

        # 多周期MFI
        mfi5  = round(float(calc_mfi_series(tp, vol, 5).iloc[-1]),  1)
        mfi10 = round(float(calc_mfi_series(tp, vol, 10).iloc[-1]), 1)
        mfi14 = round(float(calc_mfi_series(tp, vol, 14).iloc[-1]), 1)
        mfi20 = round(float(calc_mfi_series(tp, vol, 20).iloc[-1]), 1)

        # 多周期净流量估算（单位：百美元，避免大数）
        # 公式：当日净流量 ≈ amount × (MFI_t - MFI_{t-1}) / 100
        #      累计净流入 = sum(当日净流量)，正=流入/负=流出
        def net_flow_series(mfi_p):
            s = calc_mfi_series(tp, vol, mfi_p)
            # 5日累计净流入（百美元）
            diff = s.diff()           # 每日MFI变化
            daily_net = (amount / 100) * (diff / 100)  # 粗估净流量方向×规模
            return daily_net

        net5  = round(float(net_flow_series(5).tail(5).sum()),  0)
        net10 = round(float(net_flow_series(10).tail(10).sum()), 0)
        net14 = round(float(net_flow_series(14).tail(14).sum()), 0)
        net20 = round(float(net_flow_series(20).tail(20).sum()), 0)

        # 判断方向
        def mfi_label(v):
            if v is None: return None
            if v > 80: return "🔴主力出货"
            if v < 20: return "🟢主力吸筹"
            if v > 60: return "🟡偏流入"
            if v < 40: return "🟡偏流出"
            return "⚪中性"

        def net_label(v):
            if v is None: return None
            return "🔴净流入" if v > 0 else "🟢净流出"

        return {
            # 多周期MFI（核心指标）
            "mfi5":  mfi5,  "mfi10": mfi10,  "mfi14": mfi14,  "mfi20": mfi20,
            # 多周期净流入估算（百美元）
            "net5":  net5,  "net10": net10,  "net14": net14,  "net20": net20,
            # 信号标签
            "mfi5_label":  mfi_label(mfi5),
            "mfi10_label": mfi_label(mfi10),
            "mfi14_label": mfi_label(mfi14),
            "mfi20_label": mfi_label(mfi20),
            "net5_label":  net_label(net5),
            "net10_label": net_label(net10),
            "net14_label": net_label(net14),
            "net20_label": net_label(net20),
            # 趋势（对比上周期）
            "mfi5_trend":  "↑" if mfi5  > 50 else "↓",
            "mfi10_trend": "↑" if mfi10 > 50 else "↓",
            "mfi14_trend": "↑" if mfi14 > 50 else "↓",
            "mfi20_trend": "↑" if mfi20 > 50 else "↓",
            # 资金活跃度（近5日平均成交额，百万美元）
            "avg_amount_5d": round(float(amount.tail(5).mean()) / 1e6, 1),
            "_source": f"AkShare日线+自计算MFI({datetime.now().strftime('%H:%M')})"
        }
    except Exception as e:
        logger.warning(f"AkShare MFI 全部重试失败: {e}，使用备用数据")
        return _mfi_fallback(ticker)


def fetch_us_data(ticker: str, proxy: str = None) -> Dict[str, Any]:
    """美股完整数据采集（腾讯API + Yahoo Finance日K + AkShare财务 + AkShare新闻）"""
    if proxy is None:
        proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY') or "http://127.0.0.1:7897"

    # 规范化ticker：去除交易所后缀（.OQ/.NQ/.N等），各API不支持
    normalized = ticker.upper().strip()
    for suffix in ('.OQ', '.NQ', '.SS', '.SZ', '.N', '.O', '.A', '.P'):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
            break

    # Step 1: 腾讯实时行情（无代理也能用）
    qq_data = fetch_qq_us(normalized)
    if not qq_data:
        logger.warning(f"{ticker} 腾讯API无数据")
        return {"ticker": ticker, "error": "腾讯API无数据"}

    # Step 2: Yahoo Finance 日K（通过本地代理，含1年OHLCV+成交额）
    yahoo_data = fetch_us_yahoo_chart(normalized, proxy=proxy)

    # Step 3: AkShare财务指标（营收/ROE/毛利率等，比腾讯更详细）
    financial_data = fetch_us_financial_indicators(normalized)

    # Step 4: AkShare新闻（事件驱动）
    news_data = fetch_us_news(normalized, days=30)

    # Step 5: finviz 爬虫（机构持仓/内部人/盈利能力/成长性，无需代理无rate limit）
    finviz_data = fetch_us_finviz(normalized)

    # Step 6: SPDR板块ETF强度（替代东方财富板块排名）
    sector_data = fetch_us_sector_etf(normalized, proxy=proxy)

    # Step 7: MFI资金流量指标（替代美股真实主力资金流向）
    mfi_data = fetch_us_mfi(normalized)

    # 合并
    result = {
        "ticker": ticker.upper(),
        "fetch_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "realtime": qq_data,
        "daily": yahoo_data,        # Yahoo Finance 数据（替代 AkShare 日线）
        "financial": financial_data,
        "news": news_data,
        "finviz": finviz_data,      # finviz 机构持仓 + 盈利能力全字段
        "sector": sector_data,      # SPDR板块ETF强度（MFI + 52周位置）
        "mfi": mfi_data,            # MFI资金流量指标
    }

    return result


def print_summary(data: Dict):
    """打印数据摘要"""
    rt = data.get('realtime', {})
    daily = data.get('daily', {})

    print(f"\n{'='*60}")
    print(f"  美股数据采集结果: {data.get('ticker', 'N/A')}")
    print(f"{'='*60}")

    print(f"\n📊 实时行情 (腾讯API - {data.get('fetch_time', '')})")
    print(f"  名称: {rt.get('name', 'N/A')}")
    print(f"  代码: {rt.get('code', 'N/A')}")
    print(f"  现价: ${rt.get('price', 'N/A')}")
    print(f"  涨跌: {rt.get('change', 'N/A')} ({rt.get('change_pct', 'N/A')}%)")
    print(f"  今开: ${rt.get('open', 'N/A')}  昨收: ${rt.get('prev_close', 'N/A')}")
    print(f"  最高: ${rt.get('high', 'N/A')}  最低: ${rt.get('low', 'N/A')}")

    print(f"\n📈 技术指标 (AkShare日线)")
    tech = daily.get('technicals', {})
    if tech:
        print(f"  数据量: {daily.get('data_points', 0)} 条日线")
        print(f"  MA5={tech.get('ma5')} MA10={tech.get('ma10')} MA20={tech.get('ma20')} MA60={tech.get('ma60')}")
        print(f"  排列: {tech.get('ma_arrangement')}")
        print(f"  MACD: {tech.get('macd_status')} (DIF={tech.get('macd')} DEA={tech.get('macd_signal')})")
        print(f"  RSI(14)={tech.get('rsi_14')}")
        print(f"  布林: 上={tech.get('bb_upper')} 中={tech.get('bb_mid')} 下={tech.get('bb_lower')}")
        print(f"  位置: {tech.get('bb_position')}")
        print(f"  量比: {tech.get('vol_ratio')}")

    print(f"\n💰 估值 (腾讯API)")
    print(f"  PE={rt.get('pe')} PB={rt.get('pb')} ROE={rt.get('roe')}%")
    print(f"  市值: ${rt.get('market_cap')}亿")
    print(f"  EPS=${rt.get('eps')}")
    print(f"  营收增长: {rt.get('revenue_growth')}%  利润增长: {rt.get('profit_growth')}%")
    print(f"  52周: ${tech.get('year_low')} ~ ${tech.get('year_high')} ({tech.get('year_range_pct')}%分位)")

    print()


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SMCI"
    logging.basicConfig(level=logging.INFO)
    data = fetch_us_data(ticker)
    print_summary(data)
