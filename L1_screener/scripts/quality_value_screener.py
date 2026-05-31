#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 Screener - 质量价值策略 (Quality Value)
独立运行脚本，调用 l1_runner.py
"""
import sys, os
BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, info

sys.path.insert(0, os.path.join(BASE_DIR, "L1_screener"))
from l1_runner import run_l1


def main():
    if len(sys.argv) > 1:
        pool = sys.argv[1]
    else:
        pool = "index800"

    log_start("quality_value_screener", "run", f"pool={pool}")
    result = run_l1("by_strategy", {"strategy": "quality_value", "pool": pool})
    print(f"quality_value: {result['stock_count']} stocks, {result['duration_ms']}ms")
    log_end("quality_value_screener", "run", f"{result['stock_count']} stocks")
    return result


if __name__ == '__main__':
    main()