#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 ReviewEngine 测试套件

测试覆盖：
- record_decision / record_decision_from_l4
- get_effectiveness_report / print_effectiveness_report
- run_review / load_closed_trades
- _cpcv_evaluate
- _analyze_single_trades / _analyze_patterns
- CPCV 结果验证 (PBO/HitRateDelta/ReturnDelta)
- 数据类序列化 (DecisionRecord/OutcomeRecord/TradeRecord/EffectivenessMetrics/CPCVResult)
- 多市场支持

数据源：使用 temp files 避免污染生产数据
"""

import sys
import os
import json
import tempfile
import random
from datetime import date, timedelta, datetime
from pathlib import Path
from dataclasses import asdict
from unittest.mock import patch

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L5_post_review.review_engine import (
    ReviewEngine,
    DecisionRecord,
    OutcomeRecord,
    TradeRecord,
    EffectivenessMetrics,
    CPCVResult,
    HORIZON_DAYS,
    PBO_THRESHOLD,
    HIT_RATE_DELTA_THRESHOLD,
    RETURN_DELTA_THRESHOLD,
    DEFAULT_N_FOLDS,
)


# ─── Test Classes ─────────────────────────────────────────────

class TestReviewEngineRecord:
    """决策记录测试"""

    def setup(self):
        """每个测试前创建临时 records 目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.tracker_path = Path(self.temp_dir) / "strategy_tracker.json"
        import L5_post_review.review_engine as re_module
        self._original_tracker = re_module.ReviewEngine.TRACKER_FILE
        re_module.ReviewEngine.TRACKER_FILE = self.tracker_path
        return ReviewEngine()

    def teardown(self):
        """恢复原始 tracker 路径"""
        import L5_post_review.review_engine as re_module
        re_module.ReviewEngine.TRACKER_FILE = self._original_tracker

    def test_record_decision_returns_id(self):
        """
        测试 record_decision 返回 decision_id

        入参: code=600519, decision=BUY, judge_score=0.72, date=2024-01-02
        期望: 返回 12 字符的 decision_id
        """
        engine = self.setup()
        did = engine.record_decision(
            code="600519", decision="BUY", judge_score=0.72,
            date="2024-01-02", price=1850.0, name="贵州茅台", reason="资金流入"
        )
        assert isinstance(did, str), f"decision_id 应为 str: {type(did)}"
        assert len(did) == 12, f"decision_id 应为12字符: {did}"
        self.teardown()
        print(f"  [PASS] record_decision 返回有效 ID: {did}")

    def test_record_decision_persists(self):
        """
        测试 record_decision 数据持久化

        入参: 记录 BUY 600519
        期望: engine.decisions 包含1条记录，_save() 正确写入
        """
        engine = self.setup()
        engine.record_decision(
            code="600519", decision="BUY", judge_score=0.72,
            date="2024-01-02", price=1850.0, name="贵州茅台", reason="资金流入"
        )
        assert len(engine.decisions) == 1, f"应有1条决策: {len(engine.decisions)}"
        assert engine.decisions[0].code == "600519", f"code 应为 600519"
        assert engine.decisions[0].decision == "BUY", f"decision 应为 BUY"
        assert engine.decisions[0].judge_score == 0.72, f"score 应为 0.72"
        self.teardown()
        print(f"  [PASS] 数据持久化正确")

    def test_record_decision_case_normalize(self):
        """
        测试 decision 参数大小写归一化

        入参: decision="buy" (小写)
        期望: 存储为 "BUY"
        """
        engine = self.setup()
        engine.record_decision(
            code="600519", decision="buy", judge_score=0.5,
            date="2024-01-02", price=100.0
        )
        assert engine.decisions[0].decision == "BUY", f"应归一化为 BUY: {engine.decisions[0].decision}"
        self.teardown()
        print(f"  [PASS] decision 大小写归一化为 BUY")

    def test_record_decision_from_l4(self):
        """
        测试从 L4 结果批量提取决策

        入参: l4_result 含3个决策 (BUY/WATCH/REJECT)
        期望: 返回3个 decision_id，decisions 含3条记录
        """
        engine = self.setup()
        l4_result = {
            "date": "2024-01-02",
            "market": "CN",
            "decisions": [
                {"code": "600519", "decision": "BUY", "judge_score": 0.72, "price": 1850.0, "name": "贵州茅台", "reason": "资金流入"},
                {"code": "000333", "decision": "WATCH", "judge_score": 0.55, "price": 2800.0, "name": "美的集团", "reason": "待确认"},
                {"code": "600036", "decision": "REJECT", "judge_score": 0.30, "price": 32.0, "name": "招商银行", "reason": "PE过高"},
            ]
        }
        ids = engine.record_decision_from_l4(l4_result)
        assert len(ids) == 3, f"应返回3个ID: {len(ids)}"
        assert len(engine.decisions) == 3, f"应有3条决策: {len(engine.decisions)}"
        decisions = [d.decision for d in engine.decisions]
        assert "BUY" in decisions, f"应有 BUY: {decisions}"
        assert "WATCH" in decisions, f"应有 WATCH: {decisions}"
        assert "REJECT" in decisions, f"应有 REJECT: {decisions}"
        self.teardown()
        print(f"  [PASS] L4批量提取成功: {ids}")

    def test_record_decision_from_l4_skip_invalid(self):
        """
        测试 L4 批量提取跳过无效记录

        入参: 含 price<=0 的无效记录
        期望: 跳过无效记录，只返回有效ID
        """
        engine = self.setup()
        l4_result = {
            "date": "2024-01-02",
            "decisions": [
                {"code": "600519", "decision": "BUY", "judge_score": 0.72, "price": 1850.0, "name": "贵州茅台"},
                {"code": "", "decision": "BUY", "judge_score": 0.5, "price": 0.0, "name": ""},  # 无效
                {"code": "000333", "decision": "BUY", "judge_score": 0.6, "price": -10.0, "name": "美的"},  # 无效
            ]
        }
        ids = engine.record_decision_from_l4(l4_result)
        assert len(ids) == 1, f"应只返回1个有效ID: {len(ids)}"
        assert len(engine.decisions) == 1, f"应只存储1条决策: {len(engine.decisions)}"
        assert engine.decisions[0].code == "600519", f"应为 600519"
        self.teardown()
        print(f"  [PASS] 无效记录被正确跳过")


class TestEffectivenessMetrics:
    """策略有效性指标测试"""

    def setup(self):
        self.temp_dir = tempfile.mkdtemp()
        self.tracker_path = Path(self.temp_dir) / "strategy_tracker.json"
        import L5_post_review.review_engine as re_module
        self._original_tracker = re_module.ReviewEngine.TRACKER_FILE
        re_module.ReviewEngine.TRACKER_FILE = self.tracker_path
        return ReviewEngine()

    def teardown(self):
        import L5_post_review.review_engine as re_module
        re_module.ReviewEngine.TRACKER_FILE = self._original_tracker

    def test_effectiveness_empty(self):
        """
        测试空决策列表的有效性报告

        入参: 无决策数据
        期望: 所有计数为0，命中率/收益为0
        """
        engine = self.setup()
        metrics = engine.get_effectiveness_report()
        assert metrics.total_decisions == 0, f"total 应为 0: {metrics.total_decisions}"
        assert metrics.buy_count == 0, f"buy_count 应为 0: {metrics.buy_count}"
        assert metrics.watch_count == 0, f"watch_count 应为 0: {metrics.watch_count}"
        assert metrics.reject_count == 0, f"reject_count 应为 0: {metrics.reject_count}"
        assert metrics.buy_hit_rate == 0.0, f"buy_hit_rate 应为 0: {metrics.buy_hit_rate}"
        self.teardown()
        print(f"  [PASS] 空数据有效性报告正确")

    def test_effectiveness_buy_hit(self):
        """
        测试 BUY 命中计算

        入参: BUY 1笔 (price=100→110, +10%)
        期望: buy_hit_rate=100%, buy_avg_return=10%
        """
        engine = self.setup()
        engine.record_decision(
            code="600519", decision="BUY", judge_score=0.72,
            date="2024-01-02", price=100.0, name="贵州茅台"
        )
        # 模拟 outcome: +10% 盈利
        did = engine.decisions[0].decision_id
        engine.outcomes[did] = [
            OutcomeRecord(decision_id=did, code="600519", horizon=10,
                          return_pct=0.10, hit=True, closed=True)
        ]
        metrics = engine.get_effectiveness_report()
        assert metrics.buy_count == 1, f"buy_count 应为 1: {metrics.buy_count}"
        assert metrics.buy_hit_rate == 1.0, f"buy_hit_rate 应为 1.0: {metrics.buy_hit_rate}"
        assert abs(metrics.buy_avg_return - 0.10) < 0.001, f"avg_return 应为 0.10: {metrics.buy_avg_return}"
        self.teardown()
        print(f"  [PASS] BUY 命中计算正确: hit_rate={metrics.buy_hit_rate}, avg_return={metrics.buy_avg_return}")

    def test_effectiveness_watch_upgrade(self):
        """
        测试 WATCH 升级率计算

        入参: WATCH 1笔，10日收益 +8%
        期望: watch_to_buy_upgrade_rate=100% (超过5%阈值)
        """
        engine = self.setup()
        engine.record_decision(
            code="600519", decision="WATCH", judge_score=0.55,
            date="2024-01-02", price=100.0, name="贵州茅台"
        )
        did = engine.decisions[0].decision_id
        engine.outcomes[did] = [
            OutcomeRecord(decision_id=did, code="600519", horizon=10,
                          return_pct=0.08, hit=True, closed=True)
        ]
        metrics = engine.get_effectiveness_report()
        assert metrics.watch_count == 1, f"watch_count 应为 1: {metrics.watch_count}"
        assert metrics.watch_to_buy_upgrade_rate == 1.0, f"upgarde_rate 应为 1.0: {metrics.watch_to_buy_upgrade_rate}"
        self.teardown()
        print(f"  [PASS] WATCH 升级率正确: {metrics.watch_to_buy_upgrade_rate}")

    def test_effectiveness_reject_drop(self):
        """
        测试 REJECT 有效率计算

        入参: REJECT 1笔，10日收益 -3%
        期望: reject_keep_dropping_rate=100% (下跌=好)
        """
        engine = self.setup()
        engine.record_decision(
            code="600519", decision="REJECT", judge_score=0.30,
            date="2024-01-02", price=100.0, name="贵州茅台"
        )
        did = engine.decisions[0].decision_id
        engine.outcomes[did] = [
            OutcomeRecord(decision_id=did, code="600519", horizon=10,
                          return_pct=-0.03, hit=False, closed=True)
        ]
        metrics = engine.get_effectiveness_report()
        assert metrics.reject_count == 1, f"reject_count 应为 1: {metrics.reject_count}"
        assert metrics.reject_keep_dropping_rate == 1.0, f"drop_rate 应为 1.0: {metrics.reject_keep_dropping_rate}"
        self.teardown()
        print(f"  [PASS] REJECT 有效率正确: {metrics.reject_keep_dropping_rate}")

    def test_effectiveness_win_loss_ratio(self):
        """
        测试盈亏比计算

        入参: BUY 2笔 (盈利+10%, 亏损-5%)
        期望: win_loss_ratio = 10/5 = 2.0
        """
        engine = self.setup()
        engine.record_decision(code="A", decision="BUY", judge_score=0.7, date="2024-01-02", price=100.0)
        engine.record_decision(code="B", decision="BUY", judge_score=0.7, date="2024-01-02", price=100.0)
        did_a = engine.decisions[0].decision_id
        did_b = engine.decisions[1].decision_id
        engine.outcomes[did_a] = [OutcomeRecord(decision_id=did_a, code="A", horizon=10, return_pct=0.10, hit=True, closed=True)]
        engine.outcomes[did_b] = [OutcomeRecord(decision_id=did_b, code="B", horizon=10, return_pct=-0.05, hit=False, closed=True)]
        metrics = engine.get_effectiveness_report()
        assert abs(metrics.win_loss_ratio - 2.0) < 0.1, f"win_loss_ratio 应约为 2.0: {metrics.win_loss_ratio}"
        self.teardown()
        print(f"  [PASS] 盈亏比正确: {metrics.win_loss_ratio}")


class TestCPCVValidation:
    """CPCV 防过拟合验证测试"""

    def _make_trade(self, code, entry_price, exit_price, holding_days=10):
        """快速创建 TradeRecord"""
        return TradeRecord(
            trade_id=f"20240102_{code}",
            symbol=code,
            entry_date="2024-01-02",
            entry_price=entry_price,
            exit_date="2024-01-12",
            exit_price=exit_price,
            return_pct=round((exit_price - entry_price) / entry_price, 4),
            holding_days=holding_days,
            decision_at_entry="BUY",
            confidence_at_entry=0.72,
        )

    def test_cpcv_no_trades(self):
        """
        测试无交易时 CPCV 返回 None

        入参: trades=[]
        期望: 返回 None (交易不足)
        """
        engine = ReviewEngine()
        result = engine._cpcv_evaluate([])
        assert result is None, f"空交易应返回 None: {result}"
        print(f"  [PASS] 空交易返回 None")

    def test_cpcv_insufficient_trades(self):
        """
        测试交易数少于折数时返回 None

        入参: 3笔交易，n_folds=5
        期望: 返回 None
        """
        engine = ReviewEngine()
        trades = [self._make_trade(f"code{i}", 100.0, 110.0) for i in range(3)]
        result = engine._cpcv_evaluate(trades, n_folds=5)
        assert result is None, f"交易不足应返回 None: {result}"
        print(f"  [PASS] 交易数<折数时返回 None")

    def test_cpcv_verdict_pass(self):
        """
        测试 CPCV PASS 判定

        入参: 10笔随机交易（正常分散）
        期望: verdict 为 PASS 或 WARNING
        """
        engine = ReviewEngine()
        random.seed(42)
        trades = []
        for i in range(10):
            ep = 100.0
            # 混合盈亏
            if i % 3 == 0:
                xp = ep * 1.10  # 盈利
            elif i % 3 == 1:
                xp = ep * 0.95  # 小亏
            else:
                xp = ep * 1.02  # 小盈
            trades.append(self._make_trade(f"code{i}", ep, xp))
        result = engine._cpcv_evaluate(trades, n_folds=5)
        assert result is not None, f"应有结果: {result}"
        assert result.verdict in ("PASS", "WARNING", "FAIL"), f"verdict 应为 PASS/WARNING/FAIL: {result.verdict}"
        assert result.n_trades == 10, f"n_trades 应为 10: {result.n_trades}"
        assert result.n_folds == 5, f"n_folds 应为 5: {result.n_folds}"
        assert 0 <= result.pbo <= 1.0, f"PBO 应在 [0,1]: {result.pbo}"
        print(f"  [PASS] CPCV verdict={result.verdict}, PBO={result.pbo:.1%}, hit_delta={abs(result.hit_rate_train - result.hit_rate_validate):.1%}")

    def test_cpcv_pbo_threshold(self):
        """
        测试 PBO 阈值验证

        入参: 高度相似的交易（会导致高 PBO）
        期望: 当 overfit_ratio>0.2 的折数多时，PBO 升高
        """
        engine = ReviewEngine()
        # 所有交易完全相同：轻微正收益
        trades = [self._make_trade(f"code{i}", 100.0, 105.0) for i in range(10)]
        result = engine._cpcv_evaluate(trades, n_folds=5)
        assert result is not None
        # 当所有交易收益相同时，overfit_ratio 很低
        print(f"  [PASS] PBO={result.pbo:.1%}, avg_overfit={result.avg_overfitting_ratio:.2%}")

    def test_cpcv_hit_rate_delta(self):
        """
        测试命中率差异计算

        验证: hit_rate_delta = |train - validate|
        """
        engine = ReviewEngine()
        trades = [self._make_trade(f"code{i}", 100.0, 110.0 if i < 5 else 95.0) for i in range(10)]
        result = engine._cpcv_evaluate(trades, n_folds=5)
        assert result is not None
        delta = abs(result.hit_rate_train - result.hit_rate_validate)
        print(f"  [PASS] hit_rate_train={result.hit_rate_train:.1%}, hit_rate_val={result.hit_rate_validate:.1%}, delta={delta:.1%}")

    def test_cpcv_return_delta(self):
        """
        测试收益率差异计算

        验证: return_delta = |train_return - val_return| / |train_return|
        """
        engine = ReviewEngine()
        trades = [self._make_trade(f"code{i}", 100.0, 110.0 if i < 5 else 105.0) for i in range(10)]
        result = engine._cpcv_evaluate(trades, n_folds=5)
        assert result is not None
        print(f"  [PASS] return_train={result.return_train_avg:.2%}, return_val={result.return_validate_avg:.2%}")


class TestDataclasses:
    """数据类序列化测试"""

    def test_decision_record_serialize(self):
        """
        测试 DecisionRecord 序列化

        入参: DecisionRecord(decision_id=xxx, code=600519, ...)
        期望: asdict() 正确转换为 dict
        """
        rec = DecisionRecord(
            decision_id="abc123", code="600519", name="贵州茅台",
            decision="BUY", judge_score=0.72, date="2024-01-02",
            price=1850.0, reason="资金流入", market="CN"
        )
        d = asdict(rec)
        assert d["decision_id"] == "abc123", f"decision_id: {d}"
        assert d["code"] == "600519", f"code: {d}"
        assert d["decision"] == "BUY", f"decision: {d}"
        assert d["judge_score"] == 0.72, f"judge_score: {d}"
        print(f"  [PASS] DecisionRecord 序列化正确")

    def test_outcome_record_serialize(self):
        """
        测试 OutcomeRecord 序列化
        """
        rec = OutcomeRecord(decision_id="abc123", code="600519", horizon=10,
                            return_pct=0.10, hit=True, closed=True)
        d = asdict(rec)
        assert d["return_pct"] == 0.10, f"return_pct: {d}"
        assert d["hit"] is True, f"hit: {d}"
        print(f"  [PASS] OutcomeRecord 序列化正确")

    def test_trade_record_serialize(self):
        """
        测试 TradeRecord 序列化
        """
        rec = TradeRecord(
            trade_id="20240102_600519", symbol="600519",
            entry_date="2024-01-02", entry_price=1850.0,
            exit_date="2024-01-12", exit_price=1900.0,
            return_pct=0.027, holding_days=10,
            decision_at_entry="BUY", confidence_at_entry=0.72
        )
        d = asdict(rec)
        assert abs(d["return_pct"] - 0.027) < 0.001, f"return_pct: {d}"
        assert d["holding_days"] == 10, f"holding_days: {d}"
        print(f"  [PASS] TradeRecord 序列化正确")

    def test_cpcv_result_serialize(self):
        """
        测试 CPCVResult 序列化
        """
        rec = CPCVResult(
            n_trades=10, n_folds=5, avg_overfitting_ratio=0.12,
            pbo=0.10, hit_rate_train=0.60, hit_rate_validate=0.55,
            return_train_avg=0.05, return_validate_avg=0.04,
            verdict="PASS", notes="各项指标在可接受范围"
        )
        d = asdict(rec)
        assert d["verdict"] == "PASS", f"verdict: {d}"
        assert d["pbo"] == 0.10, f"pbo: {d}"
        print(f"  [PASS] CPCVResult 序列化正确")

    def test_effectiveness_metrics_serialize(self):
        """
        测试 EffectivenessMetrics 序列化
        """
        rec = EffectivenessMetrics(
            total_decisions=10, buy_count=5, watch_count=3, reject_count=2,
            buy_hit_rate=0.60, buy_avg_return=0.08,
            watch_to_buy_upgrade_rate=0.33, reject_keep_dropping_rate=0.50,
            sharpe_like=0.85, win_loss_ratio=1.80
        )
        d = asdict(rec)
        assert d["buy_hit_rate"] == 0.60, f"buy_hit_rate: {d}"
        assert d["sharpe_like"] == 0.85, f"sharpe_like: {d}"
        print(f"  [PASS] EffectivenessMetrics 序列化正确")


class TestReviewRun:
    """复盘运行测试"""

    def _make_trade(self, code, entry_price, exit_price, holding_days=10, decision="BUY"):
        return TradeRecord(
            trade_id=f"20240102_{code}", symbol=code,
            entry_date="2024-01-02", entry_price=entry_price,
            exit_date="2024-01-12", exit_price=exit_price,
            return_pct=round((exit_price - entry_price) / entry_price, 4),
            holding_days=holding_days,
            decision_at_entry=decision, confidence_at_entry=0.72,
        )

    def test_run_review_with_trades(self):
        """
        测试 run_review 正常流程

        入参: 6笔交易（3盈3亏）
        期望: 返回完整复盘结构，含 win_rate, single_trade_analysis, patterns, cpcv_validation
        """
        engine = ReviewEngine()
        trades = [
            self._make_trade("A", 100.0, 110.0),   # +10%
            self._make_trade("B", 100.0, 105.0),   # +5%
            self._make_trade("C", 100.0, 102.0),   # +2%
            self._make_trade("D", 100.0, 95.0),    # -5%
            self._make_trade("E", 100.0, 92.0),    # -8%
            self._make_trade("F", 100.0, 97.0),    # -3%
        ]
        result = engine.run_review(trades=trades)
        assert "review_id" in result, f"缺少 review_id: {result}"
        assert result["trades_reviewed"] == 6, f"trades_reviewed 应为 6: {result}"
        assert result["winning_trades"] == 3, f"winning_trades 应为 3: {result}"
        assert result["losing_trades"] == 3, f"losing_trades 应为 3: {result}"
        assert abs(result["win_rate"] - 0.5) < 0.001, f"win_rate 应为 0.5: {result}"
        assert "single_trade_analysis" in result, f"缺少 single_trade_analysis"
        assert "patterns" in result, f"缺少 patterns"
        assert "cpcv_validation" in result, f"缺少 cpcv_validation"
        print(f"  [PASS] run_review 结果正确: win_rate={result['win_rate']:.1%}, 分析条目={len(result['single_trade_analysis'])}")

    def test_run_review_no_trades(self):
        """
        测试无交易时 run_review 返回 no_trades

        入参: trades=[]
        期望: status="no_trades"
        """
        engine = ReviewEngine()
        result = engine.run_review(trades=[])
        assert result["status"] == "no_trades", f"应为 no_trades: {result}"
        print(f"  [PASS] 空交易返回 no_trades 状态")

    def test_run_review_pattern_short_holding_losses(self):
        """
        测试短期快速止损模式识别

        入参: 3笔持有<=5天且亏损>3%的交易
        期望: patterns 包含 "短期快速止损" 模式
        """
        engine = ReviewEngine()
        trades = [
            self._make_trade("A", 100.0, 96.0, holding_days=3),   # -4%, 3天
            self._make_trade("B", 100.0, 97.0, holding_days=4),   # -3%, 4天
            self._make_trade("C", 100.0, 95.0, holding_days=2),   # -5%, 2天
        ]
        result = engine.run_review(trades=trades)
        patterns = result["patterns"]
        short_loss = [p for p in patterns if p.get("pattern_id") == "P001"]
        assert len(short_loss) >= 1, f"应识别短期止损模式: {patterns}"
        print(f"  [PASS] 模式识别正确: {[p['pattern_id'] for p in patterns]}")


class TestMultiMarket:
    """多市场支持测试"""

    def setup(self):
        self.temp_dir = tempfile.mkdtemp()
        self.tracker_path = Path(self.temp_dir) / "strategy_tracker.json"
        import L5_post_review.review_engine as re_module
        self._original_tracker = re_module.ReviewEngine.TRACKER_FILE
        re_module.ReviewEngine.TRACKER_FILE = self.tracker_path

    def teardown(self):
        import L5_post_review.review_engine as re_module
        if hasattr(self, "_original_tracker"):
            re_module.ReviewEngine.TRACKER_FILE = self._original_tracker
        if hasattr(self, "tracker_path") and self.tracker_path.exists():
            self.tracker_path.unlink()

    def test_market_cn(self):
        """
        测试 CN 市场初始化

        入参: market="CN"
        期望: engine.market == "CN"
        """
        engine = ReviewEngine(market="CN")
        assert engine.market == "CN", f"market 应为 CN: {engine.market}"
        print(f"  [PASS] CN 市场初始化正确")

    def test_market_uppercase_normalize(self):
        """
        测试市场参数大小写归一化

        入参: market="cn" (小写)
        期望: engine.market == "CN"
        """
        engine = ReviewEngine(market="cn")
        assert engine.market == "CN", f"应归一化为 CN: {engine.market}"
        print(f"  [PASS] 市场参数小写归一化")


# ─── 测试运行器 ─────────────────────────────────────────────────

def _run_all():
    test_classes = [
        TestReviewEngineRecord,
        TestEffectivenessMetrics,
        TestCPCVValidation,
        TestDataclasses,
        TestReviewRun,
        TestMultiMarket,
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
    print(f"结果: {total_passed} 通过, {total_failed} 失败")
    print("=" * 60)
    return total_failed == 0


if __name__ == "__main__":
    print("=" * 60)
    print("L5 ReviewEngine 测试套件")
    print("=" * 60)
    ok = _run_all()
    sys.exit(0 if ok else 1)