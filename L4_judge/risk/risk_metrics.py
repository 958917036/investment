# -*- coding: utf-8 -*-
"""
增强风控指标 — Sortino / Calmar / MaxDrawdown（真实）/ 历史VaR / CVaR

参照 QuantConnect LEAN 的 16+ 风险指标体系。
"""

from __future__ import annotations

import math
from typing import Optional, Tuple
import numpy as np
import pandas as pd


# ======================== MaxDrawdown（含 Peak/Trough/Recovery）====================

def compute_max_drawdown(
    cumulative_returns: pd.Series,
) -> dict:
    """
    计算真实最大回撤，含 Peak / Trough / Recovery 日期。

    Args:
        cumulative_returns: 累计收益率序列（index=日期，values=累计收益小数，如 0.05 表示 5%）

    Returns:
        dict: {
            max_drawdown: 最大回撤（负值，如 -0.15）,
            peak_date: 最大点日期,
            trough_date: 最低点日期,
            recovery_date: 恢复日期（或 None）,
            duration_days: 回落持续天数,
            current_drawdown: 当前回撤
        }
    """
    if cumulative_returns.empty or len(cumulative_returns) < 2:
        return {
            "max_drawdown": 0.0,
            "peak_date": None,
            "trough_date": None,
            "recovery_date": None,
            "duration_days": 0,
            "current_drawdown": 0.0,
        }

    # 累计最高点
    running_max = cumulative_returns.cummax()
    drawdown = cumulative_returns - running_max  # 负值

    # 最大回撤
    max_dd = drawdown.min()
    trough_idx = drawdown.idxmin()
    peak_before = cumulative_returns[:trough_idx].idxmax()
    peak_date = peak_before if not pd.isna(peak_before) else None

    # 恢复日期（回撤恢复到 max_dd 以上的第一个点）
    recovery_idx = None
    post_trough = drawdown[trough_idx:]
    if len(post_trough) > 1:
        recovered = post_trough[1:][post_trough[1:] >= max_dd * 0.999]  # 容差
        if not recovered.empty:
            recovery_idx = recovered.index[0]

    # 持续天数
    if peak_date is not None and trough_idx is not None:
        if isinstance(peak_date, pd.Timestamp) and isinstance(trough_idx, pd.Timestamp):
            duration = (trough_idx - peak_date).days
        else:
            duration = 0
    else:
        duration = 0

    # 当前回撤
    current_dd = drawdown.iloc[-1]

    return {
        "max_drawdown": float(max_dd),
        "peak_date": str(peak_date)[:10] if peak_date else None,
        "trough_date": str(trough_idx)[:10] if trough_idx else None,
        "recovery_date": str(recovery_idx)[:10] if recovery_idx else None,
        "duration_days": duration,
        "current_drawdown": float(current_dd),
    }


def compute_max_drawdown_from_prices(prices: pd.Series) -> dict:
    """
    从价格序列计算最大回撤（自动转换为累计收益率）。

    Args:
        prices: 价格序列（index=日期，values=价格）
    """
    if prices.empty:
        return {k: 0.0 if k in ("max_drawdown", "current_drawdown") else None for k in
                ("max_drawdown", "peak_date", "trough_date", "recovery_date", "duration_days", "current_drawdown")}
    cumulative = (prices / prices.iloc[0]) - 1.0
    return compute_max_drawdown(cumulative)


# ======================== Sortino Ratio ========================

def compute_sortino(
    returns: pd.Series,
    target_return: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """
    Sortino Ratio = (年化收益 - 目标收益) / 下行标准差

    下行标准差 = std(returns[returns < target_return])

    Args:
        returns: 日收益率序列
        target_return: 目标收益（日率化，默认 0）
        periods_per_year: 年化因子（默认 252）

    Returns:
        Sortino Ratio（超出目标收益的 Sharped 调整后收益）
    """
    if returns.empty or len(returns) < 2:
        return 0.0

    # 年化收益率
    annual_return = returns.mean() * periods_per_year
    # 下行偏差
    downside_returns = returns[returns < target_return]
    if downside_returns.empty or downside_returns.std() == 0:
        return 0.0

    downside_std = downside_returns.std() * math.sqrt(periods_per_year)
    if downside_std == 0:
        return 0.0

    return (annual_return - target_return) / downside_std


# ======================== Calmar Ratio ========================

def compute_calmar(
    returns: pd.Series,
    max_drawdown: float,
    periods_per_year: int = 252,
) -> float:
    """
    Calmar Ratio = 年化收益 / |最大回撤|

    Args:
        returns: 日收益率序列
        max_drawdown: 最大回撤（负值，如 -0.15）
        periods_per_year: 年化因子
    """
    if returns.empty or len(returns) < 2 or max_drawdown == 0:
        return 0.0

    annual_return = returns.mean() * periods_per_year
    if abs(max_drawdown) < 1e-8:
        return 0.0

    return annual_return / abs(max_drawdown)


# ======================== 历史模拟法 VaR ========================

def compute_historical_var(
    returns: pd.Series,
    confidence: float = 0.95,
) -> float:
    """
    历史模拟法 VaR = 置信度下的最低收益率

    例如 95% VaR = np.percentile(returns, 5) — 有 5% 的概率损失超过此值

    Args:
        returns: 日收益率序列
        confidence: 置信度（默认 95%）

    Returns:
        VaR 值（负值，如 -0.02 表示 2% 的 VaR）
    """
    if returns.empty or len(returns) < 20:
        return 0.0

    var = np.percentile(returns, (1 - confidence) * 100)
    return float(var)


# ======================== CVaR (Expected Shortfall) ========================

def compute_cvar(
    returns: pd.Series,
    confidence: float = 0.95,
) -> float:
    """
    CVaR (Expected Shortfall) = VaR 以下的平均损失
    比 VaR 更保守，衡量尾部风险。

    Args:
        returns: 日收益率序列
        confidence: 置信度（默认 95%）

    Returns:
        CVaR 值（负值）
    """
    if returns.empty or len(returns) < 20:
        return 0.0

    var = np.percentile(returns, (1 - confidence) * 100)
    cvar = returns[returns <= var].mean()
    return float(cvar) if not math.isnan(cvar) else var


# ======================== 真实协方差矩阵 ========================

def compute_covariance_matrix_from_weights(
    positions: list,
    corr_matrix: pd.DataFrame,
) -> np.ndarray:
    """
    根据持仓权重和相关系数矩阵构建协方差矩阵。

    Args:
        positions: Position 对象列表
        corr_matrix: 相关系数矩阵 DataFrame

    Returns:
        协方差矩阵 np.ndarray
    """
    codes = [p.stock_code for p in positions]
    vols = np.array([
        getattr(p, "volatility", 0.30) or 0.30 for p in positions
    ])
    # Σ_ij = ρ_ij × σ_i × σ_j
    cov = np.outer(vols, vols) * corr_matrix.values
    return cov


def compute_covariance_matrix(
    returns_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    计算真实历史协方差矩阵（替换 0.3 假设）。

    Args:
        returns_df: 日收益率 DataFrame（index=日期，columns=股票代码）

    Returns:
        协方差矩阵 DataFrame
    """
    if returns_df.empty or returns_df.shape[1] < 2:
        return pd.DataFrame()

    return returns_df.cov()


def compute_correlation_matrix(
    returns_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    计算收益率相关系数矩阵。

    Args:
        returns_df: 日收益率 DataFrame

    Returns:
        相关系数矩阵 DataFrame
    """
    if returns_df.empty or returns_df.shape[1] < 2:
        return pd.DataFrame()

    return returns_df.corr()


# ======================== 组合 VaR（真实协方差）====================

def compute_portfolio_var(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
    confidence: float = 0.95,
    periods_per_year: int = 252,
) -> Tuple[float, float]:
    """
    基于真实协方差矩阵的组合 VaR。

    Args:
        weights: 持仓权重数组
        cov_matrix: 协方差矩阵（np.ndarray）
        confidence: 置信度
        periods_per_year: 年化因子

    Returns:
        (日 VaR, 年化 VaR)
    """
    if weights.size == 0 or cov_matrix.size == 0:
        return 0.0, 0.0

    # 组合方差 = w' Σ w
    port_variance = float(weights @ cov_matrix @ weights)
    port_vol_daily = math.sqrt(port_variance)
    port_vol_annual = port_vol_daily * math.sqrt(periods_per_year)

    # VaR（日） = -port_vol_daily × z_score
    from scipy.stats import norm
    z = norm.ppf(1 - confidence)  # 95% → 1.645
    daily_var = port_vol_daily * z
    annual_var = port_vol_annual * z

    return float(daily_var), float(annual_var)


# ======================== Sharpe Ratio（含 Sortino/Calmar）====================

def compute_sharpe(
    returns: pd.Series,
    risk_free_rate: float = 0.03,
    periods_per_year: int = 252,
) -> float:
    """
    Sharpe Ratio = (年化收益 - 无风险利率) / 年化波动率
    """
    if returns.empty or len(returns) < 2:
        return 0.0

    annual_return = returns.mean() * periods_per_year
    annual_vol = returns.std() * math.sqrt(periods_per_year)

    if annual_vol == 0:
        return 0.0

    return (annual_return - risk_free_rate) / annual_vol


# ======================== 流动性风险 ========================

def compute_amihud_liquidity(
    returns: pd.Series,
    volume: pd.Series,
    periods_per_year: int = 252,
) -> float:
    """
    Amihud 流动性比率 = 日均 |return| / 日均成交额（单位：1/万元）

    衡量单位成交额带来的价格冲击。
    值越大说明同等成交额下价格波动越大，流动性越差。

    Args:
        returns: 日收益率序列
        volume: 日成交额序列（单位：元）
        periods_per_year: 年化因子

    Returns:
        Amihud 流动性比率（年化）
    """
    if returns.empty or volume.empty or len(returns) < 20:
        return 0.0

    # 对齐
    common_idx = returns.index.intersection(volume.index)
    if len(common_idx) < 20:
        return 0.0

    ret = returns.loc[common_idx].abs()
    vol = volume.loc[common_idx].replace(0, np.nan)

    daily_ratio = ret / vol * 1e6  # 转换为 1/万元
    avg_ratio = daily_ratio.mean()
    return float(avg_ratio) if not math.isnan(avg_ratio) else 0.0


def compute_liquidity_metrics(
    returns: pd.Series,
    volume: pd.Series,
    position_value: float,
    avg_daily_volume_20d: float,
) -> dict:
    """
    综合流动性风险评估。

    Args:
        returns: 日收益率序列
        volume: 日成交额序列（元）
        position_value: 持仓市值（元）
        avg_daily_volume_20d: 20日日均成交额（元）

    Returns:
        {
            amihud_ratio: Amihud 流动性比率,
            position_to_volume_ratio: 持仓占比（日均成交倍数）,
            liquidation_days_estimate: 估计变现天数,
            liquidity_alert: 预警级别（green/yellow/red）
        }
    """
    amihud = compute_amihud_liquidity(returns, volume)

    # 持仓占日均成交比例（变现难度）
    if avg_daily_volume_20d > 0:
        pos_to_vol = position_value / avg_daily_volume_20d
    else:
        pos_to_vol = float("inf")

    # 估计变现天数（假设每天最多变现日均成交量的 10%）
    liquidation_days = round(pos_to_vol / 0.10, 1) if pos_to_vol < float("inf") else 999

    # 预警
    if liquidation_days > 20 or (avg_daily_volume_20d < 1e8 and position_value > 1e7):
        alert = "red"
    elif liquidation_days > 5 or amihud > 0.5:
        alert = "yellow"
    else:
        alert = "green"

    return {
        "amihud_ratio": round(amihud, 6),
        "position_to_volume_ratio": round(pos_to_vol, 2) if pos_to_vol < float("inf") else 999.0,
        "liquidation_days_estimate": liquidation_days,
        "liquidity_alert": alert,
    }


# ======================== 因子 Alpha/Beta 分解 ========================

def compute_factor_alpha_beta(
    factor_returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = 252,
) -> dict:
    """
    因子 Alpha / Beta 分解。

    Jensen's Alpha = 因子年化收益 - Beta × 市场年化收益
    Beta = Cov(因子收益, 市场收益) / Var(市场收益)

    Args:
        factor_returns: 因子日收益率序列
        benchmark_returns: 市场基准日收益率序列（如沪深300）
        periods_per_year: 年化因子

    Returns:
        {
            alpha: Jensen's Alpha（年化）,
            beta: 系统性风险 Beta,
            annual_factor_return: 因子年化收益率,
            annual_market_return: 市场年化收益率,
            correlation: 相关系数,
            r_squared: R² 决定系数
        }
    """
    common_idx = factor_returns.index.intersection(benchmark_returns.index)
    if len(common_idx) < 30:
        return {
            "alpha": 0.0, "beta": 0.0,
            "annual_factor_return": 0.0, "annual_market_return": 0.0,
            "correlation": 0.0, "r_squared": 0.0,
        }

    f_ret = factor_returns.loc[common_idx]
    m_ret = benchmark_returns.loc[common_idx]

    # Beta
    covariance = f_ret.cov(m_ret)
    m_var = m_ret.var()
    beta = covariance / m_var if m_var != 0 else 0.0

    # Alpha
    annual_factor_ret = f_ret.mean() * periods_per_year
    annual_market_ret = m_ret.mean() * periods_per_year
    alpha = annual_factor_ret - beta * annual_market_ret

    # 相关系数
    correlation = f_ret.corr(m_ret)

    # R²
    r_squared = correlation ** 2 if not math.isnan(correlation) else 0.0

    return {
        "alpha": round(alpha, 6),
        "beta": round(float(beta), 4),
        "annual_factor_return": round(annual_factor_ret, 6),
        "annual_market_return": round(annual_market_ret, 6),
        "correlation": round(float(correlation), 4),
        "r_squared": round(float(r_squared), 4),
    }


def compute_factor_return_contribution(
    factor_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> dict:
    """
    因子收益分解：市场贡献 + 超额收益（Alpha）。

    因子总收益 = 市场收益(Beta部分) + Alpha
    """
    result = compute_factor_alpha_beta(factor_returns, benchmark_returns)

    # 市场贡献 = Beta × 市场收益
    result["market_contribution"] = round(
        result["beta"] * result["annual_market_return"], 6
    )
    # 超额收益 = Alpha
    result["active_contribution"] = result["alpha"]

    return result

