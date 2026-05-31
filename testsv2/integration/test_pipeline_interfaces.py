#!/usr/bin/env python3
"""
神农系统 — 分层接口完整验证脚本
================================
目标：逐层验证每个接口的真实行为（成功率/耗时/数据质量）
原则：
  1. 不凭猜测，每步实测
  2. 数据缺失 → 标记 None，不补中性假值
  3. timeout 只做兜底，不做主要流量控制
  4. 每个接口独立测，记录真实结果

运行：python3 tests/test_pipeline_interfaces.py
"""

import sys, time, json, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from L2_data_enrich import data_fetcher as df

TODAY_STR = datetime.now().strftime('%Y-%m-%d')
REPORT = []  # 收集所有测试结果

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}" + (f" → {detail}" if detail else ""))
    REPORT.append({"check": label, "pass": bool(condition), "detail": str(detail) if detail else ""})
    return bool(condition)

def timing(label, elapsed, threshold_s):
    ok = elapsed < threshold_s
    print(f"  {'✅' if ok else '⚠️'} {label}: {elapsed:.1f}s < {threshold_s}s → {'OK' if ok else f'超过阈值({elapsed:.1f}s)'}")
    REPORT.append({"check": label, "pass": ok, "elapsed_s": round(elapsed, 2), "threshold_s": threshold_s})
    return ok

def save_report():
    path = "/tmp/interface_test_report.json"
    with open(path, 'w') as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print(f"\n📄 报告已保存: {path}")


# ─────────────────────────────────────────────────────────
# TEST SETUP: 统一测试名单
# ─────────────────────────────────────────────────────────
TEST_CODES_SMALL  = ['600519', '000858', '601318', '600036', '000001']  # 5只
TEST_CODES_MEDIUM  = TEST_CODES_SMALL + ['600887', '601166', '600016', '601328', '600030',
                                           '000002', '601398', '601939', '600000', '601288',
                                           '601818', '600028', '601088', '601601', '600809']  # 20只
TEST_NAMES = {c: '' for c in TEST_CODES_MEDIUM}


# ─────────────────────────────────────────────────────────
# LAYER 0: 语法 & import 验证
# ─────────────────────────────────────────────────────────
section("LAYER 0: 模块导入 & 语法")

try:
    import L2_data_enrich.data_fetcher as df
    import main.shennong as sn
    check("data_fetcher 模块导入", True)
except Exception as e:
    check("data_fetcher 模块导入", False, str(e))

try:
    from L2_data_enrich.data_fetcher import (
        batch_query_fund_flow, batch_query_qq_realtime,
        batch_query_financials, batch_query_events,
        query_baostock_daily_batch, estimate_fund_flow_from_kline,
        _fetch_single_fund_flow_eastmoney,
        batch_query_sector,
    )
    check("所有批量函数可导入", True)
except Exception as e:
    check("所有批量函数可导入", False, str(e))

try:
    import akshare as ak
    check("AkShare 可用", True)
except:
    check("AkShare 可用", False)

try:
    import baostock as bs
    bs.login()
    bs.logout()
    check("BaoStock 可用", True)
except Exception as e:
    check("BaoStock 可用", False, str(e))


# ─────────────────────────────────────────────────────────
# LAYER 1: 腾讯行情 API
# ─────────────────────────────────────────────────────────
section("LAYER 1: 腾讯行情 batch_query_qq_realtime")

t0 = time.time()
r1 = batch_query_qq_realtime(TEST_CODES_SMALL)
t1 = time.time()

ok1_count = sum(1 for v in r1.values() if v and v.get('price') is not None)
ok1 = check(f"腾讯行情 返回率", ok1_count == len(TEST_CODES_SMALL),
            f"{ok1_count}/{len(TEST_CODES_SMALL)} 有 price 字段")
timing(f"腾讯行情 耗时(5只)", t1-t0, 5.0)

# 验证关键字段存在
if r1:
    sample = list(r1.values())[0]
    price_field_ok = 'price' in sample or 'current_price' in sample
    check("腾讯行情 price 字段", price_field_ok,
          f"字段={list(sample.keys())[:5]}")
    name_ok = 'name' in sample
    check("腾讯行情 name 字段", name_ok)
    vol_ok = 'volume' in sample
    check("腾讯行情 volume 字段", vol_ok)


# ─────────────────────────────────────────────────────────
# LAYER 2: 东方财富资金流 API（单只）
# ─────────────────────────────────────────────────────────
section("LAYER 2: 东方财富资金流 _fetch_single_fund_flow_eastmoney (单只重试3次)")

em_success_count = 0
for code in TEST_CODES_SMALL[:3]:
    for attempt in range(1, 4):
        d = _fetch_single_fund_flow_eastmoney(code, '')
        ok = d and isinstance(d, dict) and d.get('main_net_flow_5d') not in (None, 0, '')
        if ok:
            em_success_count += 1
            print(f"  ✅ {code} 第{attempt}次成功: flow={d.get('main_net_flow_5d')}, source={d.get('_source')}")
            break
        else:
            print(f"  ⚠️  {code} 第{attempt}次失败, source={d.get('_source') if d else 'None'}")
        time.sleep(1)

check("东方财富资金流 单只成功率", em_success_count > 0,
      f"3只中{em_success_count}只成功（若=0则是API本身挂了，非代码bug）")


# ─────────────────────────────────────────────────────────
# LAYER 3: BaoStock 资金流估算 fallback
# ─────────────────────────────────────────────────────────
section("LAYER 3: BaoStock 资金流估算 estimate_fund_flow_from_kline")

t0 = time.time()
ba_success = 0
for code in TEST_CODES_SMALL:
    d = estimate_fund_flow_from_kline(code, '')
    ok = d and isinstance(d, dict) and d.get('main_net_flow_5d') not in (None, 0, '')
    if ok:
        ba_success += 1
timed = time.time() - t0

check("BaoStock 资金流估算成功率", ba_success == len(TEST_CODES_SMALL),
      f"{ba_success}/{len(TEST_CODES_SMALL)}")
timing(f"BaoStock 资金流估算 耗时({len(TEST_CODES_SMALL)}只)", timed, 10.0)


# ─────────────────────────────────────────────────────────
# LAYER 4: 批量资金流 batch_query_fund_flow（分批 + 串行东方财富 + BaoStock fallback）
# ─────────────────────────────────────────────────────────
section("LAYER 4: 批量资金流 batch_query_fund_flow（20只，串行东方财富→BaoStock fallback）")

t0 = time.time()
r4 = batch_query_fund_flow(TEST_NAMES)
t4 = time.time()

ok4_total = sum(1 for v in r4.values() if v and v.get('main_net_flow_5d') not in (None, 0, ''))
em4 = sum(1 for v in r4.values() if v and str(v.get('_source','')).startswith('东方财富'))
ba4 = sum(1 for v in r4.values() if v and str(v.get('_source','')).startswith('BaoStock'))
none4 = sum(1 for v in r4.values() if not v or v.get('main_net_flow_5d') in (None, 0, ''))

check("批量资金流 总有效率", ok4_total == len(TEST_NAMES),
      f"{ok4_total}/{len(TEST_NAMES)} (EM:{em4} BaoStock:{ba4} 无:{none4})")
timing(f"批量资金流 耗时(20只)", t4-t0, 60.0)  # 串行东方财富约45-50s，接受60s阈值

# 验证：所有结果必须有 _source 字段标记来源（严禁假兜底）
all_have_source = all(v and '_source' in v for v in r4.values() if v)
check("批量资金流 所有结果有 _source 标记", all_have_source,
      "每个结果必须标记来源，不允许无标记的隐式兜底")


# ─────────────────────────────────────────────────────────
# LAYER 5: BaoStock 日线 batch
# ─────────────────────────────────────────────────────────
section("LAYER 5: BaoStock 日线 query_baostock_daily_batch (20只)")

t0 = time.time()
r5 = query_baostock_daily_batch(TEST_CODES_MEDIUM)
t5 = time.time()

ok5 = sum(1 for v in r5.values() if v is not None and not v.empty)
check("BaoStock 日线 成功率", ok5 == len(TEST_CODES_MEDIUM), f"{ok5}/{len(TEST_CODES_MEDIUM)}")
timing(f"BaoStock 日线 耗时(20只)", t5-t0, 15.0)

if r5.get(TEST_CODES_MEDIUM[0]) is not None:
    df5 = r5[TEST_CODES_MEDIUM[0]]
    has_ohlcv = all(col in df5.columns for col in ['open','high','low','close','volume'])
    check("BaoStock 日线 包含 OHLCV 字段", has_ohlcv, f"列={list(df5.columns)}")
    latest_close = df5.iloc[-1]['close']
    check("BaoStock 日线 最新收盘价合理", 0 < latest_close < 100000,
          f"{TEST_CODES_MEDIUM[0]} 最新收盘={latest_close}")


# ─────────────────────────────────────────────────────────
# LAYER 6: AkShare 财务 batch
# ─────────────────────────────────────────────────────────
section("LAYER 6: AkShare 财务 batch_query_financials (10只)")

t0 = time.time()
r6 = batch_query_financials(TEST_CODES_SMALL)
t6 = time.time()

ok6 = sum(1 for v in r6.values() if v and isinstance(v, dict) and len(v) > 0)
check("AkShare 财务 成功率", ok6 == len(TEST_CODES_SMALL), f"{ok6}/{len(TEST_CODES_SMALL)}")
timing(f"AkShare 财务 耗时(5只)", t6-t0, 30.0)

if r6.get(TEST_CODES_SMALL[0]):
    d6 = r6[TEST_CODES_SMALL[0]]
    has_roe = 'roe' in d6 or 'ROE' in d6
    check("AkShare 财务 包含 ROE 字段", has_roe, f"字段={list(d6.keys())}")
    has_source = '_source' in d6
    check("AkShare 财务 有 _source 标记", has_source, f"source={d6.get('_source','无')}")


# ─────────────────────────────────────────────────────────
# LAYER 7: AkShare 事件 batch
# ─────────────────────────────────────────────────────────
section("LAYER 7: AkShare 事件 batch_query_events (10只)")

t0 = time.time()
r7 = batch_query_events(TEST_NAMES)
t7 = time.time()

ok7 = sum(1 for v in r7.values() if v and isinstance(v, dict) and len(v) > 0)
check("AkShare 事件 成功率", ok7 == len(TEST_NAMES), f"{ok7}/{len(TEST_NAMES)}")
timing(f"AkShare 事件 耗时(10只)", t7-t0, 30.0)


# ─────────────────────────────────────────────────────────
# LAYER 8: 板块 batch_query_sector
# ─────────────────────────────────────────────────────────
section("LAYER 8: AkShare 板块 batch_query_sector (10只)")

t0 = time.time()
r8 = batch_query_sector(TEST_CODES_SMALL)
t8 = time.time()

ok8 = sum(1 for v in r8.values() if v and isinstance(v, (dict, list)))
check("AkShare 板块 成功率", ok8 == len(TEST_CODES_SMALL), f"{ok8}/{len(TEST_CODES_SMALL)}")
timing(f"AkShare 板块 耗时(5只)", t8-t0, 15.0)


# ─────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────
section("测试结果汇总")

passed = sum(1 for r in REPORT if r.get('pass'))
total  = len(REPORT)
print(f"\n  通过率: {passed}/{total} ({100*passed//total}%)\n")

critical_fails = [r for r in REPORT if not r.get('pass') and
                  any(k in r['check'] for k in ['成功率', '总有效率', '导入', '可用'])]
if critical_fails:
    print("  ⚠️  关键失败项:")
    for r in critical_fails:
        print(f"    ❌ {r['check']}: {r.get('detail','')}")
else:
    print("  ✅ 无关键失败项")

save_report()
print(f"\n{'='*60}")
print(f"  全部接口测试完成 {datetime.now().strftime('%H:%M:%S')}")
print(f"{'='*60}")
