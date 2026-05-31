#!/usr/bin/env python3
"""
三市场全链路测试 — 用户主动选股场景
测试A股(茅台)、港股(美团)、美股(台积电)全链路是否存在问题

使用方式:
  python test_cross_market.py                # 三市场全测
  python test_cross_market.py --market CN   # 只测A股
  python test_cross_market.py --market HK    # 只测港股
  python test_cross_market.py --market US    # 只测美股
  python test_cross_market.py --market CN   # 只测A股

触发条件(自动执行):
  - 完成技术侧改造后
  - 用户要求"测试输出模式"时
"""
import sys
import os
import time
import argparse
from datetime import datetime

PROJECT_ROOT = os.path.expanduser("~/.hermes/investment")
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

TODAY = datetime.now().strftime("%Y-%m-%d")
TEST_RESULTS = []  # 收集各市场测试结果


def test_market_cn(symbol: str = "600519", name: str = "贵州茅台") -> dict:
    """测试A股全链路"""
    from main.shennong import run_pipeline

    print(f"\n{'='*60}")
    print(f"  A股测试: {symbol} {name}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        result = run_pipeline(
            symbols=[symbol],
            market="CN",
            mode="L4",
        )
        elapsed = time.time() - t0

        # 检查各层状态
        layers = {
            "L1": result.get("L1"),
            "L2": result.get("L2"),
            "L3": result.get("L3"),
            "L4": result.get("L4"),
            "report": result.get("report"),
        }

        l2_stocks = result.get("L2", {}).get("stocks", [])
        l3_results = result.get("L3", {}).get("results", [])
        l4_decisions = result.get("L4", {}).get("decisions", [])

        status = {
            "market": "CN",
            "code": symbol,
            "name": name,
            "elapsed_s": round(elapsed, 1),
            "L1_ok": bool(result.get("L1")),
            "L2_stocks": len(l2_stocks),
            "L3_scores": len(l3_results),
            "L4_decisions": len(l4_decisions),
            "report_len": len(result.get("report") or ""),
            "report": result.get("report"),
            "error": None,
        }

        # 打印报告摘要
        report = result.get("report") or ""
        if report:
            print("--- 报告片段(前800字) ---")
            print(report[:800])
        else:
            print("⚠️ 报告为空!")

        print(f"\n✅ A股 {symbol} 全链路完成 | L2:{len(l2_stocks)}只 L3:{len(l3_results)}只 L4:{len(l4_decisions)}只 | 耗时{elapsed:.0f}s")
        return status

    except Exception as e:
        import traceback
        print(f"❌ A股 {symbol} 全链路失败: {e}")
        traceback.print_exc()
        return {
            "market": "CN", "code": symbol, "name": name,
            "elapsed_s": round(time.time() - t0, 1),
            "error": str(e),
            "L1_ok": False, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }


def test_market_hk(symbol: str = "3690", name: str = "美团") -> dict:
    """测试港股全链路"""
    from main.shennong import run_pipeline

    print(f"\n{'='*60}")
    print(f"  港股测试: {symbol} {name}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        # 港股代码格式: 5位数字如 03690 → 3690
        code5 = symbol.strip().lstrip('HK').lstrip('0').zfill(5)
        result = run_pipeline(
            symbols=[code5],
            market="HK",
            mode="L4",
        )
        elapsed = time.time() - t0

        l4_decisions = result.get("L4", {}).get("decisions", [])
        report = result.get("report") or ""

        status = {
            "market": "HK",
            "code": symbol,
            "name": name,
            "elapsed_s": round(elapsed, 1),
            "L1_ok": True,
            "L2_stocks": len(result.get("L2", {}).get("stocks", [])),
            "L3_scores": len(result.get("L3", {}).get("results", [])),
            "L4_decisions": len(l4_decisions),
            "report_len": len(report),
            "report": report,
            "error": None,
        }

        if report:
            print("--- 报告片段(前800字) ---")
            print(report[:800])
        else:
            print("⚠️ 报告为空!")

        print(f"\n✅ 港股 {symbol} 全链路完成 | L3:{len(result.get('L3',{}).get('results',[]))}只 L4:{len(l4_decisions)}只 | 耗时{elapsed:.0f}s")
        return status

    except Exception as e:
        import traceback
        print(f"❌ 港股 {symbol} 全链路失败: {e}")
        traceback.print_exc()
        return {
            "market": "HK", "code": symbol, "name": name,
            "elapsed_s": round(time.time() - t0, 1),
            "error": str(e),
            "L1_ok": True, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }


def test_market_us(ticker: str = "TSM", name: str = "台积电") -> dict:
    """测试美股全链路"""
    from main.shennong import run_pipeline

    print(f"\n{'='*60}")
    print(f"  美股测试: {ticker} {name}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        ticker_clean = ticker.strip().lstrip('US').strip().upper()
        result = run_pipeline(
            symbols=[ticker_clean],
            market="US",
            mode="L4",
        )
        elapsed = time.time() - t0

        l4_decisions = result.get("L4", {}).get("decisions", [])
        report = result.get("report") or ""

        status = {
            "market": "US",
            "code": ticker,
            "name": name,
            "elapsed_s": round(elapsed, 1),
            "L1_ok": True,
            "L2_stocks": len(result.get("L2", {}).get("stocks", [])),
            "L3_scores": len(result.get("L3", {}).get("results", [])),
            "L4_decisions": len(l4_decisions),
            "report_len": len(report),
            "report": report,
            "error": None,
        }

        if report:
            print("--- 报告片段(前800字) ---")
            print(report[:800])
        else:
            print("⚠️ 报告为空!")

        print(f"\n✅ 美股 {ticker} 全链路完成 | L3:{len(result.get('L3',{}).get('results',[]))}只 L4:{len(l4_decisions)}只 | 耗时{elapsed:.0f}s")
        return status

    except Exception as e:
        import traceback
        print(f"❌ 美股 {ticker} 全链路失败: {e}")
        traceback.print_exc()
        return {
            "market": "US", "code": ticker, "name": name,
            "elapsed_s": round(time.time() - t0, 1),
            "error": str(e),
            "L1_ok": True, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }


def print_summary():
    """打印测试汇总"""
    print(f"\n\n{'#'*70}")
    print(f"  三市场全链路测试汇总 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'#'*70}")

    total_ok = 0
    total_fail = 0

    for r in TEST_RESULTS:
        mkt = r["market"]
        code = r["code"]
        name = r["name"]
        ok = r["error"] is None
        elapsed = r["elapsed_s"]

        if ok:
            total_ok += 1
            icon = "✅"
            # 检查各层完整性
            layer_check = []
            if mkt == "CN":
                if not r["L1_ok"]: layer_check.append("L1❌")
                if r["L2_stocks"] == 0: layer_check.append("L2❌")
            if r["L3_scores"] == 0: layer_check.append("L3❌")
            if r["L4_decisions"] == 0: layer_check.append("L4❌")
            if r["report_len"] < 200: layer_check.append("报告❌")
            check_str = " | ".join(layer_check) if layer_check else "全层✅"
        else:
            total_fail += 1
            icon = "❌"
            check_str = f"错误: {r['error']}"

        print(f"\n{icon} {mkt} {code} {name}")
        print(f"   耗时: {elapsed}s | 报告: {r['report_len']}字")
        print(f"   {check_str}")

    print(f"\n{'─'*70}")
    print(f"汇总: ✅{total_ok} 只 | ❌{total_fail} 只")
    print(f"{'─'*70}")

    # 返回码: 0=全部通过, 1=有失败
    return 1 if total_fail > 0 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="三市场全链路测试")
    parser.add_argument("--market", default="ALL",
                        choices=["ALL", "CN", "HK", "US"],
                        help="测试市场(默认ALL三市场)")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="自定义测试标的，格式: CN:600519 HK:3690 US:TSM")
    args = parser.parse_args()

    print(f"🌾 神农系统三市场全链路测试 — {TODAY}")
    print(f"模式: {args.market}")

    # 解析自定义标的
    if args.symbols:
        test_list = []
        for s in args.symbols:
            if ':' in s:
                mkt, code = s.split(':', 1)
                test_list.append((mkt.upper(), code))
            else:
                test_list.append(('CN', s))
    else:
        test_list = [
            ('CN', '600519'),  # 贵州茅台
            ('HK', '3690'),    # 美团
            ('US', 'TSM'),     # 台积电
        ]

    # 根据market过滤
    if args.market != "ALL":
        test_list = [(m, c) for m, c in test_list if m == args.market]

    # 执行测试
    for mkt, code in test_list:
        if mkt == "CN":
            r = test_market_cn(code, name={
                '600519': '贵州茅台',
            }.get(code, code))
        elif mkt == "HK":
            r = test_market_hk(code, name={
                '3690': '美团',
            }.get(code, code))
        elif mkt == "US":
            r = test_market_us(code, name={
                'TSM': '台积电',
            }.get(code, code))
        TEST_RESULTS.append(r)

    # 汇总
    exit_code = print_summary()
    sys.exit(exit_code)
