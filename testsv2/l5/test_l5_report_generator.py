#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 ReportGenerator 测试套件

测试覆盖：
- ReportGenerator 初始化
- generate_daily_report / generate_weekly_report
- 章节构建方法
- _render_markdown 渲染
- save_report 保存

来源：基于 testsv2/l5/test_l5_freeze_manager.py 风格
"""

import sys
import os
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L5_post_review.utils.report_generator import (
    ReportGenerator,
    GeneratedReport,
    ReportSection,
)


class TestReportGeneratorBasics:
    """ReportGenerator 基本功能测试"""

    def test_initialization(self):
        """
        测试 ReportGenerator 初始化

        入参: market="CN"
        期望: 初始化成功，market 属性正确
        """
        rg = ReportGenerator(market="CN")
        assert rg.market == "CN"
        assert rg._engine is None  # 懒加载
        assert rg._freeze_mgr is None
        print(f"  [PASS] 初始化成功")

    def test_lazy_loading(self):
        """
        测试懒加载子模块

        入参: 调用 review_engine 属性
        期望: 懒加载 ReviewEngine 实例
        """
        rg = ReportGenerator(market="CN")
        # 不调用 review_engine 前应为 None
        assert rg._engine is None
        # 调用后应加载
        engine = rg.review_engine
        from L5_post_review.review_engine import ReviewEngine
        assert isinstance(engine, ReviewEngine)
        print(f"  [PASS] 懒加载正常")


class TestReportSections:
    """报告章节构建测试"""

    @patch.object(Path, "exists", return_value=False)
    def test_build_operations_section(self, mock_exists):
        """
        测试操作回顾章节构建

        入参: mock空的position_tracker
        期望: 返回包含表格内容的 ReportSection
        """
        rg = ReportGenerator(market="CN")
        # Mock position_tracker 返回空列表（patch _tracker 内部属性）
        mock_pt = MagicMock()
        mock_pt.get_positions.return_value = []
        rg._tracker = mock_pt
        section = rg._build_operations_section("2026-05-31")

        assert isinstance(section, ReportSection)
        assert "操作回顾" in section.title
        assert "当日无操作记录" in section.content
        print(f"  [PASS] 操作回顾章节构建正确")

    @patch.object(Path, "exists", return_value=False)
    def test_build_positions_section(self, mock_exists):
        """
        测试持仓状态章节构建

        入参: mock position_tracker
        期望: 返回持仓统计内容
        """
        rg = ReportGenerator(market="CN")
        mock_pt = MagicMock()
        mock_summary = MagicMock()
        mock_summary.pending_count = 1
        mock_summary.executed_count = 2
        mock_summary.stopped_count = 0
        mock_summary.take_profit_count = 0
        mock_summary.expired_count = 0
        mock_summary.total_count = 3
        mock_summary.total_pnl_pct = 0.05
        mock_summary.avg_holding_days = 10.5
        mock_pt.get_position_summary.return_value = mock_summary
        rg._tracker = mock_pt

        section = rg._build_positions_section("2026-05-31")

        assert isinstance(section, ReportSection)
        assert "持仓状态" in section.title
        assert "pending" in section.content
        print(f"  [PASS] 持仓状态章节构建正确")

    def test_build_freeze_section(self):
        """
        测试冷冻状态章节构建

        入参: mock freeze_manager
        期望: 返回冷冻统计内容
        """
        rg = ReportGenerator(market="CN")
        mock_fm = MagicMock()
        mock_fm.get_summary.return_value = {
            "frozen_count": 5,
            "observing_count": 3,
            "buy_signals_count": 2,
            "frozen_codes": ["600519", "000858"],
        }
        rg._freeze_mgr = mock_fm
        section = rg._build_freeze_section()

        assert isinstance(section, ReportSection)
        assert "冷冻状态" in section.title
        assert "5" in section.content
        print(f"  [PASS] 冷冻状态章节构建正确")


class TestReportGeneration:
    """报告生成测试"""

    @patch.object(Path, "exists", return_value=False)
    def test_generate_daily_report_structure(self, mock_exists):
        """
        测试每日报告结构

        入参: mock 各子模块
        期望: GeneratedReport 包含必要字段
        """
        rg = ReportGenerator(market="CN")

        mock_pt = MagicMock()
        mock_pt.get_positions.return_value = []
        mock_pt.get_position_summary.return_value = MagicMock(
            pending_count=0, executed_count=0, stopped_count=0,
            take_profit_count=0, expired_count=0, total_count=0,
            total_pnl_pct=0.0, avg_holding_days=0.0
        )

        mock_fm = MagicMock()
        mock_fm.get_summary.return_value = {
            "frozen_count": 0, "observing_count": 0, "buy_signals_count": 0
        }

        mock_re = MagicMock()
        mock_re.get_effectiveness_report.return_value = MagicMock(
            buy_hit_rate=0.0, buy_avg_return=0.0,
            watch_to_buy_upgrade_rate=0.0, reject_keep_dropping_rate=0.0,
            win_loss_ratio=0.0, sharpe_like=0.0
        )
        mock_re.run_review.return_value = {"cpcv_validation": {}}

        rg._tracker = mock_pt
        rg._freeze_mgr = mock_fm
        rg._engine = mock_re

        with patch.object(rg, "_get_report_path") as mock_path:
            mock_path.return_value = Path(tempfile.mktemp(suffix=".md"))
            report = rg.generate_daily_report("2026-05-31")

        assert isinstance(report, GeneratedReport)
        assert report.report_type == "daily"
        assert report.date == "2026-05-31"
        assert len(report.sections) > 0
        assert report.generated_at != ""
        print(f"  [PASS] 每日报告结构正确")

    def test_weekly_report_id(self):
        """
        测试周报 report_id 格式

        入参: week_start="2026-05-25"（周一）
        期望: report_id 包含 week_start
        """
        rg = ReportGenerator(market="CN")
        mock_pt = MagicMock()
        mock_pt.get_positions.return_value = []
        mock_pt.get_position_summary.return_value = MagicMock(
            pending_count=0, executed_count=0, stopped_count=0,
            take_profit_count=0, expired_count=0, total_count=0,
            total_pnl_pct=0.0, avg_holding_days=0.0
        )
        mock_fm = MagicMock()
        mock_fm.get_summary.return_value = {
            "frozen_count": 0, "observing_count": 0, "buy_signals_count": 0
        }
        mock_re = MagicMock()
        mock_re.get_effectiveness_report.return_value = MagicMock(
            buy_hit_rate=0.0, buy_avg_return=0.0,
            watch_to_buy_upgrade_rate=0.0, reject_keep_dropping_rate=0.0,
            win_loss_ratio=0.0, sharpe_like=0.0
        )
        mock_re.run_review.return_value = {"cpcv_validation": {}}

        rg._tracker = mock_pt
        rg._freeze_mgr = mock_fm
        rg._engine = mock_re

        with patch.object(rg, "_get_report_path") as mock_path:
            mock_path.return_value = Path(tempfile.mktemp(suffix=".md"))
            report = rg.generate_weekly_report("2026-05-25")

        assert "weekly" in report.report_type
        assert report.week_start == "2026-05-25"
        assert report.week_end == "2026-05-31"
        print(f"  [PASS] 周报 report_id 正确")


class TestReportRendering:
    """报告渲染测试"""

    def test_render_markdown(self):
        """
        测试 Markdown 渲染

        入参: 包含标题和内容的 GeneratedReport
        期望: 输出包含 #标题的 Markdown
        """
        rg = ReportGenerator(market="CN")
        report = GeneratedReport(
            report_id="20260531_daily",
            report_type="daily",
            date="2026-05-31",
            sections=[
                ReportSection(title="测试章节", content="测试内容", order=1, level=2),
            ],
            generated_at="2026-05-31T10:00:00",
            markets=["CN"],
        )

        md = rg._render_markdown(report)

        assert "# 神农系统" in md
        assert "测试章节" in md
        assert "测试内容" in md
        assert "生成时间" in md
        print(f"  [PASS] Markdown 渲染正确")

    def test_render_weekly_markdown(self):
        """
        测试周报 Markdown 渲染

        入参: weekly report
        期望:包含周期信息
        """
        rg = ReportGenerator(market="CN")
        report = GeneratedReport(
            report_id="20260525_weekly",
            report_type="weekly",
            date="2026-05-31",
            week_start="2026-05-25",
            week_end="2026-05-31",
            sections=[],
            generated_at="2026-05-31T10:00:00",
            markets=["CN"],
        )

        md = rg._render_markdown(report)

        assert "2026-05-25 ~ 2026-05-31" in md
        print(f"  [PASS] 周报 Markdown 渲染正确")


# ─── 测试运行器 ────────────────────────────────────────────────

def run_tests():
    """运行所有测试"""
    classes = [
        TestReportGeneratorBasics,
        TestReportSections,
        TestReportGeneration,
        TestReportRendering,
    ]

    total = 0
    passed = 0

    for cls in classes:
        print(f"\n{'='*60}")
        print(f"测试类: {cls.__name__}")
        print('='*60)
        instance = cls()

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

    print(f"\n{'='*60}")
    print(f"测试结果: {passed}/{total} 通过")
    print('='*60)


if __name__ == "__main__":
    run_tests()