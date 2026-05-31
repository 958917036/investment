# -*- coding: utf-8 -*-
"""
因子研究主入口 — 整合因子库、IC分析、分层回测

提供完整的因子有效性研究报告。
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from L3_quant_analysis.factor.factor_library import FactorLibrary, Factor
from L3_quant_analysis.factor.ic_analyzer import ICAnalyzer
from L3_quant_analysis.factor.quantile_backtest import QuantileBacktester
from L4_judge.risk.risk_metrics import compute_factor_alpha_beta, compute_factor_return_contribution

logger = logging.getLogger("factor.researcher")


class FactorResearcher:
    """
    因子研究主入口

    使用方式：
        researcher = FactorResearcher()

        # 设置数据
        researcher.set_factor_data("pe_ttm", factor_df)
        researcher.set_returns_data(returns_df)

        # 生成完整报告
        report = researcher.generate_report(
            factors=["pe_ttm", "roe", "revenue_growth", "ret_20d"],
            ic_window=20,
            quantiles=5,
        )
        researcher.print_report(report)
    """

    def __init__(self):
        self.factor_data: Dict[str, pd.DataFrame] = {}  # factor_name -> DataFrame
        self.returns_data: Optional[pd.DataFrame] = None  # 全收益 DataFrame
        self.benchmark_data: Optional[pd.Series] = None  # 基准收益率 Series
        self.library = FactorLibrary()
        self.ic_analyzer = ICAnalyzer()
        self.quantile_bt = QuantileBacktester(quantiles=5)

    def set_factor_data(self, factor_name: str, data: pd.DataFrame) -> None:
        """
        设置因子数据

        Args:
            factor_name: 因子名称
            data: DataFrame，index=日期，columns=股票代码，values=因子值
        """
        if not isinstance(data.index, pd.DatetimeIndex):
            data = data.copy()
            data.index = pd.to_datetime(data.index)

        self.factor_data[factor_name] = data.sort_index()
        logger.info(f"设置因子数据 {factor_name}: {data.shape}")

    def set_returns_data(self, data: pd.DataFrame) -> None:
        """
        设置收益率数据

        Args:
            data: DataFrame，index=日期，columns=股票代码，values=收益率(%)
        """
        if not isinstance(data.index, pd.DatetimeIndex):
            data = data.copy()
            data.index = pd.to_datetime(data.index)

        self.returns_data = data.sort_index()
        logger.info(f"设置收益率数据: {data.shape}")

    def set_benchmark_data(self, data: pd.Series) -> None:
        """
        设置基准收益率数据（用于 Alpha/Beta 分解）

        Args:
            data: Series，index=日期，values=日收益率（小数，如 0.01 表示 1%）
        """
        if not isinstance(data.index, pd.DatetimeIndex):
            data = data.copy()
            data.index = pd.to_datetime(data.index)

        self.benchmark_data = data.sort_index()
        logger.info(f"设置基准数据: {data.shape}")

    def generate_report(
        self,
        factors: List[str],
        ic_window: int = 20,
        quantiles: int = 5,
        forward_periods: List[int] = [1, 5],
        benchmark: Optional[pd.Series] = None,
    ) -> Dict:
        """
        生成因子有效性报告

        Args:
            factors: 要分析的因子列表
            ic_window: 滚动 IC 窗口
            quantiles: 分层回测的组数
            forward_periods: 持有的期数列表
            benchmark: 基准收益率 Series（index=日期，values=日收益率）
                       若传入则自动计算 Jensen's Alpha / Beta / R²

        Returns:
            dict: 完整的因子研究报告
        """
        if not factors:
            factors = list(self.factor_data.keys())

        if self.returns_data is None:
            raise ValueError("收益率数据未设置，请先调用 set_returns_data()")

        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "factors": {},
            "summary": {},
        }

        bench_series = benchmark if benchmark is not None else self.benchmark_data

        for fname in factors:
            if fname not in self.factor_data:
                logger.warning(f"因子 {fname} 无数据，跳过")
                continue

            factor_df = self.factor_data[fname]
            logger.info(f"分析因子: {fname}")

            # IC 分析
            ic_result = self._analyze_ic(factor_df, self.returns_data, ic_window)

            # 分层回测
            bt_results = {}
            alpha_beta = None
            for period in forward_periods:
                try:
                    bt = QuantileBacktester(quantiles=quantiles)
                    bt_result = bt.run(factor_df, self.returns_data, forward_period=period)
                    bt_results[period] = bt_result
                except Exception as e:
                    logger.warning(f"分层回测失败 {fname} period={period}: {e}")
                    bt_results[period] = None

            # Alpha/Beta 分解（用持有1期的多空组合收益率）
            if bench_series is not None:
                try:
                    bt_1d = bt_results.get(1)
                    if bt_1d and bt_1d.get("portfolio_returns") is not None:
                        factor_ret = bt_1d["portfolio_returns"]
                        common_idx = factor_ret.index.intersection(bench_series.index)
                        if len(common_idx) >= 30:
                            alpha_beta = compute_factor_alpha_beta(
                                factor_ret.loc[common_idx],
                                bench_series.loc[common_idx],
                            )
                            alpha_beta = compute_factor_return_contribution(
                                factor_ret.loc[common_idx],
                                bench_series.loc[common_idx],
                            )
                except Exception as e:
                    logger.warning(f"Alpha/Beta 计算失败 {fname}: {e}")

            report["factors"][fname] = {
                "ic": ic_result,
                "quantile_backtest": bt_results,
                "alpha_beta": alpha_beta,
                "factor_info": self.library.get_factor(fname).__dict__ if self.library.get_factor(fname) else {},
            }

        # 汇总
        report["summary"] = self._generate_summary(report["factors"])

        logger.info(f"因子研究报告生成完成: {len(report['factors'])} 个因子")
        return report

    def _analyze_ic(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        window: int,
    ) -> Dict:
        """IC 分析"""
        rolling_ic = self.ic_analyzer.rolling_IC(factor_df, returns_df, window=window)
        summary = self.ic_analyzer.IC_summary(rolling_ic)
        ic_decay = self.ic_analyzer.IC_decay(factor_df, returns_df, periods=[1, 5, 10, 20])

        return {
            "rolling_ic": rolling_ic.to_dict() if not rolling_ic.empty else {},
            "summary": summary,
            "decay": ic_decay,
        }

    def _generate_summary(self, factors_result: Dict) -> Dict:
        """生成汇总"""
        rows = []
        for fname, result in factors_result.items():
            ic_sum = result.get("ic", {}).get("summary", {})
            ls_ret = result.get("quantile_backtest", {}).get(1, {}).get("long_short_return")
            ab = result.get("alpha_beta", {})

            rows.append({
                "factor": fname,
                "mean_ic": ic_sum.get("mean_ic", np.nan),
                "ir": ic_sum.get("ir", np.nan),
                "positive_rate": ic_sum.get("positive_rate", np.nan),
                "ls_return": ls_ret,
                "alpha": ab.get("alpha", np.nan),
                "beta": ab.get("beta", np.nan),
            })

        df = pd.DataFrame(rows).sort_values("ir", ascending=False)

        return {
            "ranking": df.to_dict("records"),
            "top_factor": df.iloc[0]["factor"] if len(df) > 0 else None,
            "bottom_factor": df.iloc[-1]["factor"] if len(df) > 0 else None,
        }

    def print_report(self, report: Dict) -> None:
        """打印因子研究报告"""
        print("\n" + "=" * 80)
        print(f"因子有效性研究报告 — 生成时间: {report['generated_at']}")
        print("=" * 80)

        # 汇总排名
        summary = report.get("summary", {})
        ranking = summary.get("ranking", [])

        if ranking:
            print(f"\n{'排名':<4} {'因子':<20} {'IC均值':>10} {'IR':>8} {'IC胜率':>10} {'多空收益':>12} {'Alpha':>10} {'Beta':>8}")
            print("-" * 90)
            for i, row in enumerate(ranking):
                print(
                    f"{i + 1:<4} "
                    f"{row['factor']:<20} "
                    f"{row.get('mean_ic', 0):>10.4f} "
                    f"{row.get('ir', 0):>8.2f} "
                    f"{row.get('positive_rate', 0):>10.1%} "
                    f"{row.get('ls_return', 0):>12.2%} "
                    f"{row.get('alpha', 0):>10.2%} "
                    f"{row.get('beta', 0):>8.4f}"
                )

            print(f"\n最优因子: {summary.get('top_factor', 'N/A')}")
            print(f"最差因子: {summary.get('bottom_factor', 'N/A')}")

        # 各因子详情
        for fname, result in report.get("factors", {}).items():
            info = result.get("factor_info", {})
            print(f"\n{'─' * 80}")
            print(f"因子: {fname} — {info.get('description', '')}")
            print(f"类型: {info.get('factor_type', '')} / {info.get('category', '')}")

            ic_sum = result.get("ic", {}).get("summary", {})
            if ic_sum:
                print(f"\n  IC 分析（窗口={20}天）:")
                print(f"    IC均值={ic_sum.get('mean_ic', 0):.4f}, IR={ic_sum.get('ir', 0):.2f}, "
                      f"胜率={ic_sum.get('positive_rate', 0):.1%}")

            ic_decay = result.get("ic", {}).get("decay", {})
            if ic_decay:
                print(f"  IC 衰减:")
                for period, v in ic_decay.items():
                    ic_val = v.get("ic", 0)
                    print(f"    {period}天持有: IC={ic_val:.4f}" if ic_val else f"    {period}天持有: N/A")

            bt_1d = result.get("quantile_backtest", {}).get(1, {})
            if bt_1d:
                print(f"\n  分层回测（持有1天）:")
                for q, ret in bt_1d.get("mean_return", {}).items():
                    print(f"    {q}: {ret:.3f}%")
                ls = bt_1d.get("long_short_return")
                if ls is not None:
                    print(f"    多空(Q5-Q1): {ls:.2%}")

            ab = result.get("alpha_beta")
            if ab:
                print(f"\n  Alpha/Beta 分解:")
                print(f"    Jensen's Alpha(年化): {ab.get('alpha', 0):.2%}")
                print(f"    Beta: {ab.get('beta', 0):.4f}")
                print(f"    R²: {ab.get('r_squared', 0):.4f}")
                print(f"    因子年化收益: {ab.get('annual_factor_return', 0):.2%}")
                print(f"    市场年化收益: {ab.get('annual_market_return', 0):.2%}")
                print(f"    市场贡献(Beta×市场): {ab.get('market_contribution', 0):.2%}")
                print(f"    超额收益(Alpha): {ab.get('active_contribution', 0):.2%}")

        print("\n" + "=" * 80)
