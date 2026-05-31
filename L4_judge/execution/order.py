# -*- coding: utf-8 -*-
"""
订单与持仓数据类

定义订单（Order）、成交（Trade）、持仓（Position）、账户（AccountInfo）等核心数据结构。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List

logger = logging.getLogger("execution.order")


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"      # 市价单
    LIMIT = "limit"       # 限价单


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"       # 待发送
    SUBMITTED = "submitted"   # 已提交
    PARTIAL = "partial"       # 部分成交
    FILLED = "filled"         # 全部成交
    CANCELLED = "cancelled"   # 已撤销
    REJECTED = "rejected"     # 已拒绝


@dataclass
class Order:
    """
    订单

    Attributes:
        order_id: 订单ID（由网关生成）
        code: 股票代码
        side: 买卖方向
        type: 订单类型
        quantity: 委托数量
        price: 委托价格（市价单可为None）
        submitted_at: 提交时间
        status: 订单状态
        filled_quantity: 已成交数量
        avg_fill_price: 成交均价
        cancel_reason: 撤销/拒绝原因
    """
    code: str
    side: OrderSide
    type: OrderType
    quantity: int
    price: Optional[float] = None
    order_id: str = ""
    submitted_at: Optional[datetime] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    cancel_reason: str = ""

    def __post_init__(self):
        if not self.order_id:
            self.order_id = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "code": self.code,
            "side": self.side.value,
            "type": self.type.value,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": round(self.avg_fill_price, 2) if self.avg_fill_price else 0,
            "cancel_reason": self.cancel_reason,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
        }


@dataclass
class Trade:
    """
    成交记录

    Attributes:
        trade_id: 成交ID
        order_id: 对应订单ID
        code: 股票代码
        side: 买卖方向
        price: 成交价格
        quantity: 成交数量
        commission: 手续费
        traded_at: 成交时间
    """
    order_id: str
    code: str
    side: OrderSide
    price: float
    quantity: int
    commission: float = 0.0
    trade_id: str = ""
    traded_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.trade_id:
            self.trade_id = f"T{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "code": self.code,
            "side": self.side.value,
            "price": round(self.price, 2),
            "quantity": self.quantity,
            "commission": round(self.commission, 2),
            "traded_at": self.traded_at.isoformat() if self.traded_at else None,
        }


@dataclass
class Position:
    """
    持仓

    Attributes:
        code: 股票代码
        quantity: 持仓数量（正数=多头，负数=空头）
        avg_cost: 平均成本价
        buy_date: 买入日期（用于T+1判断）
        today_quantity: 今日买入数量（当日不能卖）
    """
    code: str
    quantity: int
    avg_cost: float
    buy_date: str = ""
    buy_price: float = 0.0

    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.avg_cost) * self.quantity

    def unrealized_pnl_pct(self, current_price: float) -> float:
        if self.avg_cost == 0:
            return 0.0
        return (current_price - self.avg_cost) / self.avg_cost

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "quantity": self.quantity,
            "avg_cost": round(self.avg_cost, 2),
            "buy_date": self.buy_date,
            "buy_price": round(self.buy_price, 2) if self.buy_price else 0,
        }


@dataclass
class AccountInfo:
    """
    账户信息

    Attributes:
        account_id: 账户ID
        cash: 可用资金
        market_value: 持仓市值
        total_asset: 总资产
        frozen_cash: 冻结资金
        commission_today: 今日手续费
    """
    account_id: str = "default"
    cash: float = 0.0
    market_value: float = 0.0
    total_asset: float = 0.0
    frozen_cash: float = 0.0
    commission_today: float = 0.0

    def available_cash(self) -> float:
        """可用资金 = 现金 - 冻结资金"""
        return self.cash - self.frozen_cash

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "cash": round(self.cash, 2),
            "market_value": round(self.market_value, 2),
            "total_asset": round(self.total_asset, 2),
            "frozen_cash": round(self.frozen_cash, 2),
            "commission_today": round(self.commission_today, 2),
            "available_cash": round(self.available_cash(), 2),
        }


@dataclass
class FillResult:
    """
    模拟撮合结果

    Attributes:
        success: 是否成交
        order_id: 订单ID
        filled_price: 成交价
        filled_quantity: 成交数量
        commission: 手续费
        reason: 失败原因
    """
    success: bool
    order_id: str
    filled_price: float = 0.0
    filled_quantity: int = 0
    commission: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "order_id": self.order_id,
            "filled_price": round(self.filled_price, 2),
            "filled_quantity": self.filled_quantity,
            "commission": round(self.commission, 2),
            "reason": self.reason,
        }
