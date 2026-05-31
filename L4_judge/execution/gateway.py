# -*- coding: utf-8 -*-
"""
执行网关抽象基类

定义统一的订单执行接口，支持多券商网关实现。
参照 vnpy Gateway 架构设计。
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from L4_judge.execution.order import Order, Position, AccountInfo, Trade

logger = logging.getLogger("execution.gateway")


class ExecutionGateway(ABC):
    """
    执行网关抽象基类

    所有券商/通道实现此类，提供：
    - send_order: 发送订单
    - cancel_order: 撤销订单
    - get_positions: 查询持仓
    - get_account: 查询账户

    使用方式：
        class MyBrokerGateway(ExecutionGateway):
            def send_order(self, order: Order) -> str:
                ...

        gw = MyBrokerGateway()
        gw.send_order(Order(...))
    """

    name: str = "BaseGateway"

    @abstractmethod
    def send_order(self, order: Order) -> str:
        """
        发送订单

        Args:
            order: Order 对象

        Returns:
            order_id: 成功返回订单ID，失败抛出 GatewayError

        Raises:
            GatewayError: 发送失败时抛出
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        撤销订单

        Args:
            order_id: 订单ID

        Returns:
            True=撤销成功，False=订单不存在或已成交

        Raises:
            GatewayError: 通信失败时抛出
        """
        pass

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """
        查询当前持仓

        Returns:
            Position 列表
        """
        pass

    @abstractmethod
    def get_account(self) -> AccountInfo:
        """
        查询账户信息

        Returns:
            AccountInfo 对象
        """
        pass

    @abstractmethod
    def get_trades(self, order_id: Optional[str] = None) -> List[Trade]:
        """
        查询成交记录

        Args:
            order_id: 可选，指定订单ID

        Returns:
            Trade 列表
        """
        pass


class GatewayError(Exception):
    """网关异常"""
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code


class AllGatewayFailedError(GatewayError):
    """所有网关都失败"""
    def __init__(self, message: str = "所有网关均失败"):
        super().__init__(message)
