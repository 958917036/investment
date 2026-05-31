#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理器单元测试
测试 RiskManager, RiskAssessment, PortfolioRisk 数据类
"""
import unittest
import sys
import os

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L4_judge.risk.risk_manager import (
    RiskManager,
    RiskAssessment,
    PortfolioRisk,
    Position,
)


class TestRiskAssessment(unittest.TestCase):
    """RiskAssessment 数据类测试"""

    def test_creation(self):
        assess = RiskAssessment(
            stock_code="600519",
            stock_name="贵州茅台",
            assess_date="2026-05-04"
        )
        self.assertEqual(assess.stock_code, "600519")
        self.assertEqual(assess.stock_name, "贵州茅台")
        self.assertEqual(assess.var_95, 0.0)

    def test_to_dict(self):
        assess = RiskAssessment(
            stock_code="600519",
            stock_name="贵州茅台",
            assess_date="2026-05-04",
            volatility=0.25,
            var_95=0.026
        )
        d = assess.to_dict()
        self.assertEqual(d["stock_code"], "600519")
        self.assertEqual(d["volatility"], 0.25)


class TestPortfolioRisk(unittest.TestCase):
    """PortfolioRisk 数据类测试"""

    def test_creation(self):
        pr = PortfolioRisk(
            total_capital=100_000,
            used_capital=50_000,
            available_capital=50_000,
            positions_count=2
        )
        self.assertEqual(pr.total_capital, 100_000)
        self.assertEqual(pr.positions_count, 2)


class TestRiskManager(unittest.TestCase):
    """RiskManager 风险管理器测试"""

    def test_initialization(self):
        rm = RiskManager(total_capital=100_000)
        self.assertEqual(rm.total_capital, 100_000)
        self.assertEqual(len(rm.positions), 0)

    def test_config_loading(self):
        """测试风控配置是否正确加载"""
        rm = RiskManager(total_capital=100_000)
        # 配置项应该存在
        self.assertIn("stop_loss_default", rm.config)
        self.assertIn("take_profit_default", rm.config)
        self.assertEqual(rm.config["stop_loss_default"], -0.08)

    def test_assess_stock_risk_basic(self):
        """测试个股风险评估基本功能"""
        rm = RiskManager(total_capital=100_000)
        assess = rm.assess_stock_risk("600519", "贵州茅台", current_price=1850.0)
        self.assertEqual(assess.stock_code, "600519")
        self.assertGreater(assess.volatility, 0)  # 应该有波动率估算
        self.assertGreater(assess.var_95, 0)  # 应该有VaR

    def test_recommend_position_size(self):
        """测试建议仓位计算"""
        rm = RiskManager(total_capital=100_000)
        assess = RiskAssessment(
            stock_code="600519",
            stock_name="贵州茅台",
            assess_date="2026-05-04",
            volatility=0.25,
            kelly_fraction=0.20
        )
        position_size = rm._recommend_position_size(assess, None)
        self.assertGreaterEqual(position_size, 0)
        self.assertLessEqual(position_size, rm.config["max_single_position"])

    def test_can_buy_approved(self):
        """测试买入检查通过"""
        rm = RiskManager(total_capital=100_000)
        assess = RiskAssessment(
            stock_code="600519",
            stock_name="贵州茅台",
            assess_date="2026-05-04",
            volatility=0.20,
            alert_level="normal"
        )
        can_buy, reason = rm.can_buy("600519", 10000, assess)
        self.assertTrue(can_buy)

    def test_can_buy_danger_rejected(self):
        """测试高风险个股被拒绝"""
        rm = RiskManager(total_capital=100_000)
        assess = RiskAssessment(
            stock_code="600519",
            stock_name="贵州茅台",
            assess_date="2026-05-04",
            volatility=0.70,  # 高波动
            alert_level="danger"
        )
        can_buy, reason = rm.can_buy("600519", 10000, assess)
        self.assertFalse(can_buy)

    def test_update_position(self):
        """测试持仓更新"""
        rm = RiskManager(total_capital=100_000)
        pos = Position(
            stock_code="600519",
            stock_name="贵州茅台",
            entry_price=1800.0,
            current_price=1850.0,
            shares=20,
            cost=36000.0,
            market_value=37000.0,
            pnl_pct=0.028,
            pnl_amount=1000.0,
            weight=0.37
        )
        rm.update_position(pos)
        self.assertIn("600519", rm.positions)

    def test_remove_position(self):
        """测试持仓移除"""
        rm = RiskManager(total_capital=100_000)
        pos = Position(
            stock_code="600519",
            stock_name="贵州茅台",
            entry_price=1800.0,
            current_price=1850.0,
            shares=20,
            cost=36000.0,
            market_value=37000.0,
            pnl_pct=0.028,
            pnl_amount=1000.0,
            weight=0.37
        )
        rm.update_position(pos)
        rm.remove_position("600519")
        self.assertNotIn("600519", rm.positions)


if __name__ == "__main__":
    unittest.main(verbosity=2)
