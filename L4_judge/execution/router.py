# -*- coding: utf-8 -*-
"""
券商路由器

支持多券商账户管理，自动故障转移。
"""

import logging
from typing import Dict, List, Optional

from L4_judge.execution.gateway import ExecutionGateway, GatewayError, AllGatewayFailedError
from L4_judge.execution.order import Order, Position, AccountInfo, Trade

logger = logging.getLogger("execution.router")


class BrokerRouter:
    """
    券商路由器

    功能：
    - 管理多个券商网关
    - 自动故障转移（主券商失败自动切换到备用）
    - 按券商路由订单

    使用方式：
        router = BrokerRouter()
        router.register("main", MainBrokerGateway())
        router.register("backup", BackupBrokerGateway())
        router.set_active("main")

        order_id = router.send_order(order)  # 自动选择可用网关
    """

    def __init__(self):
        self.gateways: Dict[str, ExecutionGateway] = {}
        self._active_name: Optional[str] = None
        self._fallback_order: List[str] = []  # 故障转移顺序

    def register(self, name: str, gateway: ExecutionGateway, fallback: bool = False) -> None:
        """
        注册网关

        Args:
            name: 网关名称
            gateway: ExecutionGateway 实例
            fallback: 是否作为备用网关
        """
        self.gateways[name] = gateway
        if fallback:
            self._fallback_order.append(name)
        if self._active_name is None:
            self._active_name = name
        logger.info(f"注册网关: {name} (active={self._active_name == name})")

    def set_active(self, name: str) -> None:
        """设置主用网关"""
        if name not in self.gateways:
            raise ValueError(f"网关不存在: {name}")
        self._active_name = name
        logger.info(f"设置主用网关: {name}")

    def send_order(self, order: Order) -> str:
        """
        发送订单（自动故障转移）

        按以下顺序尝试：
        1. 当前激活的主网关
        2. 按注册顺序尝试其他网关

        Returns:
            order_id

        Raises:
            AllGatewayFailedError: 所有网关都失败
        """
        tried = set()

        # 先尝试主网关
        if self._active_name:
            gw = self.gateways.get(self._active_name)
            if gw:
                try:
                    order_id = gw.send_order(order)
                    logger.debug(f"订单由 {self._active_name} 执行: {order_id}")
                    return order_id
                except GatewayError as e:
                    logger.warning(f"网关 {self._active_name} 失败: {e.message}，尝试备用")
                    tried.add(self._active_name)

        # 尝试其他网关
        for name, gw in self.gateways.items():
            if name in tried:
                continue
            try:
                order_id = gw.send_order(order)
                logger.info(f"主网关失败，切换到备用 {name} 执行订单: {order_id}")
                # 切换主网关
                self._active_name = name
                return order_id
            except GatewayError as e:
                logger.warning(f"网关 {name} 也失败: {e.message}")
                tried.add(name)
                continue

        raise AllGatewayFailedError(f"所有网关均失败，已尝试: {tried}")

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单（尝试所有网关）"""
        for name, gw in self.gateways.items():
            try:
                if gw.cancel_order(order_id):
                    logger.info(f"订单 {order_id} 由 {name} 撤销成功")
                    return True
            except GatewayError as e:
                logger.warning(f"网关 {name} 撤销订单失败: {e.message}")
        return False

    def get_positions(self) -> List[Position]:
        """查询持仓（从当前主网关）"""
        if self._active_name:
            gw = self.gateways.get(self._active_name)
            if gw:
                return gw.get_positions()
        return []

    def get_account(self) -> AccountInfo:
        """查询账户（从当前主网关）"""
        if self._active_name:
            gw = self.gateways.get(self._active_name)
            if gw:
                return gw.get_account()
        return AccountInfo()

    def get_trades(self, order_id: Optional[str] = None) -> List[Trade]:
        """查询成交（从当前主网关）"""
        if self._active_name:
            gw = self.gateways.get(self._active_name)
            if gw:
                return gw.get_trades(order_id)
        return []

    def health_check(self) -> Dict[str, bool]:
        """健康检查"""
        results = {}
        for name, gw in self.gateways.items():
            try:
                gw.get_account()
                results[name] = True
            except Exception:
                results[name] = False
        return results

    def summary(self) -> dict:
        """路由器摘要"""
        return {
            "active": self._active_name,
            "gateways": list(self.gateways.keys()),
            "health": self.health_check(),
        }
