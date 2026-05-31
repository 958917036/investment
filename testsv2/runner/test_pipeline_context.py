#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""testsv2/runner/test_pipeline_context.py — PipelineContext 整体流程"""
import sys, os, time
sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))

from main.contracts import PipelineContext, Market, load_all_config
from main.shennong import run_pipeline, _check_veto


def test_context_creation():
    """PipelineContext 创建 + load_all_config"""
    ctx = PipelineContext(run_date="2026-05-31", market=Market.CN, mode="full")
    ctx = load_all_config(ctx)
    assert ctx.run_date == "2026-05-31"
    assert ctx.market == Market.CN
    assert isinstance(ctx.l1_config, dict)
    print(f"  输入: run_date=2026-05-31, market=CN, mode=full")
    print(f"  预期: config dicts loaded")
    print(f"  实际: l1_config keys={list(ctx.l1_config.keys())[:3]}")
    print(f"  耗时: immediate")


def test_check_veto_empty():
    """极差判断空输入"""
    ctx = PipelineContext(run_date="2026-05-31", market=Market.CN)
    ctx.l2_result = None
    result = _check_veto(ctx)
    assert result["pass_count"] == 0
    print(f"  输入: l2_result=None")
    print(f"  预期: pass_count=0")
    print(f"  实际: pass_count={result['pass_count']}")
    print(f"  耗时: immediate")


def _run_all():
    tests = [
        test_context_creation,
        test_check_veto_empty,
    ]
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