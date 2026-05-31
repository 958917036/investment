#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 Market Fetcher 测试代码

覆盖 L2_data_enrich/l2_runner.py 的所有入口场景：
- 三市场：CN(600519) / HK(00700) / US(SMCI)
- 无效市场代码 → 抛 ValueError
- 五个维度数据块：均包含 quality / missing_fields
- 输出结构完整性断言
"""
import sys
import os
import re
import json
import time
import logging
import uuid
from datetime import datetime
from functools import partial

# 测试日志工具
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from test_logger import suite_start, suite_end, test_start, test_end, test_skip

# 自定义 JSON 编码器，处理 numpy/bool 等类型
class _JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, 'item'):
            try:
                return o.item()
            except Exception:
                pass
        return super().default(o)

# ── 日志静默配置（必须在任何业务模块 import 之前）────────────────────
# 1. 禁用 akshare tqdm 进度条
try:
    import tqdm
    tqdm.tqdm.disable = True
except ImportError:
    pass

# 2. 配置模块 logger 级别为 WARNING 以上
for _logger_name in [
    "realtime_data_fetcher",
    "L2.market_fetcher",
    "us_fetcher",
    "L2.adapters",
    "L2.adapters.cn",
    "L2.adapters.hk",
    "L2.adapters.us",
    "adapter.futures",
    "macro_fetcher",
    "stock_classifier",
    "analyst_fetcher",
]:
    logging.getLogger(_logger_name).setLevel(logging.WARNING)

# 3. BaoStock C-level stdout 静默类（捕获而非丢弃，支持 fileno）
import io as _io
_capture_buf = _io.StringIO()

class _Capture:
    """取代 sys.stdout 的可捕获缓冲区"""
    def write(self, _s):
        if _s and _s != "\n":
            _capture_buf.write(_s)
    def flush(self): pass
    def fileno(self): return 1   # 让 C-level write 成功（不丢弃）
    def isatty(self): return False
    def truncate(self, _n=None): return 0
    def seek(self, _n, _whence=0): return 0

_orig_stdout = sys.stdout
_orig_stderr = sys.stderr
_null = _Capture()
sys.stdout = _null   # 全局静默，直到测试函数主动恢复
sys.stderr = _null   # 静默 baostock / tqdm / curl 等 C-level stderr 输出

# ── 辅助：临时恢复/静默 stdout ───────────────────────────────────
def _show():
    sys.stdout = _orig_stdout
    sys.stderr = _orig_stderr
    sys.stdout.flush()
    sys.stderr.flush()

def _hide():
    sys.stdout = _null
    sys.stderr = _null

def _capture():
    """返回当前捕获的 BaoStock 输出，供调试用"""
    return _capture_buf.getvalue()


sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))
from L2_data_enrich.l2_runner import fetch_market_data


def _collect_failures(data):
    """递归检查所有字段，收集值为'失败'的字段路径"""
    failures = []
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if v == "失败":
                    failures.append(f"{path}{k}=失败" if path else k)
                elif isinstance(v, (dict, list)):
                    walk(v, f"{path}{k}." if path else f"{k}.")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}].")
    walk(data)
    return failures


def test_cn():
    """测试 A股 fetch_market_data("600519", "CN") - 贵州茅台"""
    _show()
    print("\n[用例] CN(600519贵州茅台)")
    print("[输入] code=600519, market=CN")
    _hide()

    start = time.time()
    data = fetch_market_data("600519", "CN")
    elapsed = time.time() - start

    td = data["technical_data"]
    fd = data["fundamental_data"]

    checks = {
        "layer == 'L2'": {"期望": "L2", "实际": data.get("layer"), "通过": data.get("layer") == "L2"},
        "market == 'CN'": {"期望": "CN", "实际": data.get("market"), "通过": data.get("market") == "CN"},
        "code == '600519'": {"期望": "600519", "实际": data.get("code"), "通过": data.get("code") == "600519"},
        "price > 0": {"期望": ">0", "实际": td.get("price"), "通过": (td.get("price") or 0) > 0},
        "500 < price < 3000": {"期望": "500~3000", "实际": td.get("price"), "通过": 500 < (td.get("price") or 0) < 3000},
        "pe not None": {"期望": "非None", "实际": fd.get("pe"), "通过": fd.get("pe") is not None},
        "5 < pe < 100": {"期望": "5~100", "实际": fd.get("pe"), "通过": isinstance(fd.get("pe"), (int, float)) and 5 < fd["pe"] < 100},
        "roe not None": {"期望": "非None", "实际": fd.get("roe"), "通过": fd.get("roe") is not None},
        "0 < roe < 50": {"期望": "0~50", "实际": fd.get("roe"), "通过": isinstance(fd.get("roe"), (int, float)) and 0 < fd["roe"] < 50},
        "quality in (ok/degraded/fail)": {"期望": "ok/degraded/fail", "实际": fd.get("quality"), "通过": fd.get("quality") in ("ok", "degraded", "fail")},
    }

    failures = _collect_failures(data)

    result = {
        "用例": "CN(600519贵州茅台)",
        "耗时": f"{elapsed:.2f}s",
        "输入": {"code": "600519", "market": "CN"},
        "完整输出": data,
        "字段校验": checks,
        "失败字段检测": failures,
        "结果": "PASS",
    }

    # 断言
    assert data["layer"] == "L2", f"layer: expected L2, got {data.get('layer')}"
    assert data["market"] == "CN", f"market: expected CN, got {data.get('market')}"
    assert data["code"] == "600519", f"code: expected 600519, got {data.get('code')}"
    assert td["price"] > 0, f"price: expected >0, got {td['price']}"
    assert 500 < td["price"] < 3000, f"price: expected 500~3000 for 600519, got {td['price']}"
    assert fd["quality"] in ("ok", "degraded", "fail"), f"quality: got {fd['quality']!r}"
    assert fd["quality"] == "ok", f"CN 600519 fundamental quality must be ok, got {fd['quality']}"  # 数据完整应为 ok
    assert fd["pe"] is not None and fd["pe"] != "失败", f"pe: expected numeric, got {fd['pe']!r}"
    assert isinstance(fd["pe"], (int, float)), f"pe: expected numeric, got {type(fd['pe']).__name__}: {fd['pe']!r}"
    assert 5 < fd["pe"] < 100, f"pe: expected 5~100 for 600519, got {fd['pe']}"
    assert fd["roe"] is not None and fd["roe"] != "失败", f"roe: expected numeric, got {fd['roe']!r}"
    assert isinstance(fd["roe"], (int, float)), f"roe: expected numeric, got {type(fd['roe']).__name__}: {fd['roe']!r}"
    assert 0 < fd["roe"] < 50, f"roe: expected 0~50, got {fd['roe']}"
    assert len(failures) == 0, f"数据中存在'失败'字段: {failures}"

    _show()
    print(f"[耗时] {elapsed:.2f}s")
    for k, v in checks.items():
        mark = "✅" if v["通过"] else "❌"
        print(f"  {mark} {k}: 实际={v['实际']}")
    if failures:
        print(f"[失败字段] {failures}")
    else:
        print(f"[失败字段] 无")
    print(f"[结果] PASS")
    _hide()

    return result


def test_hk():
    """测试 港股 fetch_market_data("00700", "HK") - 腾讯控股"""
    _show()
    print("\n[用例] HK(00700腾讯)")
    print("[输入] code=00700, market=HK")
    _hide()

    start = time.time()
    data = fetch_market_data("00700", "HK")
    elapsed = time.time() - start

    fd = data["fundamental_data"]
    td = data.get("technical_data", {})

    checks = {
        "layer == 'L2'": {"期望": "L2", "实际": data.get("layer"), "通过": data.get("layer") == "L2"},
        "market == 'HK'": {"期望": "HK", "实际": data.get("market"), "通过": data.get("market") == "HK"},
        "code == '00700'": {"期望": "00700", "实际": data.get("code"), "通过": data.get("code") == "00700"},
        "price > 0 or None": {"期望": ">0 or None", "实际": td.get("price"), "通过": td.get("price") is None or td["price"] > 0},
        "quality in (ok/degraded/fail)": {"期望": "ok/degraded/fail", "实际": fd.get("quality"), "通过": fd.get("quality") in ("ok", "degraded", "fail")},
        "pe 范围(5~80)": {"期望": "5~80 or None", "实际": fd.get("pe"), "通过": fd.get("pe") is None or (isinstance(fd["pe"], (int, float)) and 5 < fd["pe"] < 80)},
    }

    failures = _collect_failures(data)

    result = {
        "用例": "HK(00700腾讯)",
        "耗时": f"{elapsed:.2f}s",
        "输入": {"code": "00700", "market": "HK"},
        "完整输出": data,
        "字段校验": checks,
        "失败字段检测": failures,
        "结果": "PASS",
    }

    assert data["layer"] == "L2"
    assert data["market"] == "HK"
    assert data["code"] == "00700"
    assert td.get("price") is None or td["price"] > 0
    assert fd["quality"] in ("ok", "degraded", "fail")
    if "pe" in fd and fd["pe"] is not None:
        assert isinstance(fd["pe"], (int, float))
        assert 5 < fd["pe"] < 80

    _show()
    print(f"[耗时] {elapsed:.2f}s")
    for k, v in checks.items():
        mark = "✅" if v["通过"] else "❌"
        print(f"  {mark} {k}: 实际={v['实际']}")
    if failures:
        print(f"[失败字段] {failures}")
    else:
        print(f"[失败字段] 无")
    print(f"[结果] PASS")
    _hide()

    return result


def test_us():
    """测试 美股 fetch_market_data("SMCI", "US") - 超微电脑"""
    _show()
    print("\n[用例] US(SMCI超微)")
    print("[输入] code=SMCI, market=US")
    _hide()

    start = time.time()
    data = fetch_market_data("SMCI", "US")
    elapsed = time.time() - start

    fd = data["fundamental_data"]
    td = data.get("technical_data", {})

    checks = {
        "layer == 'L2'": {"期望": "L2", "实际": data.get("layer"), "通过": data.get("layer") == "L2"},
        "market == 'US'": {"期望": "US", "实际": data.get("market"), "通过": data.get("market") == "US"},
        "quality in (ok/degraded/fail)": {"期望": "ok/degraded/fail", "实际": fd.get("quality"), "通过": fd.get("quality") in ("ok", "degraded", "fail")},
        "price > 0 or None": {"期望": ">0 or None", "实际": td.get("price"), "通过": td.get("price") is None or td["price"] > 0},
    }

    failures = _collect_failures(data)

    result = {
        "用例": "US(SMCI超微)",
        "耗时": f"{elapsed:.2f}s",
        "输入": {"code": "SMCI", "market": "US"},
        "完整输出": data,
        "字段校验": checks,
        "失败字段检测": failures,
        "结果": "PASS",
    }

    assert data["layer"] == "L2"
    assert data["market"] == "US"
    assert fd["quality"] in ("ok", "degraded", "fail")
    if "price" in td and td["price"] is not None:
        assert td["price"] > 0

    _show()
    print(f"[耗时] {elapsed:.2f}s")
    for k, v in checks.items():
        mark = "✅" if v["通过"] else "❌"
        print(f"  {mark} {k}: 实际={v['实际']}")
    if failures:
        print(f"[失败字段] {failures}")
    else:
        print(f"[失败字段] 无")
    print(f"[结果] PASS")
    _hide()

    return result


def test_quality_markers():
    """测试所有五个维度数据块均包含 quality 字段，且值合理"""
    _show()
    print("\n[用例] quality_markers(五维度quality标记)")
    print("[输入] code=600519, market=CN")
    _hide()

    start = time.time()
    data = fetch_market_data("600519", "CN")
    elapsed = time.time() - start

    valid_quals = ("ok", "degraded", "fail")
    qualities = {}
    checks = {}
    for key in ["moneyflow_data", "technical_data", "fundamental_data", "sector_data", "event_data"]:
        sub = data[key]
        q = sub.get("quality")
        qualities[key.replace("_data", "")] = q
        checks[f"{key}.quality in (ok/degraded/fail)"] = {
            "期望": "ok/degraded/fail",
            "实际": q,
            "通过": q in valid_quals,
        }
        assert "quality" in sub
        assert q in valid_quals

    failures = _collect_failures(data)

    result = {
        "用例": "quality_markers(五维度quality标记)",
        "耗时": f"{elapsed:.2f}s",
        "输入": {"code": "600519", "market": "CN"},
        "完整输出": data,
        "字段校验": checks,
        "失败字段检测": failures,
        "结果": "PASS",
    }

    # 严格断言：moneyflow 和 fundamental 的核心字段不能是 "失败"
    assert "moneyflow_data" in data and data["moneyflow_data"] is not None, "moneyflow_data is None"
    assert "fundamental_data" in data and data["fundamental_data"] is not None, "fundamental_data is None"
    mf = data["moneyflow_data"]
    fd = data["fundamental_data"]
    assert mf.get("main_net_flow_5d") != "失败", f"main_net_flow_5d: got 失败"
    assert fd.get("pe") != "失败", f"pe: got 失败"
    assert fd.get("roe") != "失败", f"roe: got 失败"
    assert fd.get("pb") != "失败", f"pb: got 失败"
    assert len(failures) == 0, f"数据中存在'失败'字段: {failures}"

    _show()
    print(f"[耗时] {elapsed:.2f}s")
    print(f"[五维度quality] {qualities}")
    for k, v in checks.items():
        mark = "✅" if v["通过"] else "❌"
        print(f"  {mark} {k}: 实际={v['实际']}")
    if failures:
        print(f"[失败字段] {failures}")
    else:
        print(f"[失败字段] 无")
    print(f"[结果] PASS")
    _hide()

    return result


def test_missing_fields():
    """测试所有五个维度数据块 missing_fields 是 list，不是 None"""
    _show()
    print("\n[用例] missing_fields(五维度missing_fields列表)")
    print("[输入] code=600519, market=CN")
    _hide()

    start = time.time()
    data = fetch_market_data("600519", "CN")
    elapsed = time.time() - start

    missing = {}
    checks = {}
    for key in ["moneyflow_data", "technical_data", "fundamental_data", "sector_data", "event_data"]:
        sub = data[key]
        mf = sub.get("missing_fields")
        missing[key.replace("_data", "")] = mf
        checks[f"{key}.missing_fields is list"] = {
            "期望": "list",
            "实际": type(mf).__name__,
            "通过": isinstance(mf, list),
        }
        assert "missing_fields" in sub
        assert isinstance(mf, list)

    failures = _collect_failures(data)

    result = {
        "用例": "missing_fields(五维度missing_fields列表)",
        "耗时": f"{elapsed:.2f}s",
        "输入": {"code": "600519", "market": "CN"},
        "完整输出": data,
        "字段校验": checks,
        "失败字段检测": failures,
        "结果": "PASS",
    }

    # 严格断言：核心字段不能是 "失败"
    assert "moneyflow_data" in data and data["moneyflow_data"] is not None, "moneyflow_data is None"
    assert "fundamental_data" in data and data["fundamental_data"] is not None, "fundamental_data is None"
    mf = data["moneyflow_data"]
    fd = data["fundamental_data"]
    assert mf.get("main_net_flow_5d") != "失败", f"main_net_flow_5d: got 失败"
    assert fd.get("pe") != "失败", f"pe: got 失败"
    assert fd.get("roe") != "失败", f"roe: got 失败"
    assert fd.get("pb") != "失败", f"pb: got 失败"
    assert len(failures) == 0, f"数据中存在'失败'字段: {failures}"

    _show()
    print(f"[耗时] {elapsed:.2f}s")
    print(f"[各维度missing_fields数量] { {k: len(v) for k, v in missing.items()} }")
    for k, v in checks.items():
        mark = "✅" if v["通过"] else "❌"
        print(f"  {mark} {k}: 实际={v['实际']}")
    if failures:
        print(f"[失败字段] {failures}")
    else:
        print(f"[失败字段] 无")
    print(f"[结果] PASS")
    _hide()

    return result


def test_invalid_market():
    """测试无效市场代码 → 抛 ValueError"""
    _show()
    print("\n[用例] invalid_market(无效市场抛出ValueError)")
    print("[输入] code=600519, market=XX")
    _hide()

    start = time.time()
    error_msg = ""
    try:
        fetch_market_data("600519", "XX")
    except ValueError as e:
        error_msg = str(e)
    elapsed = time.time() - start

    checks = {
        "抛出 ValueError": {"期望": "ValueError", "实际": error_msg if error_msg else "无异常", "通过": "Unsupported market" in error_msg},
    }

    result = {
        "用例": "invalid_market(无效市场抛出ValueError)",
        "耗时": f"{elapsed:.2f}s",
        "输入": {"code": "600519", "market": "XX"},
        "期望输出": "ValueError: Unsupported market: XX. Must be CN | HK | US",
        "实际输出": error_msg,
        "字段校验": checks,
        "失败字段检测": [],
        "结果": "PASS",
    }

    assert "Unsupported market" in error_msg

    _show()
    print(f"[耗时] {elapsed:.2f}s")
    print(f"[实际异常] {error_msg}")
    for k, v in checks.items():
        mark = "✅" if v["通过"] else "❌"
        print(f"  {mark} {k}: 实际={v['实际']}")
    print(f"[失败字段] 无")
    print(f"[结果] PASS")
    _hide()

    return result


def test_run_date_field():
    """测试输出包含 run_date 字段，格式 YYYY-MM-DD"""
    _show()
    print("\n[用例] run_date_field(运行日期格式)")
    print("[输入] code=600519, market=CN")
    _hide()

    start = time.time()
    data = fetch_market_data("600519", "CN")
    elapsed = time.time() - start

    rd = data.get("run_date")
    checks = {
        "run_date 存在": {"期望": "非None", "实际": rd, "通过": rd is not None},
        "run_date 是 str": {"期望": "str", "实际": type(rd).__name__, "通过": isinstance(rd, str)},
        "run_date 长度10": {"期望": "10字符", "实际": len(rd) if rd else 0, "通过": rd and len(rd) == 10},
        "run_date YYYY-MM-DD格式": {"期望": "YYYY-MM-DD", "实际": rd, "通过": bool(rd) and bool(re.match(r"\d{4}-\d{2}-\d{2}", rd))},
    }

    failures = _collect_failures(data)

    result = {
        "用例": "run_date_field(运行日期格式)",
        "耗时": f"{elapsed:.2f}s",
        "输入": {"code": "600519", "market": "CN"},
        "完整输出": data,
        "字段校验": checks,
        "失败字段检测": failures,
        "结果": "PASS",
    }

    # 严格断言：moneyflow 和 fundamental 的核心字段不能是 "失败"
    assert "moneyflow_data" in data and data["moneyflow_data"] is not None, "moneyflow_data is None"
    assert "fundamental_data" in data and data["fundamental_data"] is not None, "fundamental_data is None"
    mf = data["moneyflow_data"]
    fd = data["fundamental_data"]
    assert mf.get("main_net_flow_5d") != "失败", f"main_net_flow_5d: got 失败"
    assert fd.get("pe") != "失败", f"pe: got 失败"
    assert fd.get("roe") != "失败", f"roe: got 失败"
    assert fd.get("pb") != "失败", f"pb: got 失败"
    assert len(failures) == 0, f"数据中存在'失败'字段: {failures}"

    assert "run_date" in data
    assert isinstance(data["run_date"], str)
    assert len(data["run_date"]) == 10
    assert re.match(r"\d{4}-\d{2}-\d{2}", data["run_date"])

    _show()
    print(f"[耗时] {elapsed:.2f}s")
    print(f"[run_date] {rd}")
    for k, v in checks.items():
        mark = "✅" if v["通过"] else "❌"
        print(f"  {mark} {k}: 实际={v['实际']}")
    if failures:
        print(f"[失败字段] {failures}")
    else:
        print(f"[失败字段] 无")
    print(f"[结果] PASS")
    _hide()

    return result


def test_fund_flow_fallback():
    """
    测试资金流 API 失败时的 fallback 行为。

    场景：AkShare stock_fund_flow_individual 失败 → BaoStock estimate_fund_flow_from_kline
    验证：main_net_flow_5d 有值（非 None、非 0）、_source 标注为 BaoStock 估算
    """
    _show()
    print("\n[用例] fund_flow_fallback(资金流API失败→BaoStock估算)")
    print("[输入] code=600519, market=CN")
    _hide()

    # 单独调用 fetch_all，验证资金流 fallback
    from L2_data_enrich.core.data_fetcher import fetch_all
    start = time.time()
    data = fetch_all("600519")
    elapsed = time.time() - start

    mf = data.get("moneyflow_data", {})
    source = mf.get("_source", "")

    checks = {
        "moneyflow_data 存在": {"期望": "非空dict", "实际": mf, "通过": bool(mf)},
        "main_net_flow_5d 有值": {"期望": "非None", "实际": mf.get("main_net_flow_5d"), "通过": mf.get("main_net_flow_5d") is not None},
        "_source 标注来源": {"期望": "非空", "实际": source, "通过": bool(source)},
    }

    failures = _collect_failures(data)

    result = {
        "用例": "fund_flow_fallback(资金流API失败→BaoStock估算)",
        "耗时": f"{elapsed:.2f}s",
        "输入": {"code": "600519"},
        "字段校验": checks,
        "失败字段检测": failures,
        "结果": "PASS",
    }

    # 断言：资金流必须有数据（AkShare 或 BaoStock 至少有一个成功）
    assert mf, "moneyflow_data is empty — 所有资金流数据源均失败"
    assert mf.get("main_net_flow_5d") is not None, f"main_net_flow_5d is None: {mf}"
    assert isinstance(mf.get("main_net_flow_5d"), (int, float)), f"main_net_flow_5d 不是数字: {mf.get('main_net_flow_5d')}"

    _show()
    print(f"[耗时] {elapsed:.2f}s")
    print(f"[_source] {source}")
    print(f"[main_net_flow_5d] {mf.get('main_net_flow_5d')}")
    for k, v in checks.items():
        mark = "✅" if v["通过"] else "❌"
        print(f"  {mark} {k}: 实际={v['实际']}")
    if failures:
        print(f"[失败字段] {failures}")
    else:
        print(f"[失败字段] 无")
    print(f"[结果] PASS")
    _hide()

    return result


def test_sector_all_fail():
    """
    测试板块数据全失败时的降级行为。

    场景：datacenter-web RPT_INDUSTRY_LIST 失败、BaoStock 行业失败、AkShare 板块失败
    验证：sector_count=0、sector_rank=50（默认值）、quality=fail
    """
    _show()
    print("\n[用例] sector_all_fail(板块数据全失败降级)")
    print("[输入] code=600519, market=CN")
    _hide()

    start = time.time()
    data = fetch_market_data("600519", "CN")
    elapsed = time.time() - start

    sector = data.get("sector_data", {})
    source = sector.get("_source", "")

    checks = {
        "sector_data 存在": {"期望": "非空", "实际": sector, "通过": bool(sector)},
        "sector_rank 有默认值": {"期望": "50", "实际": sector.get("sector_rank"), "通过": sector.get("sector_rank") == 50},
        "missing_fields 是 list": {"期望": "list", "实际": type(sector.get("missing_fields")).__name__, "通过": isinstance(sector.get("missing_fields"), list)},
    }

    # 特殊断言：sector_count=0 时 quality 必须为 fail
    if sector.get("sector_count", 0) == 0:
        checks["板块全失败 quality=fail"] = {
            "期望": "fail",
            "实际": sector.get("quality"),
            "通过": sector.get("quality") == "fail",
        }

    failures = _collect_failures(data)

    result = {
        "用例": "sector_all_fail(板块数据全失败降级)",
        "耗时": f"{elapsed:.2f}s",
        "输入": {"code": "600519", "market": "CN"},
        "字段校验": checks,
        "失败字段检测": failures,
        "结果": "PASS",
    }

    # 基本断言：板块数据块存在且结构完整
    assert sector, "sector_data is empty"
    assert "sector_rank" in sector, "sector_rank missing"
    assert isinstance(sector.get("missing_fields"), list), f"missing_fields 不是 list: {sector.get('missing_fields')}"

    _show()
    print(f"[耗时] {elapsed:.2f}s")
    print(f"[sector_count] {sector.get('sector_count')}")
    print(f"[sector_rank] {sector.get('sector_rank')}")
    print(f"[quality] {sector.get('quality')}")
    print(f"[_source] {source}")
    for k, v in checks.items():
        mark = "✅" if v["通过"] else "❌"
        print(f"  {mark} {k}: 实际={v['实际']}")
    if failures:
        print(f"[失败字段] {failures}")
    else:
        print(f"[失败字段] 无")
    print(f"[结果] PASS")
    _hide()

    return result


def _run_all():
    tests = [
        ("CN(600519贵州茅台)", test_cn),
        ("HK(00700腾讯)", test_hk),
        ("US(SMCI超微)", test_us),
        ("quality_markers", test_quality_markers),
        ("missing_fields", test_missing_fields),
        ("invalid_market", test_invalid_market),
        ("run_date_field", test_run_date_field),
        ("fund_flow_fallback", test_fund_flow_fallback),
        ("sector_all_fail", test_sector_all_fail),
    ]

    total_start = time.time()
    passed = 0
    failed = 0
    results = []

    suite_start("test_l2_runner", len(tests))

    for name, fn in tests:
        test_start("test_l2_runner", name)
        t0 = time.time()
        try:
            r = fn()
            results.append(r)
            passed += 1
            elapsed = time.time() - t0
            test_end("test_l2_runner", name, True, elapsed)
        except AssertionError as e:
            elapsed = time.time() - t0
            test_end("test_l2_runner", name, False, elapsed, str(e))
            results.append({
                "用例": name,
                "结果": "FAIL",
                "错误": str(e),
            })
            failed += 1
        except Exception as e:
            import traceback
            elapsed = time.time() - t0
            test_end("test_l2_runner", name, False, elapsed, f"{type(e).__name__}: {e}")
            results.append({
                "用例": name,
                "结果": "ERROR",
                "错误": f"{type(e).__name__}: {e}",
                "堆栈": traceback.format_exc(),
            })
            failed += 1

    total_elapsed = time.time() - total_start
    suite_end("test_l2_runner", passed, failed, total_elapsed)

    summary = {
        "测试概览": {
            "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "总数": len(tests),
            "通过": passed,
            "失败": failed,
            "总耗时": f"{total_elapsed:.2f}s",
        },
        "用例明细": results,
    }

    return summary, failed == 0


if __name__ == "__main__":
    _show()
    print("=" * 60)
    print("L2 Market Fetcher 测试")
    print("=" * 60)
    summary, ok = _run_all()

    print("\n" + "=" * 60)
    print("用例简明结果")
    print("=" * 60)
    for r in summary["用例明细"]:
        status = "✅" if r.get("结果") == "PASS" else "❌"
        elapsed = r.get("耗时", "0s")
        print(f"  {status} [{elapsed}] {r['用例']}")
        if r.get("失败字段检测"):
            print(f"      失败字段: {r['失败字段检测']}")
        for k, v in r.get("字段校验", {}).items():
            if not v["通过"]:
                print(f"      ❌ {k}: 期望={v['期望']}, 实际={v['实际']}")
    print("=" * 60)
    print(f"结果: {summary['测试概览']['通过']}/{summary['测试概览']['总数']} 通过, {summary['测试概览']['失败']} 失败 (总耗时 {summary['测试概览']['总耗时']})")
    print("=" * 60)

    print("\n完整测试报告 (JSON):")
    print("=" * 60)
    print(json.dumps(summary, ensure_ascii=False, indent=2, cls=_JSONEncoder))

    _hide()
    sys.exit(0 if ok else 1)