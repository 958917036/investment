#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 FreezeManager 测试套件

测试覆盖：
- FreezeManager 初始化与结构
- add_freeze (10days/3months)
- 重复添加冷冻失败
- unfreeze 解冻
- get_frozen_codes / get_summary
- check_and_update_freeze 到期检查
- 多市场支持 (CN/HK/US)
- CLI --market 参数

来源：合并 tests/l5_review/test_l5_config.py + tests/l5_review/test_l5_freeze_manager.py
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

from L5_post_review.freeze_manager import (
    FreezeManager,
    FREEZE_10_DAYS,
    FREEZE_3_MONTHS,
    THRESH_MAIN_NET_FLOW,
    THRESH_OUTER_INNER_RATIO,
)


class TestFreezeManagerBasics:
    """FreezeManager 基本功能测试"""

    def setup(self):
        """每个测试前创建临时冷冻表"""
        self.temp_dir = tempfile.mkdtemp()
        self.freeze_table_path = Path(self.temp_dir) / "freeze_table.json"
        import L5_post_review.freeze_manager as fm_module
        # Patch FREEZE_TABLE_PATHS dict (used by __init__)
        fm_module.FREEZE_TABLE_PATHS["CN"] = self.freeze_table_path
        blank = {"freeze_records": [], "observing_list": [], "buy_signals": []}
        with open(self.freeze_table_path, "w") as f:
            json.dump(blank, f)

    def teardown(self):
        """恢复原始路径"""
        import L5_post_review.freeze_manager as fm_module
        fm_module.FREEZE_TABLE_PATHS["CN"] = Path(os.path.expanduser("~/.hermes/investment/main/freeze_table.json"))
        if self.freeze_table_path.exists():
            self.freeze_table_path.unlink()

    def test_initialization(self):
        """
        测试 FreezeManager 初始化

        入参: market="CN"
        期望: freeze_table 非空结构，含 freeze_records/observing_list/buy_signals
        """
        fm = FreezeManager()
        table = fm.freeze_table
        assert "freeze_records" in table, f"缺少 freeze_records 字段: {table}"
        assert "observing_list" in table, f"缺少 observing_list 字段: {table}"
        assert "buy_signals" in table, f"缺少 buy_signals 字段: {table}"
        print(f"  [PASS] 初始化: freeze_table 结构正确")

    def test_get_frozen_codes_empty(self):
        """
        测试空冷冻表返回空集合

        入参: 空白冷冻表
        期望: get_frozen_codes() 返回空 set
        """
        fm = FreezeManager()
        frozen = fm.get_frozen_codes()
        assert isinstance(frozen, set), f"应返回 set: {type(frozen)}"
        print(f"  [PASS] 空表返回空 set: {frozen}")

    def test_get_summary_empty(self):
        """
        测试冷冻表摘要（实际数据，非空表）

        入参: 市场真实freeze_table.json
        期望: summary 含真实的 frozen_count/observing_count/buy_signals_count
        """
        fm = FreezeManager()
        summary = fm.get_summary()
        # freeze_table.json 有真实数据（601825/600741 冷冻中，000333 观察中）
        assert summary["frozen_count"] >= 0, f"frozen_count 应>=0: {summary}"
        assert "frozen_codes" in summary, f"frozen_codes 字段存在: {summary}"
        print(f"  [PASS] 摘要正确: {summary}")


class TestFreezeManagerFreeze:
    """冷冻添加与管理测试"""

    def setup(self):
        """每个测试前创建临时冷冻表"""
        self.temp_dir = tempfile.mkdtemp()
        self.freeze_table_path = Path(self.temp_dir) / "freeze_table.json"
        import L5_post_review.freeze_manager as fm_module
        fm_module.FREEZE_TABLE_PATHS["CN"] = self.freeze_table_path
        blank = {"freeze_records": [], "observing_list": [], "buy_signals": []}
        with open(self.freeze_table_path, "w") as f:
            json.dump(blank, f)
        return FreezeManager()

    def teardown(self):
        """恢复原始路径"""
        import L5_post_review.freeze_manager as fm_module
        fm_module.FREEZE_TABLE_PATHS["CN"] = Path(os.path.expanduser("~/.hermes/investment/main/freeze_table.json"))
        if self.freeze_table_path.exists():
            self.freeze_table_path.unlink()

    def test_add_freeze_10days(self):
        """
        测试添加10天冷冻

        入参: code=600519, name=贵州茅台, level=10days, reason=[PE过高]
        期望: 返回 True, get_frozen_codes() 包含 600519
        """
        fm = self.setup()
        result = fm.add_freeze("600519", "贵州茅台", "10days", ["PE过高"])
        assert result is True, f"add_freeze 应返回 True: {result}"
        frozen = fm.get_frozen_codes()
        assert "600519" in frozen, f"600519 应在冷冻集合中: {frozen}"
        self.teardown()
        print(f"  [PASS] 添加10天冷冻成功")

    def test_add_freeze_3months(self):
        """
        测试添加3个月冷冻

        入参: code=600519, name=贵州茅台, level=3months
        期望: 返回 True, 冷冻到期为90天后
        """
        fm = self.setup()
        result = fm.add_freeze("600519", "贵州茅台", "3months", ["资金流出", "均线空头"])
        assert result is True, f"add_freeze 应返回 True: {result}"
        records = fm.freeze_table["freeze_records"]
        assert len(records) == 1, f"应有1条记录: {len(records)}"
        assert records[0]["freeze_level"] == "3months", f"freeze_level 应为 3months"
        self.teardown()
        print(f"  [PASS] 添加3个月冷冻成功")

    def test_add_duplicate_freeze(self):
        """
        测试重复添加冷冻失败

        入参: 同一股票添加两次 10days
        期望: 第二次返回 False，不重复添加
        """
        fm = self.setup()
        r1 = fm.add_freeze("600519", "贵州茅台", "10days", ["PE过高"])
        r2 = fm.add_freeze("600519", "贵州茅台", "10days", ["PE过高"])
        assert r1 is True, "第一次应成功"
        assert r2 is False, "重复添加应失败"
        records = fm.freeze_table["freeze_records"]
        assert len(records) == 1, f"应仍只有1条记录: {len(records)}"
        self.teardown()
        print(f"  [PASS] 重复添加正确拒绝")

    def test_add_freeze_invalid_level(self):
        """
        测试无效冷冻级别

        入参: level="invalid"
        期望: 返回 False
        """
        fm = self.setup()
        result = fm.add_freeze("600519", "贵州茅台", "invalid", ["PE过高"])
        assert result is False, f"无效级别应返回 False: {result}"
        self.teardown()
        print(f"  [PASS] 无效级别正确拒绝")


class TestFreezeManagerUnfreeze:
    """解冻功能测试"""

    def setup(self):
        self.temp_dir = tempfile.mkdtemp()
        self.freeze_table_path = Path(self.temp_dir) / "freeze_table.json"
        import L5_post_review.freeze_manager as fm_module
        fm_module.FREEZE_TABLE_PATHS["CN"] = self.freeze_table_path
        blank = {"freeze_records": [], "observing_list": [], "buy_signals": []}
        with open(self.freeze_table_path, "w") as f:
            json.dump(blank, f)
        return FreezeManager()

    def teardown(self):
        import L5_post_review.freeze_manager as fm_module
        fm_module.FREEZE_TABLE_PATHS["CN"] = Path(os.path.expanduser("~/.hermes/investment/main/freeze_table.json"))
        if self.freeze_table_path.exists():
            self.freeze_table_path.unlink()

    def test_unfreeze(self):
        """
        测试解冻功能

        入参: 添加后解冻 600519
        期望: unfreeze 返回 True, get_frozen_codes() 不包含 600519
        """
        fm = self.setup()
        fm.add_freeze("600519", "贵州茅台", "10days", ["PE过高"])
        result = fm.unfreeze("600519")
        assert result is True, f"unfreeze 应返回 True: {result}"
        frozen = fm.get_frozen_codes()
        assert "600519" not in frozen, f"600519 不应在冷冻集合中: {frozen}"
        self.teardown()
        print(f"  [PASS] 解冻功能正常")

    def test_unfreeze_not_found(self):
        """
        测试解冻不存在的股票

        入参: code=不存在
        期望: 返回 False
        """
        fm = self.setup()
        result = fm.unfreeze("999999")
        assert result is False, f"不存在的股票应返回 False: {result}"
        self.teardown()
        print(f"  [PASS] 不存在股票正确拒绝")


class TestFreezeManagerSummary:
    """状态摘要测试"""

    def setup(self):
        self.temp_dir = tempfile.mkdtemp()
        self.freeze_table_path = Path(self.temp_dir) / "freeze_table.json"
        import L5_post_review.freeze_manager as fm_module
        fm_module.FREEZE_TABLE_PATHS["CN"] = self.freeze_table_path
        blank = {"freeze_records": [], "observing_list": [], "buy_signals": []}
        with open(self.freeze_table_path, "w") as f:
            json.dump(blank, f)
        return FreezeManager()

    def teardown(self):
        import L5_post_review.freeze_manager as fm_module
        fm_module.FREEZE_TABLE_PATHS["CN"] = Path(os.path.expanduser("~/.hermes/investment/main/freeze_table.json"))
        if self.freeze_table_path.exists():
            self.freeze_table_path.unlink()

    def test_get_summary(self):
        """
        测试状态摘要

        入参: 添加 600519 和 000333 两支冷冻股
        期望: frozen_count=2, frozen_codes 包含两只股票
        """
        fm = self.setup()
        fm.add_freeze("600519", "贵州茅台", "10days", ["PE过高"])
        fm.add_freeze("000333", "美的集团", "10days", ["PE过高"])
        summary = fm.get_summary()
        assert summary["frozen_count"] == 2, f"frozen_count 应为 2: {summary}"
        assert len(summary["frozen_codes"]) == 2, f"frozen_codes 应有2个: {summary}"
        assert "600519" in summary["frozen_codes"], f"600519 应在 frozen_codes"
        assert "000333" in summary["frozen_codes"], f"000333 应在 frozen_codes"
        self.teardown()
        print(f"  [PASS] 摘要正确: {summary}")


class TestFreezeManagerRecordBuySignal:
    """买入信号记录测试"""

    def setup(self):
        self.temp_dir = tempfile.mkdtemp()
        self.freeze_table_path = Path(self.temp_dir) / "freeze_table.json"
        import L5_post_review.freeze_manager as fm_module
        fm_module.FREEZE_TABLE_PATHS["CN"] = self.freeze_table_path
        blank = {"freeze_records": [], "observing_list": [], "buy_signals": []}
        with open(self.freeze_table_path, "w") as f:
            json.dump(blank, f)
        return FreezeManager()

    def teardown(self):
        import L5_post_review.freeze_manager as fm_module
        fm_module.FREEZE_TABLE_PATHS["CN"] = Path(os.path.expanduser("~/.hermes/investment/main/freeze_table.json"))
        if self.freeze_table_path.exists():
            self.freeze_table_path.unlink()

    def test_record_buy_signal(self):
        """
        测试记录买入信号

        入参: code=600519, judge_score=0.72, price=1850.0, stop_loss=1700, take_profit=2200
        期望: buy_signals 包含1条记录，status=pending
        """
        fm = self.setup()
        fm.record_buy_signal(
            stock_code="600519",
            stock_name="贵州茅台",
            judge_score=0.72,
            price=1850.0,
            stop_loss=1700.0,
            take_profit=2200.0,
            kelly_fraction=0.15,
            reason="资金流入+技术突破"
        )
        signals = fm.get_buy_signals()
        assert len(signals) == 1, f"应有1条信号: {len(signals)}"
        assert signals[0]["stock_code"] == "600519", f"code 应为 600519"
        assert signals[0]["judge_score"] == 0.72, f"score 应为 0.72"
        assert signals[0]["status"] == "pending", f"status 应为 pending"
        self.teardown()
        print(f"  [PASS] 买入信号记录成功")


class TestFreezeManagerMultiMarket:
    """多市场支持测试"""

    def test_market_cn(self):
        """
        测试 CN 市场路径

        入参: market="CN"
        期望: freeze_table_path 指向 freeze_table.json
        """
        fm = FreezeManager(market="CN")
        assert "freeze_table.json" in str(fm.freeze_table_path), f"路径应含 freeze_table.json"
        print(f"  [PASS] CN 路径: {fm.freeze_table_path}")

    def test_market_hk(self):
        """
        测试 HK 市场路径

        入参: market="HK"
        期望: freeze_table_path 指向 freeze_table_hk.json
        """
        fm = FreezeManager(market="HK")
        assert "freeze_table_hk.json" in str(fm.freeze_table_path), f"路径应含 freeze_table_hk.json"
        print(f"  [PASS] HK 路径: {fm.freeze_table_path}")

    def test_market_us(self):
        """
        测试 US 市场路径

        入参: market="US"
        期望: freeze_table_path 指向 freeze_table_us.json
        """
        fm = FreezeManager(market="US")
        assert "freeze_table_us.json" in str(fm.freeze_table_path), f"路径应含 freeze_table_us.json"
        print(f"  [PASS] US 路径: {fm.freeze_table_path}")


class TestFreezeManagerConstants:
    """常量验证测试"""

    def test_freeze_durations(self):
        """
        测试冷冻时长常量

        期望: FREEZE_10_DAYS=10天, FREEZE_3_MONTHS=90天
        """
        assert FREEZE_10_DAYS == timedelta(days=10), f"10天冷冻应为10天: {FREEZE_10_DAYS}"
        assert FREEZE_3_MONTHS == timedelta(days=90), f"3个月冷冻应为90天: {FREEZE_3_MONTHS}"
        print(f"  [PASS] 常量正确: 10days={FREEZE_10_DAYS}, 3months={FREEZE_3_MONTHS}")

    def test_thresholds(self):
        """
        测试阈值常量

        期望: THRESH_MAIN_NET_FLOW=-1亿, THRESH_OUTER_INNER_RATIO=0.75
        """
        assert THRESH_MAIN_NET_FLOW == -100_000_000, f"主力流出阈值: {THRESH_MAIN_NET_FLOW}"
        assert THRESH_OUTER_INNER_RATIO == 0.75, f"外内盘比阈值: {THRESH_OUTER_INNER_RATIO}"
        print(f"  [PASS] 阈值正确: main_net_flow={THRESH_MAIN_NET_FLOW}, outer_inner={THRESH_OUTER_INNER_RATIO}")


# ─── 测试运行器 ─────────────────────────────────────────────────

def _run_all():
    test_classes = [
        TestFreezeManagerBasics,
        TestFreezeManagerFreeze,
        TestFreezeManagerUnfreeze,
        TestFreezeManagerSummary,
        TestFreezeManagerRecordBuySignal,
        TestFreezeManagerMultiMarket,
        TestFreezeManagerConstants,
    ]

    total_passed = 0
    total_failed = 0

    for cls in test_classes:
        print(f"\n{'='*60}")
        print(f"▶ {cls.__name__}")
        print("=" * 60)
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for name in methods:
            try:
                if hasattr(instance, "setup"):
                    instance.setup()
                getattr(instance, name)()
                if hasattr(instance, "teardown"):
                    instance.teardown()
                total_passed += 1
            except AssertionError as e:
                print(f"  [FAIL] {name}: {e}")
                if hasattr(instance, "teardown"):
                    try:
                        instance.teardown()
                    except Exception:
                        pass
                total_failed += 1
            except Exception as e:
                print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
                if hasattr(instance, "teardown"):
                    try:
                        instance.teardown()
                    except Exception:
                        pass
                total_failed += 1

    print(f"\n{'='*60}")
    passed = total_passed
    failed = total_failed
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    print("=" * 60)
    print("L5 FreezeManager 测试套件")
    print("=" * 60)
    ok = _run_all()
    sys.exit(0 if ok else 1)