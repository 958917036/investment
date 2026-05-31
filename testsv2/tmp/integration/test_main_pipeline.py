#!/usr/bin/env python3
"""
main/shennong.py 全链路测试 — 基于 PipelineContext 直接调用
测试A股(茅台)、港股(美团)、美股(台积电)全链路是否符合预期

使用方式:
  python test_main_pipeline.py                # 三市场全测
  python test_main_pipeline.py --market CN   # 只测A股
  python test_main_pipeline.py --market HK    # 只测港股
  python test_main_pipeline.py --market US    # 只测美股

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
TEST_RESULTS = []


def test_market_cn(symbol: str = "600519", name: str = "贵州茅台") -> dict:
    """测试A股全链路

    入参:
      symbol: A股代码(6位纯数字，如600519)
      name: 股票名称
    """
    from main.shennong import run_pipeline
    from main.contracts import PipelineContext, Market, load_all_config

    print(f"\n{'='*60}")
    print(f"  A股测试: {symbol} {name}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        ctx = PipelineContext(
            run_date=TODAY,
            market=Market.CN,
            mode="L4",
        )
        ctx = load_all_config(ctx)

        # 强制限制 L1 只返回此股票(by_code)
        ctx.l1_config["_force_symbols"] = [symbol]
        ctx.l1_config["_force_mode"] = "by_code"

        result = run_pipeline(ctx)
        elapsed = time.time() - t0

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

        # 断言
        assert result.get("L1"), "L1 必须有结果"
        assert len(l2_stocks) >= 1, f"L2 必须有数据，实际{len(l2_stocks)}"
        assert len(l3_results) >= 1, f"L3 必须有数据，实际{len(l3_results)}"
        assert len(l4_decisions) >= 1, f"L4 必须有裁定结果，实际{len(l4_decisions)}"
        assert result.get("report"), "report 不能为空"

        # L2 字段校验
        s = l2_stocks[0]
        price = s.get("technical_data", {}).get("price")
        assert price and price > 0, f"price 必须>0，实际{price}"
        assert s.get("code") == symbol, f"code 必须为{symbol}，实际{s.get('code')}"
        pe = s.get("fundamental_data", {}).get("pe")
        roe = s.get("fundamental_data", {}).get("roe")

        # L3 字段校验
        r = l3_results[0]
        score_dict = r.get("score", {})
        assert "five_score" in score_dict or "five_score" in r, "L3 结果必须有 five_score（in score or top-level）"
        l3_five_score = score_dict.get("five_score") or r.get("five_score")
        l3_grade = score_dict.get("grade") or r.get("grade")
        l3_quality = r.get("quality") or score_dict.get("quality") or "ok"
        assert l3_five_score is not None, f"L3 five_score 不能为 None，实际r={r}"
        assert l3_quality in ("ok", "degraded"), f"L3 quality 必须为 ok/degraded，实际{l3_quality}"

        # L4 字段校验
        d = l4_decisions[0]
        assert "decision" in d, "L4 decision 必须存在"
        assert d.get("decision") in ("BUY", "WATCH", "REJECT", "HOLD"), f"L4 decision 值异常: {d.get('decision')}"
        assert "judge_score" in d, "L4 judge_score 必须存在"

        print(f"  输入: by_code, code={symbol}")
        print(f"  预期: stock_count=1, name={name}")
        print(f"  实际: L2={len(l2_stocks)}只, L3={len(l3_results)}只, L4={len(l4_decisions)}只")
        print(f"  L2[0] price={price}, pe={pe}, roe={roe}")
        print(f"  L3[0] five_score={l3_five_score}, grade={l3_grade}, quality={l3_quality}")
        print(f"  L4[0] decision={d.get('decision')}, judge_score={d.get('judge_score'):.3f}")
        print(f"  耗时: {elapsed:.2f}秒")
        print(f"\n✅ A股 {symbol} 全链路 PASS | 耗时{elapsed:.0f}s")
        return status

    except AssertionError as ae:
        print(f"  ❌ 断言失败: {ae}")
        return {
            "market": "CN", "code": symbol, "name": name,
            "elapsed_s": round(time.time() - t0, 1),
            "error": f"断言失败: {ae}",
            "L1_ok": False, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }
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


def test_market_hk(symbol: str = "09999", name: str = "邮储银行") -> dict:
    """测试港股全链路

    入参:
      symbol: 港股代码(5位数字，如03690→3690)
      name: 股票名称
    """
    from main.shennong import run_pipeline
    from main.contracts import PipelineContext, Market, load_all_config

    print(f"\n{'='*60}")
    print(f"  港股测试: {symbol} {name}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        # 港股代码格式: 5位数字如 03690 → 3690, 09999 → 9999
        code5 = symbol.strip().lstrip('HK').lstrip('0').zfill(5)

        ctx = PipelineContext(
            run_date=TODAY,
            market=Market.HK,
            mode="L4",
        )
        ctx = load_all_config(ctx)

        # 强制限制 L1 只返回此股票
        ctx.l1_config["_force_symbols"] = [code5]
        ctx.l1_config["_force_mode"] = "by_code"

        result = run_pipeline(ctx)
        elapsed = time.time() - t0

        l2_stocks = result.get("L2", {}).get("stocks", [])
        l3_results = result.get("L3", {}).get("results", [])
        l4_decisions = result.get("L4", {}).get("decisions", [])

        status = {
            "market": "HK",
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

        # 断言
        assert len(l2_stocks) >= 1, f"L2 必须有数据，实际{len(l2_stocks)}"
        assert len(l3_results) >= 1, f"L3 必须有数据，实际{len(l3_results)}"
        assert len(l4_decisions) >= 1, f"L4 必须有裁定结果，实际{len(l4_decisions)}"

        # L2 字段校验(港股)
        s = l2_stocks[0]
        price = s.get("technical_data", {}).get("price")
        assert price and price > 0, f"price 必须>0，实际{price}"

        # L3 字段校验
        r = l3_results[0]
        score_dict = r.get("score", {})
        l3_five_score = score_dict.get("five_score") or r.get("five_score")
        l3_grade = score_dict.get("grade") or r.get("grade")

        # L4 字段校验
        d = l4_decisions[0]
        assert "decision" in d, "L4 decision 必须存在"
        assert "judge_score" in d, "L4 judge_score 必须存在"

        print(f"  输入: by_code, code={code5}")
        print(f"  预期: stock_count=1, name={name}")
        print(f"  实际: L2={len(l2_stocks)}只, L3={len(l3_results)}只, L4={len(l4_decisions)}只")
        print(f"  L2[0] price={price}, sector={s.get('sector_data',{}).get('related_sector')}")
        print(f"  L3[0] five_score={l3_five_score}, grade={l3_grade}")
        print(f"  L4[0] decision={d.get('decision')}, judge_score={d.get('judge_score'):.3f}")
        print(f"  耗时: {elapsed:.2f}秒")
        print(f"\n✅ 港股 {symbol} 全链路 PASS | 耗时{elapsed:.0f}s")
        return status

    except AssertionError as ae:
        print(f"  ❌ 断言失败: {ae}")
        return {
            "market": "HK", "code": symbol, "name": name,
            "elapsed_s": round(time.time() - t0, 1),
            "error": f"断言失败: {ae}",
            "L1_ok": False, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }
    except Exception as e:
        import traceback
        print(f"❌ 港股 {symbol} 全链路失败: {e}")
        traceback.print_exc()
        return {
            "market": "HK", "code": symbol, "name": name,
            "elapsed_s": round(time.time() - t0, 1),
            "error": str(e),
            "L1_ok": False, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }


def test_market_us(ticker: str = "TSM", name: str = "台积电") -> dict:
    """测试美股全链路

    入参:
      ticker: 美股代码(如TSM)
      name: 股票名称
    """
    from main.shennong import run_pipeline
    from main.contracts import PipelineContext, Market, load_all_config

    print(f"\n{'='*60}")
    print(f"  美股测试: {ticker} {name}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        ticker_clean = ticker.strip().lstrip('US').strip().upper()

        ctx = PipelineContext(
            run_date=TODAY,
            market=Market.US,
            mode="L4",
        )
        ctx = load_all_config(ctx)

        # 强制限制 L1 只返回此股票
        ctx.l1_config["_force_symbols"] = [ticker_clean]
        ctx.l1_config["_force_mode"] = "by_code"

        result = run_pipeline(ctx)
        elapsed = time.time() - t0

        l2_stocks = result.get("L2", {}).get("stocks", [])
        l3_results = result.get("L3", {}).get("results", [])
        l4_decisions = result.get("L4", {}).get("decisions", [])

        status = {
            "market": "US",
            "code": ticker,
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

        # 断言
        assert len(l2_stocks) >= 1, f"L2 必须有数据，实际{len(l2_stocks)}"
        assert len(l3_results) >= 1, f"L3 必须有数据，实际{len(l3_results)}"
        assert len(l4_decisions) >= 1, f"L4 必须有裁定结果，实际{len(l4_decisions)}"

        # L2 字段校验(美股)
        s = l2_stocks[0]
        price = s.get("technical_data", {}).get("price")
        assert price and price > 0, f"price 必须>0，实际{price}"

        # L3 字段校验
        r = l3_results[0]
        score_dict = r.get("score", {})
        l3_five_score = score_dict.get("five_score") or r.get("five_score")
        l3_grade = score_dict.get("grade") or r.get("grade")

        # L4 字段校验
        d = l4_decisions[0]
        assert "decision" in d, "L4 decision 必须存在"
        assert "judge_score" in d, "L4 judge_score 必须存在"

        print(f"  输入: by_code, ticker={ticker_clean}")
        print(f"  预期: stock_count=1, name={name}")
        print(f"  实际: L2={len(l2_stocks)}只, L3={len(l3_results)}只, L4={len(l4_decisions)}只")
        print(f"  L2[0] price={price}")
        print(f"  L3[0] five_score={l3_five_score}, grade={l3_grade}")
        print(f"  L4[0] decision={d.get('decision')}, judge_score={d.get('judge_score'):.3f}")
        print(f"  耗时: {elapsed:.2f}秒")
        print(f"\n✅ 美股 {ticker} 全链路 PASS | 耗时{elapsed:.0f}s")
        return status

    except AssertionError as ae:
        print(f"  ❌ 断言失败: {ae}")
        return {
            "market": "US", "code": ticker, "name": name,
            "elapsed_s": round(time.time() - t0, 1),
            "error": f"断言失败: {ae}",
            "L1_ok": False, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }
    except Exception as e:
        import traceback
        print(f"❌ 美股 {ticker} 全链路失败: {e}")
        traceback.print_exc()
        return {
            "market": "US", "code": ticker, "name": name,
            "elapsed_s": round(time.time() - t0, 1),
            "error": str(e),
            "L1_ok": False, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }


def test_batch_2symbols() -> dict:
    """批量场景测试: A股 2只股票(by_code)，限定2种策略，每种最多2只

    入参: 无（使用固定测试标的）
    """
    from main.shennong import run_pipeline
    from main.contracts import PipelineContext, Market, load_all_config

    print(f"\n{'='*60}")
    print(f"  批量场景测试: A股 2只股票(by_code)")
    print(f"{'='*60}")

    t0 = time.time()
    symbols = ["600519", "000858"]  # 贵州茅台、五粮液

    try:
        ctx = PipelineContext(
            run_date=TODAY,
            market=Market.CN,
            mode="L4",
        )
        ctx = load_all_config(ctx)

        # 强制限制: by_code，2只股票
        ctx.l1_config["_force_symbols"] = symbols
        ctx.l1_config["_force_mode"] = "by_code"
        # 限定策略数量和每策略候选数（加快测试）
        ctx.l1_config["test_limit"] = 2

        result = run_pipeline(ctx)
        elapsed = time.time() - t0

        l2_stocks = result.get("L2", {}).get("stocks", [])
        l3_results = result.get("L3", {}).get("results", [])
        l4_decisions = result.get("L4", {}).get("decisions", [])

        status = {
            "market": "CN",
            "code": "+".join(symbols),
            "name": "批量2只",
            "elapsed_s": round(elapsed, 1),
            "L1_ok": bool(result.get("L1")),
            "L2_stocks": len(l2_stocks),
            "L3_scores": len(l3_results),
            "L4_decisions": len(l4_decisions),
            "report_len": len(result.get("report") or ""),
            "report": result.get("report"),
            "error": None,
        }

        # 断言
        assert len(l2_stocks) >= 1, f"L2 必须有数据，实际{len(l2_stocks)}"
        assert len(l3_results) >= 1, f"L3 必须有数据，实际{len(l3_results)}"
        assert len(l4_decisions) >= 1, f"L4 必须有裁定结果，实际{len(l4_decisions)}"

        print(f"  输入: by_code, symbols={symbols}, test_limit=2")
        print(f"  预期: L2>=1, L3>=1, L4>=1")
        print(f"  实际: L2={len(l2_stocks)}只, L3={len(l3_results)}只, L4={len(l4_decisions)}只")
        print(f"  耗时: {elapsed:.2f}秒")
        print(f"\n✅ 批量2只 PASS | L2:{len(l2_stocks)} L3:{len(l3_results)} L4:{len(l4_decisions)} | 耗时{elapsed:.0f}s")
        return status

    except AssertionError as ae:
        print(f"  ❌ 断言失败: {ae}")
        return {
            "market": "CN", "code": "+".join(symbols), "name": "批量2只",
            "elapsed_s": round(time.time() - t0, 1),
            "error": f"断言失败: {ae}",
            "L1_ok": False, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }
    except Exception as e:
        import traceback
        print(f"❌ 批量2只测试失败: {e}")
        traceback.print_exc()
        return {
            "market": "CN", "code": "+".join(symbols), "name": "批量2只",
            "elapsed_s": round(time.time() - t0, 1),
            "error": str(e),
            "L1_ok": False, "L2_stocks": 0, "L3_scores": 0,
            "L4_decisions": 0, "report_len": 0, "report": None,
        }


def print_summary():
    """打印测试汇总"""
    print(f"\n\n{'#'*70}")
    print(f"  神农全链路测试汇总 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
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
            layer_check = []
            if not r["L1_ok"]: layer_check.append("L1❌")
            if r["L2_stocks"] == 0: layer_check.append("L2❌")
            if r["L3_scores"] == 0: layer_check.append("L3❌")
            if r["L4_decisions"] == 0: layer_check.append("L4❌")
            if r["report_len"] < 30: layer_check.append("报告❌")
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

    return 1 if total_fail > 0 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="神农全链路测试")
    parser.add_argument("--market", default="ALL",
                        choices=["ALL", "CN", "HK", "US", "BATCH"],
                        help="测试市场(默认ALL三市场+BATCH)")
    args = parser.parse_args()

    print(f"🌾 神农系统全链路测试 — {TODAY}")
    print(f"模式: {args.market}")

    if args.market in ("ALL", "CN"):
        TEST_RESULTS.append(test_market_cn())
    if args.market in ("ALL", "HK"):
        TEST_RESULTS.append(test_market_hk())
    if args.market in ("ALL", "US"):
        TEST_RESULTS.append(test_market_us())
    if args.market in ("ALL", "BATCH"):
        TEST_RESULTS.append(test_batch_2symbols())

    exit_code = print_summary()
    sys.exit(exit_code)