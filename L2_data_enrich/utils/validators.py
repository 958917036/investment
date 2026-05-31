#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2数据完整性校验模块

职责：校验L2数据层的各维度数据完整性，避免部分数据得出错误结果。

校验规则来自 l2_data_validation.json 配置
"""

import json
import os
from typing import Dict, List, Optional, Tuple
from enum import Enum

# ======================== 路径配置 ========================

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "main", "config", "l2_data_validation.json"
)


class DataQuality(Enum):
    """数据质量等级"""
    OK = "ok"           # 所有关键维度数据完整
    DEGRADED = "degraded"  # 部分维度数据缺失
    FAIL = "fail"       # 关键维度数据缺失


def _load_validation_config() -> dict:
    """加载数据校验配置"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_validation_config_cache = None
def get_validation_config() -> dict:
    global _validation_config_cache
    if _validation_config_cache is None:
        _validation_config_cache = _load_validation_config()
    return _validation_config_cache


def validate_stock_data(stock_data: dict) -> dict:
    """
    校验单只股票数据的完整性

    Args:
        stock_data: 包含各维度数据的字典

    Returns:
        {
            "is_valid": bool,
            "quality": DataQuality,
            "missing_dimensions": List[str],
            "missing_fields": Dict[str, List[str]],
            "quality_issues": List[str],
            "completeness_score": float  # 0.0 ~ 1.0
        }
    """
    cfg = get_validation_config()
    dim_reqs = cfg.get("dimension_requirements", {})
    quality_thresholds = cfg.get("quality_thresholds", {})

    result = {
        "is_valid": True,
        "quality": DataQuality.OK,
        "missing_dimensions": [],
        "missing_fields": {},
        "quality_issues": [],
        "completeness_score": 1.0
    }

    # 检查每个维度
    total_dimensions = len(dim_reqs)
    missing_dims = 0

    for dim_name, dim_config in dim_reqs.items():
        dim_data = stock_data.get(f"{dim_name}_data")

        if dim_data is None:
            result["missing_dimensions"].append(dim_name)
            result["missing_fields"][dim_name] = dim_config.get("required_fields", [])
            missing_dims += 1
            continue

        # 检查必填字段
        required_fields = dim_config.get("required_fields", [])
        missing_fields = []
        for field in required_fields:
            if field not in dim_data or dim_data[field] is None:
                missing_fields.append(field)

        if missing_fields:
            result["missing_fields"][dim_name] = missing_fields
            result["quality_issues"].append(f"{dim_name}缺失字段: {missing_fields}")

        # 检查数据范围
        issues = _check_data_range(dim_name, dim_data, quality_thresholds)
        result["quality_issues"].extend(issues)

    # 计算完整性得分
    if total_dimensions > 0:
        result["completeness_score"] = (total_dimensions - missing_dims) / total_dimensions

    # 判断有效性
    critical_fields_cfg = cfg.get("critical_fields", {})
    for field_name, field_cfg in critical_fields_cfg.items():
        if field_cfg.get("required", False):
            data = stock_data.get(field_name)
            if data is None:
                result["is_valid"] = False
                result["quality"] = DataQuality.FAIL
                break

    if result["missing_dimensions"]:
        result["is_valid"] = False
        result["quality"] = DataQuality.FAIL
    elif result["missing_fields"]:
        result["is_valid"] = False
        result["quality"] = DataQuality.DEGRADED
    elif result["quality_issues"]:
        result["quality"] = DataQuality.DEGRADED

    return result


def _check_data_range(dim_name: str, dim_data: dict, thresholds: dict) -> List[str]:
    """检查数据值是否在合理范围内"""
    issues = []

    if dim_name == "moneyflow":
        # 检查资金流数据范围
        main_net_flow = dim_data.get("main_net_flow_5d")
        if main_net_flow is not None:
            if abs(main_net_flow) > 10_000_000_000:  # 超过100亿
                issues.append(f"main_net_flow_5d数值异常: {main_net_flow}")

        ratio = dim_data.get("outer_inner_ratio")
        if ratio is not None:
            min_ratio = thresholds.get("min_outer_inner_ratio", 0)
            max_ratio = thresholds.get("max_outer_inner_ratio", 2.0)
            if ratio < min_ratio or ratio > max_ratio:
                issues.append(f"outer_inner_ratio超出范围: {ratio}")

    elif dim_name == "technical":
        # 检查技术指标范围
        rsi = dim_data.get("rsi")
        if rsi is not None:
            min_rsi = thresholds.get("min_rsi", 0)
            max_rsi = thresholds.get("max_rsi", 100)
            if rsi < min_rsi or rsi > max_rsi:
                issues.append(f"RSI超出范围: {rsi}")

        sector_rank = dim_data.get("sector_rank")
        if sector_rank is not None:
            min_rank = thresholds.get("min_sector_rank", 0)
            max_rank = thresholds.get("max_sector_rank", 100)
            if sector_rank < min_rank or sector_rank > max_rank:
                issues.append(f"sector_rank超出范围: {sector_rank}")

    return issues


def validate_batch(stocks_data: List[dict]) -> Dict[str, dict]:
    """
    批量校验多只股票数据

    Returns:
        {
            "stock_code": {...validation_result...},
            ...
        }
    """
    results = {}
    for stock in stocks_data:
        code = stock.get("code") or stock.get("stock_code", "unknown")
        results[code] = validate_stock_data(stock)
    return results


def get_data_quality_summary(validation_results: Dict[str, dict]) -> dict:
    """
    获取批量校验的汇总报告

    Returns:
        {
            "total": int,
            "ok_count": int,
            "degraded_count": int,
            "fail_count": int,
            "avg_completeness": float,
            "common_missing_fields": Dict[str, int]
        }
    """
    summary = {
        "total": len(validation_results),
        "ok_count": 0,
        "degraded_count": 0,
        "fail_count": 0,
        "avg_completeness": 0.0,
        "common_missing_fields": {}
    }

    if not validation_results:
        return summary

    total_completeness = 0.0

    for code, result in validation_results.items():
        if result["quality"] == DataQuality.OK:
            summary["ok_count"] += 1
        elif result["quality"] == DataQuality.DEGRADED:
            summary["degraded_count"] += 1
        elif result["quality"] == DataQuality.FAIL:
            summary["fail_count"] += 1

        total_completeness += result.get("completeness_score", 0)

        # 统计缺失字段
        for dim_name, fields in result.get("missing_fields", {}).items():
            for field in fields:
                key = f"{dim_name}.{field}"
                summary["common_missing_fields"][key] = summary["common_missing_fields"].get(key, 0) + 1

    summary["avg_completeness"] = total_completeness / len(validation_results)

    return summary


if __name__ == "__main__":
    # 测试
    test_data = {
        "moneyflow_data": {
            "main_net_flow_5d": 100_000_000,
            "outer_inner_ratio": 0.85
        },
        "technical_data": {
            "ma_status": "bullish",
            "macd_status": "golden_cross",
            "rsi": 55,
            "sector_rank": 30
        },
        "fundamental_data": {
            "pe": 25.5,
            "pb": 3.2,
            "roe": 15.0
        },
        "sector_data": {
            "sector_rank": 25,
            "sector_strength": 0.65
        }
    }

    result = validate_stock_data(test_data)
    print("数据校验结果:")
    print(f"  有效: {result['is_valid']}")
    print(f"  质量: {result['quality'].value}")
    print(f"  完整性: {result['completeness_score']:.1%}")
    if result.get("missing_dimensions"):
        print(f"  缺失维度: {result['missing_dimensions']}")
    if result.get("quality_issues"):
        print(f"  问题: {result['quality_issues']}")
