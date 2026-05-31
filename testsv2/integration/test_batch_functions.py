"""
神农系统批量查询函数 — 单元测试
=====================================
每个批量函数必须满足:
1. chunk_size 参数（可配置，默认合理值）
2. 内部显式分批 for i in range(0, N, chunk_size)
3. timeout 只做兜底保护，不做主要流量控制

fund_flow: 串行（enumerate）东方财富 API 不支持并发
其他 4 个: 分批并行（for i in range）

运行: python3 tests/test_batch_functions.py
"""

import inspect, sys
sys.path.insert(0, '/Users/guchuang/.hermes/investment')

from L2_data_enrich import data_fetcher as df


def test_chunking_signature():
    """验证所有批量函数有 chunk_size 参数"""
    # chunk_size=None 表示从配置加载（设计目标），允许 None 或合理整数值
    funcs = [
        ('batch_query_fund_flow', None),        # 从配置加载
        ('batch_query_events', None),           # 从配置加载
        ('batch_query_sector', None),           # 从配置加载
        ('batch_query_financials', None),       # 从配置加载
        ('query_baostock_daily_batch', 50),     # 硬编码默认值（BaoStock登录开销大）
    ]
    for name, expected_default in funcs:
        fn = getattr(df, name)
        sig = inspect.signature(fn)
        assert 'chunk_size' in sig.parameters, f"{name}: 缺少 chunk_size 参数"
        default = sig.parameters['chunk_size'].default
        assert default == expected_default, f"{name}: chunk_size 默认值应为 {expected_default}, 实际 {default}"
        print(f"✅ {name}: chunk_size={default}")


def test_chunking_implementation():
    """验证所有批量函数内部有显式分批/串行循环"""
    # fund_flow: 串行 enumerate（东方财富不支持并发）
    fn = getattr(df, 'batch_query_fund_flow')
    src = inspect.getsource(fn)
    assert 'for idx, code in enumerate' in src, "batch_query_fund_flow: 缺少 enumerate 串行循环"
    assert 'random.uniform' in src, "batch_query_fund_flow: 缺少 random.uniform 防限流"
    print("✅ batch_query_fund_flow: 串行+防限流验证通过")

    # 其他 4 个: 必须用 for i in range 分批
    parallel_funcs = ['batch_query_events', 'batch_query_sector',
                      'batch_query_financials', 'query_baostock_daily_batch']
    for name in parallel_funcs:
        fn = getattr(df, name)
        src = inspect.getsource(fn)
        checks = [
            ('range(0, len(', 'range(0, len(' in src),
            ('for i in range', 'for i in range' in src),
            ('chunk assignment', 'chunk' in src and ('= codes[' in src or '= codes_list[' in src or '= chunk_keys' in src)),
            ('inner for over chunk', 'in chunk' in src or 'in chunk_keys' in src),
        ]
        for check_name, result in checks:
            assert result, f"{name}: {check_name} — 缺少显式分批循环"
        print(f"✅ {name}: 显式分批循环验证通过")


def test_no_syntax_errors():
    """验证文件无语法错误"""
    import subprocess
    result = subprocess.run(
        ['python3', '-c',
         'import sys; sys.path.insert(0,"/Users/guchuang/.hermes/investment"); import L2_data_enrich.data_fetcher'],
        capture_output=True, text=True,
        cwd='/Users/guchuang/.hermes/investment'
    )
    assert result.returncode == 0, f"语法错误: {result.stderr[:200]}"
    print(f"✅ 语法检查通过")


if __name__ == '__main__':
    print("=" * 50)
    print("测试1: chunk_size 参数签名")
    print("=" * 50)
    test_chunking_signature()

    print("\n" + "=" * 50)
    print("测试2: 分批/串行循环实现")
    print("=" * 50)
    test_chunking_implementation()

    print("\n" + "=" * 50)
    print("测试3: 语法正确性")
    print("=" * 50)
    test_no_syntax_errors()

    print("\n" + "=" * 50)
    print("✅ 全部通过")
    print("=" * 50)
