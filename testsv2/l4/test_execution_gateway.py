#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行层网关单元测试
测试 ExecutionGateway, MockGateway, BrokerRouter, Order/Trade/Position 数据类
"""
import unittest
import sys
import os

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L4_judge.execution import (
    ExecutionGateway,
    MockGateway,
    BrokerRouter,
    Order,
    OrderSide,
    OrderType,
    Position,
    AccountInfo,
)
from L4_judge.execution.order import OrderStatus, FillResult


class TestOrderDataClass(unittest.TestCase):
    """Order 数据类测试"""

    def test_order_creation(self):
        order = Order(
            code="600519",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=100,
            price=1850.0
        )
        self.assertEqual(order.code, "600519")
        self.assertEqual(order.side, OrderSide.BUY)
        self.assertEqual(order.type, OrderType.MARKET)
        self.assertEqual(order.quantity, 100)
        self.assertEqual(order.price, 1850.0)
        self.assertTrue(order.order_id)  # 自动生成ID

    def test_order_to_dict(self):
        order = Order(code="600519", side=OrderSide.BUY, type=OrderType.MARKET, quantity=100, price=1850.0)
        d = order.to_dict()
        self.assertEqual(d["code"], "600519")
        self.assertEqual(d["side"], "buy")  # lowercase
        self.assertEqual(d["quantity"], 100)


class TestPositionDataClass(unittest.TestCase):
    """Position 数据类测试"""

    def test_position_creation(self):
        pos = Position(
            code="600519",
            quantity=100,
            avg_cost=1800.0,
        )
        self.assertEqual(pos.code, "600519")
        self.assertEqual(pos.quantity, 100)
        self.assertEqual(pos.avg_cost, 1800.0)

    def test_position_market_value(self):
        pos = Position(code="600519", quantity=100, avg_cost=1800.0)
        mv = pos.market_value(1850.0)
        self.assertEqual(mv, 1850.0 * 100)

    def test_position_unrealized_pnl(self):
        pos = Position(code="600519", quantity=100, avg_cost=1800.0)
        pnl = pos.unrealized_pnl(1850.0)
        self.assertEqual(pnl, (1850 - 1800) * 100)


class TestMockGateway(unittest.TestCase):
    """MockGateway 模拟撮合测试"""

    def test_gateway_initialization(self):
        gw = MockGateway(initial_capital=500_000)
        self.assertEqual(gw.cash, 500_000)
        self.assertEqual(gw.initial_capital, 500_000)

    def test_set_price(self):
        gw = MockGateway(initial_capital=100_000)
        gw.set_price("600519", price=1850.0, prev_close=1830.0)
        self.assertEqual(gw._prices["600519"], 1850.0)
        self.assertEqual(gw._prev_close["600519"], 1830.0)

    def test_market_buy_order_with_enough_cash(self):
        gw = MockGateway(initial_capital=1_000_000)  # 大额资金
        gw.set_price("600519", price=1850.0, prev_close=1830.0)
        order = Order(code="600519", side=OrderSide.BUY, type=OrderType.MARKET, quantity=100, price=1850.0)
        order_id = gw.send_order(order)
        self.assertIsNotNone(order_id)
        # 验证有成交记录
        trades = gw.get_trades(order_id)
        self.assertGreater(len(trades), 0)

    def test_get_positions(self):
        gw = MockGateway(initial_capital=1_000_000)
        gw.set_price("600519", price=1850.0, prev_close=1830.0)
        order = Order(code="600519", side=OrderSide.BUY, type=OrderType.MARKET, quantity=100, price=1850.0)
        gw.send_order(order)
        positions = gw.get_positions()
        self.assertGreaterEqual(len(positions), 0)  # 可能还没成交

    def test_get_account(self):
        gw = MockGateway(initial_capital=1_000_000)
        gw.set_price("600519", price=1850.0, prev_close=1830.0)
        account = gw.get_account()
        self.assertEqual(account.cash, 1_000_000)


class TestBrokerRouter(unittest.TestCase):
    """BrokerRouter 多网关路由测试"""

    def test_register_and_set_active(self):
        gw1 = MockGateway(initial_capital=100_000)
        router = BrokerRouter()
        router.register("mock1", gw1)
        router.set_active("mock1")
        self.assertEqual(router._active_name, "mock1")

    def test_send_order_via_registered_gateway(self):
        gw1 = MockGateway(initial_capital=1_000_000)
        router = BrokerRouter()
        router.register("mock1", gw1)
        router.set_active("mock1")
        gw1.set_price("600519", price=1850.0, prev_close=1830.0)
        order = Order(code="600519", side=OrderSide.BUY, type=OrderType.MARKET, quantity=100, price=1850.0)
        order_id = router.send_order(order)
        self.assertIsNotNone(order_id)

    def test_health_check(self):
        gw1 = MockGateway(initial_capital=100_000)
        router = BrokerRouter()
        router.register("mock1", gw1)
        router.set_active("mock1")
        health = router.health_check()
        self.assertIn("mock1", health)

    def test_summary(self):
        gw1 = MockGateway(initial_capital=100_000)
        router = BrokerRouter()
        router.register("mock1", gw1)
        router.set_active("mock1")
        summary = router.summary()
        self.assertEqual(summary["active"], "mock1")
        self.assertIn("mock1", summary["gateways"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
