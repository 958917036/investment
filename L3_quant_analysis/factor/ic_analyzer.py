# -*- coding: utf-8 -*-
"""
IC 分析器 — 信息系数分析

功能：
- 计算因子 IC（Spearman / Pearson）
- 滚动 IC 序列
- IC 衰减分析（不同持有期）
- IC 分位数分布
"""

import logging
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr

logger = logging.getLogger("factor.ic")


class ICAnalyzer:
    """
    IC 分析器

    使用方式：
        analyzer = ICAnalyzer()
        ic_result = analyzer.compute_IC(factor_series, returns_series)
        print(f"IC均值: {ic_result['mean_ic']:.4f}, IR: {ic_result['ir']:.2f}")

        # 滚动IC
        rolling_ic = analyzer.rolling_IC(factor_df, returns_df, window=20)

        # IC衰减
        ic_decay = analyzer.IC_decay(factor_df, returns_df, periods=[1, 5, 10, 20])
    """

    def compute_IC(
        self,
        factor: pd.Series,
        returns: pd.Series,
        method: Literal["spearman", "pearson"] = "spearman"
    ) -> Dict:
        """
        计算单期 IC

        Args:
            factor: 因子值序列
            returns: 收益率序列
            method: IC 计算方法，"spearman" 或 "pearson"

        Returns:
            dict: {
                "ic": float,          # IC 值
                "p_value": float,     # p 值
                "n": int,             # 样本数量
                "method": str,        # 计算方法
            }
        """
        # 对齐索引
        valid_idx = factor.notna() & returns.notna() & factor.index.isin(returns.index)
        f = factor[valid_idx]
        r = returns[valid_idx]

        if len(f) < 10:
            logger.warning(f"样本不足: {len(f)} < 10")
            return {"ic": np.nan, "p_value": np.nan, "n": len(f), "method": method}

        if method == "spearman":
            ic, p_value = spearmanr(f, r)
        else:
            ic, p_value = pearsonr(f, r)

        return {
            "ic": round(float(ic), 6) if not np.isnan(ic) else np.nan,
            "p_value": round(float(p_value), 6) if not np.isnan(p_value) else np.nan,
            "n": int(len(f)),
            "method": method,
        }

    def rolling_IC(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        window: int = 20,
        method: Literal["spearman", "pearson"] = "spearman"
    ) -> pd.DataFrame:
        """
        计算滚动 IC 序列

        Args:
            factor_df: DataFrame，index=日期，columns=股票代码，values=因子值
            returns_df: DataFrame，index=日期，columns=股票代码，values=收益率
            window: 滚动窗口大小（天数）
            method: IC 计算方法

        Returns:
            DataFrame: index=日期，columns=[ic, p_value, n]
        """
        # 找到共同的日期
        common_dates = factor_df.index.intersection(returns_df.index)
        if len(common_dates) < window + 1:
            logger.warning(f"共同日期不足: {len(common_dates)} < {window + 1}")
            return pd.DataFrame()

        results = []
        for i in range(window, len(common_dates)):
            date = common_dates[i]
            hist_dates = common_dates[i - window:i]

            # 取窗口内的因子和收益
            f = factor_df.loc[hist_dates].stack()
            r = returns_df.loc[hist_dates].stack()

            ic_result = self.compute_IC(f, r, method)
            results.append({
                "date": date,
                "ic": ic_result["ic"],
                "p_value": ic_result["p_value"],
                "n": ic_result["n"],
            })

        df = pd.DataFrame(results).set_index("date")
        logger.info(f"滚动IC计算完成: {len(df)} 个观测, 平均IC={df['ic'].mean():.4f}")
        return df

    def IC_decay(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        periods: List[int] = [1, 5, 10, 20],
        method: Literal["spearman", "pearson"] = "spearman"
    ) -> Dict[int, Dict]:
        """
        计算不同持有期的 IC（IC 衰减分析）

        Args:
            factor_df: 因子值，index=日期，columns=股票代码
            returns_df: 收益率，index=日期，columns=股票代码
            periods: 持有期列表
            method: IC 计算方法

        Returns:
            dict: {period: {"ic": float, "ir": float, "positive_rate": float}}
        """
        common_dates = factor_df.index.intersection(returns_df.index)
        result = {}

        for period in periods:
            ic_list = []
            for i in range(0, len(common_dates) - period, period):
                f = factor_df.loc[common_dates[i]].stack()
                r = returns_df.loc[common_dates[i + period]].stack()

                ic_val = self.compute_IC(f, r, method)["ic"]
                if not np.isnan(ic_val):
                    ic_list.append(ic_val)

            if ic_list:
                ic_arr = np.array(ic_list)
                result[period] = {
                    "ic": round(float(np.mean(ic_arr)), 6),
                    "ir": round(float(np.mean(ic_arr) / np.std(ic_arr)), 4) if np.std(ic_arr) > 0 else 0.0,
                    "positive_rate": round(float(np.mean(ic_arr > 0)), 4),
                    "count": len(ic_arr),
                }
            else:
                result[period] = {"ic": np.nan, "ir": np.nan, "positive_rate": np.nan, "count": 0}

        logger.info(f"IC衰减分析完成: {result}")
        return result

    def IC_summary(
        self,
        rolling_ic: pd.DataFrame
    ) -> Dict:
        """
        对滚动 IC 序列进行汇总统计

        Args:
            rolling_ic: rolling_IC() 返回的 DataFrame

        Returns:
            dict: IC 统计摘要
        """
        if rolling_ic.empty:
            return {}

        ic = rolling_ic["ic"].dropna()

        return {
            "mean_ic": round(float(ic.mean()), 6),
            "std_ic": round(float(ic.std()), 6),
            "ir": round(float(ic.mean() / ic.std()), 4) if ic.std() > 0 else np.nan,
            "positive_rate": round(float(np.mean(ic > 0)), 4),
            "min_ic": round(float(ic.min()), 6),
            "max_ic": round(float(ic.max()), 6),
            "count": int(len(ic)),
        }

    def IC_quantile_analysis(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        quantiles: int = 5,
        period: int = 1,
        method: Literal["spearman", "pearson"] = "spearman"
    ) -> pd.DataFrame:
        """
        按因子分位数计算各组 IC

        Args:
            factor_df: 因子值
            returns_df: 收益率
            quantiles: 分组数量
            period: 持有期（天）
            method: IC 方法

        Returns:
            DataFrame: index=日期，columns=[Q1_ic, Q2_ic, ..., QN_ic, IC_spread]
        """
        common_dates = factor_df.index.intersection(returns_df.index)
        results = []

        for i in range(0, len(common_dates) - period, period):
            f_date = common_dates[i]
            r_date = common_dates[i + period] if i + period < len(common_dates) else common_dates[-1]

            f_row = factor_df.loc[f_date]
            r_row = returns_df.loc[r_date]

            # 计算分位数边界
            try:
                q_bounds = f_row.quantile([j / quantiles for j in range(1, quantiles)]).values
            except:
                continue

            ic_by_quantile = {}
            prev_bound = -np.inf
            for q_idx, bound in enumerate(q_bounds):
                mask = (f_row > prev_bound) & (f_row <= bound)
                if mask.sum() < 5:
                    prev_bound = bound
                    continue

                f_q = f_row[mask]
                r_q = r_row[mask]
                ic_result = self.compute_IC(f_q, r_q, method)
                ic_by_quantile[f"Q{q_idx + 1}"] = ic_result["ic"]
                prev_bound = bound

            # 最后一组
            mask = f_row > prev_bound
            if mask.sum() >= 5:
                f_q = f_row[mask]
                r_q = r_row[mask]
                ic_result = self.compute_IC(f_q, r_q, method)
                ic_by_quantile[f"Q{quantiles}"] = ic_result["ic"]

            if ic_by_quantile:
                ic_by_quantile["IC_spread"] = ic_by_quantile.get(f"Q{quantiles}", 0) - ic_by_quantile.get("Q1", 0)
                ic_by_quantile["date"] = f_date
                results.append(ic_by_quantile)

        df = pd.DataFrame(results).set_index("date") if results else pd.DataFrame()
        return df
