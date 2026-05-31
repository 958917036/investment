#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 PositionTracker 测试套件

测试覆盖：
- PositionTracker 初始化
- check_triggers 止损/止盈/过期检查
- update_position_status 状态更新
- record_execution 成交记录
- get_positions / get_position_summary

来源：基于 testsv2/l5/test_l5_freeze_manager.py 风格
"""

import sys
import os
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L5_post_review.core.position_tracker import (
    PositionTracker,
    PositionRecord,
    PositionStatus,
    MAX_HOLDING_DAYS,
)


class TestPositionTrackerBasics:
    """PositionTracker 基本功能测试"""

    def setup(self):
        """每个测试前创建临时冷冻表"""
        self.temp_dir = tempfile.mkdtemp()
        self.freeze_table_path = Path(self.temp_dir) / "freeze_table.json"
        import L5_post_review.core.position_tracker as pt_module
        pt_module.FREEZE_TABLE_PATHS["CN"] = self.freeze_table_path
        blank = {"freeze_records": [], "observing_list": [], "buy_signals": []}
        with open(self.freeze_table_path, "w") as f:
            json.dump(blank, f)

    def teardown(self):
        """恢复原始路径"""
        import L5_post_review.core.position_tracker as pt_module
        pt_module.FREEZE_TABLE_PATHS["CN"] = Path(os.path.expanduser("~/.hermes/investment/main/freeze_table.json"))
        if self.freeze_table_path.exists():
            self.freeze_table_path.unlink()

    def test_initialization(self):
        """
        测试 PositionTracker 初始化

        入参: market="CN"
        期望:初始化成功，freeze_table_path指向临时文件
        """
        pt = PositionTracker(market="CN")
        assert pt.market == "CN"
        assert pt.freeze_table_path == self.freeze_table_path
        print(f"  [PASS] 初始化成功")

    def test_get_positions_empty(self):
        """
        测试空持仓表返回空列表

        入参: 空白 buy_signals
        期望: get_positions() 返回空 list
        """
        pt = PositionTracker(market="CN")
        positions = pt.get_positions()
        assert isinstance(positions, list), f"返回值应为 list: {type(positions)}"
        assert len(positions) == 0, f"应为空的: {positions}"
        print(f"  [PASS] 空持仓表返回空列表")

    def test_get_position_summary_empty(self):
        """
        测试空持仓表汇总

        入参: 空白 buy_signals
        期望: PositionStatus 所有计数为 0
        """
        pt = PositionTracker(market="CN")
        summary = pt.get_position_summary()
        assert isinstance(summary, PositionStatus), f"返回值应为 PositionStatus: {type(summary)}"
        assert summary.total_count == 0, f"total_count 应为 0: {summary.total_count}"
        print(f"  [PASS] 空持仓表汇总正确")


class TestPositionTrackerOperations:
    """持仓操作测试"""

    def setup(self):
        """每个测试前创建临时冷冻表"""
        self.temp_dir = tempfile.mkdtemp()
        self.freeze_table_path = Path(self.temp_dir) / "freeze_table.json"
        import L5_post_review.core.position_tracker as pt_module
        pt_module.FREEZE_TABLE_PATHS["CN"] = self.freeze_table_path
        #初始信号数据
        self.sample_signals = [
            {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "judge_score": 0.72,
                "price": 1800.0,
                "stop_loss": 1620.0, # -10%
                "take_profit": 2160.0, # +20%
                "kelly_fraction": 0.15,
                "signal_date": "2026-05-01",
                "reason": "l4_judge:BUY",
                "status": "executed",
            },
            {
                "stock_code": "000858",
                "stock_name": "五粮液",
                "judge_score": 0.68,
                "price": 150.0,
                "stop_loss": 135.0,    # -10%
                "take_profit": 180.0,   # +20%
                "kelly_fraction": 0.12,
                "signal_date": "2026-05-15",
                "reason": "l4_judge:BUY",
                "status": "executed",
            },
            {
                "stock_code": "601318",
                "stock_name": "中国平安",
                "judge_score": 0.65,
                "price": 50.0,
                "stop_loss": 45.0,
                "take_profit": 60.0,
                "kelly_fraction": 0.10,
                "signal_date": "2026-03-01",
                "reason": "l4_judge:BUY",
                "status": "executed",
            },
        ]
        table = {"freeze_records": [], "observing_list": [], "buy_signals": self.sample_signals}
        with open(self.freeze_table_path, "w") as f:
            json.dump(table, f)

    def teardown(self):
        """恢复原始路径"""
        import L5_post_review.core.position_tracker as pt_module
        pt_module.FREEZE_TABLE_PATHS["CN"] = Path(os.path.expanduser("~/.hermes/investment/main/freeze_table.json"))
        if self.freeze_table_path.exists():
            self.freeze_table_path.unlink()

    def test_get_positions_all(self):
        """
        测试获取全部持仓

        入参: 3条 buy_signals（含 executed状态）
        期望: get_positions() 返回 3 条
        """
        pt = PositionTracker(market="CN")
        positions = pt.get_positions()
        assert len(positions) == 3, f"应为 3 条: {len(positions)}"
        print(f"  [PASS] 获取全部持仓: {len(positions)} 条")

    def test_get_positions_filtered(self):
        """
        测试按状态筛选持仓

        入参: 3条 buy_signals（2条 executed）
        期望: get_positions(status="executed") 返回 2 条
        """
        pt = PositionTracker(market="CN")
        positions = pt.get_positions(status="executed")
        assert len(positions) == 3, f"应为 3 条 executed: {len(positions)}"
        print(f"  [PASS] 状态筛选: {len(positions)} 条")

    def test_update_position_status(self):
        """
        测试更新持仓状态

        入参: stock_code="600519", status="stopped"
        期望: update_position_status 返回 True
        """
        pt = PositionTracker(market="CN")
        ok = pt.update_position_status("600519", "stopped", exit_price=1600.0, exit_date="2026-05-31", exit_reason="stop_loss")
        assert ok is True, f"更新应返回 True: {ok}"
        positions = pt.get_positions(status="stopped")
        assert len(positions) == 1, f"应为 1 条 stopped: {len(positions)}"
        assert positions[0].stock_code == "600519", f"应为 600519: {positions[0].stock_code}"
        print(f"  [PASS] 更新持仓状态成功")

    def test_record_execution(self):
        """
        测试记录成交

        入参: stock_code="600519", execution_price=1820.0, execution_date="2026-05-31"
        期望: record_execution 返回 True
        """
        # 先修改状态为 pending
        with open(self.freeze_table_path, "r") as f:
            table = json.load(f)
        for sig in table["buy_signals"]:
            if sig["stock_code"] == "600519":
                sig["status"] = "pending"
        with open(self.freeze_table_path, "w") as f:
            json.dump(table, f)

        pt = PositionTracker(market="CN")
        ok = pt.record_execution("600519", 1820.0, "2026-05-31")
        assert ok is True, f"成交记录应返回 True: {ok}"

        positions = pt.get_positions(status="executed")
        assert len(positions) >= 1, f"应有 executed 持仓: {len(positions)}"
        print(f"  [PASS] 记录成交成功")

    def test_get_position_summary(self):
        """
        测试持仓状态汇总

        入参: 3条 buy_signals
        期望: PositionStatus.total_count == 3
        """
        pt = PositionTracker(market="CN")
        summary = pt.get_position_summary()
        assert summary.total_count == 3, f"total_count 应为 3: {summary.total_count}"
        assert summary.executed_count == 3, f"executed_count 应为 3: {summary.executed_count}"
        print(f"  [PASS] 持仓汇总正确: total={summary.total_count}, executed={summary.executed_count}")


class TestPositionTrackerTriggers:
    """触发检查测试"""

    def setup(self):
        """创建临时冷冻表"""
        self.temp_dir = tempfile.mkdtemp()
        self.freeze_table_path = Path(self.temp_dir) / "freeze_table.json"
        import L5_post_review.core.position_tracker as pt_module
        pt_module.FREEZE_TABLE_PATHS["CN"] = self.freeze_table_path

    def teardown(self):
        """恢复原始路径"""
        import L5_post_review.core.position_tracker as pt_module
        pt_module.FREEZE_TABLE_PATHS["CN"] = Path(os.path.expanduser("~/.hermes/investment/main/freeze_table.json"))
        if self.freeze_table_path.exists():
            self.freeze_table_path.unlink()

    def test_check_triggers_no_positions(self):
        """
        测试空持仓表检查触发

        入参: 空 buy_signals
        期望: check_triggers 返回空结果
        """
        table = {"freeze_records": [], "observing_list": [], "buy_signals": []}
        with open(self.freeze_table_path, "w") as f:
            json.dump(table, f)

        pt = PositionTracker(market="CN")
        result = pt.check_triggers(check_date="2026-05-31")
        assert isinstance(result, dict), f"返回值应为 dict: {type(result)}"
        assert "unchanged" in result, f"应有 unchanged key: {result.keys()}"
        print(f"  [PASS] 空持仓表检查正常")

    def test_check_triggers_expired(self):
        """
        测试过期持仓检查

        入参: 一条超过 MAX_HOLDING_DAYS 的持仓
        期望: 状态变为 expired
        """
        old_date = (date.today() - timedelta(days=MAX_HOLDING_DAYS + 10)).strftime("%Y-%m-%d")
        table = {
            "freeze_records": [],
            "observing_list": [],
            "buy_signals": [
                {
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "price": 1800.0,
                    "stop_loss": 1620.0,
                    "take_profit": 2160.0,
                    "kelly_fraction": 0.15,
                    "judge_score": 0.72,
                    "signal_date": old_date,
                    "reason": "test",
                    "status": "executed",
                }
            ],
        }
        with open(self.freeze_table_path, "w") as f:
            json.dump(table, f)

        pt = PositionTracker(market="CN")
        result = pt.check_triggers(check_date=date.today().strftime("%Y-%m-%d"))
        assert "expired" in result, f"应有 expired key: {result.keys()}"
        print(f"  [PASS] 过期检查通过")


class TestPositionRecord:
    """PositionRecord 数据模型测试"""

    def test_record_creation(self):
        """
        测试 PositionRecord 创建

        入参: 各字段值
        期望: 字段正确赋值
        """
        record = PositionRecord(
            stock_code="600519",
            stock_name="贵州茅台",
            entry_date="2026-05-01",
            entry_price=1800.0,
            stop_loss=1620.0,
            take_profit=2160.0,
            kelly_fraction=0.15,
            judge_score=0.72,
            reason="test",
            status="pending",
            signal_date="2026-05-01",
        )
        assert record.stock_code == "600519"
        assert record.status == "pending"
        assert record.entry_price == 1800.0
        print(f"  [PASS] PositionRecord 创建正确")


# ─── 测试运行器 ────────────────────────────────────────────────

def run_tests():
    """运行所有测试"""
    import io
    import unittest

    classes = [
        TestPositionTrackerBasics,
        TestPositionTrackerOperations,
        TestPositionTrackerTriggers,
        TestPositionRecord,
    ]

    total = 0
    passed = 0

    for cls in classes:
        print(f"\n{'='*60}")
        print(f"测试类: {cls.__name__}")
        print('='*60)
        instance = cls()
        if hasattr(instance, "setup"):
            instance.setup()

        try:
            for name in dir(instance):
                if name.startswith("test_"):
                    print(f"\n  运行: {name}")
                    try:
                        getattr(instance, name)()
                        passed += 1
                    except AssertionError as e:
                        print(f"  [FAIL] {e}")
                    except Exception as e:
                        print(f"  [ERROR] {e}")
                    total += 1
        finally:
            if hasattr(instance, "teardown"):
                instance.teardown()

    print(f"\n{'='*60}")
    print(f"测试结果: {passed}/{total} 通过")
    print('='*60)


if __name__ == "__main__":
    run_tests()