# -*- coding: utf-8 -*-
"""
因子库 — 18 个预置 A 股因子

因子类型：
- value: 估值因子
- growth: 成长因子
- quality: 质量因子
- momentum: 动量因子
- moneyflow: 资金流因子
- technical: 技术因子
- volatility: 波动率因子

使用方式：
    from L3_quant_analysis.factor import FactorLibrary

    lib = FactorLibrary()
    lib.bind_computer()  # 绑定 FactorComputer，实现 compute_fn

    # 计算单因子
    df = lib.compute_factor("roe", ["600519", "000858"], "2025-01-01", "2026-01-01")
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Callable, Any

logger = logging.getLogger("factor.library")


@dataclass
class Factor:
    """
    因子定义

    Attributes:
        name: 因子名称（英文，代码中使用）
        description: 因子中文描述
        factor_type: 因子类型
        category: 因子细分类别
        data_source: 数据来源描述
        required_fields: 计算所需的原始字段
        compute_fn: 计算函数 (stock_codes, start_date, end_date) -> pd.DataFrame
    """
    name: str
    description: str
    factor_type: Literal[
        "value", "growth", "quality", "momentum", "moneyflow", "technical", "volatility"
    ]
    category: str = ""
    data_source: str = ""
    required_fields: List[str] = field(default_factory=list)
    compute_fn: Optional[Callable[..., Any]] = None


class FactorLibrary:
    """
    A股因子库

    预置 18 个因子，覆盖价值、成长、质量、动量、资金流、技术、波动率七个大类。

    使用方式：
        lib = FactorLibrary()
        lib.bind_computer()  # 绑定 FactorComputer，实现 compute_fn

        factor = lib.get_factor("roe")
        print(factor.description)  # 净资产收益率

        # 计算单因子
        df = lib.compute_factor("roe", ["600519", "000858"], "2025-01-01", "2026-01-01")

        # 获取某类型全部因子
        value_factors = lib.get_factors("value")
        for f in value_factors:
            print(f"  {f.name}: {f.description}")
    """

    def __init__(self):
        self.factors: Dict[str, Factor] = {}
        self._computer = None
        self._register_preset_factors()

    def bind_computer(self):
        """
        绑定 FactorComputer，将所有因子的 compute_fn 指向实际计算方法。
        必须在调用 compute_factor() 之前调用。
        """
        from L3_quant_analysis.factor.factor_computer import FactorComputer

        self._computer = FactorComputer()

        binding = {
            "pe_ttm": self._computer.compute_pe_ttm,
            "pb": self._computer.compute_pb,
            "ps_ttm": self._computer.compute_ps_ttm,
            "pcf": self._computer.compute_pcf,
            "revenue_growth": self._computer.compute_revenue_growth,
            "net_profit_growth": self._computer.compute_net_profit_growth,
            "eps_growth": self._computer.compute_eps_growth,
            "roe": self._computer.compute_roe,
            "gross_margin": self._computer.compute_gross_margin,
            "net_margin": self._computer.compute_net_margin,
            "asset_turnover": self._computer.compute_asset_turnover,
            "ret_20d": self._computer.compute_ret_20d,
            "ret_60d": self._computer.compute_ret_60d,
            "ret_120d": self._computer.compute_ret_120d,
            "main_net_flow_5d": self._computer.compute_main_net_flow_5d,
            "rsi_14": self._computer.compute_rsi_14,
            "macd_signal": self._computer.compute_macd_signal,
            "kdj": self._computer.compute_kdj,
            "vol_20d": self._computer.compute_vol_20d,
        }

        for name, fn in binding.items():
            if name in self.factors:
                self.factors[name].compute_fn = fn

        logger.info(f"因子计算器绑定完成: {len(binding)} 个因子已绑定 compute_fn")

    def compute_factor(
        self, name: str, stock_codes: List[str], start_date: str, end_date: str
    ) -> Optional["pd.DataFrame"]:
        """
        计算指定因子。

        Args:
            name: 因子名称（如 "roe"）
            stock_codes: 股票代码列表（如 ["600519", "000858"]）
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）

        Returns:
            pd.DataFrame: index=日期, columns=股票代码
        """
        if self._computer is None:
            logger.warning("FactorComputer 未绑定，请先调用 bind_computer()")
            return None

        factor = self.factors.get(name)
        if factor is None or factor.compute_fn is None:
            logger.warning(f"因子 {name} 不存在或 compute_fn 未绑定")
            return None

        return factor.compute_fn(stock_codes, start_date, end_date)

    def compute_all_factors(
        self, stock_codes: List[str], start_date: str, end_date: str
    ) -> Dict[str, "pd.DataFrame"]:
        """计算所有已绑定 compute_fn 的因子。"""
        results = {}
        for name, factor in self.factors.items():
            if factor.compute_fn is not None:
                try:
                    results[name] = factor.compute_fn(stock_codes, start_date, end_date)
                except Exception as e:
                    logger.warning(f"因子 {name} 计算失败: {e}")
        return results

    def _register_preset_factors(self):
        """注册 18 个预置因子（compute_fn 由 bind_computer 绑定）"""
        presets = [
            # ── 价值因子 (4个) ──────────────────────────
            Factor(
                name="pe_ttm",
                description="市盈率 TTM",
                factor_type="value",
                category="估值",
                data_source="BaoStock 利润表+日线",
                required_fields=["close", "net_profit", "shares"],
            ),
            Factor(
                name="pb",
                description="市净率",
                factor_type="value",
                category="估值",
                data_source="BaoStock 资产负债表+日线",
                required_fields=["close", "bvps"],
            ),
            Factor(
                name="ps_ttm",
                description="市销率 TTM",
                factor_type="value",
                category="估值",
                data_source="BaoStock 利润表+日线",
                required_fields=["close", "revenue", "shares"],
            ),
            Factor(
                name="pcf",
                description="PCF现金流比率",
                factor_type="value",
                category="估值",
                data_source="BaoStock 现金流量表+日线",
                required_fields=["close", "op_cash_flow", "shares"],
            ),

            # ── 成长因子 (3个) ──────────────────────────
            Factor(
                name="revenue_growth",
                description="营收增速",
                factor_type="growth",
                category="成长",
                data_source="BaoStock 利润表",
                required_fields=["revenue"],
            ),
            Factor(
                name="net_profit_growth",
                description="净利润增速",
                factor_type="growth",
                category="成长",
                data_source="BaoStock 利润表",
                required_fields=["netProfit"],
            ),
            Factor(
                name="eps_growth",
                description="EPS增速",
                factor_type="growth",
                category="成长",
                data_source="BaoStock 盈利能力数据",
                required_fields=["eps"],
            ),

            # ── 质量因子 (4个) ──────────────────────────
            Factor(
                name="roe",
                description="净资产收益率",
                factor_type="quality",
                category="盈利能力",
                data_source="BaoStock 杜邦分析",
                required_fields=["roe"],
            ),
            Factor(
                name="gross_margin",
                description="毛利率",
                factor_type="quality",
                category="盈利能力",
                data_source="BaoStock 利润表",
                required_fields=["revenue", "opCost"],
            ),
            Factor(
                name="net_margin",
                description="净利率",
                factor_type="quality",
                category="盈利能力",
                data_source="BaoStock 利润表",
                required_fields=["revenue", "netProfit"],
            ),
            Factor(
                name="asset_turnover",
                description="资产周转率",
                factor_type="quality",
                category="运营效率",
                data_source="BaoStock 资产负债表+利润表",
                required_fields=["revenue", "totalAssets"],
            ),

            # ── 动量因子 (3个) ──────────────────────────
            Factor(
                name="ret_20d",
                description="20日收益率",
                factor_type="momentum",
                category="动量",
                data_source="BaoStock 日线 close",
                required_fields=["close"],
            ),
            Factor(
                name="ret_60d",
                description="60日收益率",
                factor_type="momentum",
                category="动量",
                data_source="BaoStock 日线 close",
                required_fields=["close"],
            ),
            Factor(
                name="ret_120d",
                description="120日收益率",
                factor_type="momentum",
                category="动量",
                data_source="BaoStock 日线 close",
                required_fields=["close"],
            ),

            # ── 资金流因子 (1个) ─────────────────────────
            Factor(
                name="main_net_flow_5d",
                description="5日主力净流入",
                factor_type="moneyflow",
                category="资金流",
                data_source="BaoStock 资金流向",
                required_fields=["mainNetProjFlow"],
            ),

            # ── 技术因子 (2个) ──────────────────────────
            Factor(
                name="rsi_14",
                description="RSI-14",
                factor_type="technical",
                category="技术指标",
                data_source="BaoStock 日线 close",
                required_fields=["close"],
            ),
            Factor(
                name="macd_signal",
                description="MACD 信号",
                factor_type="technical",
                category="技术指标",
                data_source="BaoStock 日线 close",
                required_fields=["close"],
            ),
            Factor(
                name="kdj",
                description="KDJ 随机指标（K/D/J 三值）",
                factor_type="technical",
                category="技术指标",
                data_source="BaoStock 日线 high/low/close",
                required_fields=["high", "low", "close"],
            ),

            # ── 波动率因子 (1个) ────────────────────────
            Factor(
                name="vol_20d",
                description="20日年化波动率",
                factor_type="volatility",
                category="波动率",
                data_source="BaoStock 日线 close",
                required_fields=["close"],
            ),
        ]

        for f in presets:
            self.factors[f.name] = f

        logger.info(f"因子库初始化: {len(self.factors)} 个预置因子（compute_fn 待绑定）")

    def get_factor(self, name: str) -> Optional[Factor]:
        """获取指定因子"""
        return self.factors.get(name)

    def get_factors(self, factor_type: str) -> List[Factor]:
        """获取指定类型的所有因子"""
        return [f for f in self.factors.values() if f.factor_type == factor_type]

    def list_all_factors(self) -> List[Factor]:
        """列出全部因子"""
        return list(self.factors.values())

    def summary(self) -> Dict:
        """因子库摘要"""
        by_type = {}
        for f in self.factors.values():
            if f.factor_type not in by_type:
                by_type[f.factor_type] = []
            by_type[f.factor_type].append({
                "name": f.name,
                "description": f.description,
                "has_compute_fn": f.compute_fn is not None,
            })

        return {
            "total_count": len(self.factors),
            "by_type": by_type,
        }
