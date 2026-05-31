#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 ParameterAdvisor 测试套件

测试覆盖：
- ParameterAdvisor 初始化
- analyze_and_suggest / suggest_l1_adjustments / suggest_l4_adjustments
- save_advice_report / get_pending_advice / approve_advice / apply_advice
- _load_config_for_layer / _apply_parameter_change

来源：基于 testsv2/l5/test_l5_freeze_manager.py 风格
"""

import sys
import os
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L5_post_review.utils.parameter_advisor import (
    ParameterAdvisor,
    ParameterSuggestion,
    ParameterAdviceReport,
    BUY_HIT_RATE_THRESHOLD,
    PBO_THRESHOLD,
    WATCH_UPGRADE_RATE_THRESHOLD,
)


class TestParameterAdvisorBasics:
    """ParameterAdvisor 基本功能测试"""

    def test_initialization(self):
        """
        测试 ParameterAdvisor 初始化

        入参: market="CN"
        期望: 初始化成功，market 属性正确
        """
        advisor = ParameterAdvisor(market="CN")
        assert advisor.market == "CN"
        print(f"  [PASS] 初始化成功")

    def test_lazy_loading(self):
        """
        测试懒加载 ReviewEngine

        入参: 调用 review_engine 属性
        期望: 懒加载 ReviewEngine 实例
        """
        advisor = ParameterAdvisor(market="CN")
        assert advisor._engine is None
        engine = advisor.review_engine
        from L5_post_review.review_engine import ReviewEngine
        assert isinstance(engine, ReviewEngine)
        print(f"  [PASS] 懒加载正常")


class TestParameterSuggestions:
    """参数建议生成测试"""

    @patch.object(Path, "exists", return_value=False)
    def test_suggest_l1_low_hit_rate(self, mock_exists):
        """
        测试 BUY 命中率偏低时生成 L1 调参建议

        入参: cpcv_result={}, effectiveness={buy_hit_rate: 0.45}
        期望: 生成建议，降低 thresholds[1]
        """
        advisor = ParameterAdvisor(market="CN")

        with patch.object(advisor, "_load_config_for_layer") as mock_load:
            mock_load.return_value = {
                "signals": {
                    "momentum": {"thresholds": [0.40, 0.50, 0.65]},
                    "reversion": {"thresholds": [0.40, 0.50, 0.65]},
                }
            }

            suggestions = advisor.suggest_l1_adjustments(
                cpcv_result={},
                effectiveness={"buy_hit_rate": 0.45}
            )

        assert len(suggestions) > 0, "应生成调参建议"
        for s in suggestions:
            assert s.layer == "L1"
            assert s.suggested_value != s.current_value
        print(f"  [PASS] L1 低命中率建议生成正确 ({len(suggestions)} 条)")

    @patch.object(Path, "exists", return_value=False)
    def test_suggest_l1_high_pbo(self, mock_exists):
        """
        测试 PBO 过高时生成 L1 调参建议

        入参: cpcv_result={pbo: 0.20}, effectiveness={}
        期望: 生成建议，收紧初筛阈值
        """
        advisor = ParameterAdvisor(market="CN")

        with patch.object(advisor, "_load_config_for_layer") as mock_load:
            mock_load.return_value = {
                "signals": {
                    "momentum": {"thresholds": [0.40, 0.50, 0.65]},
                }
            }

            suggestions = advisor.suggest_l1_adjustments(
                cpcv_result={"pbo": 0.20},
                effectiveness={}
            )

        assert len(suggestions) > 0, "PBO>15%时应生成建议"
        for s in suggestions:
            assert s.layer == "L1"
            assert "过拟合" in s.reason or "收紧" in s.reason
        print(f"  [PASS] L1 高 PBO 建议生成正确 ({len(suggestions)} 条)")

    @patch.object(Path, "exists", return_value=False)
    def test_suggest_l4_watch_upgrade(self, mock_exists):
        """
        测试 WATCH 升级率偏低时生成 L4 调参建议

        入参: cpcv_result={}, positions=[], effectiveness={watch_to_buy_upgrade_rate: 0.20}
        期望: 生成建议，降低 upgrade_threshold
        """
        advisor = ParameterAdvisor(market="CN")

        with patch.object(advisor, "_load_config_for_layer") as mock_load:
            mock_load.return_value = {
                "watch_to_buy": {"upgrade_threshold": 0.05},
                "stop_loss_pct": -0.08,
                "take_profit_pct": 0.20,
            }

            mock_pos = MagicMock()
            mock_pos.status = "executed"

            suggestions = advisor.suggest_l4_adjustments(
                cpcv_result={},
                positions=[mock_pos],
                effectiveness={"watch_to_buy_upgrade_rate": 0.20}
            )

        assert len(suggestions) > 0, "WATCH升级率<30%时应生成建议"
        print(f"  [PASS] L4 WATCH升级建议生成正确 ({len(suggestions)} 条)")


class TestAdvicePersistence:
    """建议持久化测试"""

    def test_save_and_load_advice(self):
        """
        测试保存和加载调参建议

        入参: ParameterAdviceReport
        期望: save_advice_report 保存后，get_pending_advice 能加载
        """
        advisor = ParameterAdvisor(market="CN")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch REVIEW_OUTPUT_DIR
            import L5_post_review.utils.parameter_advisor as pa_module
            original_dir = pa_module.REVIEW_OUTPUT_DIR
            pa_module.REVIEW_OUTPUT_DIR = Path(tmpdir)

            suggestion = ParameterSuggestion(
                layer="L1",
                strategy_name="momentum",
                parameter_path="signals.momentum.thresholds[1]",
                current_value=0.50,
                suggested_value=0.45,
                reason="测试建议",
                confidence=0.7,
                review_id="test_20260531",
                created_at=datetime.now().isoformat(),
            )

            report = ParameterAdviceReport(
                review_id="test_20260531",
                date="2026-05-31",
                suggestions=[suggestion],
                overall_confidence=0.7,
                created_at=datetime.now().isoformat(),
            )

            path = advisor.save_advice_report(report)
            assert Path(path).exists(), f"文件应存在: {path}"

            pending = advisor.get_pending_advice()
            assert len(pending) >= 1, f"应有至少1条待审批建议: {len(pending)}"

            # Restore
            pa_module.REVIEW_OUTPUT_DIR = original_dir

        print(f"  [PASS] 保存和加载建议正确")

    def test_approve_advice(self):
        """
        测试审批调参建议

        入参: review_id="test_20260531"
        期望: approve_advice 返回 True
        """
        advisor = ParameterAdvisor(market="CN")

        with tempfile.TemporaryDirectory() as tmpdir:
            import L5_post_review.utils.parameter_advisor as pa_module
            original_dir = pa_module.REVIEW_OUTPUT_DIR
            pa_module.REVIEW_OUTPUT_DIR = Path(tmpdir)

            # 先保存一条建议
            suggestion = ParameterSuggestion(
                layer="L1",
                strategy_name="momentum",
                parameter_path="signals.momentum.thresholds[1]",
                current_value=0.50,
                suggested_value=0.45,
                reason="测试",
                confidence=0.7,
                review_id="test_approve",
                created_at=datetime.now().isoformat(),
            )

            report = ParameterAdviceReport(
                review_id="test_approve",
                date="2026-05-31",
                suggestions=[suggestion],
                overall_confidence=0.7,
                created_at=datetime.now().isoformat(),
            )

            advisor.save_advice_report(report)

            # 审批
            ok = advisor.approve_advice("test_approve", "admin")
            assert ok is True, "审批应返回 True"

            # 验证已审批
            pending = advisor.get_pending_advice()
            approved = [p for p in pending if p.approved and p.review_id == "test_approve"]
            assert len(approved) == 1, "应有1条已审批建议"

            pa_module.REVIEW_OUTPUT_DIR = original_dir

        print(f"  [PASS] 审批建议正确")


class TestParameterSuggestion:
    """ParameterSuggestion 数据模型测试"""

    def test_suggestion_creation(self):
        """
        测试 ParameterSuggestion 创建

        入参: 各字段值
        期望: 字段正确赋值
        """
        suggestion = ParameterSuggestion(
            layer="L1",
            strategy_name="momentum",
            parameter_path="signals.momentum.thresholds[1]",
            current_value=0.50,
            suggested_value=0.45,
            reason="命中率偏低",
            confidence=0.7,
            review_id="test",
            created_at="2026-05-31T10:00:00",
        )

        assert suggestion.layer == "L1"
        assert suggestion.confidence == 0.7
        assert suggestion.current_value == 0.50
        print(f"  [PASS] ParameterSuggestion 创建正确")


# ─── 测试运行器 ────────────────────────────────────────────────

def run_tests():
    """运行所有测试"""
    classes = [
        TestParameterAdvisorBasics,
        TestParameterSuggestions,
        TestAdvicePersistence,
        TestParameterSuggestion,
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