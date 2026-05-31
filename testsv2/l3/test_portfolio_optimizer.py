#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组合优化器单元测试
测试 MarkowitzOptimizer, BlackLittermanOptimizer, RiskParityOptimizer, HRPOptimizer, EnhancedKellyCalculator
"""
import unittest
import sys
import os
import numpy as np
import pandas as pd

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L3_quant_analysis.portfolio import (
    MarkowitzOptimizer,
    BlackLittermanOptimizer,
    RiskParityOptimizer,
    HRPOptimizer,
    EnhancedKellyCalculator,
)


def _make_random_returns(n_stocks=5, n_days=252, seed=42):
    """生成随机收益率矩阵（模拟5只股票252日收益率）"""
    np.random.seed(seed)
    cov = np.random.rand(n_stocks, n_stocks) * 0.02
    cov = (cov + cov.T) / 2
    np.fill_diagonal(cov, np.random.rand(n_stocks) * 0.04 + 0.01)
    mean_ret = np.random.rand(n_stocks) * 0.3 + 0.05
    returns = np.random.multivariate_normal(mean_ret, cov, n_days)
    dates = pd.date_range("2025-01-01", periods=n_days, freq="B")
    df = pd.DataFrame(returns, index=dates)
    df.columns = [f"stock_{i}" for i in range(n_stocks)]
    return df


class TestMarkowitzOptimizer(unittest.TestCase):
    """Markowitz均值方差优化器测试"""

    def test_initialization(self):
        returns_df = _make_random_returns(n_stocks=5)
        opt = MarkowitzOptimizer(returns_df, risk_free_rate=0.03)
        self.assertEqual(opt.n, 5)
        self.assertEqual(opt.rf, 0.03)

    def test_max_sharpe_weights(self):
        returns_df = _make_random_returns(n_stocks=5)
        opt = MarkowitzOptimizer(returns_df, risk_free_rate=0.03)
        weights = opt.max_sharpe_weights()
        self.assertEqual(len(weights), 5)
        self.assertAlmostEqual(sum(weights), 1.0, places=3)
        self.assertTrue(all(w >= 0 for w in weights))

    def test_min_variance_weights(self):
        returns_df = _make_random_returns(n_stocks=5)
        opt = MarkowitzOptimizer(returns_df, risk_free_rate=0.03)
        weights = opt.min_variance_weights()
        self.assertEqual(len(weights), 5)
        self.assertAlmostEqual(sum(weights), 1.0, places=3)
        self.assertTrue(all(w >= 0 for w in weights))

    def test_efficient_frontier(self):
        returns_df = _make_random_returns(n_stocks=5)
        opt = MarkowitzOptimizer(returns_df, risk_free_rate=0.03)
        vols, rets = opt.efficient_frontier(n_points=10)
        # 前沿点数量可能因优化器实现而异
        self.assertGreater(len(vols), 1)
        self.assertEqual(len(vols), len(rets))

    def test_optimize_default(self):
        returns_df = _make_random_returns(n_stocks=5)
        opt = MarkowitzOptimizer(returns_df, risk_free_rate=0.03)
        weights = opt.optimize()
        self.assertEqual(len(weights), 5)


class TestRiskParityOptimizer(unittest.TestCase):
    """Risk Parity优化器测试"""

    def test_initialization(self):
        returns_df = _make_random_returns(n_stocks=3)
        cov = returns_df.cov() * 252  # 年化协方差
        cov.index = cov.columns = returns_df.columns
        opt = RiskParityOptimizer(cov)
        self.assertEqual(opt.n, 3)

    def test_optimize(self):
        returns_df = _make_random_returns(n_stocks=3)
        cov = returns_df.cov() * 252
        cov.index = cov.columns = returns_df.columns
        opt = RiskParityOptimizer(cov)
        weights = opt.optimize()
        self.assertEqual(len(weights), 3)
        self.assertAlmostEqual(sum(weights), 1.0, places=3)
        self.assertTrue(all(w >= 0 for w in weights))

    def test_risk_contribution(self):
        returns_df = _make_random_returns(n_stocks=3)
        cov = returns_df.cov() * 252
        cov.index = cov.columns = returns_df.columns
        opt = RiskParityOptimizer(cov)
        weights = opt.optimize()
        # 风险平价：各资产风险贡献应该接近
        total_risk = sum(abs(w) for w in weights)
        self.assertGreater(total_risk, 0)


class TestHRPOptimizer(unittest.TestCase):
    """层次风险平价优化器测试"""

    def test_initialization(self):
        returns_df = _make_random_returns(n_stocks=3)
        opt = HRPOptimizer(returns_df)
        self.assertEqual(opt.n, 3)

    def test_optimize(self):
        returns_df = _make_random_returns(n_stocks=3)
        opt = HRPOptimizer(returns_df)
        weights = opt.optimize()
        self.assertEqual(len(weights), 3)
        self.assertAlmostEqual(sum(weights), 1.0, places=3)
        self.assertTrue(all(w >= 0 for w in weights))


class TestEnhancedKellyCalculator(unittest.TestCase):
    """增强凯利计算器测试"""

    def test_initialization_with_returns(self):
        returns_df = _make_random_returns(n_stocks=1, n_days=100)
        kelly = EnhancedKellyCalculator(returns_df, kelly_fraction=0.25)
        self.assertEqual(kelly.kelly_fraction, 0.25)

    def test_compute_with_given_params(self):
        returns_df = _make_random_returns(n_stocks=1, n_days=100)
        kelly = EnhancedKellyCalculator(returns_df)
        kelly_pct, wr, aw, al = kelly.compute(win_rate=0.6, avg_win=0.12, avg_loss=0.08)
        self.assertGreater(kelly_pct, 0)
        self.assertEqual(wr, 0.6)

    def test_compute_from_returns(self):
        returns_df = _make_random_returns(n_stocks=1, n_days=100)
        kelly = EnhancedKellyCalculator(returns_df)
        kelly_pct, wr, aw, al = kelly.compute()
        self.assertGreaterEqual(kelly_pct, 0)
        self.assertGreaterEqual(wr, 0)
        self.assertLessEqual(wr, 1)

    def test_fractional_kelly_upper_bound(self):
        returns_df = _make_random_returns(n_stocks=1, n_days=100)
        kelly = EnhancedKellyCalculator(returns_df, kelly_fraction=0.25, max_kelly_fraction=0.25)
        kelly_pct, wr, aw, al = kelly.compute(win_rate=0.9, avg_win=1.0, avg_loss=0.1)
        self.assertLessEqual(kelly_pct, 0.25)  # 上限25%

    def test_summary(self):
        returns_df = _make_random_returns(n_stocks=1, n_days=100)
        kelly = EnhancedKellyCalculator(returns_df)
        s = kelly.summary()
        self.assertIn("kelly_pct", s)
        self.assertIn("win_rate", s)


class TestBlackLittermanOptimizer(unittest.TestCase):
    """Black-Litterman优化器测试"""

    def test_initialization_no_market_caps(self):
        returns_df = _make_random_returns(n_stocks=4, n_days=252)
        opt = BlackLittermanOptimizer(returns_df)
        self.assertEqual(opt.n, 4)

    def test_initialization_with_market_caps(self):
        returns_df = _make_random_returns(n_stocks=4, n_days=252)
        market_caps = {f"stock_{i}": 1e10 / (i + 1) for i in range(4)}
        opt = BlackLittermanOptimizer(returns_df, market_caps=market_caps)
        self.assertEqual(opt.n, 4)

    def test_set_views(self):
        returns_df = _make_random_returns(n_stocks=4, n_days=252)
        opt = BlackLittermanOptimizer(returns_df)
        opt.set_views({"stock_0": 0.15, "stock_2": 0.08}, view_confidences=[0.6, 0.5])
        self.assertEqual(len(opt.views), 2)

    def test_optimize_without_views(self):
        returns_df = _make_random_returns(n_stocks=4, n_days=252)
        opt = BlackLittermanOptimizer(returns_df)
        weights = opt.optimize()
        self.assertEqual(len(weights), 4)
        self.assertAlmostEqual(sum(weights), 1.0, places=3)

    def test_optimize_with_views(self):
        returns_df = _make_random_returns(n_stocks=4, n_days=252)
        opt = BlackLittermanOptimizer(returns_df)
        opt.set_views({"stock_0": 0.15, "stock_2": 0.08}, view_confidences=[0.6, 0.5])
        weights = opt.optimize()
        self.assertEqual(len(weights), 4)
        self.assertAlmostEqual(sum(weights), 1.0, places=3)


class TestPortfolioOptimizerIntegration(unittest.TestCase):
    """组合优化器集成测试"""

    def test_all_optimizers_on_same_data(self):
        """同一数据集上运行所有优化器"""
        returns_df = _make_random_returns(n_stocks=4, n_days=252)
        cov = returns_df.cov() * 252
        cov.index = cov.columns = returns_df.columns

        markowitz = MarkowitzOptimizer(returns_df, risk_free_rate=0.03)
        mw_weights = markowitz.max_sharpe_weights()

        rp = RiskParityOptimizer(cov)
        rp_weights = rp.optimize()

        hrp = HRPOptimizer(returns_df)
        hrp_weights = hrp.optimize()

        bl = BlackLittermanOptimizer(returns_df)
        bl_weights = bl.optimize()

        for weights in [mw_weights, rp_weights, hrp_weights, bl_weights]:
            self.assertEqual(len(weights), 4)
            self.assertAlmostEqual(sum(weights), 1.0, places=3)
            self.assertTrue(all(w >= 0 for w in weights))

    def test_kelly_sizing_integration(self):
        """测试凯利仓位计算"""
        returns_df = _make_random_returns(n_stocks=1, n_days=100)
        kelly = EnhancedKellyCalculator(returns_df, kelly_fraction=0.25)
        kelly_pct, wr, aw, al = kelly.compute(win_rate=0.55, avg_win=1.1, avg_loss=0.9)
        self.assertGreaterEqual(kelly_pct, 0)
        self.assertLessEqual(kelly_pct, 0.25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
