#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run all 5 L1 strategies via l1_runner.py (optimized, shared quote fetching)."""
import sys
import os
from datetime import datetime

BASE_DIR = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE_DIR, "main", "utils"))
from logger import log_start, log_end, log_fail, info

sys.path.insert(0, os.path.join(BASE_DIR, "L1_screener"))
from l1_runner import run_l1


def main():
    log_start("run_all", "batch_run")
    print(f"L1 Screener Batch Run - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    for strategy in ["breakout", "growth_momentum", "garp", "pullback", "quality_value"]:
        log_start("run_all", f"run_screener", f"strategy={strategy}")
        try:
            result = run_l1("by_strategy", {"strategy": strategy, "pool": "index800"})
            info("run_all", f"{strategy}: {result['stock_count']} stocks, {result['duration_ms']}ms")
            print(f"  {strategy}: {result['stock_count']} stocks")
            log_end("run_all", f"run_screener", f"strategy={strategy}, ok")
        except Exception as e:
            log_fail("run_all", f"run_screener", f"strategy={strategy}, error={e}")
            print(f"  {strategy}: ERROR {e}")

    log_end("run_all", "batch_run")


if __name__ == '__main__':
    main()