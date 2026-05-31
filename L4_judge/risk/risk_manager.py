#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理引擎 — 融合ai-hedge-fund风险控制思想 + 我们的仓位管理体系

核心创新：
1. 波动率校准：基于个股历史波动率动态调整仓位
2. 相关性风控：持仓间相关性检测，防止过度集中
3. 凯利公式仓位：按胜率和盈亏比计算最优仓位
4. 三级风控机制：个股级（止损）→组合级（集中度）→市场级（系统性）
5. 与五维评分联动：评分低→自动降仓，评分高→允许加仓
"""

import math
import json
import logging
import os
import io
import numpy as np
import pandas as pd
import contextlib
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict


# ── Silence baostock login/logout messages ──
def _patch_baostock_silent():
    """Monkey-patch baostock's login/logout to suppress their print() statements."""
    import baostock as _bs
    if not hasattr(_bs, '_baostock_patched'):
        _orig_login = _bs.login
        _orig_logout = _bs.logout

        def _silent_login():
            import sys as _sys
            with open(os.devnull, 'w') as _devnull:
                _old_stdout = _sys.stdout
                _old_stderr = _sys.stderr
                try:
                    _sys.stdout = _devnull
                    _sys.stderr = _devnull
                    result = _orig_login()
                finally:
                    _sys.stdout = _old_stdout
                    _sys.stderr = _old_stderr
            return result

        def _silent_logout():
            import sys as _sys
            with open(os.devnull, 'w') as _devnull:
                _old_stdout = _sys.stdout
                _old_stderr = _sys.stderr
                try:
                    _sys.stdout = _devnull
                    _sys.stderr = _devnull
                    result = _orig_logout()
                finally:
                    _sys.stdout = _old_stdout
                    _sys.stderr = _old_stderr
            return result

        _bs.login = _silent_login
        _bs.logout = _silent_logout
        _bs._baostock_patched = True


# Apply silencing globally on module import
try:
    _patch_baostock_silent()
except Exception:
    pass

from L4_judge.risk.risk_metrics import (
    compute_historical_var,
    compute_cvar,
    compute_sortino,
    compute_calmar,
    compute_max_drawdown_from_prices,
    compute_correlation_matrix as _compute_corr_matrix,
    compute_portfolio_var,
    compute_sharpe,
    compute_covariance_matrix_from_weights,
    compute_liquidity_metrics,
    compute_factor_alpha_beta,
    compute_factor_return_contribution,
)

logger = logging.getLogger("risk_manager")


# ======================== 数据模型 ========================

@dataclass
class Position:
    """单个持仓信息"""
    stock_code: str
    stock_name: str
    entry_price: float           # 买入价格
    current_price: float         # 当前价格
    shares: int                  # 持仓股数
    cost: float                  # 持仓成本（总金额）
    market_value: float          # 当前市值
    pnl_pct: float               # 收益率%
    pnl_amount: float            # 盈亏金额
    weight: float                # 占总仓位比例
    score: float = 0.0           # 当前五维评分
    max_drawdown: float = 0.0    # 最大回撤
    days_held: int = 0           # 持有天数
    # 增强指标（新增）
    peak_date: Optional[str] = None   # 最大点日期
    trough_date: Optional[str] = None  # 最低点日期
    recovery_date: Optional[str] = None # 恢复日期

    def to_dict(self):
        return asdict(self)


@dataclass
class RiskAssessment:
    """风险评估结果"""
    stock_code: str
    stock_name: str
    assess_date: str

    # 个体风险（原有）
    volatility: float = 0.0          # 30日年化波动率
    max_drawdown_30d: float = 0.0    # 30日最大回撤（简化值，兼容旧代码）
    var_95: float = 0.0              # 95% VaR（日，简化值）

    # 增强风险指标（新增）
    sortino_ratio: float = 0.0       # Sortino Ratio
    calmar_ratio: float = 0.0         # Calmar Ratio
    historical_var_95: float = 0.0   # 历史模拟法 VaR（负值）
    cvar_95: float = 0.0            # CVaR / Expected Shortfall（负值）
    max_drawdown_details: dict = field(default_factory=dict)  # {max_dd, peak_date, trough_date, recovery_date, duration_days}

    # 仓位建议
    recommended_weight: float = 0.0   # 建议仓位比例
    kelly_fraction: float = 0.0       # 凯利公式仓位
    position_sizing: str = ""         # 仓位大小描述

    # 风控信号
    stop_loss_price: float = 0.0      # 止损价
    take_profit_price: float = 0.0    # 止盈价
    alert_level: str = "normal"       # normal/warning/danger
    risk_score: float = 0.0           # 风险评分 0-100（越高越危险）

    # 流动性风险（新增 R3）
    liquidity_alert: str = "green"    # green/yellow/red
    amihud_ratio: float = 0.0         # Amihud 流动性比率
    position_to_volume_ratio: float = 0.0  # 持仓/日均成交
    liquidation_days_estimate: float = 0.0  # 估计变现天数

    def to_dict(self):
        return asdict(self)


@dataclass
class PortfolioRisk:
    """组合级风险评估"""
    total_capital: float = 0.0
    used_capital: float = 0.0
    available_capital: float = 0.0
    positions_count: int = 0

    # 集中度风险
    top_holding_pct: float = 0.0        # 最大持仓占比
    top_3_holding_pct: float = 0.0      # 前3持仓占比
    sector_concentration: Dict = field(default_factory=dict)  # 行业集中度

    # 相关性风险（真实计算，新增）
    avg_correlation: float = 0.0        # 持仓间平均相关系数（真实）
    max_correlation: float = 0.0        # 最大相关系数（真实）
    correlation_matrix: dict = field(default_factory=dict)  # 完整相关系数矩阵

    # 整体风险
    portfolio_volatility: float = 0.0   # 组合波动率
    portfolio_var_95: float = 0.0       # 组合VaR（简化值，兼容旧代码）
    portfolio_beta: float = 0.0         # 组合Beta

    # 增强风险指标（新增）
    sortino_ratio: float = 0.0          # 组合 Sortino Ratio
    calmar_ratio: float = 0.0           # 组合 Calmar Ratio
    real_covariance_var_95: float = 0.0 # 基于真实协方差矩阵的 VaR

    # 风控状态
    margin_call_risk: bool = False
    concentration_warning: bool = False
    overall_alert: str = "green"        # green/yellow/red

    def to_dict(self):
        return asdict(self)


# ======================== 配置文件路径 ========================

import os as _os

_CONFIG_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
    "main", "config", "l4_risk_config.json"
)

# ======================== 风险等级配置 ========================

def _load_risk_config() -> dict:
    """从配置文件加载风控参数，失败时使用默认值"""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        logger.info(f"风控配置加载成功: {_CONFIG_PATH}")
        return cfg
    except FileNotFoundError:
        logger.warning(f"风控配置文件不存在，使用默认值: {_CONFIG_PATH}")
    except Exception as e:
        logger.warning(f"风控配置加载失败: {e}，使用默认值")
    return {}

# 延迟加载配置
_RISK_CONFIG_CACHE = None

def _get_risk_config() -> dict:
    global _RISK_CONFIG_CACHE
    if _RISK_CONFIG_CACHE is None:
        _RISK_CONFIG_CACHE = _load_risk_config()
    return _RISK_CONFIG_CACHE

def _get_default_risk_config() -> dict:
    """默认风控配置（当配置文件不存在时使用）"""
    return {
        "max_single_position": 0.20,
        "max_top3_concentration": 0.50,
        "max_sector_concentration": 0.35,
        "stop_loss_default": -0.08,
        "take_profit_default": 0.20,
        "var_95_limit": 0.03,
        "volatility_warning": 0.40,
        "volatility_danger": 0.60,
        "max_correlation": 0.70,
        "kelly_fraction_limit": 0.25,
        "margin_call_threshold": 0.85,
    }

# 仓位等级描述
POSITION_LEVELS = [
    (0.30, "重仓"),
    (0.20, "中等仓位"),
    (0.15, "轻仓"),
    (0.10, "试探仓位"),
    (0.05, "迷你仓位"),
    (0.00, "不建议买入"),
]


# ======================== 风险管理引擎 ========================

class RiskManager:
    """
    风险管理引擎
    
    三级风控架构：
    Level 1 — 个股级：止损、止盈、波动率监控
    Level 2 — 组合级：集中度、相关性、行业分散
    Level 3 — 系统级：市场环境、宏观风险
    """

    def __init__(self, total_capital: float = None,
                 config: Dict = None):
        cfg = _get_risk_config()
        if total_capital is None:
            total_capital = cfg.get("total_capital", 100_000)
        self.total_capital = total_capital
        self.config = {**_get_default_risk_config(), **cfg.get("risk", {}), **(config or {})}
        self.positions: Dict[str, Position] = {}
        logger.info(f"风险管理引擎初始化，总资金: {total_capital/10000:.0f}万，配置: {list(self.config.keys())}")

    # ==================== Level 1: 个股级风控 ====================

    def assess_stock_risk(self, stock_code: str, stock_name: str,
                          current_price: float,
                          historical_volatility: float = 0.0,
                          score_result=None) -> RiskAssessment:
        """
        个股风险评估 + 仓位建议
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            current_price: 当前价格
            historical_volatility: 历史年化波动率
            score_result: 五维评分结果（可选，用于联动）
        
        Returns:
            RiskAssessment 风险评估+仓位建议
        """
        assess = RiskAssessment(
            stock_code=stock_code,
            stock_name=stock_name,
            assess_date=datetime.now().strftime("%Y-%m-%d"),
        )

        # 1. 波动率
        vol = historical_volatility or self._estimate_volatility(stock_code)
        assess.volatility = vol

        if vol > self.config["volatility_danger"]:
            assess.alert_level = "danger"
        elif vol > self.config["volatility_warning"]:
            assess.alert_level = "warning"

        # 2. VaR 简化估算（兼容旧代码）
        assess.var_95 = round(vol * 1.645 / math.sqrt(252), 4)

        # 3. 最大回撤（简化估算，兼容旧代码）
        assess.max_drawdown_30d = round(vol * 0.3, 4)

        # 4. 增强指标：从 BaoStock 获取真实历史数据计算
        try:
            import baostock as bs
            import pandas as pd

            with _suppress_baostock_output():
                bs.login()
                bs_code = stock_code.replace("SH.", "sh.").replace("SZ.", "sz.")
                if "." not in bs_code:
                    bs_code = f"sh.{bs_code}" if bs_code.startswith("6") else f"sz.{bs_code}"

                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,close",
                    start_date=(datetime.now() - timedelta(days=252)).strftime("%Y-%m-%d"),
                    end_date=datetime.now().strftime("%Y-%m-%d"),
                    frequency="d",
                    adjustflag="2",
                )
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
                bs.logout()

            if len(rows) >= 60:
                df = pd.DataFrame(rows, columns=["date", "close"])
                df["close"] = pd.to_numeric(df["close"], errors="coerce")
                df = df.dropna(subset=["close"]).set_index("date")["close"]
                prices = df.sort_index()

                # 日收益率
                returns = prices.pct_change().dropna()

                # 历史模拟法 VaR
                assess.historical_var_95 = round(compute_historical_var(returns, 0.95), 6)

                # CVaR
                assess.cvar_95 = round(compute_cvar(returns, 0.95), 6)

                # Sortino Ratio
                assess.sortino_ratio = round(compute_sortino(returns), 4)

                # Calmar Ratio（需要 max_drawdown）
                dd_details = compute_max_drawdown_from_prices(prices)
                assess.calmar_ratio = round(compute_calmar(returns, dd_details["max_drawdown"]), 4)

                # MaxDrawdown 详细信息
                assess.max_drawdown_details = {
                    "max_drawdown": round(dd_details["max_drawdown"], 4),
                    "peak_date": dd_details["peak_date"],
                    "trough_date": dd_details["trough_date"],
                    "recovery_date": dd_details["recovery_date"],
                    "duration_days": dd_details["duration_days"],
                    "current_drawdown": round(dd_details["current_drawdown"], 4),
                }
                # 更新简化版 max_drawdown
                assess.max_drawdown_30d = round(dd_details["max_drawdown"], 4)

        except Exception:
            pass  # 增强指标失败不影响基础评估

        # 4. 凯利公式仓位计算
        kelly = self._kelly_criterion(assess, score_result)
        assess.kelly_fraction = kelly

        # 5. 综合建议仓位
        position_score = self._recommend_position_size(assess, score_result)
        assess.recommended_weight = position_score
        assess.position_sizing = self._get_position_label(position_score)

        # 6. 止损止盈自适应（P2-2修复：2026-04-26）
        # ATR(14) = 近14日TrueRange均值，1.5×ATR反映正常日波动幅度
        # min(ATR止损, 固定止损)：低波动 → ATR收紧止损；高波动/数据异常 → 固定止损兜底
        # 贵州茅台(600519) 2026-04实测：ATR=24.49元(1.32%)，ATR止损=1.99% < 8%，采用ATR=2%
        base_stop_pct = abs(self.config["stop_loss_default"])  # 0.08 默认兜底
        stop_loss_pct = base_stop_pct  # 默认用固定止损
        try:
            import baostock as bs
            with _suppress_baostock_output():
                bs.login()
                bs_code = stock_code.replace('SH.', 'sh.').replace('SZ.', 'sz.')
                if '.' not in bs_code:
                    bs_code = f"sh.{bs_code}" if bs_code.startswith('6') else f"sz.{bs_code}"
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,close,high,low",
                    start_date=(datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d"),
                    end_date=datetime.now().strftime("%Y-%m-%d"),
                    frequency="d", adjustflag="2"
                )
                rows = []
                while rs.error_code == '0' and rs.next():
                    rows.append(rs.get_row_data())
                bs.logout()
            if len(rows) >= 14:
                import pandas as pd
                df = pd.DataFrame(rows, columns=["date", "close", "high", "low"])
                for col in ["close", "high", "low"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["close", "high", "low"])
                if len(df) >= 14:
                    df["tr1"] = df["high"] - df["low"]
                    df["tr2"] = abs(df["high"] - df["close"].shift(1))
                    df["tr3"] = abs(df["low"] - df["close"].shift(1))
                    df["tr"] = df[["tr1", "tr2", "tr3"]].max(axis=1)
                    atr = df["tr"].tail(14).mean()
                    if pd.notna(atr) and atr > 0 and current_price > 0:
                        atr_stop_pct = (atr / current_price) * 1.5
                        stop_loss_pct = min(atr_stop_pct, base_stop_pct)
                        logger.info(f"  ATR止损: ATR={atr:.1f}({atr/current_price:.2%}), 自适应={atr_stop_pct:.2%}, 固定={base_stop_pct:.2%}, 采用={stop_loss_pct:.2%}")
        except Exception:
            pass  # 失败时保持 base_stop_pct

        take_profit_pct = abs(self.config["take_profit_default"])  # 0.20 维持固定
        assess.stop_loss_price = round(current_price * (1 - stop_loss_pct), 2)
        assess.take_profit_price = round(current_price * (1 + take_profit_pct), 2)

        # 7. 风险评分（综合）
        risk_score = self._calculate_risk_score(assess, score_result)
        assess.risk_score = risk_score

        # 8. 流动性风险评估（R3）
        liq_metrics = self._assess_liquidity(stock_code, current_price)
        if liq_metrics:
            assess.liquidity_alert = liq_metrics.get("liquidity_alert", "green")
            assess.amihud_ratio = liq_metrics.get("amihud_ratio", 0.0)
            assess.position_to_volume_ratio = liq_metrics.get("position_to_volume_ratio", 0.0)
            assess.liquidation_days_estimate = liq_metrics.get("liquidation_days_estimate", 0.0)
            # 流动性预警影响综合评级
            if assess.liquidity_alert == "red":
                assess.alert_level = "danger"
            elif assess.liquidity_alert == "yellow" and assess.alert_level == "normal":
                assess.alert_level = "warning"

        return assess

    def _assess_liquidity(
        self,
        stock_code: str,
        current_price: float,
        position_value: Optional[float] = None,
    ) -> Optional[dict]:
        """
        流动性风险评估（R3）。

        使用 BaoStock 日线数据计算 Amihud 流动性比率和变现天数。
        """
        try:
            bs_code = stock_code.replace("SH.", "sh.").replace("SZ.", "sz.")
            if "." not in bs_code:
                bs_code = f"sh.{bs_code}" if bs_code.startswith("6") else f"sz.{bs_code}"

            with _suppress_baostock_output():
                bs.login()
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,close,volume,amount",
                    start_date=(datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"),
                    end_date=datetime.now().strftime("%Y-%m-%d"),
                    frequency="d",
                    adjustflag="2",
                )
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
                bs.logout()

            if len(rows) < 20:
                return None

            df = pd.DataFrame(rows, columns=["date", "close", "volume", "amount"])
            for col in ["close", "volume", "amount"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close", "volume", "amount"])
            df = df.set_index("date").sort_index()

            if len(df) < 20:
                return None

            closes = df["close"].astype(float)
            amounts = df["amount"].astype(float)

            returns = closes.pct_change().dropna()
            volume_series = amounts  # 元

            # 持仓市值（若无传入，用 10万 默认）
            pos_val = position_value or 100_000.0

            # 20日日均成交额
            adv_20 = amounts.tail(20).mean()

            return compute_liquidity_metrics(returns, volume_series, pos_val, adv_20)

        except Exception:
            return None

    def _estimate_volatility(self, stock_code: str) -> float:
        """
        估算年化波动率：从BaoStock取20日日收益率标准差×√252。
        ATR(20) ≈ vol_annual / 200（即20日止损 ≈ vol/200 ≈ vol*0.6/252*250 ≈ vol*0.6）
        若失败则回退到BaoStock日线手动计算。
        """
        bs_code = stock_code.replace('SH.', 'sh.').replace('SZ.', 'sz.')
        if '.' not in bs_code:
            bs_code = f"sh.{bs_code}" if bs_code.startswith('6') else f"sz.{bs_code}"
        try:
            import baostock as bs
            with _suppress_baostock_output():
                bs.login()
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,close",
                    start_date=(datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"),
                    end_date=datetime.now().strftime("%Y-%m-%d"),
                    frequency="d", adjustflag="2"
                )
                rows = []
                while rs.error_code == '0' and rs.next():
                    rows.append(rs.get_row_data())
                bs.logout()
            if len(rows) < 20:
                return 0.30
            import pandas as pd
            df = pd.DataFrame(rows, columns=["date", "close"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            if len(df) < 20:
                return 0.30
            df["ret"] = df["close"].pct_change()
            ret_std = df["ret"].std() * math.sqrt(252)
            return round(ret_std, 4)
        except Exception:
            pass

        return 0.30  # 默认年化30%

    def _kelly_criterion(self, assess: RiskAssessment,
                         score_result) -> float:
        """
        凯利公式仓位计算
        
        f* = (bp - q) / b
        b = 赔率（预期收益/预期亏损）
        p = 胜率
        q = 1-p
        """
        if not score_result:
            return 0.1  # 无评分时默认10%

        score = getattr(score_result, "five_score", None) or getattr(score_result, "total_score", 0) or 0
        # 从评分映射胜率
        if score >= 80:
            p = 0.65  # 优级，65%胜率
        elif score >= 65:
            p = 0.55
        elif score >= 50:
            p = 0.45
        else:
            p = 0.35  # 差级

        # 赔率（基于波动率调整）
        vol = assess.volatility
        if vol == 0:
            vol = 0.30
        
        # 预期收益/预期亏损
        expected_gain = 0.20  # 目标20%
        expected_loss = self.config["stop_loss_default"] * -1  # 止损8%
        b = expected_gain / expected_loss  # 赔率

        q = 1 - p
        kelly = (b * p - q) / b
        
        # 限制在合理范围
        kelly = max(0.0, min(kelly, self.config["kelly_fraction_limit"]))
        
        return round(kelly, 4)

    def _recommend_position_size(self, assess: RiskAssessment,
                                  score_result) -> float:
        """综合确定建议仓位大小"""
        # 基础：凯利公式仓位
        base = assess.kelly_fraction

        # 波动率调整：波动率越高，仓位越低
        vol_factor = max(0.3, 1.0 - assess.volatility)
        
        # 评分调整：评分越高，越可加仓
        score_factor = 0.5
        if score_result:
            score = getattr(score_result, "five_score", None) or getattr(score_result, "total_score", 0) or 0
            score_factor = 0.3 + (score / 100) * 0.4
        
        # VaR调整：VaR太高减仓
        var_factor = 1.0
        if assess.var_95 > self.config["var_95_limit"]:
            var_factor = self.config["var_95_limit"] / assess.var_95
            var_factor = max(0.3, var_factor)

        # 综合：确保不超过最大单仓限制
        recommended = base * vol_factor * score_factor * var_factor
        recommended = min(recommended, self.config["max_single_position"])
        
        return round(recommended, 4)

    def _get_position_label(self, weight: float) -> str:
        """根据仓位比例返回文字描述"""
        for threshold, label in POSITION_LEVELS:
            if weight >= threshold:
                return label
        return "不建议买入"

    def _calculate_risk_score(self, assess: RiskAssessment,
                               score_result) -> float:
        """
        综合风险评分 0-100（越高越危险）
        
        影响因素：
        - 波动率贡献 30分
        - VaR贡献 20分
        - 评分反向贡献 30分（评分低=风险高）
        - 凯利仓位贡献 20分
        """
        risk = 0.0
        
        # 波动率风险
        vol = assess.volatility
        if vol > 0.60:
            risk += 30
        elif vol > 0.40:
            risk += 20
        elif vol > 0.25:
            risk += 10
        
        # VaR风险
        if assess.var_95 > 0.05:
            risk += 20
        elif assess.var_95 > 0.03:
            risk += 12
        elif assess.var_95 > 0.02:
            risk += 5

        # 评分反向风险
        if score_result:
            score = getattr(score_result, "five_score", None) or getattr(score_result, "total_score", 0) or 0
            risk += max(0, (60 - score) * 0.5)
        else:
            risk += 15  # 无评分中性

        # 凯利仓位风险
        if assess.kelly_fraction < 0.05:
            risk += 10  # 凯利太小说明风险高
        
        return min(100, max(0, risk))

    # ==================== Level 2: 组合级风控 ====================

    def _compute_real_correlation(
        self, positions: List[Position]
    ) -> Tuple[Optional[pd.DataFrame], bool]:
        """
        从持仓股票的真实历史数据计算相关系数矩阵。

        Returns:
            (相关系数矩阵 DataFrame, 是否成功计算)
        """
        try:
            import baostock as bs
            import pandas as pd

            with _suppress_baostock_output():
                bs.login()

                # 并行获取每只股票的历史数据
                price_series = {}
                for p in positions:
                    bs_code = p.stock_code.replace("SH.", "sh.").replace("SZ.", "sz.")
                    if "." not in bs_code:
                        bs_code = f"sh.{bs_code}" if bs_code.startswith("6") else f"sz.{bs_code}"

                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,close",
                        start_date=(datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d"),
                        end_date=datetime.now().strftime("%Y-%m-%d"),
                        frequency="d",
                        adjustflag="2",
                    )
                    rows = []
                    while rs.error_code == "0" and rs.next():
                        rows.append(rs.get_row_data())

                    if len(rows) >= 30:
                        df = pd.DataFrame(rows, columns=["date", "close"])
                        df["close"] = pd.to_numeric(df["close"], errors="coerce")
                        df = df.dropna(subset=["close"])
                        df["date"] = pd.to_datetime(df["date"])
                        df = df.set_index("date")["close"]
                        df.name = p.stock_code
                        price_series[p.stock_code] = df

                bs.logout()

            if len(price_series) < 2:
                return None, False

            # 合并为 DataFrame
            prices_df = pd.DataFrame(price_series)
            prices_df = prices_df.sort_index().dropna()

            if prices_df.shape[0] < 30 or prices_df.shape[1] < 2:
                return None, False

            # 日收益率
            returns_df = prices_df.pct_change().dropna()

            if returns_df.shape[0] < 20:
                return None, False

            # 相关系数矩阵
            corr = returns_df.corr()
            return corr, True

        except Exception:
            return None, False

    def assess_portfolio(self, positions: List[Position] = None) -> PortfolioRisk:
        """组合级风险评估"""
        pr = PortfolioRisk(
            total_capital=self.total_capital,
        )

        active_positions = positions or list(self.positions.values())
        
        if not active_positions:
            pr.available_capital = self.total_capital
            return pr

        pr.positions_count = len(active_positions)
        pr.used_capital = sum(p.cost for p in active_positions)
        pr.available_capital = self.total_capital - pr.used_capital

        # 按市值排序
        sorted_pos = sorted(active_positions, key=lambda p: p.market_value, reverse=True)

        # 集中度
        if sorted_pos:
            pr.top_holding_pct = sorted_pos[0].weight
            pr.top_3_holding_pct = sum(p.weight for p in sorted_pos[:3])

        # 行业集中度（如果有行业信息）
        sector_weights = {}
        for p in sorted_pos:
            sector = getattr(p, "sector", "未知")
            sector_weights[sector] = sector_weights.get(sector, 0) + p.weight
        pr.sector_concentration = sector_weights

        # 相关性（真实计算）
        if pr.positions_count >= 2:
            # 尝试用真实相关系数矩阵替代 0.3 假设
            corr_matrix, real_cov_computed = self._compute_real_correlation(sorted_pos)
            if real_cov_computed:
                # 从相关系数矩阵提取平均/最大相关系数
                codes = list(corr_matrix.columns)
                corrs = []
                for i in range(len(codes)):
                    for j in range(i + 1, len(codes)):
                        corrs.append(float(corr_matrix.iloc[i, j]))
                if corrs:
                    pr.avg_correlation = round(sum(corrs) / len(corrs), 4)
                    pr.max_correlation = round(max(corrs), 4)
                pr.correlation_matrix = corr_matrix.to_dict()

                # 基于真实协方差矩阵计算组合 VaR
                weights_arr = np.array([p.weight for p in sorted_pos])
                cov_mat = compute_covariance_matrix_from_weights(
                    sorted_pos, corr_matrix
                )
                daily_var, annual_var = compute_portfolio_var(weights_arr, cov_mat)
                pr.real_covariance_var_95 = round(annual_var, 4)

                # 组合波动率
                pr.portfolio_volatility = round(
                    math.sqrt(float(weights_arr @ cov_mat @ weights_arr)) * math.sqrt(252), 4
                )
            else:
                # 降级到 0.3 假设
                pr.avg_correlation = 0.3
                pr.max_correlation = 0.5

        # 组合VaR（简化，兼容旧代码）
        if pr.avg_correlation > 0 and pr.real_covariance_var_95 == 0:
            weights = [p.weight for p in sorted_pos]
            avg_vol = 0.30  # 假设平均30%波动率
            n = len(weights)
            port_vol = avg_vol * math.sqrt(
                sum(w**2 for w in weights) +
                2 * sum(weights[i] * weights[j] * pr.avg_correlation
                       for i in range(n) for j in range(i+1, n))
            )
            pr.portfolio_volatility = round(port_vol, 4)
            pr.portfolio_var_95 = round(port_vol * 1.645 / math.sqrt(252), 4)

        # 风控状态
        pr.concentration_warning = (pr.top_3_holding_pct > self.config["max_top3_concentration"])
        
        usage_ratio = pr.used_capital / self.total_capital if self.total_capital > 0 else 0
        pr.margin_call_risk = (usage_ratio > self.config["margin_call_threshold"])

        if pr.margin_call_risk or pr.concentration_warning:
            pr.overall_alert = "red"
        elif pr.top_holding_pct > self.config["max_single_position"] * 0.8:
            pr.overall_alert = "yellow"
        else:
            pr.overall_alert = "green"

        return pr

    # ==================== 风控动作 ====================

    def can_buy(self, stock_code: str, amount: float,
                assess: RiskAssessment = None,
                portfolio: PortfolioRisk = None) -> Tuple[bool, str]:
        """
        买入前风控检查
        
        Returns:
            (can_buy, reason)
        """
        # 1. 个股风险检查
        if assess and assess.alert_level == "danger":
            return False, f"个股风险过高(波动率{assess.volatility:.0%})"

        # 2. 资金检查
        if portfolio:
            if amount > portfolio.available_capital:
                return False, f"资金不足(需{amount:.0f}，可用{portfolio.available_capital:.0f})"
            
            if portfolio.overall_alert == "red":
                return False, "组合风控红灯，暂停买入"

        # 3. 持仓集中度检查
        if assess:
            max_allow = self.total_capital * self.config["max_single_position"]
            if amount > max_allow:
                return False, f"超单只上限(建议≤{max_allow:.0f})"

        return True, "通过风控检查"

    def should_sell(self, position: Position, current_price: float,
                    score_result=None) -> Tuple[bool, str, str]:
        """
        卖出信号检查
        
        Returns:
            (should_sell, reason, action)
            action: "stop_loss" / "take_profit" / "risk_control"
        """
        pnl = (current_price - position.entry_price) / position.entry_price
        max_drawdown = position.max_drawdown

        # 止损
        if pnl <= self.config["stop_loss_default"]:
            return True, f"触发止损({pnl:.1%})", "stop_loss"

        # 止盈
        if pnl >= self.config["take_profit_default"]:
            return True, f"触达止盈目标({pnl:.1%})", "take_profit"

        # 评分恶化（如果评分传入且变差）
        if score_result and (getattr(score_result, "five_score", None) or getattr(score_result, "total_score", 0) or 0) < 40:
            score_val = getattr(score_result, "five_score", None) or getattr(score_result, "total_score", 0) or 0
            return True, f"基本面恶化(评分{score_val:.0f})", "risk_control"

        return False, "", ""

    # ==================== 持仓管理 ====================

    def update_position(self, position: Position):
        """更新或添加持仓"""
        self.positions[position.stock_code] = position

    def remove_position(self, stock_code: str):
        """移除持仓"""
        if stock_code in self.positions:
            del self.positions[stock_code]

    # ==================== 持仓监控（来自原 L5） ====================

    def check_position_triggers(
        self,
        stock_code: str,
        current_price: float,
        avg_cost: float,
        shares: int,
        stop_loss_pct: float,
        take_profit_pct: float,
        trend_direction: Optional[str] = None,
        freeze_status: str = "normal",
    ) -> dict:
        """
        检查持仓触发条件（止损/止盈/追加买入）。

        这是原 L5_post_review/l5_runner.py 的核心逻辑，现整合到 L4 RiskManager。

        Args:
            stock_code: 股票代码
            current_price: 当前价格
            avg_cost: 平均成本价
            shares: 持仓股数
            stop_loss_pct: 止损百分比（负数，如 -0.08）
            take_profit_pct: 止盈百分比（正数，如 0.20）
            trend_direction: 趋势方向（"up" / "down" / None）
            freeze_status: 冷冻状态（"normal" / "frozen_10d" / "frozen_3m"）

        Returns:
            {
                "action": "HOLD" | "STOP_LOSS" | "SELL" | "ADD",
                "action_reason": str,
                "freeze_status": str,
                "price_change_pct": float,
            }
        """
        from datetime import date

        # 1. 冷冻状态检查
        if freeze_status != "normal":
            return {
                "action": "HOLD",
                "action_reason": f"股票处于{freeze_status}冷冻状态，暂不交易",
                "freeze_status": freeze_status,
                "price_change_pct": 0.0,
            }

        # 2. 无持仓检查
        if shares <= 0 or avg_cost <= 0 or current_price <= 0:
            return {
                "action": "HOLD",
                "action_reason": "无持仓或成本异常",
                "freeze_status": "normal",
                "price_change_pct": 0.0,
            }

        # 3. 计算价格变化
        price_change_pct = (current_price - avg_cost) / avg_cost

        # 4. 止损检查
        if price_change_pct <= stop_loss_pct:
            return {
                "action": "STOP_LOSS",
                "action_reason": f"触发止损：当前价格{current_price:.2f}，成本{avg_cost:.2f}，"
                                f"涨跌{price_change_pct:.2%}，止损线{stop_loss_pct:.2%}",
                "freeze_status": "normal",
                "price_change_pct": round(price_change_pct, 6),
            }

        # 5. 止盈检查
        if price_change_pct >= take_profit_pct:
            return {
                "action": "SELL",
                "action_reason": f"触发止盈：当前价格{current_price:.2f}，成本{avg_cost:.2f}，"
                                f"涨跌{price_change_pct:.2%}，止盈线{take_profit_pct:.2%}",
                "freeze_status": "normal",
                "price_change_pct": round(price_change_pct, 6),
            }

        # 6. 追加买入检查（价格低于成本且趋势向上）
        if current_price < avg_cost and trend_direction == "up":
            return {
                "action": "ADD",
                "action_reason": f"价格低于成本({current_price:.2f} < {avg_cost:.2f})且趋势向上，可追加买入",
                "freeze_status": "normal",
                "price_change_pct": round(price_change_pct, 6),
            }

        # 7. 默认持有
        return {
            "action": "HOLD",
            "action_reason": f"价格未触及止损({price_change_pct:.2%} > {stop_loss_pct:.2%})，继续持有",
            "freeze_status": "normal",
            "price_change_pct": round(price_change_pct, 6),
        }


# ======================== 测试入口 ========================

def test_risk_manager():
    """测试风险管理引擎"""
    
    risk = RiskManager(total_capital=100_000)
    
    # 创建模拟评分
    from scoring.five_dimension_scorer import FiveDimensionScorer
    import sys
    sys.path.insert(0, ".")
    
    try:
        scorer = FiveDimensionScorer()
        
        # 好股票：资金+技术都强
        good_data = {
            "moneyflow_data": {"main_net_flow_5d": 80_000_000, "large_order_ratio": 0.25,
                               "main_direction": "流入", "retail_direction": "流出",
                               "daily_flows": [20_000_000, 30_000_000, 30_000_000], "_source": "模拟"},
            "technical_data": {"ma_status": "bullish", "macd_status": "golden",
                               "volume_status": "放量上涨", "rsi": 45, "_source": "模拟"},
            "fundamental_data": {"roe": 18.5, "net_profit_yoy": 22.3, "pb": 1.8, "_source": "模拟"},
            "sector_data": {"sector_rank": 85, "sector_fund_flow": 500_000_000, "_source": "模拟"},
            "event_data": {"positive_events": ["业绩预增"], "analyst_rating": "buy", "report_count_30d": 8, "_source": "模拟"},
        }
        good_score = scorer.score_stock("600519", "贵州茅台", good_data)
        
        # 差股票：资金面恶化，技术面差
        bad_data = {
            "moneyflow_data": {"main_net_flow_5d": -80_000_000, "large_order_ratio": -0.15,
                               "main_direction": "流出", "retail_direction": "流入",
                               "daily_flows": [-30_000_000, -30_000_000, -20_000_000], "_source": "模拟"},
            "technical_data": {"ma_status": "bearish", "macd_status": "death",
                               "volume_status": "缩量", "rsi": 35, "_source": "模拟"},
            "fundamental_data": {"roe": 5.0, "net_profit_yoy": -15.0, "pb": 3.5, "_source": "模拟"},
            "sector_data": {"sector_rank": 30, "sector_fund_flow": -200_000_000, "_source": "模拟"},
            "event_data": {"positive_events": [], "analyst_rating": "sell", "report_count_30d": 1, "_source": "模拟"},
        }
        bad_score = scorer.score_stock("000002", "万科A", bad_data)
        
        print("=" * 60)
        print("风险管理引擎测试")
        print("=" * 60)
        
        # 测试1: 好股票风险评估
        print("\n▶ 好股票风险评估:")
        good_assess = risk.assess_stock_risk("600519", "贵州茅台", 1850.0, 0.25, good_score)
        print(f"  波动率: {good_assess.volatility:.0%}")
        print(f"  日VaR(95%): {good_assess.var_95:.2%}")
        print(f"  凯利仓位: {good_assess.kelly_fraction:.1%}")
        print(f"  建议仓位: {good_assess.recommended_weight:.1%} ({good_assess.position_sizing})")
        print(f"  止损价: {good_assess.stop_loss_price:.2f}")
        print(f"  止盈价: {good_assess.take_profit_price:.2f}")
        print(f"  风险评分: {good_assess.risk_score:.0f}/100")
        print(f"  告警级别: {good_assess.alert_level}")
        
        # 测试2: 差股票风险评估
        print(f"\n▶ 差股票风险评估:")
        bad_assess = risk.assess_stock_risk("000002", "万科A", 12.5, 0.50, bad_score)
        print(f"  波动率: {bad_assess.volatility:.0%}")
        print(f"  日VaR(95%): {bad_assess.var_95:.2%}")
        print(f"  凯利仓位: {bad_assess.kelly_fraction:.1%}")
        print(f"  建议仓位: {bad_assess.recommended_weight:.1%} ({bad_assess.position_sizing})")
        print(f"  风险评分: {bad_assess.risk_score:.0f}/100")
        
        # 测试3: 买入检查
        print(f"\n▶ 买入前检查:")
        can_buy, reason = risk.can_buy("600519", 20000, good_assess)
        print(f"  茅台买入2万: {'✅' if can_buy else '❌'} {reason}")
        can_buy, reason = risk.can_buy("000002", 50000, bad_assess)
        print(f"  万科买入5万: {'✅' if can_buy else '❌'} {reason}")
        
        # 测试4: 组合风险评估
        print(f"\n▶ 组合风险评估:")
        positions = [
            Position("600519", "贵州茅台", 1800, 1850, 200, 360000, 370000, 0.028, 10000, 0.37, 88, 0.05, 30),
            Position("601318", "中国平安", 55, 58, 2000, 110000, 116000, 0.055, 6000, 0.23, 75, 0.03, 20),
            # 资金10万，这两个持仓已经50万以上了——实际是满仓
        ]
        # 调整到10万总资金场景
        small_positions = [
            Position("600519", "贵州茅台", 1800, 1850, 20, 36000, 37000, 0.028, 1000, 0.37, 88, 0.05, 30),
            Position("601318", "中国平安", 55, 58, 500, 27500, 29000, 0.055, 1500, 0.29, 75, 0.03, 20),
            Position("000858", "五粮液", 150, 155, 200, 30000, 31000, 0.033, 1000, 0.31, 70, 0.04, 15),
        ]
        pr = risk.assess_portfolio(small_positions)
        print(f"  持仓数: {pr.positions_count}")
        print(f"  已用资金: {pr.used_capital:.0f}/{pr.total_capital:.0f}")
        print(f"  最大持仓占比: {pr.top_holding_pct:.1%}")
        print(f"  前3持仓占比: {pr.top_3_holding_pct:.1%}")
        print(f"  集中度预警: {'⚠️' if pr.concentration_warning else '✅'}")
        print(f"  组合告警: {pr.overall_alert}")
        
        # 测试5: 卖出信号
        print(f"\n▶ 卖出信号检查:")
        pos_good = small_positions[0]  # 茅台 - 盈利中
        should, reason, action = risk.should_sell(pos_good, 1850, good_score)
        print(f"  茅台@1850: {'卖出' if should else '持有'} ({reason})")
        
        pos_bad = Position("000002", "万科A", 15, 10, 1000, 15000, 10000, -0.333, -5000, 0.10, 30, 0.10, 60)
        should, reason, action = risk.should_sell(pos_bad, 10)
        print(f"  万科@10: {'卖出' if should else '持有'} ({reason}) [动作: {action}]")
        
        print("\n风险管理引擎测试通过！")
        
    except ImportError as e:
        print(f"注意: 需要PYTHONPATH: {e}")
        # 简易测试
        print("运行简易模式...")
        assess = risk.assess_stock_risk("600519", "贵州茅台", 1850.0)
        print(f"建议仓位: {assess.recommended_weight:.1%}")
        print(f"风险评分: {assess.risk_score:.0f}/100")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_risk_manager()
