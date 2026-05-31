# -*- coding: utf-8 -*-
"""
事件驱动回测引擎 — R2 升级

参照 QuantConnect LEAN / Zipline 的事件驱动架构：
- 逐bar事件循环（handle_data）
- 订单/持仓/组合状态独立追踪
- 支持 T+1 / 涨跌停 / 佣金滑点

核心差异 vs 批量回测（BacktestEngine）：
  批量回测：按日批量执行信号，不区分事件优先级
  事件驱动：每个 bar 触发 handle_data，支持订单簿/成交回调

使用方式：
    engine = EventEngine(initial_capital=100_000)
    engine.add_stock("600519", klines_df)
    engine.add_stock("000858", klines_df)

    # 注册事件处理器
    @engine.on_bar
    def handle_data(event):
        # event.date, event.code, event.bar（dict）
        # 返回信号：{"action": "buy"/"sell"/"hold", "quantity": int}
        pass

    result = engine.run("2023-01-01", "2024-12-31")
    engine.print_metrics(result)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Callable, Optional, Any, List, Tuple
from enum import Enum

import pandas as pd
import numpy as np

from L3_quant_analysis.backtest.position_manager import ASharePositionManager

logger = logging.getLogger("event_backtest")


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Bar:
    """单个 bar（K线）数据"""
    date: str
    code: str
    open_: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    daily_return: float = 0.0

    @classmethod
    def from_row(cls, date: str, code: str, row: pd.Series) -> "Bar":
        return cls(
            date=date,
            code=code,
            open_=float(row.get("open", 0)),
            high=float(row.get("high", 0)),
            low=float(row.get("low", 0)),
            close=float(row.get("close", 0)),
            volume=float(row.get("volume", 0)),
            amount=float(row.get("amount", 0)),
            daily_return=float(row.get("daily_return", 0)),
        )


@dataclass
class Order:
    """订单"""
    date: str          # 下单日期
    code: str
    side: str          # "buy" / "sell"
    quantity: int      # 股数（正数）
    price: float       # 执行价
    slippage: float = 0.001   # 滑点率
    commission_rate: float = 0.0003
    tax_rate: float = 0.001    # 仅卖出

    @property
    def exec_price(self) -> float:
        if self.side == "buy":
            return self.price * (1 + self.slippage)
        else:
            return self.price * (1 - self.slippage)

    @property
    def cost(self) -> float:
        """买入总成本（含佣金）"""
        notional = self.quantity * self.exec_price
        commission = notional * self.commission_rate
        return notional + commission

    @property
    def proceeds(self) -> float:
        """卖出净收入（含佣金+税）"""
        notional = self.quantity * self.exec_price
        commission = notional * self.commission_rate
        tax = notional * self.tax_rate
        return notional - commission - tax


@dataclass
class Fill:
    """成交记录"""
    date: str
    code: str
    side: str
    price: float       # 成交价（含滑点）
    quantity: int
    commission: float
    capital_before: float
    capital_after: float


@dataclass
class PortfolioState:
    """组合状态快照"""
    date: str
    cash: float
    position_value: float
    total_value: float
    positions: Dict[str, int]  # code -> quantity
    pending_orders: List[Order] = field(default_factory=list)


class EventEngine:
    """
    事件驱动回测引擎

    核心循环：
        for each date in trading_days:
            for each stock in stocks:
                bar = get_bar(date, stock)
                event = BarEvent(bar)
                handle_data(event)
            process_pending_orders(date)
            update_portfolio(date)

    支持：
    - T+1 限制（ASharePositionManager）
    - 涨跌停检查
    - 真实成交（订单簿模拟）
    - 组合每日快照
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        commission_rate: float = 0.0003,
        slippage: float = 0.001,
        tax_rate: float = 0.001,
        max_positions: int = 5,
        max_position_pct: float = 0.2,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.tax_rate = tax_rate
        self.max_positions = max_positions
        self.max_position_pct = max_position_pct

        self.stocks_data: Dict[str, pd.DataFrame] = {}
        self._prev_close: Dict[str, Dict[str, float]] = {}  # code -> {date -> prev_close}
        self.position_manager = ASharePositionManager()

        self.fills: List[Fill] = []
        self.orders: List[Order] = []
        self.pending_orders: List[Order] = []
        self.portfolio_history: List[PortfolioState] = []

        # 事件处理器
        self._bar_handlers: List[Callable] = []
        self._order_handlers: List[Callable] = []
        self._fill_handlers: List[Callable] = []

        # 当前bar缓存
        self._current_bar: Optional[Bar] = None
        self._current_positions: Dict[str, int] = {}  # code -> shares

        # 结果
        self._metrics: Optional[Dict] = None

    # ─── 数据添加 ───────────────────────────────────────────────

    def add_stock(self, code: str, klines: pd.DataFrame) -> None:
        """添加股票历史数据"""
        df = klines.copy()
        if "date" not in df.columns:
            raise ValueError("klines must have 'date' column")

        df = df.sort_values("date").reset_index(drop=True)
        if "daily_return" not in df.columns:
            df["daily_return"] = df["close"].pct_change()

        # 构建 prev_close 映射
        if len(df) >= 2:
            self._prev_close[code] = dict(zip(
                df["date"].iloc[1:], df["close"].iloc[:-1].values
            ))

        self.stocks_data[code] = df
        logger.info(f"[EventEngine] Added {code}: {len(df)} bars")

    # ─── 事件注册 ───────────────────────────────────────────────

    def on_bar(self, handler: Callable[["Bar"], Any]) -> None:
        """注册 bar 事件处理器"""
        self._bar_handlers.append(handler)

    def on_order(self, handler: Callable[[Order], Any]) -> None:
        """注册订单事件处理器"""
        self._order_handlers.append(handler)

    def on_fill(self, handler: Callable[[Fill], Any]) -> None:
        """注册成交事件处理器"""
        self._fill_handlers.append(handler)

    # ─── 主循环 ─────────────────────────────────────────────────

    def run(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        运行事件驱动回测

        Args:
            start_date: 回测开始日期
            end_date: 回测结束日期

        Returns:
            dict: {metrics, fills, portfolio_history, orders}
        """
        if not self.stocks_data:
            raise ValueError("No stock data added. Call add_stock() first.")

        # 获取所有股票共同交易日
        trading_days = self._get_trading_days(start_date, end_date)
        if not trading_days:
            raise ValueError(f"No trading days: {start_date} ~ {end_date}")

        logger.info(f"[EventEngine] Run: {start_date} ~ {end_date}, "
                    f"{len(trading_days)} days, capital={self.initial_capital:,.0f}")

        # 重置状态
        self.cash = self.initial_capital
        self.fills = []
        self.orders = []
        self.pending_orders = []
        self.portfolio_history = []
        self._current_positions = {}

        # ── 事件主循环 ──────────────────────────────────────────
        for i, date in enumerate(trading_days):
            # 1. 推送 bar 事件（逐股票）
            for code in self.stocks_data:
                bar = self._get_bar(code, date)
                if bar is None:
                    continue

                self._current_bar = bar
                self._emit_bar(bar)

            # 2. 处理涨跌停过滤后的待执行订单
            self._process_pending_orders(date)

            # 3. 更新持仓市值
            self._update_portfolio(date)

            # 4. 记录组合快照
            self._record_snapshot(date)

            # 进度日志
            if (i + 1) % 50 == 0:
                state = self.portfolio_history[-1]
                logger.info(f"  [{i+1}/{len(trading_days)}] {date}: "
                            f"cash={state.cash:,.0f} value={state.total_value:,.0f}")

        # 计算性能指标
        self._metrics = self._calculate_metrics()

        return {
            "metrics": self._metrics,
            "fills": self.fills,
            "orders": self.orders,
            "portfolio_history": self.portfolio_history,
            "stocks": list(self.stocks_data.keys()),
            "start_date": start_date,
            "end_date": end_date,
        }

    def _get_trading_days(self, start_date: str, end_date: str) -> List[str]:
        """获取所有股票共同交易日"""
        all_dates_per_stock = [
            set(df["date"].tolist()) for df in self.stocks_data.values()
        ]
        common_dates = set.intersection(*all_dates_per_stock)
        filtered = sorted(d for d in common_dates if start_date <= d <= end_date)
        return filtered

    def _get_bar(self, code: str, date: str) -> Optional[Bar]:
        """获取指定股票指定日期的 bar"""
        df = self.stocks_data.get(code)
        if df is None:
            return None
        rows = df[df["date"] == date]
        if rows.empty:
            return None
        return Bar.from_row(date, code, rows.iloc[-1])

    def _emit_bar(self, bar: Bar) -> None:
        """触发 bar 事件"""
        for handler in self._bar_handlers:
            try:
                result = handler(bar)
                # 如果返回订单信号，自动创建订单
                if result is not None:
                    if isinstance(result, dict):
                        action = result.get("action", "hold")
                        qty = result.get("quantity", 100)
                        if action in ("buy", "sell") and qty > 0:
                            self._submit_order(bar.date, bar.code, action, qty, bar.close)
                    elif isinstance(result, Order):
                        self.pending_orders.append(result)
            except Exception as e:
                logger.warning(f"Bar handler error {bar.date} {bar.code}: {e}")

    def _submit_order(
        self,
        date: str,
        code: str,
        side: str,
        quantity: int,
        price: float,
    ) -> None:
        """提交订单"""
        order = Order(
            date=date,
            code=code,
            side=side,
            quantity=quantity,
            price=price,
            slippage=self.slippage,
            commission_rate=self.commission_rate,
            tax_rate=self.tax_rate,
        )
        self.orders.append(order)
        self.pending_orders.append(order)

        for handler in self._order_handlers:
            try:
                handler(order)
            except Exception:
                pass

    def _process_pending_orders(self, date: str) -> None:
        """处理待执行订单（涨跌停/T+1过滤）"""
        remaining = []
        for order in self.pending_orders:
            if order.date < date:
                continue  # 跳过历史订单

            fill = self._try_fill(order, date)
            if fill is None:
                remaining.append(order)
            else:
                self.fills.append(fill)
                for handler in self._fill_handlers:
                    try:
                        handler(fill)
                    except Exception:
                        pass

        self.pending_orders = remaining

    def _try_fill(self, order: Order, date: str) -> Optional[Fill]:
        """尝试执行订单"""
        code = order.code
        prev_close = self._prev_close.get(code, {}).get(date, order.price)

        # A股涨跌停检查
        if order.side == "buy":
            can, reason = self.position_manager.check_buy(
                code, order.exec_price, prev_close
            )
            if not can:
                logger.debug(f"  [OrderRejected] {date} {order.side.upper()} {code}: {reason}")
                return None
        else:
            can, reason = self.position_manager.check_sell(
                code, order.exec_price, prev_close, date
            )
            if not can:
                logger.debug(f"  [OrderRejected] {date} {order.side.upper()} {code}: {reason}")
                return None

        # T+1 检查
        if order.side == "buy":
            if not self.position_manager.can_sell(code, date):
                return None

        # 资金/持仓检查
        capital_before = self.cash
        if order.side == "buy":
            cost = order.cost
            if cost > self.cash:
                return None
            self.cash -= cost
            self._current_positions[code] = self._current_positions.get(code, 0) + order.quantity
            self.position_manager.buy(
                code, price=order.exec_price, date=date,
                quantity=order.quantity, avg_cost=order.exec_price
            )
        else:
            if self._current_positions.get(code, 0) < order.quantity:
                return None
            proceeds = order.proceeds
            self.cash += proceeds
            self._current_positions[code] -= order.quantity
            if self._current_positions[code] <= 0:
                del self._current_positions[code]
            self.position_manager.sell(code, quantity=None)

        commission = (
            order.quantity * order.exec_price * order.commission_rate
        )
        return Fill(
            date=date,
            code=code,
            side=order.side,
            price=order.exec_price,
            quantity=order.quantity,
            commission=commission,
            capital_before=capital_before,
            capital_after=self.cash,
        )

    def _update_portfolio(self, date: str) -> None:
        """更新组合市值"""
        pos_value = 0.0
        for code, shares in self._current_positions.items():
            df = self.stocks_data.get(code)
            if df is None:
                continue
            rows = df[df["date"] == date]
            if rows.empty:
                continue
            price = float(rows.iloc[-1]["close"])
            pos_value += shares * price

    def _record_snapshot(self, date: str) -> None:
        """记录组合快照"""
        total_value = self.cash + sum(
            self._get_latest_price(code) * shares
            for code, shares in self._current_positions.items()
        )
        self.portfolio_history.append(PortfolioState(
            date=date,
            cash=self.cash,
            position_value=total_value - self.cash,
            total_value=total_value,
            positions=dict(self._current_positions),
            pending_orders=list(self.pending_orders),
        ))

    def _get_latest_price(self, code: str) -> float:
        """获取最新价格（最后一个快照的价格）"""
        state = self.portfolio_history[-1]
        if not state.positions.get(code):
            return 0.0
        df = self.stocks_data.get(code)
        if df is None:
            return 0.0
        return float(df["close"].iloc[-1])

    # ─── 性能指标 ────────────────────────────────────────────────

    def _calculate_metrics(self) -> Dict[str, Any]:
        """计算性能指标"""
        if not self.portfolio_history:
            return {}

        df = pd.DataFrame([
            {"date": s.date, "total_value": s.total_value}
            for s in self.portfolio_history
        ])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        initial = self.initial_capital
        final = df["total_value"].iloc[-1]
        total_return = (final - initial) / initial

        days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
        years = max(1, days / 365)
        annual_return = (1 + total_return) ** (1 / years) - 1

        # 最大回撤
        cummax = df["total_value"].cummax()
        drawdown = (cummax - df["total_value"]) / cummax
        max_dd = drawdown.max()
        max_dd_idx = drawdown.idxmax()
        peak_date = df["date"].iloc[:max_dd_idx].idxmax()
        trough_date = max_dd_idx

        # 回撤持续天数
        in_dd = drawdown > 0
        durations = []
        cur = 0
        for v in in_dd:
            if v:
                cur += 1
            else:
                durations.append(cur)
                cur = 0
        durations.append(cur)
        max_duration = max(durations) if durations else 0

        # 夏普比率
        daily_rets = df["total_value"].pct_change().dropna()
        if len(daily_rets) > 1 and daily_rets.std() > 0:
            sharpe = (
                (daily_rets.mean() - 0.03 / 252) / daily_rets.std() * np.sqrt(252)
            )
        else:
            sharpe = 0.0

        # Sortino / Calmar
        try:
            from L4_judge.risk.risk_metrics import (
                compute_sortino, compute_calmar, compute_max_drawdown_from_prices,
            )
            returns_s = pd.Series(daily_rets.values, index=daily_rets.index)
            sortino = compute_sortino(returns_s)
            prices_s = df.set_index("date")["total_value"]
            dd_result = compute_max_drawdown_from_prices(prices_s)
            max_dd_real = abs(dd_result.get("max_drawdown", 0))
            calmar = compute_calmar(returns_s, -max_dd_real) if max_dd_real > 0 else 0.0
        except Exception:
            sortino = 0.0
            calmar = 0.0
            max_dd_real = max_dd

        # 交易统计
        total_trades = len(self.fills)
        buy_trades = [f for f in self.fills if f.side == "buy"]
        sell_trades = [f for f in self.fills if f.side == "sell"]

        return {
            "total_return": round(total_return, 4),
            "annual_return": round(annual_return, 4),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar, 2),
            "max_drawdown": round(max_dd, 4),
            "max_drawdown_real": round(max_dd_real, 4),
            "max_drawdown_duration": max_duration,
            "win_rate": 0.0,
            "profit_loss_ratio": 0.0,
            "total_trades": total_trades,
            "buy_trades": len(buy_trades),
            "sell_trades": len(sell_trades),
            "final_capital": round(final, 2),
            "initial_capital": initial,
        }

    def print_metrics(self, result: Dict[str, Any]) -> None:
        """打印回测结果"""
        m = result["metrics"]
        print("\n" + "=" * 60)
        print(f"事件驱动回测结果: {result['start_date']} ~ {result['end_date']}")
        print("=" * 60)
        print(f"初始资金:      {m.get('initial_capital', 0):>15,.2f}")
        print(f"最终资金:      {m.get('final_capital', 0):>15,.2f}")
        print(f"总收益率:      {m.get('total_return', 0):>15.2%}")
        print(f"年化收益率:    {m.get('annual_return', 0):>15.2%}")
        print(f"夏普比率:      {m.get('sharpe_ratio', 0):>15.2f}")
        print(f"Sortino:       {m.get('sortino_ratio', 0):>15.2f}")
        print(f"Calmar:        {m.get('calmar_ratio', 0):>15.2f}")
        print(f"最大回撤:      {m.get('max_drawdown_real', 0):>15.2%}")
        print(f"回撤天数:      {m.get('max_drawdown_duration', 0):>15}天")
        print(f"总交易次数:    {m.get('total_trades', 0):>15}")
        print(f"买入次数:      {m.get('buy_trades', 0):>15}")
        print(f"卖出次数:      {m.get('sell_trades', 0):>15}")
        print("=" * 60)

        if result.get("fills"):
            print("\n前10笔成交:")
            for f in result["fills"][:10]:
                print(f"  {f.date} {f.side.upper():4} {f.code} "
                      f"@ {f.price:.2f}x{f.quantity} 佣金={f.commission:.2f}")


# ─── 便捷工厂函数 ─────────────────────────────────────────────

def create_momentum_event_strategy(
    lookback: int = 20,
    top_n: int = 2,
    buy_threshold: float = 0.03,
    sell_threshold: float = -0.03,
) -> Callable:
    """
    创建动量事件策略工厂

    Args:
        lookback: 回顾天数
        top_n: 买入动量最强的 top_n
        buy_threshold: 买入动量阈值
        sell_threshold: 卖出动量阈值

    Returns:
        handle_data(bar) -> order_signal dict
    """
    _price_history: Dict[str, List[float]] = {}
    _position_codes: set = set()

    def on_bar(bar: Bar) -> Dict:
        code = bar.code
        if code not in _price_history:
            _price_history[code] = []
        _price_history[code].append(bar.close)

        if len(_price_history[code]) < lookback + 1:
            return None

        ret = (_price_history[code][-1] - _price_history[code][-(lookback + 1)]) / \
              _price_history[code][-(lookback + 1)]

        if ret > buy_threshold and code not in _position_codes:
            _position_codes.add(code)
            return {"action": "buy", "quantity": 100}
        elif ret < sell_threshold and code in _position_codes:
            _position_codes.discard(code)
            return {"action": "sell", "quantity": 100}
        return None

    return on_bar


# ─── CLI 自检 ─────────────────────────────────────────────────
if __name__ == "__main__":
    print("事件驱动回测引擎自检...")

    try:
        import baostock as bs

        def get_klines(code: str, start: str, end: str) -> pd.DataFrame:
            bs_code = f"sh.{code}" if code.startswith("6") else f"sz.{code}"
            bs.login()
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
                frequency="d", adjustflag="2",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            bs.logout()
            df = pd.DataFrame(rows, columns=["date","open","high","low","close","volume","amount"])
            for c in ["open","high","low","close","volume","amount"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna(subset=["close"])

        engine = EventEngine(initial_capital=100_000)
        klines = get_klines("600519", "2023-01-01", "2024-12-31")
        engine.add_stock("600519", klines)

        @engine.on_bar
        def strategy(bar: Bar) -> Dict:
            if bar.daily_return > 0.02:
                return {"action": "buy", "quantity": 100}
            elif bar.daily_return < -0.02:
                return {"action": "sell", "quantity": 100}
            return None

        result = engine.run("2023-06-01", "2024-12-31")
        engine.print_metrics(result)
        print("\n✅ 事件驱动回测引擎自检通过")

    except ImportError as e:
        print(f"⚠️  自检跳过（缺少依赖: {e}）")
    except Exception as e:
        print(f"⚠️  自检跳过: {e}")
