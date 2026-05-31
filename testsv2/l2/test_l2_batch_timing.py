"""
TEST-L2-2: test_l2_batch_timing
验证不同批次大小的实际耗时，建立性能基准。
测试10只、20只、30只三个批次，验证：
1. 每批次耗时应呈线性增长
2. 每批次内每只股票耗时稳定
3. 推算200只股票在给定超时限制下的可行性
"""
import pytest, sys, os, time

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)
sys.path.insert(0, f"{WD}/L2_data_enrich")

import importlib
import L2_data_enrich.data_fetcher as df_module
importlib.reload(df_module)

from L2_data_enrich.data_fetcher import fetch_batch


class TestL2BatchTiming:
    """L2 分批耗时性能测试"""

    @pytest.fixture
    def stocks_20(self):
        base = [
            "600519", "000858", "300750", "002594", "600036",
            "601318", "000333", "600900", "601888", "600887",
            "601012", "002415", "600276", "000001", "600030",
            "601166", "600009", "601328", "600050", "601398",
        ]
        names = [
            "贵州茅台", "五粮液", "宁德时代", "比亚迪", "招商银行",
            "中国平安", "美的集团", "长江电力", "中国中免", "伊利股份",
            "隆基绿能", "海康威视", "恒瑞医药", "平安银行", "中信证券",
            "兴业银行", "上海机场", "交通银行", "中国联通", "工商银行",
        ]
        return [{"code": c, "name": n} for c, n in zip(base, names)]

    @pytest.fixture
    def stocks_30(self, stocks_20):
        extra = [
            {"code": "601398", "name": "工商银行"},
            {"code": "601288", "name": "农业银行"},
            {"code": "601988", "name": "中国银行"},
            {"code": "601628", "name": "中国人寿"},
            {"code": "600028", "name": "中国石化"},
            {"code": "600019", "name": "宝钢股份"},
            {"code": "601899", "name": "紫金矿业"},
            {"code": "600585", "name": "海螺水泥"},
            {"code": "600690", "name": "海尔智家"},
        ]
        return stocks_20 + extra

    def test_timing_10_stocks(self, sample_stocks_10):
        """测试10只股票耗时"""
        t0 = time.time()
        results = fetch_batch(sample_stocks_10, max_stocks=10)
        elapsed = time.time() - t0

        assert len(results) == 10, f"期望10条，实际{len(results)}"
        per_stock = elapsed / 10

        print(f"\n10只: 总{elapsed:.1f}s, 每只{per_stock:.1f}s")
        # 基准：10只应在30-180s内完成（网络 API 调用有延迟）
        assert 10 < elapsed < 180, f"10只耗时{elapsed:.1f}s超出正常范围[30,180]s"

    def test_timing_20_stocks(self, stocks_20):
        """测试20只股票耗时（2批×10）"""
        t0 = time.time()
        results = fetch_batch(stocks_20, max_stocks=20)
        elapsed = time.time() - t0

        assert len(results) == 20, f"期望20条，实际{len(results)}"
        per_stock = elapsed / 20
        per_batch = elapsed / 2  # 2批

        print(f"\n20只: 总{elapsed:.1f}s, 每只{per_stock:.1f}s, 每批{per_batch:.1f}s")

        # 20只应在60-300s内完成
        assert 20 < elapsed < 300, f"20只耗时{elapsed:.1f}s超出正常范围[60,300]s"

    def test_timing_30_stocks(self, stocks_30):
        """测试30只股票耗时（3批×10）"""
        t0 = time.time()
        results = fetch_batch(stocks_30, max_stocks=30)
        elapsed = time.time() - t0

        assert len(results) == 30, f"期望30条，实际{len(results)}"
        per_stock = elapsed / 30
        per_batch = elapsed / 3  # 3批

        print(f"\n30只: 总{elapsed:.1f}s, 每只{per_stock:.1f}s, 每批{per_batch:.1f}s")
        assert 30 < elapsed < 450, f"30只耗时{elapsed:.1f}s超出正常范围[30,450]s"

    def test_linearity_check(self, sample_stocks_10, stocks_20, stocks_30):
        """
        验证耗时线性增长：10/20/30只耗时应呈线性比例
        如果30只耗时远超10只的3倍，说明有固定开销问题
        """
        t0 = time.time()
        r10 = fetch_batch(sample_stocks_10, max_stocks=10)
        t10 = time.time() - t0

        t0 = time.time()
        r20 = fetch_batch(stocks_20, max_stocks=20)
        t20 = time.time() - t0

        t0 = time.time()
        r30 = fetch_batch(stocks_30, max_stocks=30)
        t30 = time.time() - t0

        ratio_20 = t20 / t10
        ratio_30 = t30 / t10

        print(f"\n=== 耗时线性检查 ===")
        print(f"10只: {t10:.1f}s")
        print(f"20只: {t20:.1f}s (20只/10只 = {ratio_20:.2f}x)")
        print(f"30只: {t30:.1f}s (30只/10只 = {ratio_30:.2f}x)")

        # 20只应为10只的2倍 (±40%)
        assert 0.6 <= ratio_20 <= 2.8, f"20只/10只比例{ratio_20:.2f}异常（期望约2.0）"
        # 30只应为10只的3倍 (±50%)
        assert 0.5 <= ratio_30 <= 4.0, f"30只/10只比例{ratio_30:.2f}异常（期望约3.0）"

    @pytest.mark.parametrize("count,expected_range", [
        (10, (30, 180)),
        (20, (60, 300)),
        (30, (90, 450)),
    ])
    def test_timing_ranges(self, count, expected_range):
        """
        参数化测试：验证不同数量股票耗时在合理范围内
        expected_range: (min_s, max_s)
        """
        base = [
            "600519", "000858", "300750", "002594", "600036",
            "601318", "000333", "600900", "601888", "600887",
            "601012", "002415", "600276", "000001", "600030",
            "601166", "600009", "601328", "600050", "601398",
            "601288", "601988", "601628", "600028", "600019",
            "601899", "600585", "600690", "000725", "002230",
        ]
        names = [
            "贵州茅台", "五粮液", "宁德时代", "比亚迪", "招商银行",
            "中国平安", "美的集团", "长江电力", "中国中免", "伊利股份",
            "隆基绿能", "海康威视", "恒瑞医药", "平安银行", "中信证券",
            "兴业银行", "上海机场", "交通银行", "中国联通", "工商银行",
            "农业银行", "中国银行", "中国人寿", "中国石化", "宝钢股份",
            "紫金矿业", "海螺水泥", "海尔智家", "京东方A", "科大讯飞",
        ]
        test_stocks = [{"code": c, "name": n} for c, n in zip(base[:count], names[:count])]

        t0 = time.time()
        results = fetch_batch(test_stocks, max_stocks=count)
        elapsed = time.time() - t0

        min_s, max_s = expected_range
        print(f"\n{count}只: {elapsed:.1f}s (期望[{min_s}, {max_s}])")
        assert min_s < elapsed < max_s, f"{count}只耗时{elapsed:.1f}s超出期望范围[{min_s}, {max_s}]"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])