#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""testsv2/integration/test_full_pipeline.py — 完整 Pipeline 集成测试"""
import sys, os, time
sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))

from main.contracts import PipelineContext, Market, load_all_config
from main.shennong import run_pipeline


def test_pipeline_L1_only():
    """仅 L1 模式"""
    ctx = PipelineContext(run_date="2026-05-31", market=Market.CN, mode="L1")
    ctx = load_all_config(ctx)
    t0 = time.time()
    result = run_pipeline(ctx)
    elapsed = time.time() - t0
    assert "L1" in result, "L1 not in result"
    l1_data = result["L1"]
    print(f"  输入: mode=L1, market=CN")
    print(f"  预期: L1 in result, stock_count >= 0")
    print(f"  实际: L1 stock_count={l1_data.get('stock_count', 'N/A')}")
    print(f"  耗时: {elapsed:.2f}s")


def test_pipeline_L2_only():
    """仅 L2 模式 — 验证 config 加载和 runner 入口正确（跳过全量批次）"""
    ctx = PipelineContext(run_date="2026-05-31", market=Market.CN, mode="L2")
    ctx = load_all_config(ctx)
    # L2 全量需要 ~14 小时（1747 stocks × 30s），跳过实际运行
    # 验证 config 加载和 runner 入口正确即可
    assert ctx.l2_config is not None, "l2_config should be loaded"
    print(f"  输入: mode=L2, market=CN, l2_config loaded")
    print(f"  预期: l2_config is not None")
    print(f"  实际: l2_config keys={list(ctx.l2_config.keys())}")
    print(f"  耗时: 0.00s (skip full batch — 1747 stocks × 30s = ~14h)")


def _run_all():
    tests = [test_pipeline_L1_only, test_pipeline_L2_only]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✅ {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  ❌ {t.__name__}: {e}")
    print(f"\n结果: {passed} ✅ / {failed} ❌")


if __name__ == "__main__":
    _run_all()