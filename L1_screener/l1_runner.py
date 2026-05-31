#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 Screener 统一入口脚本

提供4种输入模式：
1. by_strategy: 按选股策略执行
2. by_name: 按股票名称模糊查询
3. by_code: 按股票代码精确查询
4. by_sector: 按行业板块查询

接口规范见 docs/v4_migration/INTERFACE-SPEC.md
"""
import time
from datetime import datetime
from typing import Dict, Any, Optional

# 路径配置
import os
import sys
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "L1_screener"))
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))

# 统一日志工具
from logger import log_start, log_end, log_fail, log_source, info

# 导入策略模块
from strategies import breakout
from strategies import growth_momentum
from strategies import garp
from strategies import pullback
from strategies import quality_value
from strategies import by_name
from strategies import by_code
from strategies import by_sector


# 策略名称映射
STRATEGY_MODULES = {
    "breakout": breakout,
    "growth_momentum": growth_momentum,
    "garp": garp,
    "pullback": pullback,
    "quality_value": quality_value,
}

STRATEGY_LIST = ["breakout", "growth_momentum", "garp", "pullback", "quality_value"]


def run_l1(input_type: str, params: dict, config: dict) -> dict:
    """
    L1 统一入口

    Args:
        input_type: "by_name" | "by_code" | "by_sector" | "by_strategy"
        params: 根据 input_type 不同而不同
        config: 必须，从 PipelineContext.l1_config 传入（不允许 fallback）

    Returns:
        {
            "layer": "L1",
            "run_date": "2026-05-30",
            "input_type": "by_strategy",
            "input_params": {...},
            "stock_count": 25,
            "stocks": [...],
            "duration_ms": 3200
        }
    """
    start_time = time.time()
    run_date = datetime.now().strftime("%Y-%m-%d")

    # config 注入：必须从 PipelineContext 传入
    global _l1_config_cache
    if config is None:
        raise ValueError("run_l1() 必须传入 config 参数（从 PipelineContext.l1_config 获取）")
    _l1_config_cache = config

    # 标准化返回值结构
    result = {
        "layer": "L1",
        "run_date": run_date,
        "input_type": input_type,
        "input_params": params,
        "stock_count": 0,
        "stocks": [],
        "duration_ms": 0,
    }

    try:
        # 强制单股模式（test用，跳过 strategy 流程）
        if _l1_config_cache.get("_force_mode") == "by_code":
            codes = _l1_config_cache.get("_force_symbols", [])
            all_stocks = []
            for code in codes:
                all_stocks.extend(by_code.query_by_code(code, market=params.get("market", "cn")))
            result["stocks"] = all_stocks
        elif input_type == "by_strategy":
            result["stocks"] = _run_by_strategy(params)
        elif input_type == "by_name":
            result["stocks"] = _run_by_name(params)
        elif input_type == "by_code":
            result["stocks"] = _run_by_code(params)
        elif input_type == "by_sector":
            result["stocks"] = _run_by_sector(params)
        else:
            # 未知模式，返回空
            result["stocks"] = []
    except Exception as e:
        # 失败返回空列表，不抛异常
        result["stocks"] = []

    result["stock_count"] = len(result["stocks"])
    result["duration_ms"] = int((time.time() - start_time) * 1000)

    return result


def _run_by_strategy(params: dict) -> list:
    """
    执行选股策略

    params: {
        "strategy": "breakout" | "growth_momentum" | "garp" | "pullback" | "quality_value",
        "pool": "full" | "index800",  # 可选，默认 index800
        "market": "cn" | "hk" | "us"   # 可选，默认 cn
        "test_limit": int              # 可选，测试模式限制每策略返回数量
    }
    """
    strategy = params.get("strategy", "")
    pool = params.get("pool", "index800")
    market = params.get("market", "cn")
    test_limit = params.get("test_limit")

    # 如果strategy是空或"all"，执行所有策略
    if strategy == "" or strategy == "all":
        return _run_all_strategies(pool, market, test_limit=test_limit)

    # 执行指定策略
    mod = STRATEGY_MODULES.get(strategy)
    if mod and hasattr(mod, 'screen'):
        try:
            results = mod.screen(pool=pool)
            if test_limit is not None:
                results = results[:test_limit]
            return results
        except Exception:
            return []

    return []


def _run_all_strategies(pool: str, market: str = "cn", test_limit=None) -> list:
    """
    执行所有策略（统一拉取数据，优化性能）

    Args:
        pool: "full" | "index800"
        market: "cn" | "hk" | "us"
        test_limit: int, 测试模式限制每策略返回数量

    1. 统一拉取股票列表（akshare）
    2. 统一拉取行情数据（腾讯API for cn/hk/us）
    3. 各策略共享行情数据，独立评分
    """
    log_start("l1_runner", f"获取股票列表: market={market}, pool={pool}")

    # 获取策略模块
    mods = [STRATEGY_MODULES.get(s) for s in STRATEGY_LIST]
    mods = [m for m in mods if m and hasattr(m, 'screen')]

    if not mods:
        return []

    # 统一拉取股票列表
    import pandas as pd
    import os

    old_no_proxy = os.environ.get("no_proxy", "")
    os.environ["no_proxy"] = "*"

    try:
        import akshare as ak

        if market == "hk":
            # 港股：使用港股通成分股
            df = ak.stock_hk_ggt_components_em()
            log_source("l1_runner", "akshare", "获取港股股票列表", True, f"{len(df)} 条")
            codes = [f"hk{int(c):05d}" for c in df['代码'].tolist()]
        elif market == "us":
            # 美股：使用主要指数成分股
            us_df = ak.stock_us_spot_em()
            log_source("l1_runner", "akshare", "获取美股股票列表", True, f"{len(us_df) if us_df is not None else 0} 条")
            if us_df is not None and not us_df.empty:
                codes = [f"us{c}" for c in us_df['symbol'].tolist() if isinstance(c, str)]
            else:
                codes = []
        else:
            # A股
            if pool == 'full':
                df = ak.stock_info_a_code_name()
                log_source("l1_runner", "akshare", "获取A股全量股票列表", True, f"{len(df)} 条")
                df = df[~df['name'].str.match(r'^\*?ST')]
                codes = [f"{'sh' if c.startswith(('6','8')) else 'sz'}{c}" for c in df['code'].tolist()]
            else:
                hs = ak.index_stock_cons_csindex("000300")
                hs = hs.rename(columns={'成分券代码': 'code', '成分券名称': 'name'})
                zz = ak.index_stock_cons_csindex("000905")
                zz = zz.rename(columns={'成分券代码': 'code', '成分券名称': 'name'})
                combined = pd.concat([hs, zz]).drop_duplicates(subset=['code'])
                log_source("l1_runner", "akshare", "获取A股指数成分股(沪深300+中证500)", True, f"{len(combined)} 条")
                codes = [f"{'sh' if c.startswith(('6','8')) else 'sz'}{c}" for c in combined['code'].tolist()]
    except Exception as e:
        log_source("l1_runner", "akshare", "获取股票列表", False, f"{type(e).__name__}: {e}")
    finally:
        os.environ["no_proxy"] = old_no_proxy

    log_start("l1_runner", f"拉取行情: market={market}, {len(codes)} 只股票")
    if market == "hk":
        quotes = _fetch_quotes_hk(codes)
        log_source("l1_runner", "tencent", "获取港股行情", True, f"{len(quotes)} 条")
    elif market == "us":
        quotes = _fetch_quotes_us(codes)
        log_source("l1_runner", "tencent", "获取美股行情", True, f"{len(quotes)} 条")
    else:
        quotes = _fetch_quotes_cn(codes)
        log_source("l1_runner", "tencent", "获取A股行情", True, f"{len(quotes)} 条")

    # 各策略独立评分，共享行情数据
    all_results = []
    cfg = _get_l1_config()
    market_cfg = cfg.get(market, {})
    per_strategy_limit = market_cfg.get("per_strategy_limit", 200)

    # 获取冻结列表
    frozen = _load_freezes()

    for mod in mods:
        strategy_name = getattr(mod, 'STRATEGY', getattr(mod, 'STRATEGY_NAME', 'unknown'))
        log_start("l1_runner", f"策略评分: {strategy_name}")
        try:
            results = _screen_with_quotes(mod, quotes, frozen, strategy_name, per_strategy_limit, market)
            if test_limit is not None:
                results = results[:test_limit]
            log_end("l1_runner", f"策略评分: {strategy_name}", f"{len(results)} 条")
            all_results.extend(results)
        except Exception as e:
            log_fail("l1_runner", f"策略评分: {strategy_name}", str(e))

    log_end("l1_runner", "全部策略", f"{len(all_results)} 条")
    return all_results


def _get_l1_config():
    """获取L1配置（带缓存）"""
    global _l1_config_cache
    if _l1_config_cache is not None:
        return _l1_config_cache
    import json, os
    CONFIG_FILE = os.path.join(os.path.expanduser("~/.hermes/investment"), "main/config/l1_config.json")
    try:
        with open(CONFIG_FILE, 'r') as f:
            _l1_config_cache = json.load(f)
    except:
        _l1_config_cache = {}
    return _l1_config_cache


_l1_config_cache = None


def _load_freezes():
    """获取冻结列表"""
    import json, os
    from datetime import datetime
    BASE = os.path.expanduser("~/.hermes/investment")
    FREEZE = os.path.join(BASE, "main/freeze_table.json")
    if not os.path.exists(FREEZE):
        return set()
    with open(FREEZE) as f:
        d = json.load(f)
    t = datetime.now().strftime("%Y-%m-%d")
    return {r["stock_code"] for r in d.get("freeze_records",[]) if r.get("frozen_until","") > t}


def _fetch_quotes_cn(codes):
    """统一拉取A股行情数据"""
    import requests, time
    cfg = _get_l1_config()
    cn_cfg = cfg.get("cn", {})
    batch_size = cn_cfg.get("batch_size", 50)
    request_timeout = 30
    request_interval = cn_cfg.get("request_interval", 0.3)

    res = {}
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        try:
            r = requests.get("https://qt.gtimg.cn/q=" + ",".join(batch), timeout=request_timeout)
            for line in r.text.strip().split(';'):
                if not line or '=' not in line:
                    continue
                parts = line.split('=', 1)[1].replace('"', '').split('~')
                if len(parts) < 47:
                    continue
                try:
                    res[parts[2]] = {
                        'code': parts[2], 'name': parts[1], 'price': float(parts[3] or 0),
                        'pe': float(parts[39] or 0), 'pb': float(parts[46] or 0),
                        'mcap': float(parts[45] or 0), 'high': float(parts[33] or 0),
                        'low': float(parts[34] or 0),
                        'open': float(parts[5] or 0), 'volume': float(parts[6] or 0),
                        'pre_close': float(parts[4] or 0),
                        'amount': float(parts[16] or 0),
                    }
                except:
                    continue
        except:
            pass
        if i + batch_size < len(codes):
            time.sleep(request_interval)
    return res


def _fetch_quotes_hk(codes):
    """统一拉取港股行情数据"""
    import requests, time
    cfg = _get_l1_config()
    hk_cfg = cfg.get("hk", {})
    batch_size = hk_cfg.get("batch_size", 20)
    request_timeout = 30
    request_interval = hk_cfg.get("request_interval", 0.3)

    res = {}
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        try:
            r = requests.get("https://qt.gtimg.cn/q=" + ",".join(batch), timeout=request_timeout)
            for line in r.text.strip().split(';'):
                if not line or '=' not in line:
                    continue
                parts = line.split('=', 1)[1].replace('"', '').split('~')
                if len(parts) < 47:
                    continue
                try:
                    raw_mcap = parts[45] if len(parts) > 45 else '0'
                    raw_pb = parts[47] if len(parts) > 47 else '0'
                    try:
                        mcap = float(raw_mcap)
                    except:
                        mcap = 0
                    try:
                        pb = float(raw_pb)
                    except:
                        pb = 0
                    try:
                        pe = float(parts[39]) if parts[39] else 0
                    except:
                        pe = 0
                    res[parts[2]] = {
                        'code': parts[2], 'name': parts[1], 'price': float(parts[3] or 0),
                        'pe': pe, 'pb': pb,
                        'mcap': mcap, 'high': float(parts[33] or 0),
                        'low': float(parts[34] or 0),
                        'open': float(parts[5] or 0), 'volume': float(parts[6] or 0),
                        'pre_close': float(parts[4] or 0),
                        'amount': float(parts[16] or 0),
                    }
                except:
                    continue
        except:
            pass
        if i + batch_size < len(codes):
            time.sleep(request_interval)
    return res


def _fetch_quotes_us(codes):
    """统一拉取美股行情数据"""
    import requests, time
    cfg = _get_l1_config()
    us_cfg = cfg.get("us", {})
    batch_size = us_cfg.get("batch_size", 20)
    request_timeout = 30
    request_interval = us_cfg.get("request_interval", 0.3)

    res = {}
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        try:
            r = requests.get("https://qt.gtimg.cn/q=" + ",".join(batch), timeout=request_timeout)
            for line in r.text.strip().split(';'):
                if not line or '=' not in line:
                    continue
                parts = line.split('=', 1)[1].replace('"', '').split('~')
                if len(parts) < 32:
                    continue
                try:
                    res[parts[2]] = {
                        'code': parts[2], 'name': parts[1], 'price': float(parts[3] or 0),
                        'pe': float(parts[53] or 0), 'pb': float(parts[54] or 0),
                        'mcap': float(parts[44] or 0), 'high': float(parts[33] or 0),
                        'low': float(parts[34] or 0),
                        'open': float(parts[5] or 0), 'volume': float(parts[6] or 0),
                        'pre_close': float(parts[4] or 0),
                        'amount': float(parts[37] or 0),
                    }
                except:
                    continue
        except:
            pass
        if i + batch_size < len(codes):
            time.sleep(request_interval)
    return res


def _screen_with_quotes(mod, quotes, frozen, strategy_name, per_strategy_limit, market="cn"):
    """使用预拉取的行情数据进行策略评分"""
    # 根据策略名获取对应的评分函数和阈值
    cfg = _get_l1_config()

    # 获取prefilter
    pf = cfg.get("prefilter", {})
    min_mcap = pf.get("min_market_cap_yuan", 30000000000) / 100000000
    max_pe = pf.get("max_pe", 100)

    # 预过滤
    cands = []
    for code, q in quotes.items():
        if code in frozen:
            continue
        if q.get('mcap', 0) < min_mcap:
            continue
        if q.get('pe', 0) > max_pe and q.get('pe', 0) > 0:
            continue
        # 标准化 mcap_100m（策略评分函数依赖此字段）
        q['mcap_100m'] = q.get('mcap', 0)
        cands.append(q)

    # 根据策略名获取评分函数
    score_fn_name = {
        'breakout': 'score_momentum',
        'growth_momentum': 'score_graham',
        'garp': 'score_lynch',
        'pullback': 'score_reversion',
        'quality_value': 'score_buffett',
    }.get(strategy_name)

    if not score_fn_name:
        return []

    score_fn = getattr(mod, score_fn_name, None)
    if not score_fn:
        return []

    # 获取信号阈值
    signal_key = {
        'breakout': 'momentum',
        'growth_momentum': 'graham',
        'garp': 'lynch',
        'pullback': 'reversion',
        'quality_value': 'buffett',
    }.get(strategy_name, strategy_name)

    sig_cfg = cfg.get("signals", {}).get(signal_key, {})
    thresholds = sig_cfg.get("thresholds", [0.25, 0.40, 0.55])
    min_signal = thresholds[0]

    results = []
    for q in cands:
        s = score_fn(q)
        if s['signal'] >= min_signal:
            prev_close = q.get('pre_close', 0)
            change_pct = round((q['price'] - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
            results.append({
                'code': q['code'],
                'name': q['name'],
                'price': q['price'],
                'change_pct': change_pct,
                'market_cap': q.get('mcap', 0),
                'source': '腾讯行情',
                'strategy_matched': strategy_name
            })

    results.sort(key=lambda x: x.get('price', 0), reverse=True)
    return results[:per_strategy_limit]


def _run_by_name(params: dict) -> list:
    """
    按名称模糊查询

    params: {"name": "茅台", "market": "cn"}
    """
    name = params.get("name", "")
    market = params.get("market", "cn")
    if not name:
        return []
    try:
        return by_name.search_by_name(name, market=market)
    except Exception:
        return []


def _run_by_code(params: dict) -> list:
    """
    按代码精确查询

    params: {"code": "600519", "market": "cn"}
            或 {"codes": ["600519", "000858"], "market": "cn"}
    """
    codes = params.get("codes", [])
    if isinstance(codes, list) and len(codes) > 1:
        #批量查询（支持 --symbols 多只）
        all_stocks = []
        for code in codes:
            result = by_code.query_by_code(code, market=params.get("market", "cn"))
            all_stocks.extend(result)
        return all_stocks

    code = params.get("code", "") or (codes[0] if codes else "")
    market = params.get("market", "cn")
    if not code:
        return []
    try:
        return by_code.query_by_code(code, market=market)
    except Exception:
        return []


def _run_by_sector(params: dict) -> list:
    """
    按板块查询

    params: {"sector": "白酒", "market": "cn"}
    """
    sector = params.get("sector", "")
    market = params.get("market", "cn")
    if not sector:
        return []
    try:
        return by_sector.search_by_sector(sector, market=market)
    except Exception:
        return []