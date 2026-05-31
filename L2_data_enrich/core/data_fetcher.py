#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时数据获取器 — 连接AkShare+BaoStock+腾讯行情API
为五维评分引擎提供实时数据输入

数据流：
  realtime_data_fetcher.fetch_all(code, name)
    → data dict (含 moneyflow/technical/fundamental/sector/event)
    → 传入 FiveDimensionScorer.score_stock(code, name, data)

数据源优先级（按可靠性）：
  1. 腾讯行情API — 实时行情(价格/PE/PB/成交量) — curl直连，最稳定
  2. AkShare东方财富 — 资金流向(主力/超大单/大单/小单) — 最核心数据
  3. AkShare财务指标 — ROE/毛利率/净利润增速
  4. BaoStock日线 — 历史K线(MA计算/MACD/RSI/布林带)
  5. AkShare板块数据 — 行业板块强度

2026-04-23 实测验证：所有数据源可用
"""

# ======================== 数据源健康日志 ========================
# 写入 ~/.hermes/investment/logs/hermes.log，用于自动化 API 可用性监控
import os as _log_os
import os as _os
import json
import time
import re
import subprocess
import logging
from typing import Dict, Any, List, Optional
import datetime as _dt
from datetime import datetime, timedelta

_HERMES_LOG_DIR = _log_os.path.join(_log_os.path.dirname(_log_os.path.dirname(_log_os.path.dirname(_log_os.path.abspath(__file__)))), "logs")
_HERMES_LOG_FILE = _log_os.path.join(_HERMES_LOG_DIR, "hermes.log")
_log_os.makedirs(_HERMES_LOG_DIR, exist_ok=True)


def _api_log(source: str, operation: str, success: bool, detail: str = ""):
    """轻量级数据源健康日志，写入 hermes.log"""
    import datetime as _dt
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    status = "✅" if success else "❌"
    msg = f"[{ts}] [source={source}] {operation} {status}" + (f" - {detail}" if detail else "")
    try:
        with open(_HERMES_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    return msg

logger = logging.getLogger("realtime_data_fetcher")

# ======================== 配置加载 ========================

_CONFIG_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "main", "config", "l2_config.json"
)

_L2_CONFIG_CACHE = None

def _load_l2_config() -> dict:
    global _L2_CONFIG_CACHE
    if _L2_CONFIG_CACHE is None:
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                _L2_CONFIG_CACHE = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _L2_CONFIG_CACHE = {}
    return _L2_CONFIG_CACHE

def get_l2_config() -> dict:
    return _load_l2_config()

# ======================== 并发控制常量 ========================

def _get_concurrent_config() -> dict:
    cfg = get_l2_config()
    concurrent = cfg.get("concurrent", {})
    return {
        "max_fund_flow": concurrent.get("max_fund_flow", 3),
        "requests_per_second": concurrent.get("requests_per_second", 2),
        "fund_flow_interval": concurrent.get("fund_flow_interval", 0.5),
        "max_bao": concurrent.get("max_bao", 10),
    }

def _get_timeouts() -> dict:
    cfg = get_l2_config()
    timeouts = cfg.get("timeouts", {})
    return {
        "tencent": timeouts.get("tencent", 10),
        "curl": timeouts.get("curl", 10),
        "bao": timeouts.get("bao", 15),
    }

def _get_defaults() -> dict:
    cfg = get_l2_config()
    defaults = cfg.get("defaults", {})
    return {
        "sector_rank": defaults.get("sector_rank", 50),
        "stock_rank": defaults.get("stock_rank", 9999),
        "rsi": defaults.get("rsi", 50),
        "outer_inner_ratio": defaults.get("outer_inner_ratio", 1.0),
    }

def _get_field_indices() -> dict:
    cfg = get_l2_config()
    fields = cfg.get("field_indices", {})
    if fields:
        return fields
    # 默认值
    return {
        "name": 1, "code": 2, "price": 3, "prev_close": 4,
        "open": 5, "volume": 6, "outer_disk": 7, "inner_disk": 8,
        "high": 33, "low": 34, "amount": 37, "turnover": 38,
        "pe": 39, "week52_high": 47, "week52_low": 48,
        "amplitude": 49, "pb": 46, "market_cap": 45,
    }

# ======================== 腾讯API字段索引 ========================

QQ_PARTS = _get_field_indices()

# ======================== 旧版全局常量（兼容） ========================

_concurrent_cfg = _get_concurrent_config()
MAX_CONCURRENT_FUND_FLOW = _concurrent_cfg["max_fund_flow"]
REQUESTS_PER_SECOND = _concurrent_cfg["requests_per_second"]
FUND_FLOW_INTERVAL = _concurrent_cfg["fund_flow_interval"]
MAX_CONCURRENT_BAO = _concurrent_cfg["max_bao"]

# 代码前缀转换
def _to_qq_code(code: str) -> str:
    """转换为腾讯API格式：sh600320 / sz000858（无点）"""
    code = code.strip()
    if code.startswith(('sh.', 'sz.', 'hk.')):
        return code.lower().replace('.', '')  # sh.600320 → sh600320
    if code.startswith(('sh', 'sz', 'hk')):
        return code.lower()  # sh600320 → sh600320
    if code.startswith(('6', '8')):
        return f"sh{code}"  # 600320 → sh600320
    elif code.startswith(('0', '3')):
        return f"sz{code}"  # 000858 → sz000858
    return code

def _to_baostock_code(code: str) -> str:
    """转换为BaoStock格式：sh.600519 或 sz.000858"""
    code = code.strip().lower()  # 统一小写，避免 SH/SZ 大小写不匹配
    if code.startswith(('sh.', 'sz.')):
        return code
    if code.startswith(('sh', 'sz')):
        # BaoStock格式：sh.600320（有点），不是 sh600320
        return f"{code[:2]}.{code[2:]}"  # sh600320 → sh.600320
    if code.startswith(('6', '8')):
        return f"sh.{code}"
    elif code.startswith(('0', '3')):
        return f"sz.{code}"
    return code

def _to_akshare_market(code: str) -> str:
    """判断AkShare market参数"""
    code_clean = code.strip().replace('sh', '').replace('sz', '')
    if code_clean.startswith(('0', '3')):
        return 'sz'
    return 'sh'


# ======================== 数据获取器 ========================

def fetch_qq_realtime(code: str) -> Dict[str, Any]:
    """
    腾讯行情API — 实时价格/PE/PB/外内盘
    返回：{price, prev_close, change_pct, pe, pb, 等}

    注意：腾讯API需要正确的sh/sz前缀，纯数字代码会被正确转换
    """
    qq_code = _to_qq_code(code)
    logger.info(f"  腾讯API请求: {qq_code}")
    url = f"http://qt.gtimg.cn/q={qq_code}"
    
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', '5', '-A', 'Mozilla/5.0', url],
            capture_output=True, timeout=10
        )
        raw = r.stdout.decode('gbk', errors='replace')
        match = re.search(r'"([^"]+)"', raw)
        if not match:
            logger.warning(f"腾讯API无数据: {code}")
            return {}
        
        parts = match.group(1).split('~')
        if len(parts) < 50:
            logger.warning(f"腾讯API字段不足({len(parts)}): {code}")
            return {}
        
        def safe_float(idx, default=None):
            val = parts[idx] if idx < len(parts) else '-'
            if val and val != '-':
                try:
                    return float(val)
                except ValueError:
                    return default
            return default
        
        def safe_int(idx, default=0):
            val = parts[idx] if idx < len(parts) else '-'
            if val and val != '-':
                try:
                    return int(float(val))
                except ValueError:
                    return default
            return default
        
        price = safe_float(QQ_PARTS["price"])
        prev_close = safe_float(QQ_PARTS["prev_close"])
        change_pct = round((price - prev_close) / prev_close * 100, 2) if (price and prev_close and prev_close > 0) else 0
        
        outer = safe_int(QQ_PARTS["outer_disk"])
        inner = safe_int(QQ_PARTS["inner_disk"])
        outer_inner_ratio = round(outer / inner, 2) if inner > 0 else 1.0
        
        # 腾讯API字段特殊处理：
        #   PB字段原始值即为实际值（如茅台7.41），无需除以10000
        #   PE字段原始值即为实际值，无需调整
        #   market_cap和circulating_cap在腾讯API中为同一字段[45]
        raw_pb = safe_float(QQ_PARTS["pb"])
        pb = round(raw_pb, 4) if raw_pb is not None else None

        result = {
            "price": price,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "open": safe_float(QQ_PARTS["open"]),
            "high": safe_float(QQ_PARTS["high"]),
            "low": safe_float(QQ_PARTS["low"]),
            "volume": safe_int(QQ_PARTS["volume"]),
            "amount": safe_float(QQ_PARTS["amount"]),
            "pe": safe_float(QQ_PARTS["pe"]),
            "pb": pb,
            "market_cap": safe_float(QQ_PARTS["market_cap"]),
            "circulating_cap": safe_float(QQ_PARTS["market_cap"]),  # 腾讯不区分，复用总市值
            "turnover": safe_float(QQ_PARTS["turnover"]),
            "amplitude": safe_float(QQ_PARTS["amplitude"]),
            "week52_high": safe_float(QQ_PARTS["week52_high"]),
            "week52_low": safe_float(QQ_PARTS["week52_low"]),
            "outer_disk": outer,
            "inner_disk": inner,
            "outer_inner_ratio": outer_inner_ratio,
            "name": parts[QQ_PARTS["name"]] if QQ_PARTS["name"] < len(parts) else code,
            "_source": f"腾讯行情API({datetime.now().strftime('%H:%M')})",
            "_raw_fields": len(parts),
        }
        _api_log("tencent", "fetch_qq_realtime", True, f"code={code}, price={price}")
        return result

    except Exception as e:
        logger.warning(f"腾讯行情API失败 {code}: {e}")
        _api_log("tencent", "fetch_qq_realtime", False, str(e))
        return {}


def fetch_fund_flow(code: str, days: int = 10) -> Dict[str, Any]:
    """
    AkShare东方财富 — 个股资金流向（新版ak.stock_fund_flow_individual）
    
    新接口（2026-04-25验证可用）:
      - ak.stock_fund_flow_individual(symbol='即时') → 全市场5186只股票即时排名
      - 返回列: ['序号','股票代码','股票简称','最新价','涨跌幅','换手率',
                 '流入资金','流出资金','净额','成交额']
      - 净额字符串格式: '16.53亿' / '4394.96万' / '-7.03亿'
    
    同时补充（2026-04-25新增）:
      - 千股千评: ak.stock_comment_em() → 综合得分/主力成本/机构参与度/关注指数
      - 沪深港通: ak.stock_hsgt_individual_em() → 北向持股/增持/市值变化
      - 北向资金: ak.stock_hsgt_fund_flow_summary_em() → 沪股通/深股通当日净买额
      - 机构调研: ak.stock_jgdy_em() → 机构调研次数/频繁度
    """
    import akshare as ak
    import pandas as pd
    import numpy as np

    code_clean = re.sub(r'[^0-9]', '', code)
    
    # ── 解析金额字符串 → 浮点数（元）─────────────────────
    def parse_amount(s) -> float:
        if not s or s == '-' or pd.isna(s):
            return 0.0
        s = str(s).strip()
        try:
            if '亿' in s:
                return float(s.replace('亿', '')) * 1e8
            elif '万' in s:
                return float(s.replace('万', '')) * 1e4
            elif '万' not in s and '亿' not in s:
                return float(s)
        except:
            pass
        return 0.0

    result = {}

    # ── ① 个股资金流向（东方财富直连API，不依赖榜单，最优先）──
    # 这个 API 直接获取个股5日资金流，不管排名
    em_flow = _fetch_single_fund_flow_eastmoney(code_clean)
    if em_flow:
        result.update(em_flow)
        logger.info(f"  资金流(EM直连): 5日净={em_flow.get('main_net_flow_5d', 0)/1e8:.2f}亿")
    else:
        logger.info(f"  资金流(EM直连)失败，退而求榜单查找...")

    # ── ② 主力资金流（全市场排名兜底）──
    try:
        df = ak.stock_fund_flow_individual(symbol='即时')
        logger.info(f"资金流(全市场)获取成功: {len(df)}只股票")

        # 在全市场数据中找目标股票
        mask = df['股票代码'] == code_clean
        if not mask.any():
            # 尝试带0前缀
            mask = df['股票代码'] == code_clean.lstrip('0')
        
        if mask.any():
            row = df[mask].iloc[0]
            net = parse_amount(row['净额'])
            inflow = parse_amount(row['流入资金'])
            outflow = parse_amount(row['流出资金'])
            result.update({
                "main_net_flow": net,
                "main_inflow": inflow,
                "main_outflow": outflow,
                "main_net_ratio": abs(net / parse_amount(row['成交额'])) if parse_amount(row['成交额']) > 0 else 0,
                "turnover_rate": float(str(row.get('换手率','0')).replace('%','')) / 100 if row.get('换手率') else 0,
                "price_change_pct": float(str(row.get('涨跌幅','0')).replace('%','')) / 100 if row.get('涨跌幅') else 0,
                "stock_rank": int(row['序号']) if '序号' in row.index else 9999,
                "fund_flow_source": "ak.stock_fund_flow_individual(即时,2026-04-25验证✅)",
            })
            logger.info(f"  {code_clean} 主力净额={net/1e8:.2f}亿, 排名={row['序号']}")
        else:
            # 不在即时榜（说明资金流动不明显），尝试5日/10日
            logger.info(f"  {code_clean} 不在即时榜单，尝试其他时间窗口")
            result["stock_rank"] = 9999
            result["fund_flow_source"] = "ak.stock_fund_flow_individual(即时,2026-04-25验证✅)"
    except Exception as e:
        logger.warning(f"资金流(全市场)获取失败 {code}: {e}")
        result["fund_flow_source"] = f"ak.stock_fund_flow_individual失败:{str(e)[:40]}"

    # ── ② 千股千评（综合得分/主力成本/机构参与度）───────
    try:
        df_comment = ak.stock_comment_em()
        mask = df_comment['代码'] == code_clean
        if not mask.any():
            mask = df_comment['代码'] == code_clean.lstrip('0')
        
        if mask.any():
            row = df_comment[mask].iloc[0]
            result.update({
                "comprehensive_score": float(row['综合得分']) if pd.notna(row.get('综合得分')) else None,
                "main_cost": float(row['主力成本']) if pd.notna(row.get('主力成本')) else None,
                "institution_participation": float(row['机构参与度']) if pd.notna(row.get('机构参与度')) else None,
                "attention_index": float(row['关注指数']) if pd.notna(row.get('关注指数')) else None,
                "rank_position": int(row['目前排名']) if pd.notna(row.get('目前排名')) else 9999,
                "comment_source": "ak.stock_comment_em(2026-04-25验证✅)",
            })
            logger.info(f"  千股千评: 综合得分={row['综合得分']}, 主力成本={row['主力成本']}")
        else:
            result["comment_source"] = "ak.stock_comment_em(股票不在榜上)"
    except Exception as e:
        logger.warning(f"千股千评获取失败 {code}: {e}")
        result["comment_source"] = f"ak.stock_comment_em失败:{str(e)[:40]}"

    # ── ③ 沪深港通北向持股（增持/持股市值）────────────
    try:
        # 判断沪深市场
        if code_clean.startswith('6'):
            hk_market = '沪股通'
        else:
            hk_market = '深股通'
        
        # 北向持股明细
        df_hsgt = ak.stock_hsgt_individual_em(symbol=code_clean)
        if df_hsgt is not None and not df_hsgt.empty:
            latest = df_hsgt.iloc[-1]  # 最近一条
            result.update({
                "hsgt_hold_shares": float(latest['持股数量']) if pd.notna(latest.get('持股数量')) else None,
                "hsgt_hold_market_value": float(latest['持股市值']) if pd.notna(latest.get('持股市值')) else None,
                "hsgt_hold_ratio": float(latest['持股数量占A股百分比']) / 100 if pd.notna(latest.get('持股数量占A股百分比')) else None,
                "hsgt_add_shares": float(latest['今日增持股数']) if pd.notna(latest.get('今日增持股数')) else None,
                "hsgt_add_amount": float(latest['今日增持资金']) if pd.notna(latest.get('今日增持资金')) else None,
                "hsgt_change_pct": float(latest['今日持股市值变化']) / 1e8 if pd.notna(latest.get('今日持股市值变化')) else None,
                "hsgt_source": "ak.stock_hsgt_individual_em(2026-04-25验证✅)",
            })
            logger.info(f"  北向持股: 持股量={latest['持股数量']:.0f}, 增持={latest.get('今日增持股数','N/A')}")
        else:
            result["hsgt_source"] = "ak.stock_hsgt_individual_em(数据为空)"
    except Exception as e:
        logger.warning(f"沪深港通获取失败 {code}: {e}")
        result["hsgt_source"] = f"ak.stock_hsgt_individual_em失败:{str(e)[:40]}"

    # ── ④ 北向资金流汇总（大盘方向）────────────────────
    try:
        df_flow = ak.stock_hsgt_fund_flow_summary_em()
        if df_flow is not None and not df_flow.empty and '资金方向' in df_flow.columns:
            # 找到北向资金（非南向）
            north_mask = df_flow['资金方向'] == '北向'
            if north_mask.any():
                north = df_flow[north_mask].iloc[0]
                result.update({
                    "north_net_buy_today": float(north['成交净买额']) * 1e8 if pd.notna(north.get('成交净买额')) else None,
                    "north_up_count": int(north['上涨数']) if pd.notna(north.get('上涨数')) else None,
                    "north_down_count": int(north['下跌数']) if pd.notna(north.get('下跌数')) else None,
                    "north_index_pct": float(north['指数涨跌幅']) / 100 if pd.notna(north.get('指数涨跌幅')) else None,
                    "hsgt_flow_source": "ak.stock_hsgt_fund_flow_summary_em(2026-04-25验证✅)",
                })
    except Exception as e:
        logger.warning(f"北向资金流汇总失败: {e}")

    # ── ⑤ 机构调研（频繁度=关注度代理）───────────────
    # 注意：ak.stock_jgdy_tj_em 在当日无数据时返回 {"result": None}，
    # 此时 data_json["result"]["pages"] 会触发 TypeError。
    # 修复：直接请求原始 URL，先检查 result 是否为 None，避免 akshare 内部 TypeError
    try:
        import requests as _req
        today = datetime.now().strftime("%Y%m%d")
        date_str = today
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "sortColumns": "NOTICE_DATE,SUM,RECEIVE_START_DATE,SECURITY_CODE",
            "sortTypes": "-1,-1,-1,1",
            "pageSize": "500",
            "pageNumber": "1",
            "reportName": "RPT_ORG_SURVEYNEW",
            "columns": "ALL",
            "quoteColumns": "f2~01~SECURITY_CODE~CLOSE_PRICE,f3~01~SECURITY_CODE~CHANGE_RATE",
            "source": "WEB",
            "client": "WEB",
            "filter": f'(NUMBERNEW="1")(IS_SOURCE="1")(NOTICE_DATE>"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}")',
        }
        r = _req.get(url, params=params, timeout=10)
        data_json = r.json()
        if data_json.get("result") is not None and data_json["result"].get("pages", 0) > 0:
            df_all = ak.stock_jgdy_tj_em(date=today)
            if df_all is not None and not df_all.empty:
                if '代码' in df_all.columns:
                    matched = df_all[df_all['代码'] == code_clean]
                elif 'code' in df_all.columns:
                    matched = df_all[df_all['code'] == code_clean]
                else:
                    matched = df_all[df_all.iloc[:, 0].astype(str).str.contains(code_clean, na=False)]
                if matched is not None and not matched.empty:
                    row = matched.iloc[0]
                    result.update({
                        "research_count": int(row['接待机构数量']) if '接待机构数量' in row.index and pd.notna(row['接待机构数量']) else None,
                        "latest_research_date": str(row['接待日期']) if '接待日期' in row.index and pd.notna(row['接待日期']) else None,
                        "research_source": "ak.stock_jgdy_tj_em(2026-05-30修复✅)",
                    })
                else:
                    result["research_source"] = f"ak.stock_jgdy_tj_em无{code}数据"
            else:
                result["research_source"] = "ak.stock_jgdy_tj_em当日无数据"
        else:
            result["research_source"] = "ak.stock_jgdy_tj_em当日无数据"
    except Exception as e:
        logger.warning(f"机构调研获取失败 {code}: {e}")
        result["research_source"] = f"ak.stock_jgdy_tj_em失败:{str(e)[:40]}"

    result["_source"] = f"AkShare资金流+千股千评+沪深港通+机构调研({datetime.now().strftime('%Y-%m-%d')})"
    has_data = any(k in result for k in ["main_net_flow_5d", "main_net_flow", "comprehensive_score"])
    logger.info(f"资金流综合数据获取完成 {code}: keys={list(result.keys())}")
    _api_log("akshare", "fetch_fund_flow", has_data, f"code={code}, has_main_net_flow_5d={'main_net_flow_5d' in result}")
    return result


def fetch_fundamentals(code: str) -> Dict[str, Any]:
    """
    AkShare — 财务指标(ROE/净利润增速/毛利率等)
    返回：{roe, net_profit_yoy, ...}
    """
    import akshare as ak
    
    code_clean = re.sub(r'[^0-9]', '', code)
    
    try:
        fin = ak.stock_financial_analysis_indicator(symbol=code_clean, start_year="2024")
        if fin.empty:
            logger.warning(f"财务数据为空: {code}")
            return {}
        
        latest = fin.iloc[-1]
        
        # 列名处理（含中文括号）
        def get_val(name):
            # 尝试多种列名格式
            for col in fin.columns:
                if name in col:
                    return latest[col]
            return None
        
        roe = get_val("净资产收益率")
        if roe is None or (isinstance(roe, float) and roe != roe):  # NaN
            roe = get_val("加权净资产收益率")
        
        net_profit_yoy = get_val("净利润增长率")
        
        # 兼容处理
        if roe is not None and isinstance(roe, (int, float)):
            roe = float(roe)
            if roe != roe:  # NaN check
                roe = None
        
        if net_profit_yoy is not None and isinstance(net_profit_yoy, (int, float)):
            net_profit_yoy = float(net_profit_yoy)
            if net_profit_yoy != net_profit_yoy:
                net_profit_yoy = None
        
        result = {
            "roe": round(roe, 2) if roe else None,
            "net_profit_yoy": round(net_profit_yoy, 2) if net_profit_yoy else None,
            "gross_margin": get_val("毛利率"),
            "net_margin": get_val("净利率"),
            "asset_liability_ratio": get_val("资产负债率"),
            "eps": get_val("每股收益"),
            "revenue_growth": get_val("主营收入增长率"),
            "_source": f"AkShare财务指标({datetime.now().strftime('%Y-%m-%d')})",
        }
        _api_log("akshare", "fetch_fundamentals", True, f"code={code}, roe={result.get('roe')}")
        return result

    except Exception as e:
        logger.warning(f"财务数据获取失败 {code}: {e}")
        _api_log("akshare", "fetch_fundamentals", False, str(e))
        return {}


def fetch_technical(code: str) -> Dict[str, Any]:
    """
    BaoStock日线 — 技术指标计算(MA/MACD/RSI/布林带)
    返回：{ma_status, macd_status, rsi, volume_status, ...}
    """
    import baostock as bs
    import pandas as pd
    import numpy as np
    
    bs_code = _to_baostock_code(code)
    
    try:
        lg = bs.login()
        if lg.error_code != '0':
            logger.warning(f"BaoStock登录失败: {lg.error_msg}")
            return {"ma_status": "neutral", "macd_status": "neutral", "volume_status": "正常", "rsi": 50}
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,code,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"  # 前复权
        )
        
        df = rs.get_data()
        bs.logout()
        
        if df.empty or len(df) < 20:
            logger.warning(f"技术数据不足({len(df)}行): {code}")
            return {"ma_status": "neutral", "macd_status": "neutral", "volume_status": "正常", "rsi": 50}
        
        # 转换数据类型
        for col in ['close', 'high', 'low', 'open', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 计算均线
        close = df['close'].values
        volume = df['volume'].values
        
        ma5 = np.mean(close[-5:]) if len(close) >= 5 else close[-1]
        ma10 = np.mean(close[-10:]) if len(close) >= 10 else close[-1]
        ma20 = np.mean(close[-20:]) if len(close) >= 20 else close[-1]
        ma60 = np.mean(close[-60:]) if len(close) >= 60 else close[-1]
        
        current_price = close[-1]
        
        # 均线形态判断
        if current_price > ma5 > ma10 > ma20:
            ma_status = "bullish"
        elif current_price < ma5 < ma10 < ma20:
            ma_status = "bearish"
        else:
            ma_status = "neutral"
        
        # 均线具体数值
        ma_detail = {
            "ma5": round(ma5, 2),
            "ma10": round(ma10, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
        }
        
        # MACD计算
        def calc_ema(data, period):
            alpha = 2 / (period + 1)
            ema = [data[0]]
            for i in range(1, len(data)):
                ema.append(alpha * data[i] + (1 - alpha) * ema[-1])
            return np.array(ema)
        
        ema12 = calc_ema(close, 12)
        ema26 = calc_ema(close, 26)
        dif = ema12 - ema26
        dea = calc_ema(dif, 9)
        macd_hist = 2 * (dif - dea)
        
        # MACD状态
        if len(macd_hist) >= 3:
            if macd_hist[-1] > macd_hist[-2] > macd_hist[-3] and dif[-1] > dea[-1]:
                macd_status = "golden"
            elif macd_hist[-1] < macd_hist[-2] < macd_hist[-3] and dif[-1] < dea[-1]:
                macd_status = "death"
            else:
                macd_status = "neutral"
        else:
            macd_status = "neutral"
        
        # RSI(14)
        if len(close) >= 15:
            gains = []
            losses = []
            for i in range(len(close)-14, len(close)):
                delta = close[i] - close[i-1]
                if delta >= 0:
                    gains.append(delta)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(delta))
            avg_gain = np.mean(gains) if gains else 0
            avg_loss = np.mean(losses) if losses else 1
            rs_val = avg_gain / avg_loss if avg_loss > 0 else 100
            rsi = min(100, 100 - (100 / (1 + rs_val)))
        else:
            rsi = 50
        
        # 成交量状态
        if len(volume) >= 10:
            avg_vol_5 = np.mean(volume[-5:])
            avg_vol_10 = np.mean(volume[-10:])
            vol_ratio = avg_vol_5 / avg_vol_10 if avg_vol_10 > 0 else 1
            
            change_pct = (current_price - close[-2]) / close[-2] * 100 if len(close) >= 2 else 0
            
            if vol_ratio > 1.3 and change_pct > 2:
                volume_status = "放量上涨"
            elif vol_ratio > 1.3:
                volume_status = "放量"
            elif vol_ratio < 0.7:
                volume_status = "缩量"
            else:
                volume_status = "正常"
        else:
            volume_status = "正常"
            vol_ratio = 1.0
        
        # 布林带
        if len(close) >= 20:
            bb_mid = ma20
            bb_std = np.std(close[-20:])
            bb_upper = bb_mid + 2 * bb_std
            bb_lower = bb_mid - 2 * bb_std
            bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
        else:
            bb_mid = bb_upper = bb_lower = current_price
            bb_position = 0.5
        
        result = {
            "ma_status": ma_status,
            "macd_status": macd_status,
            "volume_status": volume_status,
            "volume_ratio": round(vol_ratio, 2),
            "rsi": round(rsi, 1),
            "price": round(current_price, 2),
            "change_pct": round((current_price - close[-2]) / close[-2] * 100, 2) if len(close) >= 2 else 0,
            **ma_detail,
            "dif": round(dif[-1], 3),
            "dea": round(dea[-1], 3),
            "macd_hist": round(macd_hist[-1], 3),
            "bb_upper": round(bb_upper, 2),
            "bb_mid": round(bb_mid, 2),
            "bb_lower": round(bb_lower, 2),
            "bb_position": round(bb_position, 2),
            "data_rows": len(df),
            "_source": f"BaoStock日线({datetime.now().strftime('%Y-%m-%d')})",
        }
        _api_log("baostock", "fetch_technical", True, f"code={code}, ma_status={ma_status}")
        return result

    except Exception as e:
        logger.warning(f"技术数据获取失败 {code}: {e}")
        try:
            bs.logout()
        except:
            pass
        _api_log("baostock", "fetch_technical", False, str(e))
        return {"ma_status": "neutral", "macd_status": "neutral", "volume_status": "正常", "rsi": 50}


def fetch_sector_data(code: str) -> Dict[str, Any]:
    """
    AkShare — 板块强度数据
    获取个股所属板块的涨幅排名和资金流
    
    2026-04-26修复：
    - 接口不稳定时确保 sector_count=0 触发评分器的数据缺失检测（降权10分）
    - 接口可用时获取真实板块排名
    """
    import akshare as ak
    import pandas as pd

    code_clean = re.sub(r'[^0-9]', '', code)
    result = {
        "sector_rank": 50,       # 默认中等排名
        "sector_fund_flow": 0,
        "sector_count": 0,       # 明确=0，触发评分器数据缺失检测
        "related_sector": "",
        "_source": "AkShare板块数据",
    }

    try:
        # ── 方案1：东方财富数据中心 RPT_INDUSTRY_LIST（稳定，无需代理）──
        try:
            import requests as _req
            base_url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                "reportName": "RPT_INDUSTRY_LIST",
                "columns": "ALL",
                "pageNumber": 1,
                "pageSize": 500,
                "sortColumns": "CHANGERATE_3M",
                "sortTypes": "-1",
            }
            r = _req.get(base_url, params=params, timeout=10)
            j = r.json()
            if j.get("success") and j.get("result") and j["result"].get("data"):
                sector_data = j["result"]["data"]
                result["sector_count"] = len(sector_data)
                # 按3个月涨跌幅排序
                sorted_sectors = sorted(sector_data, key=lambda x: x.get("CHANGERATE_3M") or 0, reverse=True)
                # 通过关键字匹配个股所属行业
                keywords_sh = ['食品', '饮料', '白酒', '医药', '银行', '保险', '券商', '地产', '汽车', '煤炭', '钢铁', '化工', '电力', '军工']
                keywords_sz = ['创业板', '新能源', '医药', '电子', '软件', '通信', '半导体', '医疗器械']
                keywords = keywords_sh if code_clean.startswith('6') else keywords_sz
                for s in sorted_sectors:
                    board_name = s.get("BOARD_NAME", "")
                    if any(kw in board_name for kw in keywords):
                        result["related_sector"] = board_name
                        # 计算排名
                        for idx, row in enumerate(sorted_sectors):
                            if row.get("BOARD_CODE") == s.get("BOARD_CODE"):
                                result["sector_rank"] = int((1 - idx / len(sorted_sectors)) * 100)
                                break
                        break
                result["_source"] = f"datacenter-web RPT_INDUSTRY_LIST({datetime.now().strftime('%Y-%m-%d')})"
                _api_log("akshare", "fetch_sector_data", True, f"code={code}, sector_count={result['sector_count']}")
                return result
        except Exception as e:
            logger.warning(f"RPT_INDUSTRY_LIST 失败 {code}: {e}")

        # ── 方案2：BaoStock 个股行业分类（备用，无需代理）──
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code == '0':
                rs = bs.query_stock_industry()
                df_ind = rs.get_data()
                bs.logout()
                if not df_ind.empty and "code_name" in df_ind.columns:
                    matched = df_ind[df_ind["code"] == f"sh.{code_clean}" if code_clean.startswith("6") else df_ind["code"] == f"sz.{code_clean}"]
                    if matched.empty:
                        matched = df_ind[df_ind["code"].str.contains(code_clean, na=False)]
                    if not matched.empty:
                        industry = matched.iloc[0].get("industry", "")
                        result["related_sector"] = industry
                        result["sector_rank"] = 50  # BaoStock 只提供行业，不提供排名
                        result["sector_count"] = 1
                        result["_source"] = f"BaoStock query_stock_industry({datetime.now().strftime('%Y-%m-%d')})"
                        _api_log("baostock", "fetch_sector_data", True, f"code={code}, sector={result.get('related_sector')}")
                        return result
        except Exception as e2:
            logger.warning(f"BaoStock 行业备用也失败 {code}: {e2}")

        # ── 方案3：AkShare stock_board_industry_name_em（最后备选，已知网络不稳定）──
        try:
            sector_df = ak.stock_board_industry_name_em()
            if sector_df is not None and not sector_df.empty:
                result["sector_count"] = len(sector_df)
                col_name = None
                for c in ['板块名称', '名称', '行业']:
                    if c in sector_df.columns:
                        col_name = c
                        break
                if col_name is None:
                    col_name = sector_df.columns[0]
                chg_col = None
                for c in ['涨跌幅', '今日涨跌幅', '最新涨跌幅']:
                    if c in sector_df.columns:
                        chg_col = c
                        break
                if chg_col is None and len(sector_df.columns) > 1:
                    chg_col = sector_df.columns[1]
                keywords_sh = ['食品', '饮料', '白酒', '医药', '银行', '保险', '券商', '地产', '汽车', '煤炭', '钢铁', '化工', '电力', '军工']
                keywords_sz = ['创业板', '新能源', '医药', '电子', '软件', '通信', '半导体', '医疗器械']
                keywords = keywords_sh if code_clean.startswith('6') else keywords_sz
                matched = sector_df[sector_df[col_name].str.contains('|'.join(keywords), na=False)]
                if not matched.empty and chg_col:
                    matched = matched.copy()
                    matched['_chg_abs'] = matched[chg_col].abs()
                    top_sector = matched.loc[matched['_chg_abs'].idxmax()]
                    result["related_sector"] = top_sector[col_name]
                    sector_df_sorted = sector_df.copy()
                    sector_df_sorted['_chg_abs'] = sector_df_sorted[chg_col].abs()
                    sector_df_sorted = sector_df_sorted.sort_values('_chg_abs', ascending=False).reset_index(drop=True)
                    rank_pos = sector_df_sorted[sector_df_sorted[col_name] == top_sector[col_name]].index
                    if len(rank_pos) > 0:
                        pos = rank_pos[0]
                        total = len(sector_df_sorted)
                        result["sector_rank"] = int((1 - pos / total) * 100)
                result["_source"] = f"AkShare板块数据({datetime.now().strftime('%Y-%m-%d')})"
                _api_log("akshare", "fetch_sector_data", True, f"code={code}, sector_count={result.get('sector_count', 0)}")
                return result
        except Exception as e3:
            logger.warning(f"AkShare stock_board_industry_name_em 备用也失败 {code}: {e3}")

        # 全部失败，确保 sector_count=0 触发评分器数据缺失检测
        result["sector_count"] = 0
        result["sector_rank"] = 50
        result["_source"] = f"板块数据全失败"
        _api_log("akshare", "fetch_sector_data", False, "all methods failed")
        return result
    except Exception as e_outer:
        logger.warning(f"fetch_sector_data 全局异常 {code}: {e_outer}")
        result["sector_count"] = 0
        result["sector_rank"] = 50
        result["_source"] = f"fetch_sector_data异常:{str(e_outer)[:30]}"
        _api_log("akshare", "fetch_sector_data", False, str(e_outer))
        return result


def fetch_event_data(code: str, name: str = "") -> Dict[str, Any]:
    """
    AkShare — 个股新闻/事件
    简化版：获取近期新闻判断利好/利空
    """
    import akshare as ak
    
    code_clean = re.sub(r'[^0-9]', '', code)
    
    try:
        news = ak.stock_news_em(symbol=code_clean)
        if news.empty:
            return {"positive_events": [], "analyst_rating": "neutral", "report_count_30d": 0,
                    "_source": "东方财富新闻(无数据)"}
        
        # 取最近30条标题，判断利好关键词
        titles = news['新闻标题'].head(30).tolist() if '新闻标题' in news.columns else []
        
        positive_keywords = ['业绩预增', '中标', '利好', '增持', '回购', '突破', '增长',
                            '新高', '政策支持', '降准', '降息', '放量', '签约']
        negative_keywords = ['减持', '利空', '亏损', '下调', '处罚', '立案', '风险',
                            '违约', 'st', '跌停', '崩盘']
        
        positive_count = sum(1 for t in titles if any(kw in t for kw in positive_keywords))
        negative_count = sum(1 for t in titles if any(kw in t for kw in negative_keywords))
        
        positive_events = [t for t in titles[:5] if any(kw in t for kw in positive_keywords)]
        
        # 分析师评级 — 用新闻情绪模拟
        net_sentiment = positive_count - negative_count
        if net_sentiment >= 3:
            analyst_rating = "buy"
        elif net_sentiment >= 0:
            analyst_rating = "neutral"
        else:
            analyst_rating = "sell"
        
        result = {
            "positive_events": positive_events[:5],
            "negative_event_count": negative_count,
            "positive_event_count": positive_count,
            "analyst_rating": analyst_rating,
            "report_count_30d": len(titles),
            "news_count": len(news),
            "_source": f"AkShare东方财富新闻({datetime.now().strftime('%Y-%m-%d')})",
        }
        _api_log("akshare", "fetch_event_data", True, f"code={code}, news_count={len(news)}")
        return result

    except Exception as e:
        logger.warning(f"事件数据获取失败 {code}: {e}")
        _api_log("akshare", "fetch_event_data", False, str(e))
        return {"positive_events": [], "analyst_rating": "neutral", "report_count_30d": 0,
                "_source": "事件数据暂缺"}


# ======================== BaoStock日线估算资金流向 ========================

def estimate_fund_flow_from_kline(code: str, name: str = "", max_days: int = 60) -> Dict[str, Any]:
    """
    用BaoStock日线行情估算资金流向信号（当AkShare资金流向API不可用时的fallback）

    逻辑：
    - 每日资金流估算 = 当日涨跌幅 * 当日成交额（正涨净流入，负涨净流出）
    - 主力净流入比例：使用最近20日的加权平均（越近权重越高）
    - 散户方向与主力反向

    Args:
        code: 股票代码（如 "600519"）
        name: 股票名称（可选，仅用于日志）
        max_days: 获取最多多少个交易日的数据（默认60）

    Returns:
        dict: 与 fetch_fund_flow 相同格式的资金流向数据
    """
    import baostock as bs
    import pandas as pd
    import numpy as np

    bs_code = _to_baostock_code(code)
    logger.info(f"  BaoStock估算资金流向: {name or code} ({bs_code})")

    try:
        lg = bs.login()
        if lg.error_code != '0':
            logger.warning(f"  BaoStock登录失败: {lg.error_msg}")
            return {}

        end_date = datetime.now().strftime('%Y-%m-%d')
        # 取足够多的天数以确保有 max_days 个交易日
        start_date = (datetime.now() - timedelta(days=max_days * 2)).strftime('%Y-%m-%d')

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,code,open,high,low,close,volume,amount,pctChg",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"  # 前复权
        )

        df = rs.get_data()
        bs.logout()

        if df.empty or len(df) < 5:
            logger.warning(f"  BaoStock日线数据不足({len(df)}行): {code}")
            return {}

        # 转换数据类型
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 取最近 max_days 行
        df = df.tail(max_days)
        n = len(df)

        if n < 5:
            logger.warning(f"  BaoStock日线不足5行: {code}")
            return {}

        # 1. 每日资金流估算 = pctChg(%) * amount(元) / 100
        #    正涨幅 → 净流入，负涨幅 → 净流出
        df['est_flow'] = df['pctChg'] * df['amount'] / 100.0

        # 2. 叠加主力比例：用最近20日的加权平均
        #    越近权重越高（线性加权），模拟主力行为占比
        lookback = min(20, n)
        recent_flows = df['est_flow'].values[-lookback:]
        recent_amounts = df['amount'].values[-lookback:]

        # 构造线性权重：最近一天权重最大
        weights = np.arange(1, lookback + 1, dtype=float)
        weights = weights / weights.sum()

        # 加权平均主力比例 = sum(w_i * flow_i / amount_i)
        # 用成交额加权避免零成交额问题
        weighted_ratios = []
        for i in range(lookback):
            if recent_amounts[i] > 0:
                ratio = recent_flows[i] / recent_amounts[i]
            else:
                ratio = 0.0
            weighted_ratios.append(ratio)
        main_factor = np.average(weighted_ratios, weights=weights)
        # 限制在合理范围 [-0.5, 0.5]
        main_factor = max(-0.5, min(0.5, main_factor))

        # 3. 修正后的每日资金流 = 原始估算 * (1 + main_factor 作为主力放大系数)
        #    主力比散户更敏感，对涨跌方向放大幅度
        df['adjusted_flow'] = df['est_flow'] * (1.0 + abs(main_factor))

        # 4. 提取最近5日数据
        daily_flows = df['adjusted_flow'].tail(5).tolist()
        # 处理NaN
        daily_flows = [v if not (isinstance(v, float) and v != v) else 0.0 for v in daily_flows]

        # 补齐到5个
        while len(daily_flows) < 5:
            daily_flows.insert(0, 0.0)

        # 最近5日成交额
        last_5_amounts = df['amount'].tail(5).tolist()
        last_5_amounts = [v if not (isinstance(v, float) and v != v) else 0.0 for v in last_5_amounts]
        sum_amount_5d = sum(last_5_amounts)

        # 主力5日累计净流入
        main_net_flow_5d = sum(daily_flows)

        # 最近一日数据
        latest_flow = daily_flows[-1] if daily_flows else 0.0
        latest_amount = last_5_amounts[-1] if last_5_amounts else 0.0
        latest_main_ratio = latest_flow / latest_amount if latest_amount > 0 else 0.0
        # 限制ratio范围
        latest_main_ratio = max(-0.5, min(0.5, latest_main_ratio))

        # 大单占比 = abs(5日净流) / 5日成交额（上限0.5）
        large_order_ratio = min(0.5, abs(main_net_flow_5d) / sum_amount_5d) if sum_amount_5d > 0 else 0.0

        # 主力方向
        main_direction = "流入" if main_net_flow_5d > 0 else "流出"
        # 散户与主力反向
        retail_direction = "流出" if main_net_flow_5d > 0 else "流入"

        result = {
            "main_net_flow_5d": main_net_flow_5d,
            "daily_flows": daily_flows,
            "latest_main_flow": latest_flow,
            "latest_main_ratio": latest_main_ratio,
            "large_order_ratio": large_order_ratio,
            "super_large_flow": 0.0,  # 无法估算
            "small_order_flow": -latest_flow,  # 散户反向
            "main_direction": main_direction,
            "retail_direction": retail_direction,
            "data_rows": n,
            "est_main_factor": round(main_factor, 4),
            "_source": f"BaoStock日线估算({datetime.now().strftime('%Y-%m-%d')})",
        }
        logger.info(f"  BaoStock估算资金流完成 {code}: main_net_flow_5d={main_net_flow_5d/1e4:.1f}万")
        return result

    except Exception as e:
        logger.warning(f"  BaoStock估算资金流失败 {code}: {e}")
        try:
            bs.logout()
        except:
            pass
        return {}


# ======================== 批量数据获取器 ========================

def query_baostock_daily_batch(codes: List[str], chunk_size: int = 50) -> Dict[str, 'pd.DataFrame']:
    """
    批量查询BaoStock日线数据 — 一次login查所有

    Args:
        codes: 股票代码列表（原始格式如 "600519"）

    Returns:
        Dict[str, pd.DataFrame] — key是股票代码(原始格式)，value是包含原始K线的DataFrame
        不足20行的股票会被跳过
    """
    import baostock as bs
    import pandas as pd
    import numpy as np

    if not codes:
        return {}

    logger.info(f"BaoStock批量查询: {len(codes)}只股票，一次login")
    result = {}

    try:
        lg = bs.login()
        if lg.error_code != '0':
            logger.warning(f"BaoStock登录失败: {lg.error_msg}")
            return {}

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

        for i in range(0, len(codes), chunk_size):
            chunk = codes[i:i + chunk_size]
            for code in chunk:
                bs_code = _to_baostock_code(code)
                try:
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,code,open,high,low,close,volume",
                        start_date=start_date,
                        end_date=end_date,
                        frequency="d",
                        adjustflag="2"  # 前复权
                    )
                    df = rs.get_data()
                    if df.empty or len(df) < 20:
                        logger.debug(f"  BaoStock数据不足({len(df)}行): {code}")
                        continue
                    # 转换数据类型
                    for col in ['close', 'high', 'low', 'open', 'volume']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    result[code] = df
                    logger.debug(f"  BaoStock成功: {code} ({len(df)}行)")
                except Exception as e:
                    logger.warning(f"  BaoStock查询失败 {code}: {e}")
                    continue

        bs.logout()
        logger.info(f"BaoStock批量完成: 成功{len(result)}/{len(codes)}")
        return result

    except Exception as e:
        logger.warning(f"BaoStock批量查询整体失败: {e}")
        try:
            bs.logout()
        except:
            pass
        return {}


def batch_query_financials(codes: List[str], chunk_size: int = None) -> Dict[str, Dict]:
    """
    批量查询AkShare财务指标

    Args:
        codes: 股票代码列表

    Returns:
        Dict[str, dict] — key是股票代码，value是财务数据dict
    """
    try:
        import akshare as ak
    except ImportError:
        logger.warning("AkShare不可用，财务指标查询跳过")
        return {}

    if not codes:
        return {}

    # 从配置加载chunk_size默认值
    if chunk_size is None:
        cfg = get_l2_config()
        chunk_size = cfg.get("batch", {}).get("chunk_financials", 30)

    logger.info(f"批量财务查询: {len(codes)}只")
    result = {}

    for i in range(0, len(codes), chunk_size):
        chunk = codes[i:i + chunk_size]
        for code in chunk:
            code_clean = re.sub(r'[^0-9]', '', code)
            try:
                fin = ak.stock_financial_analysis_indicator(symbol=code_clean, start_year="2024")
                if fin.empty:
                    logger.debug(f"  财务数据为空: {code}")
                    result[code] = {}
                    continue

                latest = fin.iloc[-1]

                def get_val(name):
                    for col in fin.columns:
                        if name in col:
                            return latest[col]
                    return None

                roe = get_val("净资产收益率")
                if roe is None or (isinstance(roe, float) and roe != roe):
                    roe = get_val("加权净资产收益率")

                net_profit_yoy = get_val("净利润增长率")

                if roe is not None and isinstance(roe, (int, float)):
                    roe = float(roe)
                    if roe != roe:
                        roe = None

                if net_profit_yoy is not None and isinstance(net_profit_yoy, (int, float)):
                    net_profit_yoy = float(net_profit_yoy)
                    if net_profit_yoy != net_profit_yoy:
                        net_profit_yoy = None

                result[code] = {
                    "roe": round(roe, 2) if roe else None,
                    "net_profit_yoy": round(net_profit_yoy, 2) if net_profit_yoy else None,
                    "gross_margin": get_val("毛利率"),
                    "net_margin": get_val("净利率"),
                    "asset_liability_ratio": get_val("资产负债率"),
                    "eps": get_val("每股收益"),
                    "revenue_growth": get_val("主营收入增长率"),
                    "_source": f"AkShare财务指标({datetime.now().strftime('%Y-%m-%d')})",
                }
                logger.debug(f"  财务成功: {code}")
            except Exception as e:
                logger.warning(f"  财务查询失败 {code}: {e}")
                result[code] = {}

            time.sleep(0.3)  # 避免限速

    logger.info(f"批量财务完成: 成功{sum(1 for v in result.values() if v)}/{len(codes)}")
    return result


def batch_query_qq_realtime(codes_batch: List[str]) -> Dict[str, Dict]:
    """
    批量查询腾讯行情 — 30只/批，利用逗号分隔多码特性

    Args:
        codes_batch: 股票代码列表（原始格式）

    Returns:
        Dict[str, dict] — key是股票代码(原始格式)，value是解析后的行情dict
    """
    if not codes_batch:
        return {}

    logger.info(f"腾讯批量行情: {len(codes_batch)}只")

    # 按30只一批分组
    batch_size = 30
    all_results = {}

    for batch_start in range(0, len(codes_batch), batch_size):
        batch_codes = codes_batch[batch_start:batch_start + batch_size]
        qq_codes = [_to_qq_code(c) for c in batch_codes]
        url = f"http://qt.gtimg.cn/q={','.join(qq_codes)}"

        try:
            r = subprocess.run(
                ['curl', '-s', '--max-time', '5', '-A', 'Mozilla/5.0', url],
                capture_output=True, timeout=10
            )
            raw = r.stdout.decode('gbk', errors='replace')

            # 腾讯返回格式：每只股票一行 v_sh600519="..."; 或多行拼接
            # 按 ";" 分割行
            lines = raw.strip().split(';')
            for line in lines:
                if not line.strip():
                    continue
                match = re.search(r'\"([^\"]+)\"', line)
                if not match:
                    continue

                parts = match.group(1).split('~')
                if len(parts) < 50:
                    continue

                raw_code = parts[QQ_PARTS["code"]] if QQ_PARTS["code"] < len(parts) else ""
                # 把 sh600519 → 600519 等
                original_code = re.sub(r'^(sh|sz|hk)', '', raw_code)

                def safe_float(idx, default=None):
                    val = parts[idx] if idx < len(parts) else '-'
                    if val and val != '-':
                        try:
                            return float(val)
                        except ValueError:
                            return default
                    return default

                def safe_int(idx, default=0):
                    val = parts[idx] if idx < len(parts) else '-'
                    if val and val != '-':
                        try:
                            return int(float(val))
                        except ValueError:
                            return default
                    return default

                price = safe_float(QQ_PARTS["price"])
                prev_close = safe_float(QQ_PARTS["prev_close"])
                change_pct = round((price - prev_close) / prev_close * 100, 2) if (price and prev_close and prev_close > 0) else 0

                outer = safe_int(QQ_PARTS["outer_disk"])
                inner = safe_int(QQ_PARTS["inner_disk"])
                outer_inner_ratio = round(outer / inner, 2) if inner > 0 else 1.0

                all_results[original_code] = {
                    "price": price,
                    "prev_close": prev_close,
                    "change_pct": change_pct,
                    "open": safe_float(QQ_PARTS["open"]),
                    "high": safe_float(QQ_PARTS["high"]),
                    "low": safe_float(QQ_PARTS["low"]),
                    "volume": safe_int(QQ_PARTS["volume"]),
                    "amount": safe_float(QQ_PARTS["amount"]),
                    "pe": safe_float(QQ_PARTS["pe"]),
                    "pb": safe_float(QQ_PARTS["pb"]),
                    "market_cap": safe_float(QQ_PARTS["market_cap"]),
                    "circulating_cap": safe_float(QQ_PARTS["circulating_cap"]),
                    "turnover": safe_float(QQ_PARTS["turnover"]),
                    "amplitude": safe_float(QQ_PARTS["amplitude"]),
                    "week52_high": safe_float(QQ_PARTS["week52_high"]),
                    "week52_low": safe_float(QQ_PARTS["week52_low"]),
                    "outer_disk": outer,
                    "inner_disk": inner,
                    "outer_inner_ratio": outer_inner_ratio,
                    "name": parts[QQ_PARTS["name"]] if QQ_PARTS["name"] < len(parts) else raw_code,
                    "_source": f"腾讯行情API({datetime.now().strftime('%H:%M')})",
                    "_raw_fields": len(parts),
                }
        except Exception as e:
            logger.warning(f"腾讯批量行情失败 (批次{batch_start//batch_size}): {e}")

    logger.info(f"腾讯批量完成: 成功{len(all_results)}/{len(codes_batch)}")
    return all_results


# ======================== 东方财富资金流向（直连API，绕过AkShare） ========================

def _get_eastmoney_config() -> dict:
    cfg = get_l2_config()
    api_cfg = cfg.get("api", {})
    return {
        "fund_flow_url": api_cfg.get("eastmoney_fund_flow_url",
            "https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"),
    }

_EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
}


def _to_eastmoney_secid(code: str) -> str:
    """
    转换为东方财富secid格式。
    sh.600519 → 1.600519
    sz.000333 → 0.000333
    bj.830799 → 0.830799
    6xx/8xx → 1.xxx  (上交所)
    0xx/3xx → 0.xxx  (深交所)
    """
    c = code.strip()
    if '.' in c:
        market_char, digits = c.split('.', 1)
        market_char = market_char.lower()
    elif c.startswith('sh'):
        market_char, digits = 'sh', c[2:]
    elif c.startswith('sz'):
        market_char, digits = 'sz', c[2:]
    elif c.startswith('bj'):
        market_char, digits = 'bj', c[2:]
    else:
        digits = re.sub(r'[^0-9]', '', c)
        if digits.startswith(('6', '8')):
            market_char = 'sh'
        else:
            market_char = 'sz'

    market_num = '1' if market_char == 'sh' else '0'
    return f"{market_num}.{digits}"


def _fetch_single_fund_flow_eastmoney(code: str) -> dict:
    """
    直连东方财富push2 API获取个股资金流向。
    返回结构同 batch_query_fund_flow 约定。
    失败返回 None。
    """
    import requests as _req

    em_cfg = _get_eastmoney_config()
    secid = _to_eastmoney_secid(code)
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": "101",   # 日k线
        "lmt": "10",    # 最近10个交易日
    }
    try:
        resp = _req.get(em_cfg["fund_flow_url"], params=params,
                        headers=_EASTMONEY_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug(f"  [EM资金流] 请求失败 {code}: {e}")
        return None

    if not data or data.get("rc", 1) != 0:
        logger.debug(f"  [EM资金流] 响应异常 {code}: rc={data.get('rc', 'N/A')}")
        return None

    klines = (data.get("data") or {}).get("klines") or []
    if not klines:
        logger.debug(f"  [EM资金流] 无kline数据 {code}")
        return None

    # 解析kline行: 日期,主力净流入,小单净流入,中单净流入,大单净流入,超大单净流入
    daily_entries = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 6:
            daily_entries.append({
                "date": parts[0],
                "main_net": float(parts[1]) if parts[1] else 0,
                "small_net": float(parts[2]) if parts[2] else 0,
                "mid_net": float(parts[3]) if parts[3] else 0,
                "large_net": float(parts[4]) if parts[4] else 0,
                "super_large_net": float(parts[5]) if parts[5] else 0,
            })

    if not daily_entries:
        logger.debug(f"  [EM资金流] 解析后无数据 {code}")
        return None

    latest = daily_entries[-1]
    daily_flows = [e["main_net"] for e in daily_entries]
    main_net_flow_5d = sum(daily_flows[-5:]) if len(daily_flows) >= 5 else sum(daily_flows)

    # 计算主力累计方向
    recent_main = daily_flows[-5:] if len(daily_flows) >= 5 else daily_flows
    main_direction = "流入" if sum(recent_main) >= 0 else "流出"
    retail_direction = "流入" if latest["small_net"] >= 0 else "流出"

    # 大单占比 = 大单净流入 / (大单+小单绝对值)
    total_abs = abs(latest["large_net"]) + abs(latest["small_net"])
    large_ratio = abs(latest["large_net"]) / total_abs if total_abs > 0 else 0

    result = {
        "main_net_flow_5d": main_net_flow_5d,
        "daily_flows": daily_flows,
        "latest_main_flow": latest["main_net"],
        "latest_main_ratio": large_ratio,
        "large_order_ratio": large_ratio,
        "super_large_flow": latest["super_large_net"],
        "small_order_flow": latest["small_net"],
        "main_direction": main_direction,
        "retail_direction": retail_direction,
        "data_rows": len(daily_entries),
        "_source": f"东方财富资金流向直连API({datetime.now().strftime('%Y-%m-%d')})",
    }

    # ── 补充沪深港通北向持股（EM接口不含此数据，需单独补）──────
    try:
        import pandas as _pd
        import akshare as _ak
        code_clean = code.lstrip("shszSHZS")
        df_hsgt = _ak.stock_hsgt_individual_em(symbol=code_clean)
        if df_hsgt is not None and not df_hsgt.empty:
            latest_hsgt = df_hsgt.iloc[-1]
            result["hsgt_hold_ratio"] = float(latest_hsgt['持股数量占A股百分比']) / 100 if _pd.notna(latest_hsgt.get('持股数量占A股百分比')) else None
            result["hsgt_add_shares"] = float(latest_hsgt['今日增持股数']) if _pd.notna(latest_hsgt.get('今日增持股数')) else None
            result["hsgt_add_ratio"] = float(latest_hsgt.get('增持占A股百分比', 0)) / 100 if _pd.notna(latest_hsgt.get('增持占A股百分比')) else None
            logger.debug(f"  [沪深港通] {code} 北向持股: {result['hsgt_hold_ratio']}")
    except Exception as _e:
        logger.debug(f"  [沪深港通] 补充失败 {code}: {_e}")

    logger.debug(f"  [EM资金流] 成功 {code} {name} 5日净:{main_net_flow_5d/1e4:.0f}万 方向:{main_direction}")
    return result


def batch_query_fund_flow(codes_names: Dict[str, str], chunk_size: int = None) -> Dict[str, dict]:
    """
    批量查询资金流向 — 直接调用东方财富push2 API（主通道）。
    fallback: BaoStock日线估算（备用通道）。

    Args:
        codes_names: {code: name, ...} 股票代码及名称

    Returns:
        Dict[str, dict]
    """
    if not codes_names:
        return {}

    # 从配置加载chunk_size默认值
    if chunk_size is None:
        cfg = get_l2_config()
        chunk_size = cfg.get("batch", {}).get("chunk_fund_flow", 50)

    codes_list = list(codes_names.keys())

    import random

    logger.info(f"批量资金流向: {len(codes_names)}只 (东方财富直连API, 串行)")

    result = {}

    # 串行抓取：逐只查询东方财富 API，每只间隔0.3-0.6s防限流
    for idx, code in enumerate(codes_list):
        name = codes_names[code]
        time.sleep(random.uniform(0.3, 0.6))  # 控制请求频率
        fd = _fetch_single_fund_flow_eastmoney(code)
        result[code] = fd if fd else {}
        # 每20只打一次进度日志
        if (idx + 1) % 20 == 0:
            logger.info(f"  资金流向进度: {idx+1}/{len(codes_list)}")

    # ---- Fallback: 对失败/空的股票使用BaoStock日线估算 ----
    remaining = {c: n for c, n in codes_names.items()
                 if c not in result or not result.get(c)}
    if remaining:
        logger.info(f"转为BaoStock日线估算: {len(remaining)}只")
        for code, name in remaining.items():
            try:
                est = estimate_fund_flow_from_kline(code, name)
                if est:
                    est["_source"] = f"BaoStock日线估算({datetime.now().strftime('%Y-%m-%d')})"
                    result[code] = est
                else:
                    # 严禁兜底假数据
                    result[code] = {}
                    logger.warning(f"  BaoStock估算也无法获取 {code}，标记为资金流向缺失")
            except Exception as e2:
                logger.warning(f"  BaoStock估算也失败 {code}: {e2}")
                result[code] = {}  # 标记缺失

    ok_count = sum(1 for v in result.values()
                   if v.get("_source", "").startswith(("东方财富", "BaoStock")))
    logger.info(f"批量资金流向完成: 成功{ok_count}/{len(codes_names)}")
    return result


def batch_query_events(codes_names: Dict[str, str], chunk_size: int = None) -> Dict[str, Dict]:
    """
    批量查询事件数据 — 逐个查，带全局超时预算 + fail-fast + per-item 3秒超时。

    全局超时预算20秒（接在板块查询之后），超时后剩余跳过。
    连续5次失败也触发fail-fast。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.warning("AkShare不可用，事件查询跳过")
        return {}

    if not codes_names:
        return {}

    # ── 全局超时预算 + fail-fast 参数（从配置加载）─────────────────────────
    cfg = get_l2_config()
    budget_cfg = cfg.get("budget", {})
    MAX_BUDGET_SEC = budget_cfg.get("events_max_budget_sec", 20)
    MAX_CONSEC_FAIL = budget_cfg.get("events_max_consec_fail", 5)
    ITEM_TIMEOUT_SEC = budget_cfg.get("events_item_timeout_sec", 3)
    # 从配置加载chunk_size默认值
    if chunk_size is None:
        chunk_size = cfg.get("batch", {}).get("chunk_events", 30)
    budget_start = time.time()

    codes_list = list(codes_names.keys())
    logger.info(f"批量事件查询: {len(codes_names)}只分{(len(codes_list)+chunk_size-1)//chunk_size}批 (chunk_size={chunk_size})")

    result = {}
    consec_fail = 0

    def _fetch_news_with_timeout(code_clean: str) -> Dict:
        """用threading实现per-item超时"""
        import threading
        result_holder = [None]   # mutable container

        def _worker():
            try:
                news = ak.stock_news_em(symbol=code_clean)
                result_holder[0] = news
            except Exception:
                result_holder[0] = None

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=ITEM_TIMEOUT_SEC)
        if t.is_alive():
            # 超时，thread结束（但worker可能还在跑，不阻塞主进程）
            return None
        return result_holder[0]

    for i in range(0, len(codes_list), chunk_size):
        chunk_keys = codes_list[i:i + chunk_size]
        for code, name in [(c, codes_names[c]) for c in chunk_keys]:
            # ── 全局超时检查 ──────────────────────────────────────
            elapsed = time.time() - budget_start
            if elapsed >= MAX_BUDGET_SEC:
                remaining = len(codes_names) - len(result)
                logger.warning(f"事件查询已达{MAX_BUDGET_SEC}s预算，剩余{remaining}只标记中性数据")
                break

            code_clean = re.sub(r'[^0-9]', '', code)
            try:
                news = _fetch_news_with_timeout(code_clean)

                if news is None:
                    raise RuntimeError(f"新闻API超时({ITEM_TIMEOUT_SEC}s)")

                if news.empty:
                    result[code] = {
                        "positive_events": [], "analyst_rating": "neutral",
                        "report_count_30d": 0,
                        "_source": "东方财富新闻(无数据)"
                    }
                else:
                    titles = news['新闻标题'].head(30).tolist() if '新闻标题' in news.columns else []

                    positive_keywords = ['业绩预增', '中标', '利好', '增持', '回购', '突破', '增长',
                                         '新高', '政策支持', '降准', '降息', '放量', '签约']
                    negative_keywords = ['减持', '利空', '亏损', '下调', '处罚', '立案', '风险',
                                         '违约', 'st', '跌停', '崩盘']

                    positive_count = sum(1 for t in titles if any(kw in t for kw in positive_keywords))
                    negative_count = sum(1 for t in titles if any(kw in t for kw in negative_keywords))
                    positive_events = [t for t in titles[:5] if any(kw in t for kw in positive_keywords)]

                    net_sentiment = positive_count - negative_count
                    if net_sentiment >= 3:
                        analyst_rating = "buy"
                    elif net_sentiment >= 0:
                        analyst_rating = "neutral"
                    else:
                        analyst_rating = "sell"

                    result[code] = {
                        "positive_events": positive_events[:5],
                        "negative_event_count": negative_count,
                        "positive_event_count": positive_count,
                        "analyst_rating": analyst_rating,
                        "report_count_30d": len(titles),
                        "news_count": len(news),
                        "_source": f"AkShare东方财富新闻({datetime.now().strftime('%Y-%m-%d')})",
                    }
                consec_fail = 0

            except Exception as e:
                logger.warning(f"  事件查询失败 {code}: {e}")
                result[code] = {"positive_events": [], "analyst_rating": "neutral",
                                "report_count_30d": 0, "_source": "事件数据暂缺"}
                consec_fail += 1

            if consec_fail >= MAX_CONSEC_FAIL:
                remaining = len(codes_names) - len(result)
                logger.warning(f"连续{consec_fail}次失败，触发fail-fast，剩余{remaining}只跳过")
                break

            time.sleep(0.05)

    # ── 补齐未完成的 ──────────────────────────────────────────
    for code in codes_names:
        if code not in result:
            result[code] = {"positive_events": [], "analyst_rating": "neutral",
                            "report_count_30d": 0, "_source": "事件数据超时/跳过"}

    elapsed_total = time.time() - budget_start
    ok = sum(1 for v in result.values() if v.get("_source", "").startswith("AkShare"))
    logger.info(f"批量事件完成: {ok}/{len(codes_names)}只，耗时{elapsed_total:.1f}s")
    return result


def batch_query_sector(codes: List[str], chunk_size: int = None) -> Dict[str, Dict]:
    """
    批量查询板块数据 — 预拉板块表 + 逐个匹配，带全局超时预算 + fail-fast。

    全局超时预算30秒，超时后剩余股票跳过（返回中性数据）。
    连续5次失败也触发fail-fast。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.warning("AkShare不可用，板块查询跳过")
        return {}
    import pandas as pd

    if not codes:
        return {}

    # ── 全局超时预算 + fail-fast 参数（从配置加载）─────────────────────────
    cfg = get_l2_config()
    budget_cfg = cfg.get("budget", {})
    MAX_BUDGET_SEC = budget_cfg.get("sector_max_budget_sec", 30)
    MAX_CONSEC_FAIL = budget_cfg.get("sector_max_consec_fail", 5)
    # 从配置加载chunk_size默认值
    if chunk_size is None:
        chunk_size = cfg.get("batch", {}).get("chunk_sector", 50)
    budget_start = time.time()

    logger.info(f"批量板块查询: {len(codes)}只（预算{MAX_BUDGET_SEC}s）")

    # ── 预拉板块数据（整个函数只拉一次，支持AkShare+腾讯双备源）──
    sector_df = None
    sector_source = "板块数据暂缺"

    # 首选：AkShare东方财富
    try:
        sector_df = ak.stock_board_industry_name_em()
        if sector_df is not None and not sector_df.empty:
            sector_source = f"AkShare东方财富({datetime.now().strftime('%Y-%m-%d')})"
    except Exception as e:
        logger.warning(f"板块表预拉失败(AkShare): {e}，尝试腾讯备源")

    # 备选：腾讯API行业数据
    if sector_df is None or sector_df.empty:
        try:
            import subprocess, shlex, json as _json
            # 腾讯行情接口，支持获取行业板块行情
            url = "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14,f3,f4,f8"
            cmd = f'curl -s --max-time 8 -A "Mozilla/5.0" {shlex.quote(url)}'
            r = subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
            raw = r.stdout.decode('utf-8', errors='replace')
            data = _json.loads(raw)
            rows = data.get("data", {}).get("diff", [])
            if rows:
                import pandas as pd
                sector_df = pd.DataFrame([{"板块名称": r.get("f14", ""), "涨跌幅": r.get("f3", 0)} for r in rows])
                sector_df["涨跌幅"] = pd.to_numeric(sector_df["涨跌幅"], errors="coerce").fillna(0)
                sector_source = f"腾讯东方财富备源({datetime.now().strftime('%Y-%m-%d')})"
                logger.info(f"腾讯备源板块获取成功: {len(sector_df)}条")
        except Exception as e:
            logger.warning(f"板块表预拉失败(腾讯备源): {e}")

    # 第三备源：BaoStock行业分类（独立域名，不依赖push2.eastmoney.com）
    if sector_df is None or sector_df.empty:
        try:
            import baostock as bs
            lg = bs.login()
            rs = bs.query_stock_industry()
            bs_data = []
            while rs.error_code == '0' and rs.next():
                bs_data.append(rs.get_row_data())
            bs.logout()
            if bs_data:
                _pd = pd
                sector_df = _pd.DataFrame(bs_data, columns=rs.fields)
                # BaoStock行业分类只有industry_code(如J66)和industry_name(如J66货币金融服务)
                # 需要构造一个"板块名称"列用于匹配（取行业名称前缀）
                sector_df = sector_df.rename(columns={'industry': 'industry_code', 'industryClassification': 'industry_name'})
                # 匹配：只做板块存在性校验，不做细粒度排名（sector_rank维持中性50）
                sector_source = f"BaoStock行业分类({datetime.now().strftime('%Y-%m-%d')})"
                logger.info(f"BaoStock备源板块获取成功: {len(sector_df)}条")
        except Exception as e:
            logger.warning(f"板块表预拉失败(BaoStock备源): {e}")

    if sector_df is None or sector_df.empty:
        logger.warning("板块数据全部获取失败，全部返回中性数据")
        return {code: {"sector_rank": 50, "sector_fund_flow": 0,
                       "_source": "板块数据暂缺"} for code in codes}

    result = {}
    consec_fail = 0

    for i in range(0, len(codes), chunk_size):
        chunk = codes[i:i + chunk_size]
        for code in chunk:
            # ── 全局超时检查 ──────────────────────────────────────
            elapsed = time.time() - budget_start
            if elapsed >= MAX_BUDGET_SEC:
                remaining = len(codes) - len(result)
                logger.warning(f"板块查询已达{MAX_BUDGET_SEC}s预算，剩余{remaining}只标记中性数据")
                break

            code_clean = re.sub(r'[^0-9]', '', code)
            try:
                base = {
                    "sector_rank": 50,
                    "sector_fund_flow": 0,
                    "sector_count": len(sector_df) if sector_df is not None else 0,
                    "_source": sector_source,
                }
                if sector_df is not None and not sector_df.empty:
                    # 根据可用列选择匹配方式
                    if '板块名称' in sector_df.columns:
                        # AkShare/腾讯格式：按板块名称关键词匹配
                        if code_clean.startswith('6'):
                            sh = sector_df[sector_df['板块名称'].str.contains(
                                '食品|饮料|白酒|金融|银行|医药', na=False)]
                            if not sh.empty:
                                base["sector_rank"] = 60
                                base["related_sector"] = sh.iloc[0].get('板块名称', '')
                    elif 'industry_code' in sector_df.columns:
                        # BaoStock格式：直接取该股票的行业分类（存在即证明有数据，不做细粒度排名）
                        matched = sector_df[sector_df['code'].str.contains(code_clean, na=False)]
                        if not matched.empty:
                            base["sector_rank"] = 55  # 有行业数据，非中性
                            base["related_sector"] = matched.iloc[0].get('industry_code', '')
                result[code] = base
                consec_fail = 0
            except Exception as e:
                logger.warning(f"板块查询失败 {code}: {e}")
                result[code] = {"sector_rank": 50, "sector_fund_flow": 0,
                                "_source": "板块数据暂缺"}
                consec_fail += 1

            if consec_fail >= MAX_CONSEC_FAIL:
                remaining = len(codes) - len(result)
                logger.warning(f"连续{consec_fail}次失败，触发fail-fast，剩余{remaining}只跳过")
                break

            time.sleep(0.05)   # 小间隔防限速

    # ── 补齐未完成的股票（超时/fail-fast 时）───────────────────
    for code in codes:
        if code not in result:
            result[code] = {"sector_rank": 50, "sector_fund_flow": 0,
                           "_source": "板块数据超时/跳过"}

    elapsed_total = time.time() - budget_start
    logger.info(f"批量板块完成: {len(result)}/{len(codes)}只，耗时{elapsed_total:.1f}s")
    return result


# ======================== 主获取器 ========================

def fetch_all(code: str, name: str = "") -> Dict[str, Any]:
    """
    获取所有五维评分所需数据
    
    Args:
        code: 股票代码（如 "600519", "sz000858"）
        name: 股票名称（可选）
    
    Returns:
        data dict: {
            "moneyflow_data": {...},
            "technical_data": {...},
            "fundamental_data": {...},
            "sector_data": {...},
            "event_data": {...},
        }
    """
    start_time = time.time()
    
    # 并行获取（串行调用，避免BaoStock多线程问题）
    logger.info(f"开始获取数据: {name or code} ({code})")
    
    # 1. 腾讯行情（最稳定，最先获取）
    qq_data = fetch_qq_realtime(code)
    logger.info(f"  腾讯行情: {'✅' if qq_data else '❌'}")
    
    # 2. 资金流向（核心数据）
    fund_data = fetch_fund_flow(code)
    # fallback条件：AkShare全市场排名 和 EM直连API 均无5日净额数据
    has_5d_flow = fund_data.get("main_net_flow_5d") is not None
    has_single_flow = fund_data.get("main_net_flow") is not None
    needs_estimate = not has_5d_flow and not has_single_flow
    if needs_estimate:
        logger.info(f"  资金流API全失败(无5日净额也无单日净额)，尝试BaoStock日线估算...")
        fund_data = estimate_fund_flow_from_kline(code, name)
    elif has_5d_flow:
        logger.info(f"  资金流向: ✅ EM直连5日净额={fund_data.get('main_net_flow_5d')/1e8:.2f}亿")
    elif has_single_flow:
        logger.info(f"  资金流向: ✅ AkShare全市场排名单日净额={fund_data.get('main_net_flow')/1e8:.2f}亿")
    
    # 3. 技术面（BAoStock日线）
    tech_data = fetch_technical(code)
    logger.info(f"  技术面: {'✅' if tech_data else '❌'}")
    
    # 4. 财务指标
    fin_data = fetch_fundamentals(code)
    logger.info(f"  基本面: {'✅' if fin_data else '❌'}")
    
    # 5. 板块
    sector_data = fetch_sector_data(code)
    logger.info(f"  板块: {'✅' if sector_data else '❌'}")
    
    # 6. 事件
    event_data = fetch_event_data(code, name)
    logger.info(f"  事件: {'✅' if event_data else '❌'}")
    
    # 组合数据字典
    result = {}
    
    # --- 资金面数据 ---
    moneyflow = {
        "main_net_flow_5d": fund_data.get("main_net_flow_5d", 0),
        "large_order_ratio": fund_data.get("large_order_ratio", 0),
        "main_direction": fund_data.get("main_direction", "未知"),
        "retail_direction": fund_data.get("retail_direction", "未知"),
        "daily_flows": fund_data.get("daily_flows", []),
        "latest_main_flow": fund_data.get("latest_main_flow", 0),
        "latest_main_ratio": fund_data.get("latest_main_ratio", 0),
        "super_large_flow": fund_data.get("super_large_flow", 0),
        "small_order_flow": fund_data.get("small_order_flow", 0),
        "_source": fund_data.get("_source", "数据暂缺"),
    }
    
    # 补充腾讯行情的外内盘比和单日净流入估算
    # 注：评分器访问 outer_inner_ratio（无前缀），此处同时写入两个字段名以兼容
    if qq_data:
        _qq_ratio = qq_data.get("outer_inner_ratio", 1.0)
        _qq_outer = qq_data.get("outer_disk", 0) or 0
        _qq_inner = qq_data.get("inner_disk", 0) or 0
        _qq_price = qq_data.get("price", 0) or 0

        moneyflow["qq_outer_inner_ratio"] = _qq_ratio  # 保留原名（辩论引擎用）
        moneyflow["outer_inner_ratio"] = _qq_ratio     # 评分器期望的字段名（P2.2修复）
        moneyflow["qq_outer_disk"] = _qq_outer
        moneyflow["qq_inner_disk"] = _qq_inner

        # P3修复：腾讯外内盘估算单日净流入（元）= (外盘-内盘)×100×价格
        if _qq_outer and _qq_inner and _qq_price:
            moneyflow["net_flow_1d_yuan"] = int((_qq_outer - _qq_inner) * 100 * _qq_price)
        else:
            moneyflow["net_flow_1d_yuan"] = 0
    
    result["moneyflow_data"] = moneyflow
    
    # --- 技术面数据 ---
    result["technical_data"] = {
        "ma_status": tech_data.get("ma_status", "neutral"),
        "macd_status": tech_data.get("macd_status", "neutral"),
        "volume_status": tech_data.get("volume_status", "正常"),
        "rsi": tech_data.get("rsi", 50),
        "volume_ratio": tech_data.get("volume_ratio", 1.0),
        "price": qq_data.get("price", tech_data.get("price", 0)),
        "change_pct": qq_data.get("change_pct", tech_data.get("change_pct", 0)),
        **({k: tech_data[k] for k in ["ma5","ma10","ma20","ma60","dif","dea","macd_hist","bb_upper","bb_mid","bb_lower","bb_position"] if k in tech_data}),
        "_source": tech_data.get("_source", "数据获取失败"),
    }
    
    # 补充腾讯行情价格
    if qq_data and qq_data.get("price"):
        result["technical_data"]["price"] = qq_data["price"]
    
    # --- 基本面数据 ---
    pb_from_qq = qq_data.get("pb")
    pe_from_qq = qq_data.get("pe")

    # 补充沪深港通北向持股数据（A股机构持仓的重要指标）
    # fetch_fund_flow 已获取 hsgt_* 字段，这里映射到 inst_ownership_pct 兼容字段
    # 兼容评分器字段名：L2采集的净利润增长率 → 映射为评分器期望的 eps_growth_yoy
    # 注：两者都是增速指标，可互换使用（A股财务表中 EPS增速 字段有时缺失，净利润增速更稳定）
    _net_profit = fin_data.get("net_profit_yoy")
    result["fundamental_data"] = {
        "roe": fin_data.get("roe"),
        "net_profit_yoy": _net_profit,  # 保留原名（辩论引擎使用）
        "eps_growth_yoy": _net_profit,  # 映射到评分器期望的字段名（P1.1修复）
        "pb": pb_from_qq if (pb_from_qq and pb_from_qq > 0) else None,
        "pe": pe_from_qq if (pe_from_qq and pe_from_qq > 0) else None,
        "gross_margin": fin_data.get("gross_margin"),
        "net_margin": fin_data.get("net_margin"),
        "asset_liability_ratio": fin_data.get("asset_liability_ratio"),  # 保留原名（百分比）
        # P1.2修复：评分器debt_eq阈值是0-1范围，AkShare返回的是百分比（>1），需转换
        "debt_eq": (lambda v: v / 100 if v is not None and v > 1 else v)(fin_data.get("asset_liability_ratio")),
        "eps": fin_data.get("eps"),
        "revenue_growth": fin_data.get("revenue_growth"),
        # A股机构持仓兼容字段：hsgt_hold_ratio → inst_ownership_pct
        "inst_ownership_pct": fund_data.get("hsgt_hold_ratio"),   # 北向持股比例（兼容scorer字段名）
        "inst_trans": fund_data.get("hsgt_add_ratio"),            # 北向增持比例
        "_source": (fin_data.get("_source") or "") + " + " + (qq_data.get("_source") or ""),
    }

    # --- 板块数据 ---
    result["sector_data"] = sector_data
    
    # --- 事件数据 ---
    result["event_data"] = event_data
    
    elapsed = (time.time() - start_time) * 1000
    logger.info(f"数据获取完成 {name or code}: {elapsed:.0f}ms")
    
    return result


def fetch_batch(stocks: List[Dict[str, str]], max_stocks: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    批量获取数据 — 使用batch函数高效获取

    Args:
        stocks: [{"code": "600519", "name": "茅台"}, ...]
        max_stocks: 可选，最多只取前N只股票（超时保护）

    Returns:
        [{"code": ..., "name": ..., "data": {...}}, ...]
    """
    start_time = time.time()
    results = []
    total = len(stocks)

    if not stocks:
        return results

    # 超时保护：限制股票数量
    if max_stocks is not None and total > max_stocks:
        logger.warning(f"超过max_stocks={max_stocks}, 只取前{max_stocks}只 (共{total}只)")
        stocks = stocks[:max_stocks]
        total = len(stocks)

    # 预估耗时（资金流向API是瓶颈）
    if total > 30:
        est_seconds = total * 3.5
        logger.info(f"预计总耗时约{est_seconds:.0f}秒（资金流向API限速）")

    codes = [s.get("code", "") for s in stocks]
    names = {s.get("code", ""): s.get("name", "") for s in stocks}

    logger.info(f"===== 批量获取 {total} 只股票 =====")

    # ---- 1. 腾讯行情（最快，批量30只/次） ----
    logger.info("[1/5] 腾讯批量行情...")
    qq_results = batch_query_qq_realtime(codes)

    # ---- 2. BaoStock（一次login查所有） ----
    logger.info("[2/5] BaoStock日线批量查询...")
    baostock_raw = query_baostock_daily_batch(codes)

    # ---- 3. 资金流向 ----
    logger.info("[3/5] 资金流向批量查询...")
    fund_results = batch_query_fund_flow(names)

    # ---- 4. 财务指标 ----
    logger.info("[4/5] 财务指标批量查询...")
    fin_results = batch_query_financials(codes)

    # ---- 5. 板块 + 事件 ----
    logger.info("[5/5] 板块+事件批量查询...")
    sector_results = batch_query_sector(codes)
    event_results = batch_query_events(names)

    # ---- 组装 ----
    logger.info("组装结果...")
    for code, name in zip(codes, [s.get("name", "") for s in stocks]):
        # batch_query_qq_realtime 返回的key无前缀（sh600320→600320），其他batch函数用有前缀
        qq_code_lookup = code.lstrip('shszSHZS')
        qq_data = qq_results.get(qq_code_lookup, {})
        fund_data = fund_results.get(code, {})
        fin_data = fin_results.get(code, {})
        sector_data_dict = sector_results.get(code, {})
        event_data_dict = event_results.get(code, {})

        # ── 补充沪深港通数据（EM接口失败或无hsgt时均尝试补充）─────────
        hsgt_failed = False
        if not fund_data.get("hsgt_hold_ratio"):
            try:
                import akshare as ak
                import pandas as pd
                code_clean = code.lstrip("shszSHZS")
                hk_market = '沪股通' if code_clean.startswith('6') else '深股通'
                df_hsgt = ak.stock_hsgt_individual_em(symbol=code_clean)
                if df_hsgt is not None and not df_hsgt.empty:
                    latest = df_hsgt.iloc[-1]
                    fund_data.setdefault("hsgt_hold_ratio", float(latest['持股数量占A股百分比']) / 100 if pd.notna(latest.get('持股数量占A股百分比')) else None)
                    fund_data.setdefault("hsgt_add_shares", float(latest['今日增持股数']) if pd.notna(latest.get('今日增持股数')) else None)
                    fund_data.setdefault("hsgt_add_ratio", float(latest['增持占A股百分比']) / 100 if pd.notna(latest.get('增持占A股百分比')) else None)
                    logger.info(f"  补充沪深港通: code={code}, hsgt_hold_ratio={fund_data.get('hsgt_hold_ratio')}")
                else:
                    hsgt_failed = True
            except Exception as _e:
                logger.warning(f"  补充沪深港通失败 {code}: {_e}")
                hsgt_failed = True

        # 技术面：从BaoStock原始数据计算
        tech_data = {}
        baostock_df = baostock_raw.get(code)
        if baostock_df is not None and len(baostock_df) >= 20:
            import pandas as pd
            import numpy as np
            df = baostock_df
            close = df['close'].values
            volume = df['volume'].values

            ma5 = np.mean(close[-5:]) if len(close) >= 5 else close[-1]
            ma10 = np.mean(close[-10:]) if len(close) >= 10 else close[-1]
            ma20 = np.mean(close[-20:]) if len(close) >= 20 else close[-1]
            ma60 = np.mean(close[-60:]) if len(close) >= 60 else close[-1]
            current_price = close[-1]

            if current_price > ma5 > ma10 > ma20:
                ma_status = "bullish"
            elif current_price < ma5 < ma10 < ma20:
                ma_status = "bearish"
            else:
                ma_status = "neutral"

            # MACD
            def calc_ema(data, period):
                alpha = 2 / (period + 1)
                ema = [data[0]]
                for i in range(1, len(data)):
                    ema.append(alpha * data[i] + (1 - alpha) * ema[-1])
                return np.array(ema)

            ema12 = calc_ema(close, 12)
            ema26 = calc_ema(close, 26)
            dif = ema12 - ema26
            dea = calc_ema(dif, 9)
            macd_hist = 2 * (dif - dea)

            if len(macd_hist) >= 3:
                if macd_hist[-1] > macd_hist[-2] > macd_hist[-3] and dif[-1] > dea[-1]:
                    macd_status = "golden"
                elif macd_hist[-1] < macd_hist[-2] < macd_hist[-3] and dif[-1] < dea[-1]:
                    macd_status = "death"
                else:
                    macd_status = "neutral"
            else:
                macd_status = "neutral"

            # RSI(14)
            if len(close) >= 15:
                gains = []
                losses = []
                for i in range(len(close)-14, len(close)):
                    delta = close[i] - close[i-1]
                    if delta >= 0:
                        gains.append(delta)
                        losses.append(0)
                    else:
                        gains.append(0)
                        losses.append(abs(delta))
                avg_gain = np.mean(gains) if gains else 0
                avg_loss = np.mean(losses) if losses else 1
                rs_val = avg_gain / avg_loss if avg_loss > 0 else 100
                rsi = min(100, 100 - (100 / (1 + rs_val)))
            else:
                rsi = 50

            # 成交量状态
            if len(volume) >= 10:
                avg_vol_5 = np.mean(volume[-5:])
                avg_vol_10 = np.mean(volume[-10:])
                vol_ratio = avg_vol_5 / avg_vol_10 if avg_vol_10 > 0 else 1
                change_pct = (current_price - close[-2]) / close[-2] * 100 if len(close) >= 2 else 0
                if vol_ratio > 1.3 and change_pct > 2:
                    volume_status = "放量上涨"
                elif vol_ratio > 1.3:
                    volume_status = "放量"
                elif vol_ratio < 0.7:
                    volume_status = "缩量"
                else:
                    volume_status = "正常"
            else:
                volume_status = "正常"
                vol_ratio = 1.0

            # 布林带
            if len(close) >= 20:
                bb_mid = ma20
                bb_std = np.std(close[-20:])
                bb_upper = bb_mid + 2 * bb_std
                bb_lower = bb_mid - 2 * bb_std
                bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
            else:
                bb_mid = bb_upper = bb_lower = current_price
                bb_position = 0.5

            tech_data = {
                "ma_status": ma_status,
                "macd_status": macd_status,
                "volume_status": volume_status,
                "volume_ratio": round(vol_ratio, 2),
                "rsi": round(rsi, 1),
                "price": round(current_price, 2),
                "change_pct": round((current_price - close[-2]) / close[-2] * 100, 2) if len(close) >= 2 else 0,
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "ma20": round(ma20, 2),
                "ma60": round(ma60, 2),
                "dif": round(dif[-1], 3),
                "dea": round(dea[-1], 3),
                "macd_hist": round(macd_hist[-1], 3),
                "bb_upper": round(bb_upper, 2),
                "bb_mid": round(bb_mid, 2),
                "bb_lower": round(bb_lower, 2),
                "bb_position": round(bb_position, 2),
                "data_rows": len(df),
                "_source": f"BaoStock日线({datetime.now().strftime('%Y-%m-%d')})",
            }
        else:
            tech_data = {"ma_status": "neutral", "macd_status": "neutral",
                         "volume_status": "正常", "rsi": 50, "_source": "技术数据不足"}

        # 组装 data dict (与 fetch_all 相同格式)
        data = {}

        # --- 资金面 ---
        if fund_data and fund_data.get("_source"):  # 有真实数据源才构建
            moneyflow = {
                "main_net_flow_5d": fund_data.get("main_net_flow_5d", 0),
                "large_order_ratio": fund_data.get("large_order_ratio", 0),
                "main_direction": fund_data.get("main_direction", "未知"),
                "retail_direction": fund_data.get("retail_direction", "未知"),
                "daily_flows": fund_data.get("daily_flows", []),
                "latest_main_flow": fund_data.get("latest_main_flow", 0),
                "latest_main_ratio": fund_data.get("latest_main_ratio", 0),
                "super_large_flow": fund_data.get("super_large_flow", 0),
                "small_order_flow": fund_data.get("small_order_flow", 0),
                "_source": fund_data.get("_source", "数据暂缺"),
            }
            if qq_data:
                outer_inner = qq_data.get("outer_inner_ratio", 1.0)
                moneyflow["outer_inner_ratio"] = outer_inner
                moneyflow["qq_outer_inner_ratio"] = outer_inner
                moneyflow["qq_outer_disk"] = qq_data.get("outer_disk", 0)
                moneyflow["qq_inner_disk"] = qq_data.get("inner_disk", 0)
            data["moneyflow_data"] = moneyflow
        else:
            # 严禁兜底假数据：资金流向完全不可得时，置为None
            # 上层逻辑（check_veto / generate_report）必须检查None
            logger.warning(f"  资金流向完全不可得(code={code})，标记为缺失，不输出虚假数据")
            data["moneyflow_data"] = None

        # --- 技术面 ---
        data["technical_data"] = {
            "ma_status": tech_data.get("ma_status", "neutral"),
            "macd_status": tech_data.get("macd_status", "neutral"),
            "volume_status": tech_data.get("volume_status", "正常"),
            "rsi": tech_data.get("rsi", 50),
            "volume_ratio": tech_data.get("volume_ratio", 1.0),
            "price": qq_data.get("price", tech_data.get("price", 0)),
            "change_pct": qq_data.get("change_pct", tech_data.get("change_pct", 0)),
            **({k: tech_data[k] for k in ["ma5","ma10","ma20","ma60","dif","dea","macd_hist","bb_upper","bb_mid","bb_lower","bb_position"] if k in tech_data}),
            "_source": tech_data.get("_source", "数据获取失败"),
        }
        if qq_data and qq_data.get("price"):
            data["technical_data"]["price"] = qq_data["price"]

        # --- 基本面 ---
        pb_from_qq = qq_data.get("pb")
        pe_from_qq = qq_data.get("pe")
        # 兼容评分器字段名映射（P1.1/P1.2修复：L2采集名 → 评分器期望名）
        _net_profit = fin_data.get("net_profit_yoy")
        _debt_ratio = fin_data.get("asset_liability_ratio")
        data["fundamental_data"] = {
            "roe": fin_data.get("roe"),
            "net_profit_yoy": _net_profit,  # 保留原名（辩论引擎使用）
            "eps_growth_yoy": _net_profit,   # P1.1修复：净利润增速 → EPS增速（评分器期望）
            "pb": pb_from_qq if (pb_from_qq and pb_from_qq > 0) else None,
            "pe": pe_from_qq if (pe_from_qq and pe_from_qq > 0) else None,
            "gross_margin": fin_data.get("gross_margin"),
            "net_margin": fin_data.get("net_margin"),
            "asset_liability_ratio": _debt_ratio,  # 保留原名
            "debt_eq": (_debt_ratio / 100) if (_debt_ratio and _debt_ratio > 1) else _debt_ratio,  # P1.2修复：百分比→比率
            "eps": fin_data.get("eps"),
            "revenue_growth": fin_data.get("revenue_growth"),
            # A股机构持仓兼容字段：hsgt_hold_ratio → inst_ownership_pct（第二处，batch模式走这里）
            "inst_ownership_pct": fund_data.get("hsgt_hold_ratio") if fund_data else None,
            "inst_trans": fund_data.get("hsgt_add_ratio") if fund_data else None,
            "_source": (fin_data.get("_source") or "") + " + " + (qq_data.get("_source") or ""),
        }

        # --- 板块 ---
        data["sector_data"] = sector_data_dict

        # --- 事件 ---
        data["event_data"] = event_data_dict

        # ── 数据源健康度追踪（P0改进：每只股票记录哪些源成功/失败）──────────
        def _src_status(src_str):
            """根据_source字符串判断数据质量"""
            if not src_str or src_str in ("数据暂缺", "数据获取失败", "技术数据不足"):
                return "no_data"
            if "失败" in src_str or "错误" in src_str:
                return "fail"
            if src_str in ("BaoStock日线估算",):
                return "degraded"
            return "ok"
        data["_health"] = {
            "tencent_api": "ok" if qq_data.get("price") else "fail",
            "baostock_daily": _src_status(tech_data.get("_source", "")) if tech_data else "fail",
            "fund_flow": _src_status(fund_data.get("_source", "")) if fund_data else "no_data",
            "financial_em": _src_status(fin_data.get("_source", "")) if fin_data else "no_data",
            "sector_em": _src_status(sector_data_dict.get("_source", "")) if sector_data_dict else "no_data",
            "event_em": _src_status(event_data_dict.get("_source", "")) if event_data_dict else "no_data",
        }

        # name优先用腾讯API返回的真实name（symbol_mode下L1传入的name为空）
        _resolved_name = qq_data.get("name") or name
        results.append({"code": code, "name": _resolved_name, "data": data})

    # ── 批次级健康度汇总 ──────────────────────────────────────────────
    health_counts = {"ok": 0, "degraded": 0, "fail": 0, "no_data": 0}
    for r in results:
        h = (r.get("data") or {}).get("_health", {})
        for key in h:
            status = h[key]
            if status in health_counts:
                health_counts[status] += 1

    elapsed = time.time() - start_time
    logger.info(f"===== 批量获取完成 {total}只, 耗时{elapsed:.1f}s =====")
    # 健康度汇总日志
    _bh_keys = ["tencent_api", "baostock_daily", "fund_flow"]
    _bh_labels = ["tencent", "baostock", "fund_flow"]
    for _key, _label in zip(_bh_keys, _bh_labels):
        _ok = sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get(_key) == "ok")
        _deg = sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get(_key) == "degraded")
        _fail = sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get(_key) == "fail")
        _nd = sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get(_key) == "no_data")
        logger.info(f"  {_label}: ok={_ok} degraded={_deg} fail={_fail} no_data={_nd}")
    # 注入到返回结构（放在第一个元素供检查）
    if results:
        results[0]["_batch_health"] = {
            "total": total,
            "elapsed_s": round(elapsed, 1),
            "tencent_ok": sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get("tencent_api") == "ok"),
            "baostock_ok": sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get("baostock_daily") == "ok"),
            "fund_flow_ok": sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get("fund_flow") in ("ok", "degraded")),
            "fund_flow_fail": sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get("fund_flow") == "fail"),
            "financial_ok": sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get("financial_em") == "ok"),
            "sector_ok": sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get("sector_em") in ("ok", "degraded")),
            "event_ok": sum(1 for r in results if (r.get("data") or {}).get("_health", {}).get("event_em") == "ok"),
        }
    return results


def fetch_one_stock(code: str, name: str = "") -> dict:
    """
    单只股票数据获取（用于线程池并行模式）

    Args:
        code: 股票代码，如 "600519"
        name: 股票名称（可选，腾讯API会返回真实名称）

    Returns:
        {"code": ..., "name": ..., "data": {...}}
        失败时返回 {"code": code, "name": name, "data": {}}
    """
    try:
        result = fetch_batch([{"code": code, "name": name}], max_stocks=1)
        if result and len(result) > 0:
            return result[0]
        return {"code": code, "name": name, "data": {}}
    except Exception as e:
        logger.warning(f"fetch_one_stock({code})异常: {type(e).__name__}: {e}，返回空数据")
        return {"code": code, "name": name, "data": {}}


# ======================== 测试入口 ========================

def test_fetch():
    """测试实时数据获取"""
    test_stocks = [
        ("600519", "贵州茅台"),
        ("000858", "五粮液"),
        ("002594", "比亚迪"),
    ]
    
    for code, name in test_stocks:
        print(f"\n{'='*60}")
        print(f"测试: {name} ({code})")
        print(f"{'='*60}")
        data = fetch_all(code, name)
        
        for key in ["moneyflow_data", "technical_data", "fundamental_data"]:
            print(f"\n  [{key}]:")
            d = data.get(key, {})
            for k, v in d.items():
                if k != "_source" and v is not None:
                    print(f"    {k}: {v}")
            print(f"    来源: {d.get('_source', 'N/A')}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s"
    )
    test_fetch()
