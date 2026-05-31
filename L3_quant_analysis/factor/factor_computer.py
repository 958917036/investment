"""
因子计算引擎 — 为 18 个预置因子提供实际计算实现。

每个方法接收 stock_codes + 日期范围，返回 pd.DataFrame
(index=日期, columns=股票代码)。

数据来源：BaoStock（日线+财务）、AkShare（财务）
"""

from __future__ import annotations

import baostock as bs
import pandas as pd
import numpy as np
from typing import List, Optional
from datetime import datetime, timedelta


class FactorComputer:
    """统一因子计算器，支持 18 个预置因子。"""

    def __init__(self):
        self._lg = None
        self._login()

    def _login(self):
        if self._lg is None or not self._lg.login():
            self._lg = bs.login()

    def _logout(self):
        if self._lg is not None:
            bs.logout()
            self._lg = None

    def __del__(self):
        self._logout()

    def __enter__(self):
        self._login()
        return self

    def __exit__(self, *args):
        self._logout()

    # --------------------------------------------------------------------------
    # 价值因子
    # --------------------------------------------------------------------------

    def compute_pe_ttm(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        PE-TTM = 市盈率TTM（滚动12个月净利润法）。
        数据源：BaoStock 利润表（net_profit） + 日线（收盘价）。
        返回：pd.DataFrame (index=日期, columns=code)
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                # 日线
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                prices = klines["close"]

                # 财务数据（季度，TTM）
                financials = self._fetch_financials_ttm(bs_code, end_date)
                if financials is None or financials.empty:
                    continue

                # 每股净利 TTM
                net_profit_ttm = financials["net_profit_ttm"]
                shares = financials["shares"]

                # PE-TTM = price / (net_profit_ttm / shares)
                pe = prices / (net_profit_ttm.reindex(prices.index, method="ffill") / shares)
                results[code] = pe.dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_pb(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        PB = 市净率。
        数据源：BaoStock 资产负债表（每股净资产） + 日线（收盘价）。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                prices = klines["close"]

                financials = self._fetch_balance_sheet(bs_code, end_date)
                if financials is None or financials.empty:
                    continue

                bvps = financials["bvps"]  # 每股净资产
                pb = prices / bvps.reindex(prices.index, method="ffill")
                results[code] = pb.dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_ps_ttm(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        PS-TTM = 市销率TTM。
        数据源：BaoStock 利润表（营业收入TTM） + 日线（收盘价）。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                prices = klines["close"]

                financials = self._fetch_financials_ttm(bs_code, end_date)
                if financials is None:
                    continue

                revenue_per_share = financials.get("revenue_per_share")
                if revenue_per_share is None or revenue_per_share.empty:
                    continue

                ps = prices / revenue_per_share.reindex(prices.index, method="ffill")
                results[code] = ps.dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_pcf(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        PCF = 市现率 = price / cash_flow_per_share。
        数据源：BaoStock 现金流量表（经营现金流TTM） + 日线。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                prices = klines["close"]

                financials = self._fetch_cashflow_ttm(bs_code, end_date)
                if financials is None:
                    continue

                cfps = financials.get("cfps")
                if cfps is None or cfps.empty:
                    continue

                pcf = prices / cfps.reindex(prices.index, method="ffill")
                results[code] = pcf.dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    # --------------------------------------------------------------------------
    # 成长因子
    # --------------------------------------------------------------------------

    def compute_revenue_growth(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        营收增速 = (本期营收 - 上年同期营收) / |上年同期营收|。
        数据源：BaoStock 利润表。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                rs = bs.query_growth_data(bs_code, start_date.replace("-", ""), end_date.replace("-", ""))
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    continue
                df = pd.DataFrame(rows, columns=rs.fields)
                df["date"] = pd.to_datetime(df["statDate"])
                df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
                df = df.dropna(subset=["revenue"]).sort_values("date")

                if len(df) < 2:
                    continue

                df["revenue_growth"] = df["revenue"].pct_change(4)  # 同比（季度）
                df = df.set_index("date").reindex(
                    pd.date_range(start_date, end_date, freq="D"), method="ffill"
                )
                results[code] = df["revenue_growth"].dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_net_profit_growth(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        净利润增速。
        数据源：BaoStock 利润表。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                rs = bs.query_profit_data(bs_code, start_date.replace("-", ""), end_date.replace("-", ""))
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    continue
                df = pd.DataFrame(rows, columns=rs.fields)
                df["date"] = pd.to_datetime(df["statDate"])
                df["net_profit"] = pd.to_numeric(df["netProfit"], errors="coerce")
                df = df.dropna(subset=["net_profit"]).sort_values("date")

                if len(df) < 2:
                    continue

                df["growth"] = df["net_profit"].pct_change(4)
                df = df.set_index("date").reindex(
                    pd.date_range(start_date, end_date, freq="D"), method="ffill"
                )
                results[code] = df["growth"].dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_eps_growth(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        EPS 增速。
        数据源：BaoStock 盈利能力数据。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                rs = bs.query_profit_data(bs_code, start_date.replace("-", ""), end_date.replace("-", ""))
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    continue
                df = pd.DataFrame(rows, columns=rs.fields)
                df["date"] = pd.to_datetime(df["statDate"])
                df["eps"] = pd.to_numeric(df["eps"], errors="coerce")
                df = df.dropna(subset=["eps"]).sort_values("date")

                if len(df) < 2:
                    continue

                df["eps_growth"] = df["eps"].pct_change(4)
                df = df.set_index("date").reindex(
                    pd.date_range(start_date, end_date, freq="D"), method="ffill"
                )
                results[code] = df["eps_growth"].dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    # --------------------------------------------------------------------------
    # 质量因子
    # --------------------------------------------------------------------------

    def compute_roe(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        ROE = 净资产收益率 = 净利润 / 净资产。
        数据源：BaoStock 杜邦分析。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                rs = bs.query_duanalysis(bs_code, start_date.replace("-", ""), end_date.replace("-", ""))
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    continue
                df = pd.DataFrame(rows, columns=rs.fields)
                df["date"] = pd.to_datetime(df["statDate"])
                df["roe"] = pd.to_numeric(df["roe"], errors="coerce")  # BaoStock 直接返回 ROE%
                df = df.dropna(subset=["roe"]).sort_values("date")

                df = df.set_index("date").reindex(
                    pd.date_range(start_date, end_date, freq="D"), method="ffill"
                )
                results[code] = df["roe"].dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_gross_margin(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        毛利率 = (营收 - 营业成本) / 营收。
        数据源：BaoStock 利润表。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                rs = bs.query_income_data(
                    bs_code, start_date.replace("-", ""), end_date.replace("-", "")
                )
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    continue
                df = pd.DataFrame(rows, columns=rs.fields)
                df["date"] = pd.to_datetime(df["statDate"])
                df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
                df["op_cost"] = pd.to_numeric(df["opCost"], errors="coerce")
                df = df.dropna(subset=["revenue", "op_cost"]).sort_values("date")

                if len(df) < 1:
                    continue

                df["gross_margin"] = (df["revenue"] - df["op_cost"]) / df["revenue"] * 100
                df = df.set_index("date").reindex(
                    pd.date_range(start_date, end_date, freq="D"), method="ffill"
                )
                results[code] = df["gross_margin"].dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_net_margin(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        净利率 = 净利润 / 营收。
        数据源：BaoStock 利润表。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                rs = bs.query_income_data(
                    bs_code, start_date.replace("-", ""), end_date.replace("-", "")
                )
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    continue
                df = pd.DataFrame(rows, columns=rs.fields)
                df["date"] = pd.to_datetime(df["statDate"])
                df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
                df["net_profit"] = pd.to_numeric(df["netProfit"], errors="coerce")
                df = df.dropna(subset=["revenue", "net_profit"]).sort_values("date")

                if len(df) < 1:
                    continue

                df["net_margin"] = df["net_profit"] / df["revenue"] * 100
                df = df.set_index("date").reindex(
                    pd.date_range(start_date, end_date, freq="D"), method="ffill"
                )
                results[code] = df["net_margin"].dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_asset_turnover(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        资产周转率 = 营收 / 总资产。
        数据源：BaoStock 资产负债表 + 利润表。
        """
        self._login()
        results = {}

        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                # 营收
                rs_inc = bs.query_income_data(
                    bs_code, start_date.replace("-", ""), end_date.replace("-", "")
                )
                rows_inc = []
                while rs_inc.next():
                    rows_inc.append(rs_inc.get_row_data())
                if not rows_inc:
                    continue
                df_inc = pd.DataFrame(rows_inc, columns=rs_inc.fields)
                df_inc["date"] = pd.to_datetime(df_inc["statDate"])
                df_inc["revenue"] = pd.to_numeric(df_inc["revenue"], errors="coerce")

                # 总资产
                rs_bs = bs.query_balance_data(
                    bs_code, start_date.replace("-", ""), end_date.replace("-", "")
                )
                rows_bs = []
                while rs_bs.next():
                    rows_bs.append(rs_bs.get_row_data())
                if not rows_bs:
                    continue
                df_bs = pd.DataFrame(rows_bs, columns=rs_bs.fields)
                df_bs["date"] = pd.to_datetime(df_bs["statDate"])
                df_bs["total_assets"] = pd.to_numeric(df_bs["totalAssets"], errors="coerce")

                df = pd.merge(df_inc[["date", "revenue"]], df_bs[["date", "total_assets"]], on="date", how="inner")
                df = df.dropna().sort_values("date")

                if len(df) < 1:
                    continue

                df["asset_turnover"] = df["revenue"] / df["total_assets"]
                df = df.set_index("date").reindex(
                    pd.date_range(start_date, end_date, freq="D"), method="ffill"
                )
                results[code] = df["asset_turnover"].dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    # --------------------------------------------------------------------------
    # 动量因子
    # --------------------------------------------------------------------------

    def _klines_to_returns(self, klines: pd.DataFrame) -> pd.Series:
        """从日线 DataFrame 计算日收益率。"""
        closes = klines["close"].astype(float)
        return closes.pct_change()

    def compute_ret_20d(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """20日累计收益率。"""
        self._login()
        results = {}
        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                ret = self._klines_to_returns(klines)
                ret_20d = ret.rolling(20).sum()
                results[code] = ret_20d.dropna()
            except Exception:
                continue
        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_ret_60d(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """60日累计收益率。"""
        self._login()
        results = {}
        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                ret = self._klines_to_returns(klines)
                ret_60d = ret.rolling(60).sum()
                results[code] = ret_60d.dropna()
            except Exception:
                continue
        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_ret_120d(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """120日累计收益率。"""
        self._login()
        results = {}
        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                ret = self._klines_to_returns(klines)
                ret_120d = ret.rolling(120).sum()
                results[code] = ret_120d.dropna()
            except Exception:
                continue
        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    # --------------------------------------------------------------------------
    # 资金流因子
    # --------------------------------------------------------------------------

    def compute_main_net_flow_5d(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        5日主力净流入（万元）。
        数据源：BaoStock 资金流向。
        """
        self._login()
        results = {}
        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                rs = bs.query_money_flow_data(
                    bs_code, start_date.replace("-", ""), end_date.replace("-", "")
                )
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if not rows:
                    continue
                df = pd.DataFrame(rows, columns=rs.fields)
                df["date"] = pd.to_datetime(df["date"])
                df["main_net_flow"] = pd.to_numeric(df["mainNetProjFlow"], errors="coerce")
                df = df.dropna(subset=["main_net_flow"]).sort_values("date")

                if len(df) < 5:
                    continue

                df = df.set_index("date")
                # 5日累计
                main_5d = df["main_net_flow"].rolling(5).sum()
                # 前向填充到每日
                full_idx = pd.date_range(start_date, end_date, freq="D")
                main_5d = main_5d.reindex(full_idx, method="ffill")
                results[code] = main_5d.dropna()
            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    # --------------------------------------------------------------------------
    # 技术因子
    # --------------------------------------------------------------------------

    def compute_rsi_14(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        RSI-14。
        数据源：BaoStock 日线。
        """
        self._login()
        results = {}
        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                closes = klines["close"].astype(float)
                delta = closes.diff()
                gain = delta.clip(lower=0)
                loss = (-delta).clip(lower=0)
                avg_gain = gain.rolling(14).mean()
                avg_loss = loss.rolling(14).mean()
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                results[code] = rsi.dropna()
            except Exception:
                continue
        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_macd_signal(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        MACD Signal Line (DIF 的 9 日指数移动平均线)。
        数据源：BaoStock 日线。
        """
        self._login()
        results = {}
        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                closes = klines["close"].astype(float)

                ema_12 = closes.ewm(span=12, adjust=False).mean()
                ema_26 = closes.ewm(span=26, adjust=False).mean()
                dif = ema_12 - ema_26
                macd_signal = dif.ewm(span=9, adjust=False).mean()

                results[code] = macd_signal.dropna()
            except Exception:
                continue
        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    # --------------------------------------------------------------------------
    # 波动率因子
    # --------------------------------------------------------------------------

    def compute_vol_20d(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        20日年化波动率 = std(ret_20d) × √252。
        数据源：BaoStock 日线。
        """
        self._login()
        results = {}
        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue
                closes = klines["close"].astype(float)
                ret = closes.pct_change()
                vol_20d = ret.rolling(20).std() * np.sqrt(252)
                results[code] = vol_20d.dropna()
            except Exception:
                continue
        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    def compute_kdj(
        self, stock_codes: List[str], start_date: str, end_date: str,
        n: int = 9, m1: int = 3, m2: int = 3
    ) -> pd.DataFrame:
        """
        KDJ 随机指标（RSV → K → D → J）。

        计算方法：
            RSV(n) = (Close - Low_n) / (High_n - Low_n) × 100
            K = (m1-1)/m1 × K_prev + 1/m1 × RSV
            D = (m2-1)/m2 × D_prev + 1/m2 × K
            J = 3×K - 2×D

        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            n: RSV 窗口（默认9）
            m1: K 平滑因子（默认3）
            m2: D 平滑因子（默认3）

        Returns:
            DataFrame (index=日期, columns=code)，含 K、D、J 三行
        """
        self._login()
        results = {}
        for code in stock_codes:
            try:
                bs_code = self._to_bs_code(code)
                klines = self._fetch_klines(bs_code, start_date, end_date)
                if klines is None or klines.empty:
                    continue

                high = klines["high"].astype(float)
                low = klines["low"].astype(float)
                close = klines["close"].astype(float)

                # RSV
                lowest_low = low.rolling(n).min()
                highest_high = high.rolling(n).max()
                rsv = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-9)

                # K, D, J
                k = pd.Series(index=rsv.index, dtype=float)
                d = pd.Series(index=rsv.index, dtype=float)

                k.iloc[n-1] = 50.0
                d.iloc[n-1] = 50.0

                for i in range(n, len(rsv)):
                    k.iloc[i] = (m1 - 1) / m1 * k.iloc[i - 1] + rsv.iloc[i] / m1
                    d.iloc[i] = (m2 - 1) / m2 * d.iloc[i - 1] + k.iloc[i] / m2

                j = 3 * k - 2 * d

                df = pd.DataFrame({"K": k, "D": d, "J": j})
                for col in df.columns:
                    results.setdefault(code, pd.DataFrame(index=df.index))
                    results[code][col] = df[col]

            except Exception:
                continue

        self._logout()
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(results).dropna(how="all")

    # --------------------------------------------------------------------------
    # 内部工具方法
    # --------------------------------------------------------------------------

    def _to_bs_code(self, code: str) -> str:
        """将 600519 → sh.600519，000858 → sz.000858。"""
        code = code.strip()
        if code.startswith(("6", "5")):
            return f"sh.{code}"
        return f"sz.{code}"

    def _fetch_klines(
        self, bs_code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """获取 BaoStock 日线数据。"""
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            frequency="d",
            adjustflag="2",  # 前复权
        )
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"])
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        return df.dropna(subset=["close"]).set_index("date")

    def _fetch_financials_ttm(self, bs_code: str, end_date: str) -> Optional[dict]:
        """获取 TTM 财务数据（净利润、营收、股本）。"""
        rs = bs.query_profit_data(bs_code, start_date="", end_date=end_date.replace("-", ""))
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=rs.fields)
        df["date"] = pd.to_datetime(df["statDate"])
        df["net_profit"] = pd.to_numeric(df["netProfit"], errors="coerce")
        df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
        df = df.dropna().sort_values("date")
        if len(df) < 4:
            return None

        # TTM = 最近4个季度之和
        last_4 = df.tail(4)
        net_profit_ttm = last_4["net_profit"].sum()
        revenue_ttm = last_4["revenue"].sum()

        # 股本（最新一期）
        shares = pd.to_numeric(df.iloc[-1].get("shares", 0), errors="coerce")
        if pd.isna(shares) or shares == 0:
            shares = 1.0

        return {
            "net_profit_ttm": net_profit_ttm,
            "revenue_ttm": revenue_ttm,
            "shares": shares,
            "revenue_per_share": revenue_ttm / shares,
        }

    def _fetch_balance_sheet(self, bs_code: str, end_date: str) -> Optional[dict]:
        """获取最新每股净资产。"""
        rs = bs.query_balance_data(bs_code, start_date="", end_date=end_date.replace("-", ""))
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=rs.fields)
        df["date"] = pd.to_datetime(df["statDate"])
        df["bvps"] = pd.to_numeric(df["bvps"], errors="coerce")
        df = df.dropna(subset=["bvps"]).sort_values("date")
        if df.empty:
            return None
        return {"bvps": df.iloc[-1]["bvps"]}

    def _fetch_cashflow_ttm(self, bs_code: str, end_date: str) -> Optional[dict]:
        """获取经营现金流 TTM。"""
        rs = bs.query_cash_flow_data(bs_code, start_date="", end_date=end_date.replace("-", ""))
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=rs.fields)
        df["date"] = pd.to_datetime(df["statDate"])
        df["op_cash_flow"] = pd.to_numeric(df["opCashFlow"], errors="coerce")
        df = df.dropna(subset=["op_cash_flow"]).sort_values("date")
        if len(df) < 4:
            return None

        last_4 = df.tail(4)
        cfps = last_4["op_cash_flow"].sum()
        shares = pd.to_numeric(df.iloc[-1].get("shares", 1), errors="coerce")
        if pd.isna(shares) or shares == 0:
            shares = 1.0

        return {"cfps": cfps / shares}
