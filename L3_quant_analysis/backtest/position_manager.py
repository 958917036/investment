# -*- coding: utf-8 -*-
"""
A股持仓管理器 — T+1 + 涨跌停规则

负责追踪持仓的买入日期，判断是否可以卖出（ T+1 限制），
以及涨跌停时是否能够买入/卖出。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger("backtest.position")


@dataclass
class PositionInfo:
    """持仓信息"""
    code: str
    quantity: int
    avg_cost: float
    buy_date: str           # 买入日期，格式 YYYY-MM-DD
    buy_price: float        # 买入价格


class ASharePositionManager:
    """
    A股持仓管理器

    A股规则：
    - T+1：当日买入的股票，当日不能卖出（需等到下一个交易日）
    - 涨跌停：当日涨跌达到限制时，买卖单可能无法成交
      - 主板（沪/深主板）：±10%
      - 创业板（300开头）：±20%
      - 科创板（688开头）：±20%
      - 北交所（8开头）：±30%

    使用方式：
        pm = ASharePositionManager()
        pm.buy("600519", price=1850.0, date="2024-01-02", quantity=100)
        pm.can_sell("600519", "2024-01-02")  # False - T+1
        pm.can_sell("600519", "2024-01-03")  # True
    """

    # 涨跌停比例（按板块）
    LIMIT_UP_RATIOS = {
        "main": 0.10,      # 主板: 10%
        "chinext": 0.20,   # 创业板(300): 20%
        "star": 0.20,      # 科创板(688): 20%
        "bj": 0.30,       # 北交所(8): 30%
    }
    LIMIT_DOWN_RATIOS = LIMIT_UP_RATIOS  # 对称

    def __init__(self):
        self.positions: Dict[str, PositionInfo] = {}  # code -> PositionInfo
        self._buy_history: Dict[str, list] = {}      # code -> [buy_dates]，支持多次买入

    # ── 基础持仓操作 ─────────────────────────────────────

    def buy(
        self,
        code: str,
        price: float,
        date: str,
        quantity: int,
        avg_cost: Optional[float] = None
    ) -> PositionInfo:
        """
        记录买入

        Args:
            code: 股票代码
            price: 买入价格
            date: 买入日期 (YYYY-MM-DD)
            quantity: 买入数量
            avg_cost: 持仓成本（默认用加权平均）

        Returns:
            PositionInfo 对象
        """
        if code in self.positions:
            # 增持：更新持仓成本
            existing = self.positions[code]
            total_cost = existing.avg_cost * existing.quantity + price * quantity
            total_qty = existing.quantity + quantity
            existing.avg_cost = total_cost / total_qty
            existing.quantity = total_qty
            existing.buy_price = price
            # 保留最早买入日期（T+1限制以最早买入为准）
            if date < existing.buy_date:
                existing.buy_date = date
        else:
            self.positions[code] = PositionInfo(
                code=code,
                quantity=quantity,
                avg_cost=avg_cost if avg_cost is not None else price,
                buy_date=date,
                buy_price=price,
            )

        # 记录买入历史（用于计算实际持仓成本）
        if code not in self._buy_history:
            self._buy_history[code] = []
        self._buy_history[code].append({"date": date, "price": price, "quantity": quantity})

        logger.debug(f"买入 {code}: {quantity}股 @{price}, 日期={date}, 成本={self.positions[code].avg_cost:.2f}")
        return self.positions[code]

    def sell(self, code: str, quantity: Optional[int] = None) -> Optional[Dict]:
        """
        记录卖出（不减持仓仓成本，只减少数量）

        Args:
            code: 股票代码
            quantity: 卖出数量（None=清仓）

        Returns:
            卖出信息 dict 或 None（如果无持仓）
        """
        if code not in self.positions:
            return None

        pos = self.positions[code]
        sell_qty = quantity if quantity is not None else pos.quantity

        if sell_qty >= pos.quantity:
            # 清仓
            info = {
                "code": code,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "buy_date": pos.buy_date,
            }
            del self.positions[code]
            return info
        else:
            # 部分卖出
            pos.quantity -= sell_qty
            return {
                "code": code,
                "quantity": sell_qty,
                "avg_cost": pos.avg_cost,
                "buy_date": pos.buy_date,
            }

    def get_position(self, code: str) -> Optional[PositionInfo]:
        """获取持仓信息"""
        return self.positions.get(code)

    def get_all_positions(self) -> Dict[str, PositionInfo]:
        """获取全部持仓"""
        return dict(self.positions)

    def clear(self):
        """清空所有持仓"""
        self.positions.clear()
        self._buy_history.clear()

    # ── T+1 规则 ─────────────────────────────────────

    def can_sell(self, code: str, current_date: str) -> bool:
        """
        判断当日是否可以卖出（ T+1 限制）

        A股规则：当日买入的股票，当日不能卖出。
        需检查当前持仓中是否有今日买入的股份。

        Args:
            code: 股票代码
            current_date: 当前日期 (YYYY-MM-DD)

        Returns:
            True=可以卖出，False=T+1限制不能卖
        """
        pos = self.positions.get(code)
        if pos is None:
            return True  # 无持仓，可以不关心

        # 检查是否今日买入
        if pos.buy_date == current_date:
            return False  # T+1 限制

        return True

    def get_holding_days(self, code: str, current_date: str) -> int:
        """获取持仓天数"""
        pos = self.positions.get(code)
        if pos is None:
            return 0
        d1 = datetime.strptime(pos.buy_date, "%Y-%m-%d")
        d2 = datetime.strptime(current_date, "%Y-%m-%d")
        return (d2 - d1).days

    # ── 涨跌停规则 ─────────────────────────────────────

    @staticmethod
    def get_limit_ratio(code: str) -> float:
        """
        根据股票代码判断涨跌停比例

        Args:
            code: 股票代码

        Returns:
            涨跌停比例（如 0.10 表示 ±10%）
        """
        if code.startswith("300"):
            return 0.20   # 创业板
        elif code.startswith("688"):
            return 0.20   # 科创板
        elif code.startswith("8") or code.startswith("4"):
            return 0.30   # 北交所
        else:
            return 0.10   # 主板（沪/深主板）

    def is_limit_up(self, code: str, price: float, prev_close: float) -> bool:
        """
        判断是否涨停

        Args:
            code: 股票代码
            price: 当前价格
            prev_close: 昨日收盘价

        Returns:
            True=涨停，不能买入
        """
        if prev_close <= 0:
            return False
        ratio = self.get_limit_ratio(code)
        return price >= prev_close * (1 + ratio)

    def is_limit_down(self, code: str, price: float, prev_close: float) -> bool:
        """
        判断是否跌停

        Args:
            code: 股票代码
            price: 当前价格
            prev_close: 昨日收盘价

        Returns:
            True=跌停，不能卖出
        """
        if prev_close <= 0:
            return False
        ratio = self.get_limit_ratio(code)
        return price <= prev_close * (1 - ratio)

    def get_limit_price(self, code: str, prev_close: float, direction: str) -> float:
        """
        获取涨跌停价格

        Args:
            code: 股票代码
            prev_close: 昨日收盘价
            direction: "up" 或 "down"

        Returns:
            涨跌停价格
        """
        ratio = self.get_limit_ratio(code)
        if direction == "up":
            return round(prev_close * (1 + ratio), 2)
        else:
            return round(prev_close * (1 - ratio), 2)

    # ── 组合层面检查 ─────────────────────────────────────

    def check_sell(self, code: str, price: float, prev_close: float, current_date: str) -> tuple:
        """
        综合检查卖出条件（ T+1 + 涨跌停）

        Args:
            code: 股票代码
            price: 当前价格
            prev_close: 昨日收盘价
            current_date: 当前日期

        Returns:
            (can_sell: bool, reason: str)
        """
        if code not in self.positions:
            return False, "无持仓"

        if not self.can_sell(code, current_date):
            return False, f"T+1限制（买入日期={self.positions[code].buy_date}）"

        if self.is_limit_down(code, price, prev_close):
            return False, f"跌停（现价={price}，昨收={prev_close}）"

        return True, "可以卖出"

    def check_buy(self, code: str, price: float, prev_close: float) -> tuple:
        """
        综合检查买入条件（涨跌停）

        Args:
            code: 股票代码
            price: 当前价格
            prev_close: 昨日收盘价

        Returns:
            can_buy: bool, reason: str
        """
        if self.is_limit_up(code, price, prev_close):
            return False, f"涨停（现价={price}，昨收={prev_close}）"

        return True, "可以买入"

    # ── 持仓统计 ─────────────────────────────────────

    def total_value(self, prices: Dict[str, float]) -> float:
        """计算持仓总市值"""
        total = 0.0
        for code, pos in self.positions.items():
            price = prices.get(code, pos.avg_cost)
            total += pos.quantity * price
        return total

    def total_cost(self) -> float:
        """计算持仓总成本"""
        return sum(pos.avg_cost * pos.quantity for pos in self.positions.values())

    def total_profit_loss(self, prices: Dict[str, float]) -> tuple:
        """
        计算持仓总盈亏

        Returns:
            (总盈亏金额, 总盈亏比例)
        """
        cost = self.total_cost()
        value = self.total_value(prices)
        pnl = value - cost
        pnl_ratio = pnl / cost if cost > 0 else 0.0
        return round(pnl, 2), round(pnl_ratio, 4)

    def position_count(self) -> int:
        """持仓数量"""
        return len(self.positions)

    def summary(self) -> Dict:
        """持仓摘要"""
        return {
            "position_count": self.position_count(),
            "total_cost": round(self.total_cost(), 2),
            "positions": {
                code: {
                    "quantity": pos.quantity,
                    "avg_cost": round(pos.avg_cost, 2),
                    "buy_date": pos.buy_date,
                }
                for code, pos in self.positions.items()
            }
        }
