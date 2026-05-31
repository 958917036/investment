#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨层共享枚举 — 所有层共用

定义：
- QualityLevel：数据质量等级（ok/degraded/fail）
- Market：市场代码（CN/HK/US）
- Decision：投资决策（BUY/WATCH/REJECT）
- Verdict：辩论裁决（看多/谨慎看多/中性观望/谨慎看空/看空）
- Grade：五维评分等级（A/B/C/D）
"""
from dataclasses import dataclass, field, asdict, fields
from enum import Enum
from typing import Any, Dict, List, Optional


class QualityLevel(str, Enum):
    """数据质量等级"""
    OK = "ok"
    DEGRADED = "degraded"
    FAIL = "fail"

    def to_dict(self) -> str:
        return self.value


class Market(str, Enum):
    """市场代码"""
    CN = "CN"
    HK = "HK"
    US = "US"


class Decision(str, Enum):
    """投资决策"""
    BUY = "BUY"
    WATCH = "WATCH"
    REJECT = "REJECT"


class Verdict(str, Enum):
    """辩论裁决"""
    看多 = "看多"
    谨慎看多 = "谨慎看多"
    中性观望 = "中性观望"
    谨慎看空 = "谨慎看空"
    看空 = "看空"


class Grade(str, Enum):
    """五维评分等级"""
    A = "A"
    B = "B"
    C = "C"
    D = "D"


# ── 通用基类 ──────────────────────────────────────────────────────────────

class BaseContract:
    """所有 Contract 的基类，提供 dict 序列化/反序列化能力"""

    def to_dict(self) -> dict:
        """
        序列化为普通 dict，用于 JSON 存储和跨层传输。
        枚举类型会被转为字符串值。
        """
        d = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, Enum):
                d[f.name] = v.value
            elif hasattr(v, "to_dict"):
                d[f.name] = v.to_dict()
            elif isinstance(v, list) and len(v) > 0 and hasattr(v[0], "to_dict"):
                d[f.name] = [item.to_dict() for item in v]
            elif isinstance(v, dict):
                d[f.name] = _dict_serialize(v)
            else:
                d[f.name] = v
        return d

    @classmethod
    def from_dict(cls, d: dict):
        """
        从普通 dict 反序列化（宽松加载，忽略未知字段）。
        子类可覆盖此方法以处理特殊字段。
        """
        if not d:
            return cls()
        allowed = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in allowed}
        # 处理枚举字段
        for f in fields(cls):
            if f.name in filtered and isinstance(f.type, type) and issubclass(f.type, Enum):
                if isinstance(filtered[f.name], str):
                    try:
                        filtered[f.name] = f.type(filtered[f.name])
                    except ValueError:
                        # 忽略无效枚举值
                        pass
        return cls(**filtered)


def _dict_serialize(obj: Any) -> Any:
    """递归序列化 dict 中的特殊类型"""
    if isinstance(obj, dict):
        return {k: _dict_serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_dict_serialize(item) for item in obj]
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return obj


def _safe_enum(value: Any, enum_cls: type, default: Any) -> Any:
    """安全地将值转为枚举类型，失败时返回默认值"""
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default