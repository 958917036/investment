"""
testsv2/l2/ — L2 层测试

共享 fixtures 从 tests/conftest.py 导入。
"""
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))

# 导入共享 fixtures（sample_stocks_10 等）
from tests.conftest import (
    sample_stocks_10,
    sample_stocks_20,
    assert_moneyflow_data,
    assert_fundamental_data,
    assert_technical_data,
    assert_stock_enriched,
)

__all__ = [
    "sample_stocks_10",
    "sample_stocks_20",
    "assert_moneyflow_data",
    "assert_fundamental_data",
    "assert_technical_data",
    "assert_stock_enriched",
]