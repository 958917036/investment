# -*- coding: utf-8 -*-
"""
组合优化器

支持 Markowitz / Black-Litterman / Risk Parity / HRP 四种组合优化算法。

参照：PyPortfolioOpt (5.7k★) + Markowitz (1952) + Black-Litterman (1992)
"""

import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import pdist
from scipy.optimize import minimize

logger = logging.getLogger("portfolio.optimizer")


# =============================================================================
# Base
# =============================================================================

class PortfolioOptimizer:
    """组合优化器基类"""

    name: str = "BaseOptimizer"

    def optimize(self) -> np.ndarray:
        raise NotImplementedError

    def _validate_weights(self, weights: np.ndarray, names: List[str]) -> None:
        if len(weights) != len(names):
            raise ValueError(f"权重数量({len(weights)})与资产数量({len(names)})不匹配")
        if not np.isclose(weights.sum(), 1.0):
            raise ValueError(f"权重之和({weights.sum():.4f})必须等于1")


# =============================================================================
# Markowitz Mean-Variance
# =============================================================================

class MarkowitzOptimizer(PortfolioOptimizer):
    """
    Markowitz 均值-方差优化器

    理论基础: Harry Markowitz (1952) "Portfolio Selection"

    优化目标:
      - max_sharpe: 最大夏普比率组合
      - min_variance: 最小方差组合

    数学表达:
      max Sharpe: max (w'μ - r_f) / sqrt(w'Σw)
      min var:    min w'Σw  subject to Σw_i = 1, w_i >= 0
    """

    name = "Markowitz"

    def __init__(
        self,
        returns: pd.DataFrame,
        risk_free_rate: float = 0.03,
        allow_short: bool = False,
    ):
        """
        Args:
            returns: 收益率 DataFrame，index=日期，columns=资产名
            risk_free_rate: 年化无风险利率（默认3%）
            allow_short: 是否允许做空（默认否）
        """
        self.returns = returns.dropna()
        self.expected_returns = self.returns.mean() * 252
        self.cov_matrix = self.returns.cov() * 252
        self.rf = risk_free_rate
        self.allow_short = allow_short
        self.asset_names = list(self.returns.columns)
        self.n = len(self.asset_names)

    def _port_return(self, weights: np.ndarray) -> float:
        return np.dot(weights, self.expected_returns)

    def _port_variance(self, weights: np.ndarray) -> float:
        return np.dot(weights, np.dot(self.cov_matrix.values, weights))

    def _port_volatility(self, weights: np.ndarray) -> float:
        return math.sqrt(self._port_variance(weights))

    def _sharpe_ratio(self, weights: np.ndarray) -> float:
        ret = self._port_return(weights)
        vol = self._port_volatility(weights)
        if vol == 0:
            return 0.0
        return (ret - self.rf) / vol

    def max_sharpe_weights(self) -> np.ndarray:
        """计算最大夏普比率组合权重"""
        def neg_sharpe(w):
            sr = self._sharpe_ratio(w)
            return -sr

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(-1, 2) if self.allow_short else (0, 1) for _ in range(self.n)]
        w0 = np.ones(self.n) / self.n

        result = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        if not result.success:
            logger.warning(f"Markowitz优化未收敛: {result.message}")
        weights = np.clip(result.x, 0, 1)
        weights /= weights.sum()
        self._validate_weights(weights, self.asset_names)
        return weights

    def min_variance_weights(self, target_return: Optional[float] = None) -> np.ndarray:
        """
        计算最小方差组合权重

        Args:
            target_return: 目标收益（可选），不指定则返回全局最小方差
        """
        def neg_sharpe(w):
            return self._sharpe_ratio(w)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        if target_return is not None:
            constraints.append({"type": "eq", "fun": lambda w: self._port_return(w) - target_return})

        bounds = [(-1, 2) if self.allow_short else (0, 1) for _ in range(self.n)]
        w0 = np.ones(self.n) / self.n

        result = minimize(
            lambda w: self._port_variance(w),
            w0, method="SLSQP", bounds=bounds, constraints=constraints
        )
        if not result.success:
            logger.warning(f"Markowitz优化未收敛: {result.message}")
        weights = np.clip(result.x, 0, 1)
        weights /= weights.sum()
        self._validate_weights(weights, self.asset_names)
        return weights

    def efficient_frontier(self, n_points: int = 50) -> Tuple[np.ndarray, np.ndarray]:
        """计算有效前沿（收益-波动率散点）"""
        returns_range = np.linspace(self.expected_returns.min(), self.expected_returns.max(), n_points)
        vols, rets = [], []
        for target_ret in returns_range:
            try:
                w = self.min_variance_weights(target_return=float(target_ret))
                vols.append(self._port_volatility(w))
                rets.append(self._port_return(w))
            except Exception:
                continue
        return np.array(vols), np.array(rets)

    def optimize(self) -> np.ndarray:
        """默认返回最大夏普组合"""
        return self.max_sharpe_weights()

    def summary(self, weights: Optional[np.ndarray] = None) -> dict:
        w = weights if weights is not None else self.optimize()
        return {
            "optimizer": self.name,
            "expected_return": self._port_return(w),
            "volatility": self._port_volatility(w),
            "sharpe_ratio": self._sharpe_ratio(w),
            "weights": dict(zip(self.asset_names, np.round(w, 4))),
        }


# =============================================================================
# Black-Litterman
# =============================================================================

class BlackLittermanOptimizer(PortfolioOptimizer):
    """
    Black-Litterman 逆向优化组合

    理论基础: Black & Litterman (1992)

    核心思想：将市场均衡收益率（无偏先验）与投资者主观观点融合，
    得到后验预期收益率，再输入 Markowitz 优化。

    公式:
      μ_BL = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹ [(τΣ)⁻¹μ_eq + P'Ω⁻¹Q]

    其中:
      τ = 标量（通常取1/T）
      Σ = 协方差矩阵
      P = 观点矩阵（n_views × n_assets）
      Ω = 观点不确定度矩阵（对角）
      Q = 观点收益向量
      μ_eq = 市场均衡收益率
    """

    name = "BlackLitterman"

    def __init__(
        self,
        returns: pd.DataFrame,
        market_caps: Optional[Dict[str, float]] = None,
        risk_aversion: float = 2.5,
        risk_free_rate: float = 0.03,
    ):
        """
        Args:
            returns: 收益率 DataFrame
            market_caps: 各资产市值权重 dict，{'asset': cap_weight}
            risk_aversion: 风险厌恶系数 δ（默认2.5）
            risk_free_rate: 无风险利率
        """
        self.returns = returns.dropna()
        self.cov_matrix = self.returns.cov() * 252
        self.asset_names = list(self.returns.columns)
        self.n = len(self.asset_names)
        self.delta = risk_aversion
        self.rf = risk_free_rate

        # 计算市值加权权重（若无输入则等权）
        if market_caps:
            total = sum(market_caps.values())
            self.market_weights = np.array([market_caps.get(a, 0) / total for a in self.asset_names])
        else:
            self.market_weights = np.ones(self.n) / self.n
            logger.info("未提供市值权重，使用等权组合")

        # 市场均衡收益率: μ_eq = δ × Σ × w_mkt
        self.mu_eq = self.delta * np.dot(self.cov_matrix.values, self.market_weights)

    def set_views(
        self,
        views: Dict[str, float],
        view_confidences: Optional[List[float]] = None,
    ) -> "BlackLittermanOptimizer":
        """
        设置主观观点

        Args:
            views: 观点 dict，{'asset': expected_return_annual}
            view_confidences: 置信度列表（0-1），与views顺序对应
        """
        self.views = views
        n_views = len(views)
        self.view_keys = list(views.keys())

        # 构建观点矩阵 P（n_views × n_assets）
        self.P = np.zeros((n_views, self.n))
        for i, asset in enumerate(self.view_keys):
            if asset not in self.asset_names:
                raise ValueError(f"观点中的资产'{asset}'不在组合中")
            j = self.asset_names.index(asset)
            self.P[i, j] = 1

        # 观点收益 Q
        self.Q = np.array(list(views.values()))

        # 观点不确定度 Ω（对角矩阵）
        # 置信度越高 → Ω越小 → 该观点权重越大
        if view_confidences is None:
            view_confidences = [0.5] * n_views
        self.omega_diag = [
            (1 - c) / c if c > 0 else 1.0 for c in view_confidences
        ]
        self.Omega = np.diag(self.omega_diag)

        # τ 值
        self.tau = 1.0 / self.n

        return self

    def _compute_posterior_mu(self) -> np.ndarray:
        """计算后验收益率 μ_BL"""
        Sigma = self.cov_matrix.values
        P = self.P
        Q = self.Q
        Omega = self.Omega
        tau = self.tau
        mu_eq = self.mu_eq

        # MLE 版本（简化，不含τ）
        # μ_BL = [(Σ⁻¹ + P'Ω⁻¹P)⁻¹](Σ⁻¹μ_eq + P'Ω⁻¹Q)
        M1 = np.linalg.inv(Sigma + P.T @ np.linalg.inv(Omega) @ P)
        M2 = np.linalg.solve(Sigma, mu_eq) + P.T @ np.linalg.inv(Omega) @ Q
        return M1 @ M2

    def optimize(self) -> np.ndarray:
        """用后验收益率运行 Markowitz 优化"""
        if not hasattr(self, "P"):
            logger.info("未设置观点，使用市场均衡组合（等权）")
            return self.market_weights.copy()

        mu_bl = self._compute_posterior_mu()

        # 用 BL 后验收益率做 Markowitz
        returns_df = pd.DataFrame(
            np.random.randn(252, self.n) * 0.01,
            columns=self.asset_names
        )
        # 用 μ_BL 替换样本均值，使 optimizer 使用 BL 收益率
        bl_optimizer = MarkowitzOptimizer(returns_df, risk_free_rate=self.rf)
        # 直接用 BL 收益率注入
        bl_optimizer.expected_returns = pd.Series(mu_bl, index=self.asset_names)

        return bl_optimizer.max_sharpe_weights()

    def summary(self, weights: Optional[np.ndarray] = None) -> dict:
        w = weights if weights is not None else self.optimize()
        bl_optimizer = MarkowitzOptimizer(self.returns, risk_free_rate=self.rf)
        return {
            "optimizer": self.name,
            "expected_return": bl_optimizer._port_return(w),
            "volatility": bl_optimizer._port_volatility(w),
            "sharpe_ratio": bl_optimizer._sharpe_ratio(w),
            "weights": dict(zip(self.asset_names, np.round(w, 4))),
        }


# =============================================================================
# Risk Parity
# =============================================================================

class RiskParityOptimizer(PortfolioOptimizer):
    """
    风险平价优化器

    核心思想：每个资产对组合总风险的贡献相等。
    w_i = σ_i⁻¹ / Σⱼσ_j⁻¹  （近似，当相关性低时）

    精确解通过数值优化实现：
      min Σ_i (w_i × σ_i / σ_p - 1/n)²
      subject to Σw_i = 1, w_i >= 0
    """

    name = "RiskParity"

    def __init__(self, cov_matrix: pd.DataFrame):
        """
        Args:
            cov_matrix: 年化协方差矩阵（DataFrame，index/columns=资产名）
        """
        if isinstance(cov_matrix, pd.DataFrame):
            self.cov_matrix = cov_matrix.values
            self.asset_names = list(cov_matrix.index)
        else:
            self.cov_matrix = cov_matrix
            self.asset_names = [f"asset_{i}" for i in range(len(cov_matrix))]
        self.n = len(self.asset_names)

    def _asset_vol(self, weights: np.ndarray) -> np.ndarray:
        """各资产对组合风险的边际贡献"""
        port_var = np.dot(weights, np.dot(self.cov_matrix, weights))
        port_vol = math.sqrt(port_var)
        if port_vol < 1e-10:
            return np.zeros(self.n)
        # 风险贡献 = w_i × (Σw)_i / σ_p
        marginal_contrib = np.dot(self.cov_matrix, weights)
        risk_contrib = weights * marginal_contrib / port_vol
        return risk_contrib

    def optimize(self) -> np.ndarray:
        """数值优化求解风险平价组合"""
        def objective(w):
            vol = math.sqrt(np.dot(w, np.dot(self.cov_matrix, w)))
            if vol < 1e-10:
                return 1e6
            rc = w * np.dot(self.cov_matrix, w) / vol  # 风险贡献
            target_rc = vol / self.n  # 每个资产目标风险贡献
            return np.sum((rc - target_rc) ** 2)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0, 1) for _ in range(self.n)]
        w0 = np.ones(self.n) / self.n

        result = minimize(objective, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        if not result.success:
            logger.warning(f"RiskParity优化未收敛: {result.message}")
        weights = np.clip(result.x, 1e-8, 1)
        weights /= weights.sum()
        return weights

    def summary(self, weights: Optional[np.ndarray] = None) -> dict:
        w = weights if weights is not None else self.optimize()
        port_var = np.dot(w, np.dot(self.cov_matrix, w))
        port_vol = math.sqrt(port_var)
        rc = w * np.dot(self.cov_matrix, w) / max(port_vol, 1e-10)
        return {
            "optimizer": self.name,
            "portfolio_volatility": port_vol,
            "asset_risk_contributions": dict(zip(self.asset_names, np.round(rc / port_vol, 4))),
            "weights": dict(zip(self.asset_names, np.round(w, 4))),
        }


# =============================================================================
# HRP (Hierarchical Risk Parity)
# =============================================================================

class HRPOptimizer(PortfolioOptimizer):
    """
    层次风险平价优化器

    理论基础: Lopez de Prado (2016) "Building Diversified Portfolios"

    核心思想：
      1. 用相关性距离做层次聚类
      2. 在聚类树状图上递归分组
      3. 每组内部使用风险平价分配权重
      4. 避免协方差矩阵求逆（更适合高维问题）
    """

    name = "HRP"

    def __init__(self, returns: pd.DataFrame):
        """
        Args:
            returns: 收益率 DataFrame
        """
        self.returns = returns.dropna()
        self.asset_names = list(self.returns.columns)
        self.n = len(self.asset_names)
        self.cov_matrix = self.returns.cov().values

    def _correlation_distance(self) -> np.ndarray:
        """将相关性矩阵转换为距离矩阵"""
        corr = np.corrcoef(self.returns.T)
        # 相关性距离: d = sqrt(0.5 × (1 - ρ))
        dist = np.sqrt(0.5 * (1 - corr))
        np.fill_diagonal(dist, 0)
        return dist

    def _quasi_diag(self, link: np.ndarray) -> List[int]:
        """从聚类树状图提取准对角顺序"""
        n = len(link) + 1
        sortedo = list(range(n))
        unsorted = list(range(n))
        for i in range(n - 1):
            i0 = int(link[i, 0])
            i1 = int(link[i, 1])
            s0 = sortedo[i0] if i0 < n else unsorted[i0 - n]
            s1 = sortedo[i1] if i1 < n else unsorted[i1 - n]
            if s0 < s1:
                sortedo[i0], sortedo[i1] = s1, s0
            unsorted.append(min(s0, s1))
        return sortedo

    def _get_alloc(self, cov: np.ndarray, ordered: List[int]) -> np.ndarray:
        """递归计算每组内部的风险平价权重"""
        n = len(ordered)
        if n == 1:
            return np.array([1.0])

        # 分割点（取一半）
        split = n // 2
        left = ordered[:split]
        right = ordered[split:]

        # 左组子协方差
        cov_left = cov[np.ix_(left, left)]
        vol_left = np.sqrt(np.diag(cov_left))
        inv_vol_left = 1.0 / (vol_left + 1e-10)
        w_left = inv_vol_left / inv_vol_left.sum()

        # 右组子协方差
        cov_right = cov[np.ix_(right, right)]
        vol_right = np.sqrt(np.diag(cov_right))
        inv_vol_right = 1.0 / (vol_right + 1e-10)
        w_right = inv_vol_right / inv_vol_right.sum()

        # 组合两组
        w = np.zeros(n)
        w[:split] = w_left * self._cluster_vol(cov_left, w_left)
        w[split:] = w_right * self._cluster_vol(cov_right, w_right)
        return w / w.sum()

    def _cluster_vol(self, cov: np.ndarray, w: np.ndarray) -> float:
        return math.sqrt(np.dot(w, np.dot(cov, w)))

    def optimize(self) -> np.ndarray:
        """HRP 主流程：聚类 → 排序 → 递归分配"""
        dist = self._correlation_distance()
        link = linkage(pdist(dist), method="ward")
        ordered = self._quasi_diag(link)
        weights = self._get_alloc(self.cov_matrix, ordered)

        # 将权重按原始资产顺序排列
        ordered_weights = np.zeros(self.n)
        for i, idx in enumerate(ordered):
            ordered_weights[idx] = weights[i]
        ordered_weights /= ordered_weights.sum()
        return ordered_weights

    def summary(self, weights: Optional[np.ndarray] = None) -> dict:
        w = weights if weights is not None else self.optimize()
        port_var = np.dot(w, np.dot(self.cov_matrix, w))
        return {
            "optimizer": self.name,
            "portfolio_volatility": math.sqrt(port_var),
            "weights": dict(zip(self.asset_names, np.round(w, 4))),
        }


# =============================================================================
# Enhanced Kelly
# =============================================================================

class EnhancedKellyCalculator:
    """
    增强Kelly仓位计算器

    Kelly公式: f* = (bp - q) / b
      b = 盈亏比 (avg_win / avg_loss)
      p = 胜率
      q = 1 - p

    增强版本:
      - 支持分数Kelly（1/2 Kelly、1/4 Kelly）降低波动
      - 上限控制（默认Kelly仓位 ≤ 25%）
      - 基于历史收益率自动估算胜率和盈亏比
    """

    name = "EnhancedKelly"

    def __init__(
        self,
        returns: pd.DataFrame,
        kelly_fraction: float = 0.25,
        max_kelly_fraction: float = 0.25,
    ):
        """
        Args:
            returns: 收益率序列（单资产，Series 或 DataFrame）
            kelly_fraction: Kelly分数（默认1/4 Kelly = 0.25）
            max_kelly_fraction: Kelly仓位上限（默认25%）
        """
        if isinstance(returns, pd.DataFrame):
            self.returns = returns.iloc[:, 0].dropna()
        else:
            self.returns = returns.dropna()
        self.kelly_fraction = kelly_fraction
        self.max_fraction = max_kelly_fraction

    def compute(
        self,
        win_rate: Optional[float] = None,
        avg_win: Optional[float] = None,
        avg_loss: Optional[float] = None,
    ) -> Tuple[float, float, float, float]:
        """
        计算Kelly最优仓位

        Returns:
            (kelly_pct, win_rate, avg_win_pct, avg_loss_pct)
        """
        # 从收益率序列估算
        if win_rate is None:
            gains = self.returns[self.returns > 0]
            losses = self.returns[self.returns < 0]
            win_rate = len(gains) / max(len(self.returns), 1)
            avg_win_pct = gains.mean() if len(gains) > 0 else 0.0
            avg_loss_pct = abs(losses.mean()) if len(losses) > 0 else 0.0
        else:
            avg_win_pct = avg_win or 0.0
            avg_loss_pct = avg_loss or 0.0

        if avg_loss_pct == 0 or win_rate == 0:
            return 0.0, win_rate, avg_win_pct, avg_loss_pct

        b = avg_win_pct / avg_loss_pct  # 盈亏比
        p = win_rate
        q = 1 - p
        kelly = (b * p - q) / b

        if kelly <= 0:
            return 0.0, win_rate, avg_win_pct, avg_loss_pct

        # 应用分数 + 上限
        adjusted = kelly * self.kelly_fraction
        adjusted = min(adjusted, self.max_fraction)
        return float(adjusted), float(win_rate), float(avg_win_pct), float(avg_loss_pct)

    def summary(self) -> dict:
        kelly_pct, wr, aw, al = self.compute()
        b = aw / al if al > 0 else 0
        return {
            "kelly_pct": kelly_pct,
            "win_rate": wr,
            "avg_win_pct": aw,
            "avg_loss_pct": al,
            "b_ratio": b,
            "kelly_fraction_used": self.kelly_fraction,
            "max_fraction": self.max_fraction,
        }
