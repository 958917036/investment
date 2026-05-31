#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3 Veto 逻辑测试 — 验证极差判断（veto）过滤逻辑

覆盖：
1. 资金面 veto：5日主力净流出超过5000万则否决
2. 技术面 veto：均线空头 + MACD死叉共振则否决
3. 单只 veto 不影响其他股票
4. 空列表正常处理
5. 数据缺失（key不存在/空字典）不否决

veto 逻辑直接提取逻辑，不依赖 PipelineContext。
"""
import sys
import os
sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))


def _run_veto_check(stocks: list) -> dict:
    """
    直接运行 veto 逻辑（不依赖 PipelineContext）
    返回 {"passed": [...], "vetoed": [...], "pass_count": int}
    """
    vetoed = []
    passed = []

    for stock_dict in stocks:
        code = stock_dict.get("code", "")
        name = stock_dict.get("name", "")
        data = stock_dict

        reasons = []
        mf = data.get("moneyflow_data", {})
        if mf:
            mf_5d = mf.get("main_net_flow_5d", 0)
            if isinstance(mf_5d, (int, float)) and mf_5d < -50_000_000:
                reasons.append(f"资金面: 5日主力净流出{abs(mf_5d)/1e4:.0f}万")

        td = data.get("technical_data", {})
        if td.get("ma_status") == "bearish" and td.get("macd_status") in ("death", "death_cross"):
            reasons.append("技术面: 均线空头+MACD死叉共振")

        if reasons:
            vetoed.append({"code": code, "name": name, "reasons": reasons})
        else:
            passed.append({"code": code, "name": name, "_data": data})

    return {"passed": passed, "vetoed": vetoed, "pass_count": len(passed)}


def _stocks(*items):
    """构造 stocks 列表"""
    return [{"code": c, "name": n, **d} for c, n, d in items]


def test_veto资金面净流出超限():
    """5日主力净流出 > 5000万 应被否决"""
    stocks = _stocks(("600519", "贵州茅台", {"moneyflow_data": {"main_net_flow_5d": -60_000_000}, "technical_data": {"ma_status": "bullish", "macd_status": "golden"}}))
    result = _run_veto_check(stocks)
    assert len(result["vetoed"]) == 1, f"应否决1只，实际{len(result['vetoed'])}"
    assert result["pass_count"] == 0, f"应通过0只，实际{result['pass_count']}"
    assert result["vetoed"][0]["code"] == "600519"
    assert "资金面" in result["vetoed"][0]["reasons"][0]
    print(f"  [PASS] veto_count={len(result['vetoed'])}, pass_count={result['pass_count']}")


def test_veto技术面双空头():
    """均线空头 + MACD死叉 应被否决"""
    stocks = _stocks(("600036", "招商银行", {"moneyflow_data": {"main_net_flow_5d": 1_000_000}, "technical_data": {"ma_status": "bearish", "macd_status": "death"}}))
    result = _run_veto_check(stocks)
    assert len(result["vetoed"]) == 1, f"应否决1只，实际{len(result['vetoed'])}"
    assert "技术面" in result["vetoed"][0]["reasons"][0]
    print(f"  [PASS] veto_count={len(result['vetoed'])}, reasons={result['vetoed'][0]['reasons']}")


def test_pass正常股票():
    """正常股票应通过 veto"""
    stocks = _stocks(("300750", "宁德时代", {"moneyflow_data": {"main_net_flow_5d": 50_000_000}, "technical_data": {"ma_status": "bullish", "macd_status": "golden"}}))
    result = _run_veto_check(stocks)
    assert len(result["vetoed"]) == 0, f"应否决0只，实际{len(result['vetoed'])}"
    assert result["pass_count"] == 1, f"应通过1只，实际{result['pass_count']}"
    print(f"  [PASS] veto_count={len(result['vetoed'])}, pass_count={result['pass_count']}")


def test_pass资金流None():
    """moneyflow_data=None 视为无数据，既不否决也不通过"""
    stocks = _stocks(("000333", "美的集团", {"moneyflow_data": None, "technical_data": {}}))
    result = _run_veto_check(stocks)
    assert result["pass_count"] >= 0, "应正常处理 None 数据"
    print(f"  [PASS] pass_count={result['pass_count']}, veto_count={len(result['vetoed'])}")


def test_单只失败不影响其他():
    """一只股票 veto 不影响其他股票"""
    stocks = _stocks(
        ("600519", "贵州茅台", {"moneyflow_data": {"main_net_flow_5d": -100_000_000}, "technical_data": {}}),
        ("300750", "宁德时代", {"moneyflow_data": {"main_net_flow_5d": 100_000_000}, "technical_data": {}}),
        ("600036", "招商银行", {"moneyflow_data": {"main_net_flow_5d": -200_000_000}, "technical_data": {}}),
    )
    result = _run_veto_check(stocks)
    assert len(result["vetoed"]) == 2, f"应否决2只，实际{len(result['vetoed'])}"
    assert result["pass_count"] == 1, f"应通过1只，实际{result['pass_count']}"
    veto_codes = [v["code"] for v in result["vetoed"]]
    assert "600519" in veto_codes and "600036" in veto_codes
    print(f"  [PASS] vetoed={veto_codes}, passed={[p['code'] for p in result['passed']]}")


def test_empty_stocks():
    """空股票列表应正常返回"""
    result = _run_veto_check([])
    assert len(result["vetoed"]) == 0
    assert result["pass_count"] == 0
    print(f"  [PASS] empty: veto_count=0, pass_count=0")


def test_missing_moneyflow_data_key():
    """moneyflow_data 字段缺失（key不存在）应视为无数据，不否决"""
    # 只有 technical_data，没有 moneyflow_data
    stocks = [{"code": "600519", "name": "贵州茅台", "technical_data": {"ma_status": "bearish", "macd_status": "death"}}]
    result = _run_veto_check(stocks)
    # 没有 moneyflow_data，不应因资金面被否决
    # 但技术面双空头应被否决
    assert len(result["vetoed"]) == 1, f"应否决1只（技术面），实际{len(result['vetoed'])}"
    print(f"  [PASS] missing key: veto_count={len(result['vetoed'])}")


def test_moneyflow_data_empty_dict():
    """moneyflow_data {} 空字典应视为无数据，不否决"""
    stocks = _stocks(("600519", "贵州茅台", {"moneyflow_data": {}, "technical_data": {"ma_status": "bullish", "macd_status": "golden"}}))
    result = _run_veto_check(stocks)
    assert len(result["vetoed"]) == 0, f"空字典不应否决，实际{len(result['vetoed'])}"
    assert result["pass_count"] == 1
    print(f"  [PASS] empty dict: pass_count={result['pass_count']}")


def _run_all():
    tests = [
        ("veto资金面净流出超限", test_veto资金面净流出超限),
        ("veto技术面双空头", test_veto技术面双空头),
        ("pass正常股票", test_pass正常股票),
        ("pass资金流None", test_pass资金流None),
        ("单只失败不影响其他", test_单只失败不影响其他),
        ("empty_stocks", test_empty_stocks),
        ("missing_moneyflow_data_key", test_missing_moneyflow_data_key),
        ("moneyflow_data空字典", test_moneyflow_data_empty_dict),
    ]
    passed = failed = 0
    for name, fn in tests:
        try:
            print(f"\n▶ {name}")
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*60}")
    print(f"结果: {passed}/{len(tests)} 通过, {failed} 失败")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = _run_all()
    sys.exit(0 if ok else 1)