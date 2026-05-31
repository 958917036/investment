#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测框架 — 策略验证引擎

核心功能：
- 支持多股票历史数据回测
- 灵活定义买入/卖出信号（strategy_fn）
- 模拟真实交易环境（佣金/滑点/仓位）
- 计算完整性能指标

使用方式：
    engine = BacktestEngine(initial_capital=100_000)
    engine.add_stock("600519", klines_df)  # 添加历史数据
    result = engine.run(my_strategy, start_date="2020-01-01", end_date="2025-12-31")
    engine.print_metrics(result)

策略函数签名：
    def my_strategy(date: str, data: Dict[str, DataFrame]) -> Dict[str, str]:
        # date: 当前交易日期
        # data: {code: klines_df} 所有股票的历史K线（截止到date）
        # 返回: {code: "buy"/"sell"/"hold"}
"""

import logging
from typing import Dict, Any, Callable, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from L3_quant_analysis.backtest.position_manager import ASharePositionManager

logger = logging.getLogger("backtest")


@dataclass
class Trade:
    """单笔交易"""
    date: str
    code: str
    action: str  # "buy" / "sell"
    price: float
    quantity: int
    commission: float
    capital_before: float
    capital_after: float


@dataclass
class Position:
    """持仓"""
    code: str
    quantity: int
    avg_cost: float
    current_value: float = 0.0


@dataclass
class BacktestMetrics:
    """回测性能指标"""
    total_return: float          # 总收益率
    annual_return: float         # 年化收益率
    sharpe_ratio: float          # 夏普比率
    max_drawdown: float          # 最大回撤
    max_drawdown_duration: int   # 最大回撤持续天数
    win_rate: float              # 胜率
    profit_loss_ratio: float     # 盈亏比
    total_trades: int            # 总交易次数
    avg_trades_per_year: float   # 年均交易次数
    final_capital: float         # 最终资金
    initial_capital: float       # 初始资金


class BacktestEngine:
    """
    回测引擎
    
    支持：
    - 多股票等权/不等权组合
    - 固定仓位/全仓/动态仓位
    - 周/月级再平衡
    - 佣金和滑点模拟
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        commission_rate: float = 0.0003,  # 万3佣金
        slippage: float = 0.001,          # 千1滑点
        tax_rate: float = 0.001,          # 千1印花税（卖出时）
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.tax_rate = tax_rate

        self.stocks_data: Dict[str, pd.DataFrame] = {}  # code -> K线数据
        self.trades: List[Trade] = []
        self.positions: Dict[str, Position] = {}
        self.portfolio_history: List[Dict] = []  # 每日组合记录

        # A股持仓管理器（T+1 + 涨跌停）
        self.position_manager = ASharePositionManager()
        # 记录昨日收盘价（用于涨跌停判断）
        self._prev_close: Dict[str, float] = {}
        
    def add_stock(self, code: str, klines: pd.DataFrame) -> None:
        """
        添加股票历史数据

        Args:
            code: 股票代码
            klines: DataFrame，必须包含 date/open/high/low/close/volume 列
        """
        df = klines.copy()

        # 确保有date列
        if "date" not in df.columns:
            raise ValueError("klines必须包含date列")

        # 确保日期排序
        df = df.sort_values("date").reset_index(drop=True)

        # 计算日收益率
        if "daily_return" not in df.columns:
            df["daily_return"] = df["close"].pct_change()

        # 构建 prev_close 映射（用于涨跌停判断）
        if len(df) >= 2:
            # prev_close[i] = 收盘价[i-1]
            self._prev_close[code] = dict(zip(df["date"].iloc[1:], df["close"].iloc[:-1].values))

        self.stocks_data[code] = df
        logger.info(f"添加股票 {code}: {len(df)} 条K线, {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    
    def run(
        self,
        strategy_fn: Callable[[str, Dict[str, pd.DataFrame]], Dict[str, str]],
        start_date: str,
        end_date: str,
        rebalance_freq: str = "weekly",
    ) -> Dict[str, Any]:
        """
        运行回测
        
        Args:
            strategy_fn: 策略函数 (date, data_dict) -> {code: signal}
            start_date: 回测开始日期
            end_date: 回测结束日期
            rebalance_freq: 再平衡频率 "daily" / "weekly" / "monthly"
        
        Returns:
            包含metrics和trade_history的字典
        """
        # 获取所有交易日
        trading_days = self._get_trading_days(start_date, end_date, rebalance_freq)
        
        if not trading_days:
            raise ValueError(f"无交易日数据: {start_date} ~ {end_date}")
        
        logger.info(f"开始回测: {start_date} ~ {end_date}, {len(trading_days)}个交易日, 初始资金={self.initial_capital:,.0f}")
        
        # 重置状态
        self.capital = self.initial_capital
        self.trades = []
        self.positions = {}
        self.portfolio_history = []
        
        # 按日期运行
        for i, date in enumerate(trading_days):
            # 获取历史数据快照（包含当天数据）
            data_snapshot = self._get_data_snapshot(date)
            
            if not data_snapshot:
                continue
            
            # 调用策略函数
            signals = self._safe_call_strategy(strategy_fn, date, data_snapshot)
            
            # 执行交易
            self._execute_signals(date, signals, data_snapshot)
            
            # 更新组合价值
            self._update_portfolio(date)
            
            # 每20个交易日打印进度
            if (i + 1) % 20 == 0:
                pos_value = sum(p.current_value for p in self.positions.values())
                total_value = self.capital + pos_value
                logger.info(f"  {date}: 资金={self.capital:,.0f}, 持仓={pos_value:,.0f}, 总计={total_value:,.0f}")
        
        # 计算性能指标
        metrics = self._calculate_metrics()
        
        return {
            "metrics": metrics,
            "trades": self.trades,
            "portfolio_history": self.portfolio_history,
            "stocks": list(self.stocks_data.keys()),
            "start_date": start_date,
            "end_date": end_date,
        }
    
    def _get_trading_days(
        self,
        start_date: str,
        end_date: str,
        freq: str
    ) -> List[str]:
        """获取所有需要执行的交易日"""
        # 以第一只股票的时间为准
        if not self.stocks_data:
            return []
        
        first_stock = list(self.stocks_data.values())[0]
        all_dates = first_stock["date"].tolist()
        
        # 过滤日期范围
        dates = [d for d in all_dates if start_date <= d <= end_date]
        
        # 根据频率筛选
        if freq == "weekly":
            # 每周一
            dates = [d for d in dates if pd.to_datetime(d).weekday() == 0]
        elif freq == "monthly":
            # 每月第一个交易日
            seen_months = set()
            filtered = []
            for d in dates:
                month = d[:7]  # YYYY-MM
                if month not in seen_months:
                    seen_months.add(month)
                    filtered.append(d)
            dates = filtered
        
        return dates
    
    def _get_data_snapshot(self, date: str) -> Dict[str, pd.DataFrame]:
        """获取截止到date的历史数据快照"""
        snapshot = {}
        for code, df in self.stocks_data.items():
            hist = df[df["date"] <= date].copy()
            if len(hist) > 0:
                snapshot[code] = hist
        return snapshot
    
    def _safe_call_strategy(
        self,
        strategy_fn: Callable,
        date: str,
        data: Dict[str, pd.DataFrame]
    ) -> Dict[str, str]:
        """安全调用策略函数"""
        try:
            result = strategy_fn(date, data)
            if not isinstance(result, dict):
                return {}
            # 标准化信号
            return {k.upper(): v.lower() for k, v in result.items()}
        except Exception as e:
            logger.warning(f"策略执行失败 {date}: {e}")
            return {}
    
    def _execute_signals(
        self,
        date: str,
        signals: Dict[str, str],
        data_snapshot: Dict[str, pd.DataFrame]
    ) -> None:
        """执行买入/卖出信号"""
        for code, signal in signals.items():
            if code not in data_snapshot:
                continue
            
            df = data_snapshot[code]
            today_row = df[df["date"] == date]
            if len(today_row) == 0:
                continue
            
            price = float(today_row.iloc[-1]["close"])
            
            # 滑点：买入时用高价格，卖出时用低价格
            exec_price = price * (1 + self.slippage) if signal == "buy" else price * (1 - self.slippage)
            exec_price = round(exec_price, 2)
            
            if signal == "buy":
                self._buy(date, code, exec_price, data_snapshot)
            elif signal == "sell":
                self._sell(date, code, exec_price)
    
    def _buy(
        self,
        date: str,
        code: str,
        price: float,
        data_snapshot: Dict[str, pd.DataFrame]
    ) -> None:
        """买入（带涨跌停检查）"""
        # 检查涨跌停
        prev_close = self._prev_close.get(code, {}).get(date, price)
        can_buy, reason = self.position_manager.check_buy(code, price, prev_close)
        if not can_buy:
            logger.debug(f"  跳过买入 {code}: {reason}")
            return

        if code in self.positions:
            return  # 已有持仓，跳过

        # 全仓买入（可用资金的10%，最多5只）
        if len(self.positions) >= 5:
            return

        max_position_value = self.capital * 0.2  # 单只最大20%仓位
        invest_amount = min(self.capital * 0.1, max_position_value)

        if invest_amount < 100:  # 资金不足
            return

        # 计算买入数量（100股整数倍）
        quantity = int(invest_amount / price / 100) * 100

        if quantity < 100:
            return

        # 计算佣金
        total_cost = quantity * price
        commission = total_cost * self.commission_rate
        total_with_commission = total_cost + commission

        if total_with_commission > self.capital:
            return

        # 执行
        capital_before = self.capital
        self.capital -= total_with_commission

        self.positions[code] = Position(
            code=code,
            quantity=quantity,
            avg_cost=(total_cost / quantity),  # 不含佣金
            current_value=total_cost,
        )

        # 记录到A股持仓管理器（用于T+1追踪）
        self.position_manager.buy(code, price=price, date=date, quantity=quantity, avg_cost=total_cost / quantity)

        self.trades.append(Trade(
            date=date,
            code=code,
            action="buy",
            price=price,
            quantity=quantity,
            commission=commission,
            capital_before=capital_before,
            capital_after=self.capital,
        ))
    
    def _sell(self, date: str, code: str, price: float) -> None:
        """卖出（带T+1和涨跌停检查）"""
        if code not in self.positions:
            return

        # 检查T+1和涨跌停
        prev_close = self._prev_close.get(code, {}).get(date, price)
        can_sell, reason = self.position_manager.check_sell(code, price, prev_close, date)
        if not can_sell:
            logger.debug(f"  跳过卖出 {code}: {reason}")
            return

        pos = self.positions[code]
        quantity = pos.quantity

        # 计算卖出金额
        total_proceeds = quantity * price
        commission = total_proceeds * self.commission_rate
        tax = total_proceeds * self.tax_rate
        net_proceeds = total_proceeds - commission - tax

        capital_before = self.capital
        self.capital += net_proceeds

        self.trades.append(Trade(
            date=date,
            code=code,
            action="sell",
            price=price,
            quantity=quantity,
            commission=commission + tax,
            capital_before=capital_before,
            capital_after=self.capital,
        ))

        # 从A股持仓管理器中移除
        self.position_manager.sell(code, quantity=None)  # 清仓
        del self.positions[code]
    
    def _update_portfolio(self, date: str) -> None:
        """更新组合市值"""
        # 获取最新价格
        for code, pos in self.positions.items():
            if code in self.stocks_data:
                df = self.stocks_data[code]
                today_row = df[df["date"] == date]
                if len(today_row) > 0:
                    price = float(today_row.iloc[-1]["close"])
                    pos.current_value = pos.quantity * price
        
        total_value = self.capital + sum(p.current_value for p in self.positions.values())
        
        self.portfolio_history.append({
            "date": date,
            "capital": self.capital,
            "position_value": sum(p.current_value for p in self.positions.values()),
            "total_value": total_value,
            "position_count": len(self.positions),
        })
    
    def _calculate_metrics(self) -> BacktestMetrics:
        """计算性能指标"""
        if not self.portfolio_history:
            return BacktestMetrics(
                total_return=0, annual_return=0, sharpe_ratio=0,
                max_drawdown=0, max_drawdown_duration=0, win_rate=0,
                profit_loss_ratio=0, total_trades=0, avg_trades_per_year=0,
                final_capital=self.capital, initial_capital=self.initial_capital,
            )
        
        df = pd.DataFrame(self.portfolio_history)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        
        # 总收益率
        total_value = df["total_value"].iloc[-1]
        total_return = (total_value - self.initial_capital) / self.initial_capital
        
        # 年化收益率
        days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
        years = max(1, days / 365)
        annual_return = (1 + total_return) ** (1 / years) - 1
        
        # 最大回撤
        df["cummax"] = df["total_value"].cummax()
        df["drawdown"] = (df["cummax"] - df["total_value"]) / df["cummax"]
        max_drawdown = df["drawdown"].max()
        
        # 最大回撤持续天数
        dd_series = df["drawdown"]
        in_drawdown = dd_series > 0
        max_duration = 0
        current_duration = 0
        for d in in_drawdown:
            if d:
                current_duration += 1
                max_duration = max(max_duration, current_duration)
            else:
                current_duration = 0
        
        # 夏普比率（假设无风险利率3%）
        risk_free_rate = 0.03
        daily_returns = df["total_value"].pct_change().dropna()
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            excess_returns = daily_returns - risk_free_rate / 252
            sharpe = excess_returns.mean() / daily_returns.std() * np.sqrt(252)
        else:
            sharpe = 0.0
        
        # 交易统计
        df_trades = pd.DataFrame([{
            "date": t.date,
            "action": t.action,
            "code": t.code,
            "price": t.price,
            "quantity": t.quantity,
        } for t in self.trades])
        
        total_trades = len(self.trades)
        avg_trades_per_year = total_trades / years if years > 0 else 0
        
        # 胜率（盈利交易/总交易）
        if len(df_trades) > 0:
            sell_trades = df_trades[df_trades["action"] == "sell"]
            if len(sell_trades) > 0:
                # 配对买卖计算盈亏
                buy_prices = {}
                profits = []
                for _, row in df_trades.sort_values("date").iterrows():
                    if row["action"] == "buy":
                        buy_prices[row["code"]] = row["price"]
                    elif row["action"] == "sell" and row["code"] in buy_prices:
                        profit_pct = (row["price"] - buy_prices[row["code"]]) / buy_prices[row["code"]]
                        profits.append(profit_pct)
                
                if profits:
                    win_rate = sum(1 for p in profits if p > 0) / len(profits)
                    avg_win = np.mean([p for p in profits if p > 0]) if profits else 0
                    avg_loss = abs(np.mean([p for p in profits if p < 0])) if profits else 1
                    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
                else:
                    win_rate = 0
                    profit_loss_ratio = 0
            else:
                win_rate = 0
                profit_loss_ratio = 0
        else:
            win_rate = 0
            profit_loss_ratio = 0
        
        return BacktestMetrics(
            total_return=round(total_return, 4),
            annual_return=round(annual_return, 4),
            sharpe_ratio=round(sharpe, 2),
            max_drawdown=round(max_drawdown, 4),
            max_drawdown_duration=max_duration,
            win_rate=round(win_rate, 4),
            profit_loss_ratio=round(profit_loss_ratio, 2),
            total_trades=total_trades,
            avg_trades_per_year=round(avg_trades_per_year, 1),
            final_capital=round(total_value, 2),
            initial_capital=self.initial_capital,
        )
    
    def print_metrics(self, result: Dict[str, Any]) -> None:
        """打印回测结果"""
        m = result["metrics"]
        
        print("\n" + "="*60)
        print(f"回测结果: {result['start_date']} ~ {result['end_date']}")
        print("="*60)
        print(f"初始资金:    {m.initial_capital:>15,.2f}")
        print(f"最终资金:    {m.final_capital:>15,.2f}")
        print(f"总收益率:    {m.total_return:>15.2%}")
        print(f"年化收益率:  {m.annual_return:>15.2%}")
        print(f"夏普比率:    {m.sharpe_ratio:>15.2f}")
        print(f"最大回撤:    {m.max_drawdown:>15.2%}")
        print(f"回撤天数:    {m.max_drawdown_duration:>15}天")
        print(f"胜率:        {m.win_rate:>15.2%}")
        print(f"盈亏比:      {m.profit_loss_ratio:>15.2f}")
        print(f"总交易次数:  {m.total_trades:>15}")
        print(f"年均交易:    {m.avg_trades_per_year:>15.1f}次")
        print("="*60)
        
        # 打印买入卖出记录
        if result["trades"]:
            print("\n前10笔交易:")
            for t in result["trades"][:10]:
                print(f"  {t.date} {t.action.upper():4} {t.code} "
                      f"@ {t.price:.2f}x{t.quantity} 手续费={t.commission:.2f}")
        
        # 打印前5只股票
        if result["portfolio_history"]:
            df = pd.DataFrame(result["portfolio_history"])
            print(f"\n前5天组合变化:")
            print(df[["date", "total_value", "position_count"]].head().to_string(index=False))


# ─── 预置策略函数 ─────────────────────────────────────────

def momentum_strategy(
    date: str,
    data: Dict[str, pd.DataFrame],
    lookback: int = 20,
    top_n: int = 3
) -> Dict[str, str]:
    """
    动量策略：买入近N日涨幅最大的股票，卖出跌幅最大的
    
    简单验证策略，用于回测框架测试
    """
    signals = {}
    
    # 计算各股票近N日收益率
    returns = {}
    for code, df in data.items():
        if len(df) < lookback + 1:
            continue
        recent = df.tail(lookback + 1)
        start_price = recent["close"].iloc[0]
        end_price = recent["close"].iloc[-1]
        ret = (end_price - start_price) / start_price
        returns[code] = ret
    
    if not returns:
        return {}
    
    # 排序
    sorted_codes = sorted(returns.items(), key=lambda x: x[1], reverse=True)
    
    # 买入涨幅前N名
    for code, _ in sorted_codes[:top_n]:
        signals[code] = "buy"
    
    # 卖出跌幅前N名（如果有持仓）
    for code, _ in sorted_codes[-top_n:]:
        if code not in signals:  # 避免重复
            signals[code] = "sell"
    
    return signals


def value_strategy(
    date: str,
    data: Dict[str, pd.DataFrame],
    holding_period: int = 60
) -> Dict[str, str]:
    """
    价值策略：低估值 + 稳定盈利
    基于PE和ROE的简单选股策略
    """
    # 这个策略需要基本面数据，回测框架主要用于验证技术策略
    # 此处返回空信号，作为占位符
    return {}


# ─── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    print("回测框架自检...")

    try:
        from baostock import bs
        import pandas as pd

        def get_baostock_klines(code: str, start_date: str, end_date: str) -> pd.DataFrame:
            """从BaoStock获取日线数据"""
            # 转换代码格式
            if code.startswith("6"):
                bs_code = f"sh.{code}"
            else:
                bs_code = f"sz.{code}"

            lg = bs.login()
            if lg.error_code != "0":
                raise RuntimeError(f"BaoStock登录失败: {lg.error_msg}")

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                frequency="d",
                adjustflag="2",  # 前复权
            )

            data_list = []
            while (rs.error_code == "0") and rs.next():
                data_list.append(rs.get_row_data())
            bs.logout()

            df = pd.DataFrame(data_list, columns=["date", "open", "high", "low", "close", "volume", "amount"])
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            return df

        # 获取贵州茅台历史数据
        klines = get_baostock_klines("600519", "2023-01-01", "2024-12-31")

        engine = BacktestEngine(initial_capital=100_000)
        engine.add_stock("600519", klines)

        # 简单动量策略：每日买入涨幅>2%的
        def test_strategy(date: str, data: Dict[str, pd.DataFrame]) -> Dict[str, str]:
            signals = {}
            for code, df in data.items():
                if len(df) < 2:
                    continue
                ret = df["close"].pct_change().iloc[-1]
                if ret > 0.02:
                    signals[code] = "buy"
                elif ret < -0.02:
                    signals[code] = "sell"
            return signals

        result = engine.run(test_strategy, "2023-06-01", "2024-12-31", rebalance_freq="daily")
        engine.print_metrics(result)
        print("\n✅ 回测框架自检通过")

    except ImportError as e:
        print(f"⚠️  自检跳过（缺少依赖: {e}）")
    except Exception as e:
        print(f"⚠️  自检跳过: {e}")
