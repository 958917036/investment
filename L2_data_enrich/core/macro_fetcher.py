#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观数据采集器 — CPI/GDP/PMI/美林时钟定位

数据源：
- AkShare: macro_china_cpi(), macro_china_gdp(), macro_china_pmi()
- 数据更新时间：通常在每月结束后2周内

用途：
- 早报宏观摘要
- 个股分析宏观环境判断
- 美林时钟周期定位
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger("macro_fetcher")


class MacroFetcher:
    """
    宏观数据采集器
    
    获取并解析：
    - CPI/PPI 通胀数据
    - GDP 增长数据
    - PMI 景气度数据
    - 美林时钟定位
    """

    def __init__(self, use_cache: bool = True, cache_hours: int = 24):
        self.use_cache = use_cache
        self.cache_hours = cache_hours
        self._cache: Dict[str, Any] = {}

    def fetch_all(self) -> Dict[str, Any]:
        """
        获取所有宏观数据
        
        Returns:
            {
                "cpi": {...},
                "gdp": {...},
                "pmi": {...},
                "merrill_clock": {...},
                "summary": "...",
                "fetch_time": "..."
            }
        """
        fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        cpi = self._fetch_cpi()
        gdp = self._fetch_gdp()
        pmi = self._fetch_pmi()
        clock = self._merrill_clock(cpi, gdp, pmi)
        
        result = {
            "cpi": cpi,
            "gdp": gdp,
            "pmi": pmi,
            "merrill_clock": clock,
            "fetch_time": fetch_time,
        }
        
        # 生成摘要
        result["summary"] = self._generate_summary(cpi, gdp, pmi, clock)
        
        return result

    def _fetch_cpi(self) -> Dict[str, Any]:
        """获取CPI数据"""
        cache_key = "cpi"
        if self.use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            import akshare as ak
            df = ak.macro_china_cpi()
            
            # 找最新数据
            latest = df.iloc[0].to_dict() if len(df) > 0 else {}
            
            # 提取同比值（主要看这个）
            cpi_yoy = latest.get("全国-同比增长", 0)
            cpi_mom = latest.get("全国-环比增长", 0)
            month = latest.get("月份", "")
            
            result = {
                "month": month,
                "cpi_yoy": float(cpi_yoy) if cpi_yoy else 0.0,
                "cpi_mom": float(cpi_mom) if cpi_mom else 0.0,
                "source": "AkShare macro_china_cpi",
                "fetch_date": datetime.now().strftime("%Y-%m-%d"),
                "interpretation": self._interpret_cpi(float(cpi_yoy) if cpi_yoy else 0),
            }
            
            self._cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.warning(f"CPI获取失败: {e}")
            return {
                "month": "",
                "cpi_yoy": None,
                "cpi_mom": None,
                "source": "AkShare macro_china_cpi",
                "error": str(e),
                "interpretation": "数据获取失败",
            }

    def _fetch_gdp(self) -> Dict[str, Any]:
        """获取GDP数据"""
        cache_key = "gdp"
        if self.use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            import akshare as ak
            df = ak.macro_china_gdp()
            
            # 最新季度
            latest = df.iloc[0].to_dict() if len(df) > 0 else {}
            
            gdp_yoy = latest.get("国内生产总值-同比增长", 0)
            quarter = latest.get("季度", "")
            
            result = {
                "quarter": quarter,
                "gdp_yoy": float(gdp_yoy) if gdp_yoy else 0.0,
                "gdp_absolute": latest.get("国内生产总值-绝对值", 0),
                "source": "AkShare macro_china_gdp",
                "fetch_date": datetime.now().strftime("%Y-%m-%d"),
                "interpretation": self._interpret_gdp(float(gdp_yoy) if gdp_yoy else 0),
            }
            
            self._cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.warning(f"GDP获取失败: {e}")
            return {
                "quarter": "",
                "gdp_yoy": None,
                "gdp_absolute": None,
                "source": "AkShare macro_china_gdp",
                "error": str(e),
                "interpretation": "数据获取失败",
            }

    def _fetch_pmi(self) -> Dict[str, Any]:
        """获取PMI数据"""
        cache_key = "pmi"
        if self.use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            import akshare as ak
            df = ak.macro_china_pmi()
            
            latest = df.iloc[0].to_dict() if len(df) > 0 else {}
            
            mfg_pmi = latest.get("制造业-指数", 0)
            non_mfg_pmi = latest.get("非制造业-指数", 0)
            month = latest.get("月份", "")
            
            result = {
                "month": month,
                "manufacturing_pmi": float(mfg_pmi) if mfg_pmi else None,
                "nonmanufacturing_pmi": float(non_mfg_pmi) if non_mfg_pmi else None,
                "source": "AkShare macro_china_pmi",
                "fetch_date": datetime.now().strftime("%Y-%m-%d"),
                "interpretation": self._interpret_pmi(float(mfg_pmi) if mfg_pmi else 50),
            }
            
            self._cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.warning(f"PMI获取失败: {e}")
            return {
                "month": "",
                "manufacturing_pmi": None,
                "nonmanufacturing_pmi": None,
                "source": "AkShare macro_china_pmi",
                "error": str(e),
                "interpretation": "数据获取失败",
            }

    def _merrill_clock(
        self,
        cpi: Dict[str, Any],
        gdp: Dict[str, Any],
        pmi: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        美林时钟定位
        
        周期判断：
        - 复苏期: GDP↑ + CPI↓
        - 过热期: GDP↑ + CPI↑
        - 滞胀期: GDP↓ + CPI↑
        - 衰退期: GDP↓ + CPI↓
        
        PMI作为辅助验证（>50 = 扩张，<50 = 收缩）
        """
        gdp_val = gdp.get("gdp_yoy", 0) or 0
        cpi_val = cpi.get("cpi_yoy", 0) or 0
        mfg_pmi = pmi.get("manufacturing_pmi") or 50
        
        # 判断方向
        gdp_growing = gdp_val > 0  # GDP正增长
        cpi_rising = cpi_val > 0   # 通胀上行
        
        # PMI验证
        pmi_expansion = mfg_pmi > 50
        
        # 确定周期
        if gdp_growing and not cpi_rising:
            phase = "复苏期"
            assets = "股票 > 债券 > 现金 > 商品"
            description = "经济上行 + 通胀下行，政策宽松，企业盈利恢复"
        elif gdp_growing and cpi_rising:
            phase = "过热期"
            assets = "商品 > 股票 > 现金 > 债券"
            description = "经济上行 + 通胀上行，产能不足，价格上涨"
        elif not gdp_growing and cpi_rising:
            phase = "滞胀期"
            assets = "现金 > 商品 > 债券 > 股票"
            description = "经济下行 + 通胀上行，政策两难，盈利下滑"
        else:  # not gdp_growing and not cpi_rising
            phase = "衰退期"
            assets = "债券 > 现金 > 股票 > 商品"
            description = "经济下行 + 通胀下行，政策刺激，利率下降"
        
        # PMI作为辅助
        pmi_signal = "扩张" if pmi_expansion else "收缩"
        
        return {
            "phase": phase,
            "gdp_direction": "上行" if gdp_growing else "下行",
            "cpi_direction": "上行" if cpi_rising else "下行",
            "pmi_signal": pmi_signal,
            "recommended_assets": assets,
            "description": description,
            "confidence": "high" if (gdp_val != 0 and cpi_val != 0) else "low",
        }

    def _interpret_cpi(self, cpi_yoy: float) -> str:
        """解读CPI"""
        if cpi_yoy > 5:
            return "高通通胀，警惕加息"
        elif cpi_yoy > 3:
            return "温和通胀，正常区间"
        elif cpi_yoy > 1:
            return "低通胀，接近通缩边缘"
        elif cpi_yoy > 0:
            return "轻微通胀，消费偏弱"
        else:
            return "通缩风险，宽松政策预期"

    def _interpret_gdp(self, gdp_yoy: float) -> str:
        """解读GDP"""
        if gdp_yoy > 6:
            return "高增长，强劲扩张"
        elif gdp_yoy > 4:
            return "中速增长，稳健"
        elif gdp_yoy > 0:
            return "低速增长，动能偏弱"
        else:
            return "负增长，衰退风险"

    def _interpret_pmi(self, pmi: float) -> str:
        """解读PMI"""
        if pmi > 55:
            return "强劲扩张，过热风险"
        elif pmi > 50:
            return "温和扩张，景气"
        elif pmi > 45:
            return "收缩初期，动能减弱"
        else:
            return "明显收缩，衰退风险"

    def _generate_summary(
        self,
        cpi: Dict[str, Any],
        gdp: Dict[str, Any],
        pmi: Dict[str, Any],
        clock: Dict[str, Any]
    ) -> str:
        """生成人类可读的宏观摘要"""
        lines = []
        lines.append(f"【宏观环境】{datetime.now().strftime('%Y年%m月')}")
        
        # GDP
        gdp_val = gdp.get("gdp_yoy")
        if gdp_val is not None:
            lines.append(f"• GDP: {gdp_val:.1f}% ({gdp.get('interpretation', '')})")
        
        # CPI
        cpi_val = cpi.get("cpi_yoy")
        if cpi_val is not None:
            lines.append(f"• CPI同比: {cpi_val:.1f}% ({cpi.get('interpretation', '')})")
        
        # PMI
        mfg_pmi = pmi.get("manufacturing_pmi")
        if mfg_pmi is not None:
            lines.append(f"• 制造业PMI: {mfg_pmi:.1f} ({pmi.get('interpretation', '')})")
        
        # 美林时钟
        lines.append(f"• 美林时钟: {clock.get('phase', '未知')}")
        lines.append(f"  → {clock.get('description', '')}")
        lines.append(f"  → 建议配置: {clock.get('recommended_assets', '')}")
        
        return "\n".join(lines)


# ─── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    fetcher = MacroFetcher()
    
    print("获取宏观数据...")
    result = fetcher.fetch_all()
    
    print(f"\n{fetcher._generate_summary(result['cpi'], result['gdp'], result['pmi'], result['merrill_clock'])}")
    print(f"\n数据获取时间: {result['fetch_time']}")
    print(f"数据来源: AkShare宏观数据")
