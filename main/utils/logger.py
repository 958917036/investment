#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志工具（所有层共享）
所有模块调用外部依赖（HTTP/akshare/文件IO）必须使用此工具打印日志
日志同时输出到 stdout 和文件，方便实时查看和日志文件分析

使用方式：
    import sys, os
    BASE = os.path.expanduser("~/.hermes/investment")
    sys.path.insert(0, os.path.join(BASE, "main", "utils"))
    from logger import log_start, log_end, log_fail, log_source, info

日志文件：~/.hermes/investment/logs/hermes.log

日志规范：
- 每个外部调用必须标注 data_source（如 akshare、tencent、yahoo、baostock 等）
- 格式：[source=xxx] 用于快速筛选特定数据源的日志
- 成功：log_source(source, operation, True, result_detail)
- 失败：log_source(source, operation, False, reason)
"""
import os
import datetime

# 日志文件路径（项目根目录）
BASE_DIR = os.path.expanduser("~/.hermes/investment")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "hermes.log")

# 确保日志目录存在
os.makedirs(LOG_DIR, exist_ok=True)


def _write_log(level: str, module: str, message: str):
    """写入日志到文件和 stdout"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_line = f"[{timestamp}] [{level}] [{module}] {message}"

    # 输出到 stdout（实时可见）
    print(log_line)

    # 写入文件（持久化）
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception:
        pass  # 日志写入失败不影响主流程


def info(module: str, message: str):
    """普通信息日志"""
    _write_log("INFO", module, message)


def warn(module: str, message: str):
    """警告日志"""
    _write_log("WARN", module, message)


def error(module: str, message: str):
    """错误日志"""
    _write_log("ERROR", module, message)


def debug(module: str, message: str):
    """调试日志（生产环境可关闭）"""
    _write_log("DEBUG", module, message)


def log_start(module: str, operation: str, detail: str = ""):
    """标记操作开始"""
    msg = f"开始操作: {operation}"
    if detail:
        msg += f" - {detail}"
    info(module, msg)


def log_end(module: str, operation: str, result: str = ""):
    """标记操作完成"""
    msg = f"完成操作: {operation}"
    if result:
        msg += f" - {result}"
    info(module, msg)


def log_fail(module: str, operation: str, reason: str = ""):
    """标记操作失败"""
    msg = f"操作失败: {operation}"
    if reason:
        msg += f" - {reason}"
    error(module, msg)


def log_source(module: str, source: str, operation: str, success: bool, detail: str = ""):
    """
    数据源调用日志（用于快速识别哪个数据源成功/失败）

    Args:
        module: 模块名，如 "l2_runner", "market_fetcher"
        source: 数据源名，如 "akshare", "tencent", "yahoo", "baostock"
        operation: 操作描述，如 "获取行情", "查询财务数据"
        success: True=成功，False=失败
        detail: 详情（如返回条数或错误原因）

    日志格式示例：
        [INFO] [l2_runner] [source=akshare] 获取股票列表成功 - 800条
        [ERROR] [l2_runner] [source=tencent] 获取行情失败 - Connection timeout
    """
    status = "成功" if success else "失败"
    msg = f"[source={source}] {operation}{status}"
    if detail:
        msg += f" - {detail}"

    if success:
        info(module, msg)
    else:
        error(module, msg)
