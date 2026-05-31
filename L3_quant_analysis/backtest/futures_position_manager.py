# -*- coding: utf-8 -*-
"""
期货持仓管理器 — R4 多资产支持

核心差异 vs A股PositionManager：
- 无 T+1 限制（期货当日可平仓）
- 保证金制度（margin）：占用合约价值的 N%
- 杠杆效应：保证金率 10% → 10 倍杠杆
- 多空双向：持有多头/空头均可
- 每日结算：当日盈亏当日划转

支持：
- 商品期货（农产品/金属/能化）
- 金融期货（指数/国债）

使用方式：
    pm = FuturesPositionManager()
    pm.set_margin_rate("RU2506", 0.10)   # 橡胶保证金10%

    # 买入开多（long）
    pm.buy("RU2506", price=15000, date="2024-01-02", quantity=1)

    # 卖出开空（short）
    pm.sell_short("RU2506", price=15000, date="2024-01-02", quantity=1)

    # 当日可平仓（无T+1限制）
    pm.can_sell("RU2506", "2024-01-02")  # True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Literal

logger = logging.getLogger("backtest.futures_position")


@dataclass
class FuturesPosition:
    """期货持仓"""
    code: str
    direction: Literal["long", "short"]   # 多头或空头
    quantity: int                           # 持仓手数
    avg_price: float                        # 开仓均价
    buy_date: str                           # 开仓日期
    margin_rate: float = 0.10               # 保证金率
    contract_multiplier: float = 1.0       # 合约乘数（每手对应数量）

    @property
    def contract_value(self) -> float:
        """合约名义价值 = 价格 × 乘数 × 数量"""
        return self.avg_price * self.contract_multiplier * self.quantity

    @property
    def margin_required(self) -> float:
        """占用保证金 = 名义价值 × 保证金率"""
        return self.contract_value * self.margin_rate


@dataclass
class FuturesTradeRecord:
    """期货交易记录"""
    date: str
    code: str
    direction: Literal["open_long", "open_short", "close_long", "close_short"]
    price: float
    quantity: int
    margin: float
    pnl: float = 0.0          # 平仓盈亏（仅平仓时有）


class FuturesPositionManager:
    """
    期货持仓管理器

    规则：
    - 无 T+1 限制（当日可平）
    - 保证金交易（默认10%，可按合约设置）
    - 多空双向持仓
    - 手续费默认万0.5（单边）
    """

    # 默认保证金率（品种级别，可覆盖）
    DEFAULT_MARGIN_RATES: Dict[str, float] = {
        "IF": 0.12,   # 沪深300指数期货 12%
        "IC": 0.12,   # 中证500指数期货 12%
        "IM": 0.12,   # 中证1000指数期货 12%
        "IH": 0.12,   # 上证50指数期货 12%
        "T": 0.02,    # 10年期国债期货 2%
        "TF": 0.02,   # 5年期国债期货 2%
        "RU": 0.10,   # 橡胶 10%
        "RB": 0.08,   # 螺纹钢 8%
        "HC": 0.08,   # 热卷 8%
        "FG": 0.07,   # 玻璃 7%
        "SA": 0.09,   # 纯碱 9%
        "SR": 0.07,   # 白糖 7%
        "CF": 0.07,   # 棉花 7%
        "TA": 0.06,   # PTA 6%
        "MA": 0.08,   # 甲醇 8%
        "V": 0.07,    # PVC 7%
        "PP": 0.06,   # 聚丙烯 6%
        "L": 0.06,    # 塑料 6%
        "J": 0.20,    # 焦炭 20%（利润率高，波动大）
        "JM": 0.20,   # 焦煤 20%
        "I": 0.08,    # 铁矿石 8%
    }

    # 合约乘数（每手吨数/口）
    CONTRACT_MULTIPLIERS: Dict[str, float] = {
        "IF": 300.0,
        "IC": 200.0,
        "IM": 200.0,
        "IH": 300.0,
        "T": 10000.0,
        "TF": 10000.0,
        "RU": 10.0,
        "RB": 10.0,
        "HC": 10.0,
        "FG": 20.0,
        "SA": 20.0,
        "SR": 10.0,
        "CF": 5.0,
        "TA": 5.0,
        "MA": 10.0,
        "V": 5.0,
        "PP": 5.0,
        "L": 5.0,
        "J": 100.0,
        "JM": 60.0,
        "I": 100.0,
    }

    def __init__(self, commission_rate: float = 0.00005, slippage: float = 0.0001):
        """
        Args:
            commission_rate: 手续费率（单边，默认万0.5 = 0.00005）
            slippage: 滑点率（默认万一）
        """
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.positions: Dict[str, FuturesPosition] = {}   # code → FuturesPosition
        self.trade_history: list = []
        self._margin_rates: Dict[str, float] = {}          # code → 覆盖保证金率
        self._multipliers: Dict[str, float] = {}          # code → 覆盖乘数

    # ── 保证金/乘数设置 ────────────────────────────────────────

    def set_margin_rate(self, code: str, rate: float) -> None:
        """设置单合钓保证金率（如 0.10 = 10%）"""
        self._margin_rates[code] = rate

    def set_contract_multiplier(self, code: str, multiplier: float) -> None:
        """设置合约乘数（每手对应数量）"""
        self._multipliers[code] = multiplier

    def _get_margin_rate(self, code: str) -> float:
        prefix = code[:2] if len(code) >= 2 else code
        return self._margin_rates.get(code) or self.DEFAULT_MARGIN_RATES.get(prefix, 0.10)

    def _get_multiplier(self, code: str) -> float:
        prefix = code[:2] if len(code) >= 2 else code
        return self._multipliers.get(code) or self.CONTRACT_MULTIPLIERS.get(prefix, 1.0)

    # ── 基础操作 ────────────────────────────────────────────────

    def buy(self, code: str, price: float, date: str, quantity: int) -> FuturesPosition:
        """
        买入开多仓

        Args:
            code: 期货代码（如 RU2506）
            price: 买入价格
            date: 交易日期
            quantity: 买入手数
        """
        pos = FuturesPosition(
            code=code,
            direction="long",
            quantity=quantity,
            avg_price=price,
            buy_date=date,
            margin_rate=self._get_margin_rate(code),
            contract_multiplier=self._get_multiplier(code),
        )

        if code in self.positions:
            existing = self.positions[code]
            if existing.direction != "long":
                raise ValueError(f"{code} 已有空头持仓，不能同时持有多头")
            total_cost = existing.avg_price * existing.quantity + price * quantity
            total_qty = existing.quantity + quantity
            existing.avg_price = total_cost / total_qty
            existing.quantity = total_qty
        else:
            self.positions[code] = pos

        margin = pos.margin_required
        self.trade_history.append(FuturesTradeRecord(
            date=date, code=code,
            direction="open_long",
            price=price, quantity=quantity,
            margin=margin,
        ))
        logger.debug(f"[Futures] 开多 {code} ×{quantity} @{price}, 保证金={margin:.2f}")
        return pos

    def sell_short(self, code: str, price: float, date: str, quantity: int) -> FuturesPosition:
        """
        卖出开空仓

        Args:
            code: 期货代码
            price: 卖出价格
            date: 交易日期
            quantity: 卖出手数
        """
        pos = FuturesPosition(
            code=code,
            direction="short",
            quantity=quantity,
            avg_price=price,
            buy_date=date,
            margin_rate=self._get_margin_rate(code),
            contract_multiplier=self._get_multiplier(code),
        )

        if code in self.positions:
            existing = self.positions[code]
            if existing.direction != "short":
                raise ValueError(f"{code} 已有多头持仓，不能同时持有空头")
            total_cost = existing.avg_price * existing.quantity + price * quantity
            total_qty = existing.quantity + quantity
            existing.avg_price = total_cost / total_qty
            existing.quantity = total_qty
        else:
            self.positions[code] = pos

        margin = pos.margin_required
        self.trade_history.append(FuturesTradeRecord(
            date=date, code=code,
            direction="open_short",
            price=price, quantity=quantity,
            margin=margin,
        ))
        logger.debug(f"[Futures] 开空 {code} ×{quantity} @{price}, 保证金={margin:.2f}")
        return pos

    def sell(self, code: str, quantity: Optional[int] = None) -> Optional[FuturesTradeRecord]:
        """
        平多仓（卖出平仓）

        Args:
            code: 期货代码
            quantity: 平仓手数（None=全部平）
        """
        if code not in self.positions:
            return None
        pos = self.positions[code]
        if pos.direction != "long":
            return None

        close_qty = quantity if quantity is not None else pos.quantity
        close_qty = min(close_qty, pos.quantity)

        # 平仓盈亏 = (平仓价 - 开仓价) × 乘数 × 数量（多头）
        pnl = (0 - pos.avg_price) * pos.contract_multiplier * close_qty  # 占位，由外部按实际成交价计算
        record = FuturesTradeRecord(
            date="", code=code,
            direction="close_long",
            price=0.0, quantity=close_qty,
            margin=0.0, pnl=pnl,
        )

        if close_qty >= pos.quantity:
            del self.positions[code]
        else:
            pos.quantity -= close_qty

        return record

    def buy_cover(self, code: str, quantity: Optional[int] = None) -> Optional[FuturesTradeRecord]:
        """
        平空仓（买入平仓）

        Args:
            code: 期货代码
            quantity: 平仓手数（None=全部平）
        """
        if code not in self.positions:
            return None
        pos = self.positions[code]
        if pos.direction != "short":
            return None

        close_qty = quantity if quantity is not None else pos.quantity
        close_qty = min(close_qty, pos.quantity)

        pnl = (pos.avg_price - 0) * pos.contract_multiplier * close_qty  # 占位
        record = FuturesTradeRecord(
            date="", code=code,
            direction="close_short",
            price=0.0, quantity=close_qty,
            margin=0.0, pnl=pnl,
        )

        if close_qty >= pos.quantity:
            del self.positions[code]
        else:
            pos.quantity -= close_qty

        return record

    # ── 规则检查（无T+1） ───────────────────────────────────────

    def can_sell(self, code: str, current_date: str) -> bool:
        """期货无 T+1 限制，当日可平仓"""
        return code in self.positions

    def can_buy(self, code: str, current_date: str) -> bool:
        """期货无任何当日买入限制"""
        return True

    # ── 保证金检查 ──────────────────────────────────────────────

    def margin_required(self, code: str) -> float:
        """获取持仓占用保证金"""
        pos = self.positions.get(code)
        if pos is None:
            return 0.0
        return pos.margin_required

    def total_margin(self) -> float:
        """全部持仓占用保证金"""
        return sum(p.margin_required for p in self.positions.values())

    def margin_utilization(self, available_margin: float) -> float:
        """保证金利用率 = 占用保证金 / 可用保证金"""
        if available_margin <= 0:
            return 1.0
        return self.total_margin() / available_margin

    def is_margin_call(self, equity: float, maintenance_rate: float = 0.75) -> bool:
        """
        判断是否触发追保（保证金不足）。

        Args:
            equity: 账户权益（含浮动盈亏）
            maintenance_rate: 维持保证金率（通常为开仓保证金的75%）

        Returns:
            True=触发追保，需要补充保证金
        """
        total_used = self.total_margin()
        maintenance = total_used * maintenance_rate
        return equity < maintenance

    # ── 盈亏计算 ────────────────────────────────────────────────

    def unrealized_pnl(
        self,
        prices: Dict[str, float],
        direction: str = "long"
    ) -> float:
        """
        计算浮动盈亏

        Args:
            prices: {code: current_price}
            direction: 持仓方向
        """
        total = 0.0
        for code, pos in self.positions.items():
            price = prices.get(code, pos.avg_price)
            if pos.direction == "long":
                pnl = (price - pos.avg_price) * pos.contract_multiplier * pos.quantity
            else:
                pnl = (pos.avg_price - price) * pos.contract_multiplier * pos.quantity
            total += pnl
        return total

    def realized_pnl(self) -> float:
        """已平仓盈亏合计"""
        return sum(r.pnl for r in self.trade_history if r.pnl != 0)

    # ── 持仓摘要 ────────────────────────────────────────────────

    def summary(self) -> dict:
        """持仓摘要"""
        return {
            "position_count": len(self.positions),
            "total_margin": round(self.total_margin(), 2),
            "positions": {
                code: {
                    "direction": pos.direction,
                    "quantity": pos.quantity,
                    "avg_price": round(pos.avg_price, 2),
                    "margin": round(pos.margin_required, 2),
                    "margin_rate": pos.margin_rate,
                    "multiplier": pos.contract_multiplier,
                }
                for code, pos in self.positions.items()
            }
        }
