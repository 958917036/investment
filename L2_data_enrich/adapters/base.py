# -*- coding: utf-8 -*-
"""
L2数据层 — 适配器基类
所有数据源统一适配器接口，保证返回格式一致

标准返回格式：
{
    "_source": "数据源名称",
    "_quality": "ok" | "degraded" | "fail",
    "_fetch_time_ms": 120,
    # 业务数据字段（每个适配器不同）
}

质量定义：
- ok:       数据完整，从主数据源获取
- degraded: 数据部分或降级（从备份/估算源获取）
- fail:     数据获取失败，返回空dict或含缺失标注
"""

import time
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("L2.adapters")


class DataQuality(Enum):
    OK = "ok"           # 正常
    DEGRADED = "degraded"  # 降级（部分数据来自备份）
    FAIL = "fail"       # 失败


class DataSourceAdapter(ABC):
    """数据源适配器基类"""

    name: str = "BaseAdapter"     # 适配器名称（子类必须定义）
    market: str = "CN"          # 适用市场：CN/HK/US
    description: str = ""        # 数据源描述

    def __init__(self):
        self._last_fetch_time_ms: Optional[float] = None

    def fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        """
        获取数据。子类实现具体逻辑。
        返回标准格式 dict，包含 _source / _quality 字段。
        """
        t0 = time.time()
        try:
            result = self._fetch(code, **kwargs)
            self._last_fetch_time_ms = (time.time() - t0) * 1000
            return self._wrap_result(result, quality=DataQuality.OK)
        except Exception as e:
            logger.warning(f"  [{self.name}] 获取失败 {code}: {e}")
            return self._wrap_result({}, quality=DataQuality.FAIL, error=str(e))

    @abstractmethod
    def _fetch(self, code: str, **kwargs) -> Dict[str, Any]:
        """子类必须实现的具体获取逻辑"""

    def _wrap_result(
        self,
        data: Dict[str, Any],
        quality: DataQuality,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """将业务数据包装为标准返回格式"""
        wrapped = dict(data)
        wrapped["_source"] = self.name
        wrapped["_quality"] = quality.value
        wrapped["_fetch_time_ms"] = round(self._last_fetch_time_ms or 0, 1)
        if error:
            wrapped["_error"] = error
        return wrapped

    def _degraded(self, data: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
        """返回降级数据"""
        wrapped = self._wrap_result(data, quality=DataQuality.DEGRADED)
        if reason:
            wrapped["_degraded_reason"] = reason
        return wrapped

    def _fail(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """返回失败数据"""
        return self._wrap_result(data or {}, quality=DataQuality.FAIL)


class MarketDataHub:
    """
    市场数据中枢 — 工厂类，根据市场返回对应适配器组合

    用法：
        hub = MarketDataHub.create("CN")
        realtime = hub.fetch_realtime("600519")
        moneyflow = hub.fetch_moneyflow("600519")
    """

    def __init__(self, market: str):
        self.market = market
        self._adapters: Dict[str, DataSourceAdapter] = {}

    @staticmethod
    def create(market: str) -> "MarketDataHub":
        """根据市场类型创建数据中枢"""
        if market == "CN":
            from L2_data_enrich.adapters.cn import (
                TencentCNAdapter,
                BaoStockAdapter,
                EastMoneyAdapter,
                AkShareCNAdapter,
            )
            hub = MarketDataHub("CN")
            hub.register("realtime", TencentCNAdapter())
            hub.register("moneyflow", EastMoneyAdapter())
            hub.register("technical", BaoStockAdapter())
            hub.register("fundamental", AkShareCNAdapter())
            hub.register("sector", AkShareCNAdapter())
            hub.register("event", AkShareCNAdapter())
            return hub

        elif market == "HK":
            from L2_data_enrich.adapters.hk import (
                TencentHKAdapter,
                AkShareHKAdapter,
                MFICalcAdapter,
            )
            hub = MarketDataHub("HK")
            hub.register("realtime", TencentHKAdapter())
            hub.register("moneyflow", MFICalcAdapter())
            hub.register("technical", AkShareHKAdapter())
            hub.register("fundamental", AkShareHKAdapter())
            # institution/sector/event 注册专用adapter（暂无真实数据源则注册空适配器）
            # 暂时注册AkShareHKAdapter，它没有这些方法，基类会返回错误字典（不再是静默fallback）
            hub.register("institution", AkShareHKAdapter())
            hub.register("sector", AkShareHKAdapter())
            hub.register("event", TencentHKAdapter())  # 无专属事件源，降级到行情
            return hub

        elif market == "US":
            from L2_data_enrich.adapters.us import (
                YahooFinanceAdapter,
                FinvizAdapter,
                USMFICalcAdapter,
            )
            hub = MarketDataHub("US")
            hub.register("realtime", YahooFinanceAdapter())
            hub.register("moneyflow", USMFICalcAdapter())
            hub.register("technical", YahooFinanceAdapter())
            hub.register("fundamental", FinvizAdapter())
            hub.register("sector", FinvizAdapter())
            hub.register("institution", FinvizAdapter())  # finviz提供机构持仓数据
            hub.register("event", YahooFinanceAdapter())  # 无专属事件源
            return hub

        else:
            raise ValueError(f"不支持的市场类型: {market}")

    def register(self, key: str, adapter: DataSourceAdapter):
        """注册适配器"""
        self._adapters[key] = adapter

    def get(self, key: str) -> Optional[DataSourceAdapter]:
        """获取已注册的适配器"""
        return self._adapters.get(key)

    # ── 统一数据获取接口 ───────────────────────────────────────

    def fetch_realtime(self, code: str) -> Dict[str, Any]:
        adapter = self._adapters.get("realtime")
        if not adapter:
            return {"_source": "数据暂缺", "_quality": "fail", "_error": "无实时行情适配器"}
        return adapter.fetch(code)

    def fetch_moneyflow(self, code: str, days: int = 20) -> Dict[str, Any]:
        adapter = self._adapters.get("moneyflow")
        if not adapter:
            return {"_source": "数据暂缺", "_quality": "fail", "_error": "无资金流向适配器"}
        if hasattr(adapter, '_fetch_moneyflow'):
            return adapter._fetch_moneyflow(code, days=days)
        return adapter.fetch(code, days=days)

    def fetch_technical(self, code: str) -> Dict[str, Any]:
        adapter = self._adapters.get("technical")
        if not adapter:
            return {"_source": "数据暂缺", "_quality": "fail", "_error": "无技术指标适配器"}
        return adapter.fetch(code)

    def fetch_fundamental(self, code: str) -> Dict[str, Any]:
        adapter = self._adapters.get("fundamental")
        if not adapter:
            return {"_source": "数据暂缺", "_quality": "fail", "_error": "无基本面适配器"}
        # 优先使用专属_fetch_financial方法，否则回退到通用fetch
        if hasattr(adapter, '_fetch_financial'):
            return adapter._fetch_financial(code)
        return adapter.fetch(code)

    def fetch_sector(self, code: str) -> Dict[str, Any]:
        adapter = self._adapters.get("sector")
        if not adapter:
            return {"_source": "数据暂缺", "_quality": "fail", "_error": "无板块适配器"}
        if hasattr(adapter, '_fetch_sector'):
            return adapter._fetch_sector(code)
        return {"_source": adapter.name, "_quality": "fail", "_error": f"adapter {adapter.name} 不支持 sector 数据"}

    def fetch_events(self, code: str) -> Dict[str, Any]:
        adapter = self._adapters.get("event")
        if not adapter:
            return {"_source": "数据暂缺", "_quality": "fail", "_error": "无事件适配器"}
        if hasattr(adapter, '_fetch_event'):
            return adapter._fetch_event(code)
        return adapter.fetch(code)

    def fetch_institution(self, code: str) -> Dict[str, Any]:
        """获取机构持仓数据（HK无免费数据；US通过finviz）"""
        adapter = self._adapters.get("institution")
        if not adapter:
            return {"_source": "数据暂缺", "_quality": "fail", "_error": "无机构持仓适配器"}
        if hasattr(adapter, '_fetch_institution'):
            return adapter._fetch_institution(code)
        return {"_source": adapter.name, "_quality": "fail", "_error": f"adapter {adapter.name} 不支持 institution 数据"}

    def fetch_all(self, code: str, name: str = "") -> Dict[str, Any]:
        """
        一次性获取所有维度数据，返回标准化结构。
        用于直接替代现有 fetch_all() 函数。
        """
        realtime = self.fetch_realtime(code)
        tech = self.fetch_technical(code)
        mf = self.fetch_moneyflow(code)
        fund = self.fetch_fundamental(code)
        sector = self.fetch_sector(code)
        events = self.fetch_events(code)

        return {
            "moneyflow_data": mf,
            "technical_data": tech,
            "fundamental_data": fund,
            "sector_data": sector,
            "event_data": events,
            "_realtime": realtime,  # 保留实时行情供L4使用
            "_market": self.market,
        }
