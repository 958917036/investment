#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEST-L2-VALIDATORS: test_l2_validators
L2数据完整性校验测试

测试目标：验证L2_data_enrich.validators 模块（validate_stock_data / validate_batch /
get_data_quality_summary / DataQuality）的功能正确性。

该模块同时可通过旧路径访问：from L2_data_enrich.validators import ...
"""
import unittest
import sys
import os

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L2_data_enrich.validators import (
    validate_stock_data,
    validate_batch,
    get_data_quality_summary,
    DataQuality,
)


class TestL2Validators(unittest.TestCase):
    """L2数据完整性测试"""

    def test_complete_data(self):
        """测试完整数据通过校验"""
        complete_data = {
            "moneyflow_data": {
                "main_net_flow_5d": 100_000_000,
                "outer_inner_ratio": 0.85
            },
            "technical_data": {
                "ma_status": "bullish",
                "macd_status": "golden_cross",
                "rsi": 55,
                "sector_rank": 30
            },
            "fundamental_data": {
                "pe": 25.5,
                "pb": 3.2,
                "roe": 15.0
            },
            "sector_data": {
                "sector_rank": 25,
                "sector_strength": 0.65
            },
            "event_data": {
                "event_count": 2
            }
        }

        result = validate_stock_data(complete_data)
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["quality"], DataQuality.OK)
        self.assertEqual(result["completeness_score"], 1.0)

    def test_missing_dimension(self):
        """测试缺失维度"""
        partial_data = {
            "moneyflow_data": {
                "main_net_flow_5d": 100_000_000,
                "outer_inner_ratio": 0.85
            }
            # 缺失 technical_data, fundamental_data, sector_data
        }

        result = validate_stock_data(partial_data)
        self.assertFalse(result["is_valid"])
        self.assertEqual(result["quality"], DataQuality.FAIL)
        self.assertGreater(len(result["missing_dimensions"]), 0)

    def test_missing_fields(self):
        """测试缺失字段"""
        partial_data = {
            "moneyflow_data": {
                "main_net_flow_5d": 100_000_000
                # 缺失 outer_inner_ratio
            },
            "technical_data": {
                "ma_status": "bullish",
                "macd_status": "golden_cross",
                "rsi": 55,
                "sector_rank": 30
            },
            "fundamental_data": {
                "pe": 25.5,
                "pb": 3.2,
                "roe": 15.0
            },
            "sector_data": {
                "sector_rank": 25,
                "sector_strength": 0.65
            },
            "event_data": {
                "event_count": 2
            }
        }

        result = validate_stock_data(partial_data)
        self.assertFalse(result["is_valid"])
        self.assertIn("moneyflow", result["missing_fields"])

    def test_batch_validation(self):
        """测试批量校验"""
        stocks = [
            {
                "code": "600519",
                "moneyflow_data": {"main_net_flow_5d": 100_000_000, "outer_inner_ratio": 0.85},
                "technical_data": {"ma_status": "bullish", "macd_status": "golden_cross", "rsi": 55, "sector_rank": 30},
                "fundamental_data": {"pe": 25.5, "pb": 3.2, "roe": 15.0},
                "sector_data": {"sector_rank": 25, "sector_strength": 0.65},
                "event_data": {"event_count": 2}
            },
            {
                "code": "000333",
                "moneyflow_data": {"main_net_flow_5d": 50_000_000, "outer_inner_ratio": 0.90}
            }
        ]

        results = validate_batch(stocks)
        self.assertEqual(len(results), 2)
        self.assertTrue(results["600519"]["is_valid"])
        self.assertFalse(results["000333"]["is_valid"])

    def test_quality_summary(self):
        """测试汇总报告"""
        validation_results = {
            "600519": {"quality": DataQuality.OK, "completeness_score": 1.0, "missing_fields": {}, "missing_dimensions": []},
            "000333": {"quality": DataQuality.DEGRADED, "completeness_score": 0.5, "missing_fields": {"moneyflow": ["outer_inner_ratio"]}, "missing_dimensions": []},
            "000001": {"quality": DataQuality.FAIL, "completeness_score": 0.25, "missing_fields": {}, "missing_dimensions": ["technical"]}
        }

        summary = get_data_quality_summary(validation_results)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["ok_count"], 1)
        self.assertEqual(summary["degraded_count"], 1)
        self.assertEqual(summary["fail_count"], 1)
        self.assertGreater(summary["avg_completeness"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)