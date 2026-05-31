#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""testsv2/runner/test_l1_runner.py — run_l1 单元测试"""
import sys, os, time
sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))

from main.contracts import PipelineContext, Market, load_all_config
from main.l1_runner import run_l1


def test_run_l1_cn():
    """CN市场 L1选股"""
    ctx = PipelineContext(run_date="2026-05-31", market=Market.CN, mode="full")
    ctx = load_all_config(ctx)
    t0 = time.time()
    ctx = run_l1(ctx)
    elapsed = time.time() - t0
    assert ctx.l1_result is not None, f"l1_result is None"
    print(f"  输入: market=CN, run_date=2026-05-31")
    print(f"  预期: l1_result.stock_count >= 0")
    print(f"  实际: l1_result.stock_count={ctx.l1_result.stock_count}")
    print(f"  耗时: {elapsed:.2f}s")


def _run_all():
    tests = [test_run_l1_cn]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  ❌ {t.__name__}: {e}")
    print(f"\n结果: {passed} ✅ / {failed} ❌")


if __name__ == "__main__":
    _run_all()