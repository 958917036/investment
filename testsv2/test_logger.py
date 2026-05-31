#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试日志工具

为测试执行写入 hermes.log，提供可定位的阶段标记。
每个测试文件在运行前调用 init()，结束时调用 summary()。

格式：
[2026-05-31 17:14:34.123] [TEST] test_l1_runner.py::test_by_code ▶ START
[2026-05-31 17:14:34.456] [TEST] test_l1_runner.py::test_by_code ▶ END  elapsed=0.33s  passed=True
"""
import os
import sys
import time
import logging
from datetime import datetime

_HERMES_LOG = os.path.expanduser("~/.hermes/investment/logs/hermes.log")
_test_logger = None


def _get_logger():
    global _test_logger
    if _test_logger is None:
        _test_logger = logging.getLogger("test")
        _test_logger.setLevel(logging.INFO)
        _test_logger.propagate = False
        if not _test_logger.handlers:
            handler = logging.FileHandler(_HERMES_LOG)
            handler.setFormatter(logging.Formatter("%(message)s"))
            _test_logger.addHandler(handler)
    return _test_logger


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _log(msg: str):
    """同时写入 hermes.log 和 stdout"""
    _get_logger().info(msg)
    print(msg)
    sys.stdout.flush()


def suite_start(suite_name: str, total_tests: int):
    """标记测试套件开始"""
    _log(f"[TEST] {suite_name} ▶ START  tests={total_tests}")


def suite_end(suite_name: str, passed: int, failed: int, elapsed: float):
    """标记测试套件结束"""
    status = "PASS" if failed == 0 else "FAIL"
    _log(f"[TEST] {suite_name} ▶ END  passed={passed} failed={failed} elapsed={elapsed:.1f}s  status={status}")


def test_start(suite_name: str, test_name: str):
    """标记单个测试开始"""
    _log(f"[TEST] {suite_name}::{test_name} ▶ START")


def test_end(suite_name: str, test_name: str, passed: bool, elapsed: float, error: str = ""):
    """标记单个测试结束"""
    status = "PASS" if passed else "FAIL"
    detail = f"  error={error}" if error else ""
    _log(f"[TEST] {suite_name}::{test_name} ▶ END  elapsed={elapsed:.1f}s  status={status}{detail}")


def test_skip(suite_name: str, test_name: str, reason: str):
    """标记测试跳过"""
    _log(f"[TEST] {suite_name}::{test_name} ▶ SKIP  reason={reason}")