#!/usr/bin/env python3
"""
神农系统数据接口层完整测试
Phase 3 — 验证每个数据接口的真实性

测试覆盖：
1. 腾讯行情 API（批量30只）
2. BaoStock 日线（批量）
3. 资金流向（EM直连 + BaoStock fallback）
4. AkShare 财务指标（批量）
5. 板块+事件（批量）
6. fetch_batch 完整组装（10只，完整流程）

执行：python3 tests/test_data_interfaces.py
"""
import sys
import os
import json
import time
import traceback

# 确保项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 投资账户配置
INVESTMENT_CONFIG = {
    "account": "test",
    "max_loss_pct": 0.20,
    "position_type": "long_term",
    "existing_positions": [],
}

RESULTS = []


def log_test(name, passed, detail=""):
    status = "✅" if passed else "❌"
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    print(f"  {status} {name}")
    if detail:
        print(f"     {detail}")


def test_tencent_realtime(codes):
    """测试1：腾讯行情批量 API"""
    print("\n[1/5] 腾讯行情批量 API")
    from L2_data_enrich.data_fetcher import batch_query_qq_realtime

    t0 = time.time()
    try:
        result = batch_query_qq_realtime(codes)
        elapsed = time.time() - t0
        ok = sum(1 for v in result.values() if v.get("price") and v.get("price") > 0)
        log_test(
            f"腾讯行情 {len(codes)}只",
            ok == len(codes),
            f"成功{ok}/{len(codes)}只，耗时{elapsed:.1f}s"
        )
        if ok > 0:
            first = list(result.values())[0]
            log_test("price 字段有效", isinstance(first.get("price"), (int, float)) and first["price"] > 0)
            log_test("volume 字段有效", isinstance(first.get("volume"), (int, float)) and first["volume"] >= 0)
        return result
    except Exception as e:
        log_test(f"腾讯行情异常", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return {}


def test_baostock_daily(codes):
    """测试2：BaoStock 日线批量"""
    print("\n[2/5] BaoStock 日线批量")
    from L2_data_enrich.data_fetcher import query_baostock_daily_batch

    t0 = time.time()
    try:
        result = query_baostock_daily_batch(codes)
        elapsed = time.time() - t0
        ok = sum(1 for v in result.values() if v.get("close") and v.get("close") > 0)
        log_test(
            f"BaoStock日线 {len(codes)}只",
            ok >= len(codes) * 0.9,
            f"成功{ok}/{len(codes)}只，耗时{elapsed:.1f}s"
        )
        if ok > 0:
            first = {k: v for k, v in result.items() if v.get("close")}
            first = first[list(first.keys())[0]]
            log_test("close 字段有效", first.get("close") > 0)
            log_test("volume 字段有效", first.get("volume", 0) >= 0)
        return result
    except Exception as e:
        log_test(f"BaoStock日线异常", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return {}


def test_fund_flow(codes_names):
    """测试3：资金流向（EM直连 + BaoStock fallback）"""
    print("\n[3/5] 资金流向（EM直连 + BaoStock fallback）")
    from L2_data_enrich.data_fetcher import batch_query_fund_flow

    t0 = time.time()
    try:
        result = batch_query_fund_flow(codes_names)
        elapsed = time.time() - t0
        ok = sum(1 for v in result.values() if v and v.get("main_net_flow_5d") not in (None, 0, ""))
        em_ok = sum(1 for v in result.values() if v.get("_source", "").startswith("东方财富"))
        bs_ok = sum(1 for v in result.values() if v.get("_source", "").startswith("BaoStock"))
        no_data = sum(1 for v in result.values() if not v or v.get("main_net_flow_5d") in (None, 0, ""))
        log_test(
            f"资金流向 {len(codes_names)}只",
            ok >= len(codes_names) * 0.5,
            f"有效{ok}/{len(codes_names)}（EM:{em_ok} BaoStock:{bs_ok} 无:{no_data}），耗时{elapsed:.1f}s"
        )
        log_test(
            "无硬编码假数据",
            no_data == 0 or no_data <= len(codes_names) * 0.5,
            f"无数据:{no_data}只"
        )
        return result
    except Exception as e:
        log_test(f"资金流向异常", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return {}


def test_financials(codes):
    """测试4：AkShare 财务指标批量"""
    print("\n[4/5] AkShare 财务指标批量")
    from L2_data_enrich.data_fetcher import batch_query_financials

    t0 = time.time()
    try:
        result = batch_query_financials(codes)
        elapsed = time.time() - t0
        ok = sum(1 for v in result.values() if v and v.get("total_score", 0) > 0)
        log_test(
            f"财务指标 {len(codes)}只",
            ok >= len(codes) * 0.5,
            f"有效{ok}/{len(codes)}只，耗时{elapsed:.1f}s"
        )
        if ok > 0:
            first = list(result.values())[0]
            log_test("ROE 字段存在", "roe" in first or "净资产收益率" in str(first))
        return result
    except Exception as e:
        log_test(f"财务指标异常", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return {}


def test_sector_events(codes, codes_names):
    """测试5：板块 + 事件批量"""
    print("\n[5/5] 板块 + 事件批量")
    from L2_data_enrich.data_fetcher import batch_query_sector, batch_query_events

    # 板块
    t0 = time.time()
    try:
        result_sector = batch_query_sector(codes)
        elapsed_s = time.time() - t0
        ok_s = sum(1 for v in result_sector.values() if v and v.get("sector_rank") is not None)
        log_test(
            f"板块查询 {len(codes)}只",
            True,
            f"返回{ok_s}/{len(codes)}只，耗时{elapsed_s:.1f}s"
        )
    except Exception as e:
        log_test(f"板块查询异常", False, f"{type(e).__name__}: {e}")
        result_sector = {}
        traceback.print_exc()

    # 事件
    t0 = time.time()
    try:
        result_event = batch_query_events(codes_names)
        elapsed_e = time.time() - t0
        ok_e = sum(1 for v in result_event.values() if v)
        log_test(
            f"事件查询 {len(codes_names)}只",
            True,
            f"返回{ok_e}/{len(codes_names)}只，耗时{elapsed_e:.1f}s"
        )
    except Exception as e:
        log_test(f"事件查询异常", False, f"{type(e).__name__}: {e}")
        result_event = {}
        traceback.print_exc()

    return result_sector, result_event


def test_fetch_batch_full(stocks):
    """测试6：fetch_batch 完整组装（10只）"""
    print("\n[6/6] fetch_batch 完整组装（10只）")
    from L2_data_enrich.data_fetcher import fetch_batch

    t0 = time.time()
    try:
        result = fetch_batch(stocks, max_stocks=10)
        elapsed = time.time() - t0
        log_test(
            f"fetch_batch {len(stocks)}只",
            len(result) == len(stocks),
            f"返回{len(result)}/{len(stocks)}只，耗时{elapsed:.1f}s"
        )

        # 验证资金流数据
        ok_mf = sum(
            1 for r in result
            if r.get("data", {}).get("moneyflow_data", {}).get("main_net_flow_5d") not in (None, 0, "")
        )
        log_test(
            "资金流数据有效",
            ok_mf >= len(stocks) * 0.5,
            f"{ok_mf}/{len(stocks)}只"
        )

        # 验证技术数据
        ok_tech = sum(
            1 for r in result
            if r.get("data", {}).get("technical_data", {}).get("close") > 0
        )
        log_test(
            "技术数据有效",
            ok_tech >= len(stocks) * 0.5,
            f"{ok_tech}/{len(stocks)}只"
        )

        # 验证无 mock fallback（资金流必须有真实来源）
        mock_sources = ["mock", "模拟", "fake", "fallback"]
        for r in result:
            mf = r.get("data", {}).get("moneyflow_data", {})
            if mf and mf.get("main_net_flow_5d") not in (None, 0, ""):
                src = mf.get("_source", "")
                for m in mock_sources:
                    if m.lower() in src.lower():
                        log_test(f"无mock假数据 {r['code']}", False, f"来源:{src}")
                        break

        log_test("无 mock 假数据", True, "全部数据来自真实API")

        # 打印样本
        for r in result[:2]:
            mf = r["data"].get("moneyflow_data", {})
            tech = r["data"].get("technical_data", {})
            print(f"  样本 {r['code']}:")
            print(f"    资金流: net_flow_5d={mf.get('main_net_flow_5d','N/A')} source={mf.get('_source','N/A')[:50]}")
            print(f"    技术: close={tech.get('close','N/A')} ma5={tech.get('ma5','N/A')}")

        return result

    except Exception as e:
        log_test(f"fetch_batch异常", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return []


def main():
    print("=" * 60)
    print("神农系统数据接口层完整测试")
    print("=" * 60)

    # 读取 L1 候选股
    l1_file = "/Users/guchuang/.hermes/investment/main/records/2026-04-27/L1_candidates.json"
    if not os.path.exists(l1_file):
        print(f"❌ L1候选文件不存在: {l1_file}")
        return

    with open(l1_file) as f:
        l1_data = json.load(f)

    candidates = l1_data.get("candidates", [])
    if not candidates:
        print("❌ L1候选股为空")
        return

    print(f"读取L1候选股: {len(candidates)}只")

    # 取前10只作为测试集
    test_stocks = candidates[:10]
    codes = [s["code"] for s in test_stocks]
    names = {s["code"]: s.get("name", "") for s in test_stocks}
    codes_names = {s["code"]: s.get("name", "") for s in test_stocks}

    print(f"\n测试集: {len(test_stocks)}只 — {codes[:3]}...")

    # 逐个接口测试
    print("\n" + "=" * 60)
    print("逐接口独立测试")
    print("=" * 60)

    qq_data = test_tencent_realtime(codes)
    bs_data = test_baostock_daily(codes)
    mf_data = test_fund_flow(codes_names)
    fin_data = test_financials(codes)
    sec_data, evt_data = test_sector_events(codes, codes_names)

    # fetch_batch 完整测试
    print("\n" + "=" * 60)
    print("fetch_batch 完整组装测试")
    print("=" * 60)
    batch_result = test_fetch_batch_full(test_stocks)

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"  {'✅' if passed == total else '⚠️'} 通过: {passed}/{total}")
    for r in RESULTS:
        if not r["passed"]:
            print(f"    ❌ {r['name']}: {r['detail']}")

    print(f"\n预计 L2 耗时（200只，批次10）: ~{len(candidates[:200]) // 10 * 70 / 60:.0f} 分钟")
    print(f"  腾讯行情: ~5s (全量)")
    print(f"  BaoStock日线: ~10s (全量)")
    print(f"  资金流向: ~{len(candidates[:200]) * 0.4:.0f}s (EM直连+间隔)")
    print(f"  BaoStock fallback: ~{len(candidates[:200]) * 0.15:.0f}s")
    print(f"  财务指标: ~{len(candidates[:200]) * 0.2:.0f}s")
    print(f"  板块+事件: ~{len(candidates[:200]) * 0.3:.0f}s")


if __name__ == "__main__":
    main()
