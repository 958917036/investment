# -*- coding: utf-8 -*-
"""
AkShare A股适配器 — 财务指标 / 板块数据 / 新闻舆情
数据源：AkShare SDK (东方财富)
"""

import re
import logging
from datetime import datetime
from typing import Any, Dict

import akshare as ak
import pandas as pd

from L2_data_enrich.adapters.base import DataSourceAdapter, DataQuality

logger = logging.getLogger("L2.adapters.cn")


class AkShareCNAdapter(DataSourceAdapter):
    """
    AkShare A股综合适配器。
    支持三个维度：
    - fundamental: 财务指标（ROE/毛利率/营收增速）
    - sector: 板块强度（行业排名/板块涨幅）
    - event: 新闻舆情（利好事件/研报数量）
    """

    name = "AkShare"
    market = "CN"
    description = "A股财务指标 + 板块数据 + 新闻舆情"

    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        dim = kwargs.get("dimension", "fundamental")
        if dim == "sector":
            return self._fetch_sector(code)
        elif dim == "event":
            return self._fetch_events(code)
        else:
            return self._fetch_fundamental(code)

    def _fetch_fundamental(self, code: str) -> Dict[str, Any]:
        """获取财务指标"""
        code_clean = re.sub(r'[^0-9]', '', code)

        try:
            fin = ak.stock_financial_analysis_indicator(symbol=code_clean, start_year="2024")
            if fin.empty:
                raise RuntimeError(f"财务数据为空: {code}")

            latest = fin.iloc[-1]

            def get_val(name):
                for col in fin.columns:
                    if name in col:
                        val = latest[col]
                        if isinstance(val, (int, float)) and val != val:  # NaN
                            return None
                        return val
                return None

            roe = get_val("净资产收益率")
            if roe is None:
                roe = get_val("加权净资产收益率")
            if isinstance(roe, (int, float)) and roe != roe:
                roe = None

            net_profit_yoy = get_val("净利润增长率")
            if isinstance(net_profit_yoy, (int, float)) and net_profit_yoy != net_profit_yoy:
                net_profit_yoy = None

            return {
                "roe": round(float(roe), 2) if roe is not None else None,
                "net_profit_yoy": round(float(net_profit_yoy), 2) if net_profit_yoy is not None else None,
                "gross_margin": get_val("毛利率"),
                "net_margin": get_val("净利率"),
                "asset_liability_ratio": get_val("资产负债率"),
                "eps": get_val("每股收益"),
                "revenue_growth": get_val("主营收入增长率"),
                "_source": f"AkShare财务指标({datetime.now().strftime('%Y-%m-%d')})",
            }
        except Exception as e:
            logger.warning(f"  [AkShare财务] 失败 {code}: {e}")
            return self._fail()

    def _fetch_sector(self, code: str) -> Dict[str, Any]:
        """获取板块数据"""
        code_clean = re.sub(r'[^0-9]', '', code)
        result = {
            "sector_rank": 50,
            "sector_fund_flow": 0,
            "sector_count": 0,
            "related_sector": "",
            "_source": "AkShare板块数据",
        }

        try:
            sector_df = ak.stock_board_industry_name_em()
            if sector_df is not None and not sector_df.empty:
                result["sector_count"] = len(sector_df)
                # 找涨跌幅列
                chg_col = None
                for c in ['涨跌幅', '今日涨跌幅', '最新涨跌幅']:
                    if c in sector_df.columns:
                        chg_col = c
                        break
                if chg_col is None and len(sector_df.columns) > 1:
                    chg_col = sector_df.columns[1]

                # 找行业
                name_col = None
                for c in ['板块名称', '名称', '行业']:
                    if c in sector_df.columns:
                        name_col = c
                        break
                if name_col is None:
                    name_col = sector_df.columns[0]

                # 粗略匹配
                keywords_sh = ['食品', '饮料', '白酒', '医药', '银行', '保险', '券商', '地产', '汽车', '煤炭', '钢铁', '化工', '电力', '军工']
                keywords_sz = ['创业板', '新能源', '医药', '电子', '软件', '通信', '半导体', '医疗器械']
                prefix = 'sh' if code.startswith(('6', '8')) else 'sz'
                keywords = keywords_sh if prefix == 'sh' else keywords_sz

                matched_rows = sector_df[sector_df[name_col].astype(str).str.contains('|'.join(keywords), na=False)]
                if not matched_rows.empty:
                    result["related_sector"] = matched_rows[name_col].iloc[0]
                    if chg_col:
                        result["sector_fund_flow"] = float(matched_rows[chg_col].iloc[0])

                # 简单板块排名（按涨跌幅排序）
                if chg_col:
                    sector_df_sorted = sector_df.sort_values(chg_col, ascending=False)
                    sector_df_sorted = sector_df_sorted.reset_index(drop=True)
                    matched_indices = sector_df_sorted[sector_df_sorted[name_col] == result["related_sector"]].index
                    if not matched_indices.empty:
                        rank = matched_indices[0] + 1
                        result["sector_rank"] = round((1 - rank / result["sector_count"]) * 100, 1)

            return result
        except Exception as e:
            logger.warning(f"  [AkShare板块] 失败 {code}: {e}")
            return self._degraded(result, reason=f"获取失败: {e}")

    def _fetch_events(self, code: str) -> Dict[str, Any]:
        """获取新闻舆情"""
        code_clean = re.sub(r'[^0-9]', '', code)
        try:
            news_df = ak.stock_news_em(symbol=code_clean)
            positive_events = []
            report_count_30d = 0

            if news_df is not None and not news_df.empty:
                recent = news_df.head(10)
                for _, row in recent.iterrows():
                    title = str(row.get("title", ""))
                    if any(k in title for k in ['业绩', '增长', '签约', '合作', '突破', '获批', '增持', '回购']):
                        positive_events.append(title[:50])

            return {
                "positive_events": positive_events,
                "analyst_rating": None,
                "report_count_30d": report_count_30d,
                "_source": f"AkShare新闻舆情({datetime.now().strftime('%Y-%m-%d')})",
            }
        except Exception as e:
            logger.warning(f"  [AkShare事件] 失败 {code}: {e}")
            return self._fail()
