#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 Post Review Runner 测试代码

现在 L5 持仓监控功能已整合到 L4，
此文件用于测试 check_portfolio_triggers() 函数。
"""
import sys
import os

sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))
from L4_judge.l4_runner import check_portfolio_triggers


def test_hold():
    """
    测试正常持有（未触及止损止盈）

    入参: current_price=1800 > avg_cost=1750（盈利 +2.86%）,
          L4_data stop_loss=-8%, take_profit=20%
    期望: action="HOLD"
    """
    result = check_portfolio_triggers(
        code="600519",
        L4_data={"stop_loss_pct": -0.08, "take_profit_pct": 0.20},
        current_price=1800.0,
        position={"shares": 100, "avg_cost": 1750.0}
    )

    assert result["action"] == "HOLD", f"action: expected 'HOLD', got {result['action']!r}"
    assert result["freeze_status"] == "normal", f"freeze_status: expected 'normal', got {result['freeze_status']!r}"
    assert result["action"] in ("HOLD", "STOP_LOSS", "SELL", "ADD"), \
        f"action: unexpected {result['action']!r}"

    # price_change = (1800-1750)/1750 = +2.86%, 在 [-8%, +20%] 之间，应 HOLD
    price_change = (1800 - 1750) / 1750
    stop_loss = -0.08
    take_profit = 0.20
    assert price_change > stop_loss and price_change < take_profit, \
        f"price_change({price_change:.2%}) should be in (-8%, +20%) for HOLD"
    print(f"  [PASS] HOLD: price_change={price_change:.2%} in (-8%, +20%)")


def test_stop_loss():
    """
    测试触发止损

    入参: current_price=1600 < avg_cost=1750（亏损 -8.57% <= stop_loss=-8%）
    期望: action="STOP_LOSS"
    """
    result = check_portfolio_triggers(
        code="600519",
        L4_data={"stop_loss_pct": -0.08, "take_profit_pct": 0.20},
        current_price=1600.0,
        position={"shares": 100, "avg_cost": 1750.0}
    )

    assert result["action"] == "STOP_LOSS", f"action: expected 'STOP_LOSS', got {result['action']!r}"

    # price_change = (1600-1750)/1750 = -8.57%, <= -8%，应 STOP_LOSS
    price_change = (1600 - 1750) / 1750
    assert price_change <= -0.08, f"price_change({price_change:.2%}) should be <= -8% for STOP_LOSS"
    print(f"  [PASS] STOP_LOSS: price_change={price_change:.2%} <= -8%")


def test_take_profit():
    """
    测试触发止盈

    入参: current_price=2100 > avg_cost=1750（盈利 +20% >= take_profit=20%）
    期望: action="SELL"
    """
    result = check_portfolio_triggers(
        code="600519",
        L4_data={"stop_loss_pct": -0.08, "take_profit_pct": 0.20},
        current_price=2100.0,
        position={"shares": 100, "avg_cost": 1750.0}
    )

    assert result["action"] == "SELL", f"action: expected 'SELL', got {result['action']!r}"

    # price_change = (2100-1750)/1750 = +20%, >= +20%，应 SELL
    price_change = (2100 - 1750) / 1750
    assert price_change >= 0.20, f"price_change({price_change:.2%}) should be >= +20% for SELL"
    print(f"  [PASS] SELL: price_change={price_change:.2%} >= +20%")


def test_add():
    """
    测试追加买入（价格 < 成本且趋势向上）

    入参: current_price=1700 < avg_cost=1750, trend_direction="up"
    期望: action="ADD"
    """
    result = check_portfolio_triggers(
        code="600519",
        L4_data={"stop_loss_pct": -0.08, "take_profit_pct": 0.20, "trend_direction": "up"},
        current_price=1700.0,
        position={"shares": 100, "avg_cost": 1750.0}
    )

    assert result["action"] == "ADD", f"action: expected 'ADD', got {result['action']!r}"
    assert 1700.0 < 1750.0, "current_price should be < avg_cost for ADD"
    print(f"  [PASS] ADD: price=1700 < cost=1750, trend=up")


def test_no_position():
    """
    测试无持仓

    入参: shares=0, avg_cost=0
    期望: action="HOLD"（无持仓只能观望）
    """
    result = check_portfolio_triggers(
        code="600519",
        L4_data={"stop_loss_pct": -0.08, "take_profit_pct": 0.20},
        current_price=1800.0,
        position={"shares": 0, "avg_cost": 0.0}
    )

    assert result["action"] == "HOLD", f"action: expected 'HOLD', got {result['action']!r}"
    print(f"  [PASS] HOLD: no position held")


def _run_all():
    tests = [
        ("hold", test_hold),
        ("stop_loss", test_stop_loss),
        ("take_profit", test_take_profit),
        ("add", test_add),
        ("no_position", test_no_position),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            print(f"\n{'='*60}")
            print(f"▶ {name}")
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
    print("=" * 60)
    print("L5 持仓监控测试（现在 L4 提供）")
    print("=" * 60)
    ok = _run_all()
    sys.exit(0 if ok else 1)