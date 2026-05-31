# -*- coding: utf-8 -*-
"""
腾讯港股行情适配器
数据源：腾讯行情API (qt.gtimg.cn) — hk前缀
返回：港股实时价格/PE/PB/市值/换手率/52周范围
"""

import logging
from datetime import datetime
from typing import Any, Dict

import urllib.request

from L2_data_enrich.adapters.base import DataSourceAdapter

logger = logging.getLogger("L2.adapters.hk")


class TencentHKAdapter(DataSourceAdapter):
    """港股腾讯行情适配器"""

    name = "腾讯港股API"
    market = "HK"
    description = "港股实时行情：价格/PE/PB/市值/换手率/52周范围"

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        # 转换代码为5位腾讯格式
        code5 = code.strip().lstrip('hkHK').zfill(5)
        url = f'http://qt.gtimg.cn/q=hk{code5}'

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode('gbk', errors='replace')

            parts = raw.strip().strip('"').split('~')
            if len(parts) < 52:
                raise RuntimeError(f"腾讯港股API字段不足({len(parts)}): {code}")

            price = float(parts[3]) if parts[3] else 0
            prev_close = float(parts[4]) if parts[4] else 0

            outer = float(parts[7]) if parts[7] and parts[7] != '-' else 0
            inner = float(parts[8]) if parts[8] and parts[8] != '-' else 0
            outer_inner_ratio = round(outer / inner, 2) if inner > 0 else None

            return {
                'name': parts[1],
                'code': parts[2],
                'price': price,
                'prev_close': prev_close,
                'change_pct': float(parts[32]) if parts[32] else 0,
                'open': float(parts[5]) if parts[5] else 0,
                'high': float(parts[33]) if parts[33] else 0,
                'low': float(parts[34]) if parts[34] else 0,
                'volume': float(parts[6]) if parts[6] else 0,
                'amount': float(parts[37]) if parts[37] else 0,
                'turnover': float(parts[43]) if parts[43] else 0,
                'pe': float(parts[51]) if parts[51] and parts[51] != '-' else None,
                'pb': float(parts[50]) if parts[50] and parts[50] != '-' else None,
                'market_cap': float(parts[45]) if parts[45] else 0,
                'week52_high': float(parts[48]) if parts[48] else 0,
                'week52_low': float(parts[49]) if parts[49] else 0,
                'outer_disk': outer,
                'inner_disk': inner,
                'outer_inner_ratio': outer_inner_ratio,
                '_source': f"腾讯港股API({datetime.now().strftime('%H:%M')})",
            }
        except Exception as e:
            logger.warning(f"  [腾讯港股] 获取失败 {code}: {e}")
            return self._fail()
