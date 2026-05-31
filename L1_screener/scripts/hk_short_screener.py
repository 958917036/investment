#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 Screener - 港股做空候选筛选 (HK Short Screener)
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
        pool = "hk"

    log_start("hk_short_screener", "run", f"pool={pool}")
    # 港股做空逻辑：筛选外内盘比<0.8、均线空头的股票
    result = run_l1("by_strategy", {"strategy": "pullback", "pool": pool, "market": "hk"})
    print(f"hk_short_screener: {result['stock_count']} stocks, {result['duration_ms']}ms")
    log_end("hk_short_screener", "run", f"{result['stock_count']} stocks")
    return result


if __name__ == '__main__':
    main()