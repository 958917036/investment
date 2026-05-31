#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L4配置加载测试

测试目标：验证L4相关配置正确加载
"""

import unittest
import sys
import os

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L4_judge.risk.risk_manager import RiskManager, _get_risk_config


class TestL4ConfigLoader(unittest.TestCase):
    """L4配置加载测试"""

    def test_risk_config_exists(self):
        """测试risk_config.json存在且可读"""
        cfg = _get_risk_config()
        self.assertIsInstance(cfg, dict)

    def test_risk_config_has_required_fields(self):
        """测试risk_config包含必需字段"""
        cfg = _get_risk_config()
        self.assertIn("risk", cfg)
        self.assertIn("total_capital", cfg)

    def test_risk_manager_loads_config(self):
        """测试RiskManager从配置加载"""
        rm = RiskManager()
        self.assertEqual(rm.total_capital, 100000)
        self.assertIn("max_single_position", rm.config)

    def test_risk_manager_custom_capital(self):
        """测试RiskManager接受自定义资金"""
        rm = RiskManager(total_capital=500000)
        self.assertEqual(rm.total_capital, 500000)

    def test_risk_config_values(self):
        """测试风控配置值合理"""
        cfg = _get_risk_config()
        risk_cfg = cfg.get("risk", {})

        # 检查风控阈值在合理范围
        self.assertGreaterEqual(risk_cfg.get("max_single_position", 0), 0)
        self.assertLessEqual(risk_cfg.get("max_single_position", 0), 1)
        self.assertLessEqual(risk_cfg.get("stop_loss_default", 0), 0)
        self.assertGreater(risk_cfg.get("take_profit_default", 0), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
