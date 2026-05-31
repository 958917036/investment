"""
TEST-L2-1: test_l2_data_integrity
验证 fetch_batch 返回完整5维数据（资金流、基本面、技术面、板块、事件）
对10只样例股票调用 fetch_batch，验证每只股票5个维度数据完整且类型正确。
PASS标准：10只全部成功返回，5个维度数据字段齐全。
"""
import pytest, sys, os

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)
sys.path.insert(0, f"{WD}/L2_data_enrich")

import importlib
import L2_data_enrich.data_fetcher as df_module
importlib.reload(df_module)

from L2_data_enrich.data_fetcher import fetch_batch


class TestL2DataIntegrity:
    """L2 数据完整性测试"""

    def test_fetch_batch_10_stocks_all_dimensions(self, sample_stocks_10):
        """
        测试10只股票，验证5个维度数据全部返回且字段齐全
        """
        results = fetch_batch(sample_stocks_10, max_stocks=10)

        assert len(results) == 10, f"期望返回10条，实际{len(results)}"

        for stock in results:
            code = stock.get("code", "")
            name = stock.get("name", "")
            data = stock.get("data", {})

            # 基本检查
            assert data, f"{code}({name}): data不应为空"

            # 维度1: 资金流
            mf = data.get("moneyflow_data")
            assert mf is not None, f"{code}: moneyflow_data缺失"
            assert "main_net_flow_5d" in mf, f"{code}: moneyflow_data缺少main_net_flow_5d"

            # 维度2: 基本面
            fin = data.get("fundamental_data")
            assert fin is not None, f"{code}: fundamental_data缺失"
            assert "roe" in fin, f"{code}: fundamental_data缺少roe"
            assert "pb" in fin, f"{code}: fundamental_data缺少pb"

            # 维度3: 技术面
            tech = data.get("technical_data")
            assert tech is not None, f"{code}: technical_data缺失"
            assert tech.get("price", 0) > 0, f"{code}: price应大于0"

            # 维度4: 板块数据
            sector = data.get("sector_data")
            assert sector is not None, f"{code}: sector_data缺失"
            assert isinstance(sector, dict), f"{code}: sector_data应为dict"

            # 维度5: 事件数据
            event = data.get("event_data")
            assert event is not None, f"{code}: event_data缺失"
            assert isinstance(event, dict), f"{code}: event_data应为dict"

    def test_moneyflow_source_attribution(self, sample_stocks_10):
        """
        验证资金流数据来源标注正确
        """
        results = fetch_batch(sample_stocks_10, max_stocks=10)
        for stock in results:
            code = stock.get("code", "")
            mf = stock.get("data", {}).get("moneyflow_data", {})
            src = mf.get("_source", "")
            assert src, f"{code}: moneyflow_data._source不应为空"
            known_sources = ["BaoStock", "腾讯", "EM", "eastmoney", ""]
            assert any(s in src for s in ["BaoStock", "腾讯", "EM", "eastmoney"]), \
                f"{code}: 未知资金流来源: {src}"

    def test_fundamental_source_attribution(self, sample_stocks_10):
        """
        验证基本面数据来源标注正确
        """
        results = fetch_batch(sample_stocks_10, max_stocks=10)
        for stock in results:
            code = stock.get("code", "")
            fin = stock.get("data", {}).get("fundamental_data", {})
            src = fin.get("_source", "")
            assert src, f"{code}: fundamental_data._source不应为空"

    def test_no_type_error_in_source_field(self, sample_stocks_10):
        """
        验证 _source 字段不会出现 "None + string" TypeError
        （这是之前修复的 bug：fin_data.get("_source") + " + " + qq_data.get("_source")）
        """
        results = fetch_batch(sample_stocks_10, max_stocks=10)
        for stock in results:
            code = stock.get("code", "")
            fin = stock.get("data", {}).get("fundamental_data", {})
            src = str(fin.get("_source", ""))
            assert "None" not in src, f"{code}: _source字段包含字符串'None': {src}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])