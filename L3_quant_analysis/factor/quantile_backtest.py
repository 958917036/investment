# -*- coding: utf-8 -*-
"""
分层回测器 — 按因子值分 N 组回测

功能：
- 按因子值分 5 组（Q1 ~ Q5）
- 计算各组累计收益曲线
- 多空组合收益（Q5 - Q1）
- 分组换手率统计
- 因子有效性报告
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("factor.quantile")


class QuantileBacktester:
    """
    分层回测器

    使用方式：
        bt = QuantileBacktester(quantiles=5)
        result = bt.run(factor_df, returns_df, forward_period=1)
        print(f"Q5-Q1 多空收益: {result['long_short_return']:.2%}")
        bt.print_summary(result)
    """

    def __init__(self, quantiles: int = 5):
        self.quantiles = quantiles

    def run(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        forward_period: int = 1,
        long_short: bool = True,
    ) -> Dict:
        """
        运行分层回测

        Args:
            factor_df: 因子值，index=日期，columns=股票代码
            returns_df: 收益率，index=日期，columns=股票代码
            forward_period: 持有期（天）
            long_short: 是否计算多空组合

        Returns:
            dict: {
                "quantile_returns": DataFrame,   # 各分位每日收益
                "cumulative_returns": DataFrame,  # 各分位累计收益
                "long_short_return": float,       # 多空收益（Q5-Q1）
                "turnover": DataFrame,           # 换手率
                "win_rate": dict,                # 各分位胜率
                "mean_return": dict,             # 各分位平均收益
            }
        """
        common_dates = sorted(factor_df.index.intersection(returns_df.index).tolist())
        if len(common_dates) < forward_period + 1:
            raise ValueError(f"日期不足: {len(common_dates)} < {forward_period + 1}")

        quantile_returns = {}
        turnover_records = []
        period_returns_by_quantile = {q: [] for q in range(1, self.quantiles + 1)}
        positions_by_quantile = {q: set() for q in range(1, self.quantiles + 1)}

        for i in range(0, len(common_dates) - forward_period, forward_period):
            f_date = common_dates[i]
            r_date_idx = min(i + forward_period, len(common_dates) - 1)
            r_date = common_dates[r_date_idx]

            # 获取当日因子值和未来收益
            f_row = factor_df.loc[f_date]
            r_row = returns_df.loc[r_date]

            # 过滤有效数据
            valid = f_row.notna() & r_row.notna()
            f_valid = f_row[valid]
            r_valid = r_row[valid]

            if len(f_valid) < self.quantiles * 2:
                continue

            # 分组
            try:
                q_labels = pd.qcut(f_valid, q=self.quantiles, labels=False, duplicates="drop") + 1
            except ValueError:
                # 因子值全部相同
                continue

            # 计算各组分桶收益
            for q in range(1, self.quantiles + 1):
                q_mask = q_labels == q
                q_codes = set(f_valid[q_mask].index)
                q_returns = r_valid[q_mask]

                if len(q_returns) > 0:
                    period_returns_by_quantile[q].append(q_returns.mean())

                # 换手率 = 新进股票比例
                new_positions = q_codes - positions_by_quantile[q]
                old_positions = positions_by_quantile[q] - q_codes
                total_positions = len(positions_by_quantile[q] | q_codes)
                turnover = len(new_positions | old_positions) / total_positions if total_positions > 0 else 0
                turnover_records.append({"date": r_date, f"Q{q}_turnover": turnover})

                positions_by_quantile[q] = q_codes

        # 构建收益DataFrame
        ret_data = {}
        for q in range(1, self.quantiles + 1):
            if period_returns_by_quantile[q]:
                dates = common_dates[forward_period::forward_period][:len(period_returns_by_quantile[q])]
                ret_data[f"Q{q}"] = pd.Series(period_returns_by_quantile[q][:len(dates)], index=dates)

        quantile_returns = pd.DataFrame(ret_data)

        # 累计收益
        cumulative_returns = (1 + quantile_returns / 100).cumprod() - 1

        # 多空收益
        long_short_return = None
        if long_short and "Q1" in quantile_returns and f"Q{self.quantiles}" in quantile_returns:
            ls_returns = quantile_returns[f"Q{self.quantiles}"] - quantile_returns["Q1"]
            long_short_return = round(float((1 + ls_returns / 100).prod() - 1), 6)

        # 换手率
        turnover_df = pd.DataFrame(turnover_records).set_index("date") if turnover_records else pd.DataFrame()
        avg_turnover = {f"Q{q}": round(float(turnover_df[f"Q{q}_turnover"].mean()), 4) if not turnover_df.empty else 0 for q in range(1, self.quantiles + 1)}

        # 胜率
        win_rate = {
            f"Q{q}": round(float(np.mean(np.array(period_returns_by_quantile[q]) > 0)), 4) if period_returns_by_quantile[q] else 0
            for q in range(1, self.quantiles + 1)
        }

        # 平均收益
        mean_return = {
            f"Q{q}": round(float(np.mean(period_returns_by_quantile[q])), 4) if period_returns_by_quantile[q] else 0
            for q in range(1, self.quantiles + 1)
        }

        result = {
            "quantile_returns": quantile_returns,
            "cumulative_returns": cumulative_returns * 100,  # 转为百分比
            "long_short_return": long_short_return,
            "turnover": turnover_df,
            "avg_turnover": avg_turnover,
            "win_rate": win_rate,
            "mean_return": mean_return,
            "period_days": forward_period,
            "total_periods": len(quantile_returns),
        }

        logger.info(f"分层回测完成: {result['total_periods']} 个周期, Q5-Q1收益={long_short_return}")
        return result

    def print_summary(self, result: Dict) -> None:
        """打印分层回测摘要"""
        print("\n" + "=" * 60)
        print(f"分层回测结果（持有期: {result['period_days']}天, 共{result['total_periods']}个周期）")
        print("=" * 60)

        print("\n各分组平均收益 (%):")
        for q, ret in result["mean_return"].items():
            win = result["win_rate"][q]
            print(f"  {q}: {ret:>7.3f}%  胜率={win:.1%}")

        if result["long_short_return"] is not None:
            print(f"\n多空组合 (Q5-Q1): {result['long_short_return']:>8.2%}")

        print("\n各分组平均换手率:")
        for q, to in result["avg_turnover"].items():
            print(f"  {q}: {to:.1%}")

        print("=" * 60)

    def top_stocks(
        self,
        factor_df: pd.DataFrame,
        date: str,
        top_n: int = 10,
        direction: str = "long"
    ) -> List[Tuple[str, float]]:
        """
        获取指定日期因子排名靠前的股票

        Args:
            factor_df: 因子值
            date: 日期
            top_n: 数量
            direction: "long"（最高因子值）或 "short"（最低因子值）

        Returns:
            [(code, factor_value), ...]
        """
        if date not in factor_df.index:
            return []

        row = factor_df.loc[date].dropna().sort_values(ascending=(direction == "short"))
        return [(code, float(val)) for code, val in row.head(top_n).items()]
