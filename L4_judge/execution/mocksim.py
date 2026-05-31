# -*- coding: utf-8 -*-
"""
模拟撮合网关

用于回测和模拟交易，模拟真实A股交易规则：
- T+1 限制
- 涨跌停判断
- 滑点模型
- 佣金和印花税
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from L4_judge.execution.gateway import ExecutionGateway, GatewayError
from L4_judge.execution.order import (
    Order, OrderSide, OrderType, OrderStatus,
    Position, AccountInfo, Trade, FillResult
)
from L3_quant_analysis.backtest.position_manager import ASharePositionManager

logger = logging.getLogger("execution.mocksim")


class MockGateway(ExecutionGateway):
    """
    模拟撮合网关

    Features:
    - 涨跌停判断（主板±10%、创业板/科创板±20%、北交所±30%）
    - T+1 限制（当日买的不能卖）
    - 滑点模型（买入用 ask，卖出用 bid）
    - 佣金和印花税

    使用方式：
        gw = MockGateway(initial_capital=100_000)
        order = Order(code="600519", side=OrderSide.BUY, type=OrderType.MARKET,
                     quantity=100, price=1850.0)
        result = gw.send_order(order)
    """

    name = "MockGateway"

    # 涨跌停比例（按板块）
    LIMIT_UP_RATIOS = {
        "main": 0.10,
        "chinext": 0.20,
        "star": 0.20,
        "bj": 0.30,
    }

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        commission_rate: float = 0.0003,
        tax_rate: float = 0.001,
        slippage: float = 0.001,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_rate = commission_rate
        self.tax_rate = tax_rate
        self.slippage = slippage

        # 持仓管理（使用A股专用管理器）
        self.position_manager = ASharePositionManager()

        # 订单和成交记录
        self.orders: Dict[str, Order] = {}
        self.trades: List[Trade] = []
        self.next_order_id = 1

        # 股票价格（外部传入或模拟）
        self._prices: Dict[str, float] = {}
        self._prev_close: Dict[str, float] = {}

        logger.info(f"MockGateway 初始化: 初始资金={initial_capital:,.0f}")

    def set_price(self, code: str, price: float, prev_close: Optional[float] = None) -> None:
        """设置股票价格（外部数据注入）"""
        self._prices[code] = price
        if prev_close is not None:
            self._prev_close[code] = prev_close
        elif price > 0:
            self._prev_close[code] = price  # 无昨收则用现价近似

    def send_order(self, order: Order) -> str:
        """发送订单（模拟撮合）"""
        # 生成订单ID
        order.order_id = f"M{self.next_order_id:06d}"
        self.next_order_id += 1
        order.submitted_at = datetime.now()

        # 检查持仓
        if order.side == OrderSide.SELL:
            pos = self.position_manager.get_position(order.code)
            if pos is None or pos.quantity < order.quantity:
                order.status = OrderStatus.REJECTED
                order.cancel_reason = "持仓不足"
                self.orders[order.order_id] = order
                raise GatewayError(f"持仓不足: {order.code}", code="INSUFFICIENT_POSITION")

        # 获取价格
        price = order.price or self._prices.get(order.code, 0)
        if price <= 0:
            order.status = OrderStatus.REJECTED
            order.cancel_reason = "价格无效"
            self.orders[order.order_id] = order
            raise GatewayError(f"价格无效: {order.code}", code="INVALID_PRICE")

        prev_close = self._prev_close.get(order.code, price)

        # 涨跌停检查
        if order.side == OrderSide.BUY:
            can_buy, reason = self.position_manager.check_buy(order.code, price, prev_close)
            if not can_buy:
                order.status = OrderStatus.REJECTED
                order.cancel_reason = reason
                self.orders[order.order_id] = order
                raise GatewayError(f"不能买入: {reason}", code="LIMIT_UP")

        elif order.side == OrderSide.SELL:
            can_sell, reason = self.position_manager.check_sell(order.code, price, prev_close, order.submitted_at.strftime("%Y-%m-%d"))
            if not can_sell:
                order.status = OrderStatus.REJECTED
                order.cancel_reason = reason
                self.orders[order.order_id] = order
                raise GatewayError(f"不能卖出: {reason}", code="T1_OR_LIMIT_DOWN")

        # 资金检查（买入）
        if order.side == OrderSide.BUY:
            cost = price * order.quantity * (1 + self.commission_rate)
            if cost > self.cash:
                order.status = OrderStatus.REJECTED
                order.cancel_reason = "资金不足"
                self.orders[order.order_id] = order
                raise GatewayError(f"资金不足: 需要{cost:,.0f}，可用{self.cash:,.0f}", code="INSUFFICIENT_CASH")

        # 模拟撮合（按滑点执行）
        if order.side == OrderSide.BUY:
            exec_price = price * (1 + self.slippage)  # 买入用稍高价格
        else:
            exec_price = price * (1 - self.slippage)  # 卖出用稍低价格

        exec_price = round(exec_price, 2)

        # 计算佣金和印花税
        turnover = exec_price * order.quantity
        commission = turnover * self.commission_rate
        tax = turnover * self.tax_rate if order.side == OrderSide.SELL else 0
        total_cost = commission + tax

        # 执行
        if order.side == OrderSide.BUY:
            self.cash -= (turnover + commission)
            self.position_manager.buy(
                code=order.code,
                price=exec_price,
                date=order.submitted_at.strftime("%Y-%m-%d"),
                quantity=order.quantity,
            )
        else:
            self.cash += (turnover - commission - tax)
            self.position_manager.sell(order.code, quantity=order.quantity)

        # 记录成交
        trade = Trade(
            order_id=order.order_id,
            code=order.code,
            side=order.side,
            price=exec_price,
            quantity=order.quantity,
            commission=commission + tax,
            traded_at=order.submitted_at,
        )
        self.trades.append(trade)

        # 更新订单状态
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = exec_price
        self.orders[order.order_id] = order

        logger.info(f"模拟成交: {order.side.value.upper()} {order.code} "
                    f"@{exec_price}x{order.quantity} 手续费={commission + tax:.2f}")

        return order.order_id

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        order = self.orders.get(order_id)
        if order is None:
            return False

        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False

        order.status = OrderStatus.CANCELLED
        order.cancel_reason = "用户撤销"
        self.orders[order_id] = order
        logger.info(f"撤销订单: {order_id}")
        return True

    def get_positions(self) -> List[Position]:
        """查询持仓"""
        positions = []
        for code, pos_info in self.position_manager.get_all_positions().items():
            current_price = self._prices.get(code, pos_info.avg_cost)
            positions.append(Position(
                code=code,
                quantity=pos_info.quantity,
                avg_cost=pos_info.avg_cost,
                buy_date=pos_info.buy_date,
                buy_price=pos_info.buy_price,
            ))
        return positions

    def get_account(self) -> AccountInfo:
        """查询账户"""
        positions = self.get_positions()
        market_value = sum(p.market_value(self._prices.get(p.code, p.avg_cost)) for p in positions)
        total_asset = self.cash + market_value

        return AccountInfo(
            account_id="MOCK001",
            cash=round(self.cash, 2),
            market_value=round(market_value, 2),
            total_asset=round(total_asset, 2),
            frozen_cash=0.0,
            commission_today=round(sum(t.commission for t in self.trades), 2),
        )

    def get_trades(self, order_id: Optional[str] = None) -> List[Trade]:
        """查询成交"""
        if order_id:
            return [t for t in self.trades if t.order_id == order_id]
        return list(self.trades)

    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """查询订单"""
        if status:
            return [o for o in self.orders.values() if o.status == status]
        return list(self.orders.values())

    def summary(self) -> dict:
        """账户摘要"""
        account = self.get_account()
        positions = self.get_positions()
        return {
            "account": account.to_dict(),
            "positions": {p.code: p.to_dict() for p in positions},
            "total_orders": len(self.orders),
            "total_trades": len(self.trades),
        }
