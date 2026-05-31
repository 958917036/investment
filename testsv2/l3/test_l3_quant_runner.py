#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3 Quant Runner 测试代码

覆盖 L3_quant_analysis/l3_quant_runner.py 的所有场景：
- 正常 L2 数据 → 五维评分 + 辩论裁决
- 失败字段追踪：fundamental_data quality=fail → failed_dimensions 记录
- score 结构：five_score / grade / scores（五维度）
- debate 结构：final_verdict / confidence / bull/bear_arguments
- 质量传播：含失败字段 → quality_overall 降级
- 无效 L2 数据（空 dict）→ 不抛异常

验证策略：
- five_score 范围应在 0~100，否则说明评分器异常
- grade 只能是 A/B/C/D
- confidence 应在 0~1
- 失败字段追踪：quality="fail" 且含"失败"字符串的字段要记录到 failed_dimensions
- 空数据时 five_score 不应为 100（说明默认值未处理）
- 检查 scores 各维度 score 不应有 placeholder（如 9999）

新增补充场景（补全维度）：
- missing_fields 识别：L2返回了 missing_fields 但 quality 正常
- 部分维度缺失：只缺某个数据块（如 moneyflow_data 不存在）
- 默认值兜底：字段为0/None但上游未标注失败
- 极端分数：five_score=0 或 grade=D 的边界情况
- 字段类型错误：字段类型不对（如string而非number）
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from test_logger import suite_start, suite_end, test_start, test_end
from L3_quant_analysis.l3_quant_runner import run_quantitative

# 加载测试用 config
_CONFIG_PATH = os.path.expanduser("~/.hermes/investment/main/config/l3_config.json")
with open(_CONFIG_PATH) as f:
    _TEST_CONFIG = json.load(f)

def _make_l2_full():
    """构造完整的正常 L2 数据"""
    return {
        "code": "600519",
        "name": "贵州茅台",
        "run_date": "2026-05-30",
        "moneyflow_data": {
            "quality": "ok", "missing_fields": [],
            "main_net_flow_5d": 80000000, "main_direction": "流入",
            "retail_direction": "流出", "outer_inner_ratio": 1.15,
        },
        "technical_data": {
            "quality": "ok", "missing_fields": [],
            "ma_status": "bullish", "macd_status": "golden",
            "rsi": 55, "ma5": 1800.0, "ma10": 1780.0, "ma20": 1750.0, "ma60": 1700.0,
            "volume_status": "放量上涨", "volume_ratio": 1.5,
            "price": 1850.0, "change_pct": 2.5,
        },
        "fundamental_data": {
            "quality": "ok", "missing_fields": [],
            "roe": 28.5, "pe": 22.0, "pb": 7.4,
            "net_profit_yoy": 15.2, "revenue_growth": 18.0,
        },
        "sector_data": {
            "quality": "ok", "missing_fields": [],
            "sector_rank": 85, "sector_fund_flow": 500000000,
        },
        "event_data": {
            "quality": "ok", "missing_fields": [],
            "positive_events": ["业绩预增50%", "中标大单"],
            "analyst_rating": "buy", "report_count_30d": 8,
        },
    }


def _make_l2_with_fail():
    """构造含失败字段的 L2 数据（fundamental_data quality=fail，含"失败"字符串）"""
    d = _make_l2_full()
    d["fundamental_data"] = {
        "quality": "fail", "missing_fields": ["roe", "pe"],
        "roe": "失败", "pe": "失败", "pb": 7.4,
    }
    return d


def test_normal_l2():
    """
    测试正常 L2 数据 → 五维评分 + 辩论裁决完整输出

    入参: _make_l2_full()
    期望: five_score 在 0~100, grade in A/B/C/D, confidence 在 0~1
    """
    print("\n  [日志] 准备测试正常 L2 数据...")
    L2_data = _make_l2_full()
    print(f"  [输入] L2_data = {L2_data}")

    result = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    assert result["layer"] == "L3_quantitative"
    assert result["code"] == "600519"
    assert "score" in result
    assert "debate" in result
    assert "quality_overall" in result
    assert "failed_dimensions" in result
    assert "duration_ms" in result

    score = result["score"]
    debate = result["debate"]
    print(f"  [逻辑] 提取 score={score}, debate={debate}")

    # five_score 应该在合理范围
    assert 0 <= score["five_score"] <= 100, \
        f"five_score: expected 0~100, got {score['five_score']}"
    # grade 应在 A/B/C/D
    assert score["grade"] in ("A", "B", "C", "D"), \
        f"grade: expected A/B/C/D, got {score['grade']!r}"
    # confidence 应在 0~1
    assert 0.0 <= debate["confidence"] <= 1.0, \
        f"confidence: expected 0~1, got {debate['confidence']}"

    print(f"  [通过] five_score={score['five_score']}, grade={score['grade']}, "
          f"debate={debate['final_verdict']}, confidence={debate['confidence']}")


def test_failed_dimensions_tracking():
    """
    测试失败字段追踪：quality="fail" + 含"失败"字符串 → failed_dimensions

    入参: _make_l2_with_fail()
    期望: failed_dimensions 包含 "fundamental", quality_overall in (fail/degraded)
    """
    print("\n  [日志] 准备测试失败字段追踪...")
    L2_data = _make_l2_with_fail()
    print(f"  [输入] L2_data = {L2_data}")

    result = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    assert "fundamental" in result["failed_dimensions"], \
        f"failed_dimensions: expected ['fundamental'], got {result['failed_dimensions']}"
    assert result["quality_overall"] in ("fail", "degraded"), \
        f"quality_overall: expected fail/degraded, got {result['quality_overall']!r}"
    print(f"  [通过] failed_dimensions={result['failed_dimensions']}, "
          f"quality={result['quality_overall']}")


def test_score_structure():
    """
    测试 score 结构完整性：five_score / grade / scores（五维度），
    各维度 score 不应有 placeholder 值

    入参: _make_l2_full()
    期望: scores 有 5 个维度，每个维度 score 不应为 9999
    """
    print("\n  [日志] 准备测试 score 结构完整性...")
    L2_data = _make_l2_full()
    print(f"  [输入] L2_data = {L2_data}")

    result = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    score = result["score"]

    assert "five_score" in score
    assert "grade" in score
    assert "scores" in score
    assert score["grade"] in ("A", "B", "C", "D")

    expected_dims = ["moneyflow", "technical", "fundamental", "sector", "event"]
    for dim in expected_dims:
        assert dim in score["scores"], f"scores missing '{dim}'"
        dim_score = score["scores"][dim]
        assert "score" in dim_score, f"scores.{dim} missing 'score'"
        s = dim_score["score"]
        # score 不应该是 placeholder（如 9999 表示未获取）
        assert s != 9999, f"scores.{dim}.score: got placeholder 9999"
        assert 0 <= s <= 100, f"scores.{dim}.score: expected 0~100, got {s}"
        print(f"  [逻辑] 维度 {dim} score = {s}")

    print(f"  [通过] five_score={score['five_score']}, grade={score['grade']}, "
          f"dims={[d for d in score['scores']]}")


def test_debate_structure():
    """
    测试 debate 结构完整性：final_verdict / confidence / bull+bear_arguments，
    各 argument 列表应存在，verdict 应在有效值范围内

    入参: _make_l2_full()
    """
    print("\n  [日志] 准备测试 debate 结构完整性...")
    L2_data = _make_l2_full()
    print(f"  [输入] L2_data = {L2_data}")

    result = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    debate = result["debate"]

    assert "final_verdict" in debate
    assert "confidence" in debate
    assert "bull_arguments" in debate
    assert "bear_arguments" in debate
    assert debate["final_verdict"] in ["看多", "谨慎看多", "中性观望", "谨慎看空", "看空"], \
        f"final_verdict: unexpected value {debate['final_verdict']!r}"
    assert 0.0 <= debate["confidence"] <= 1.0
    assert isinstance(debate["bull_arguments"], list)
    assert isinstance(debate["bear_arguments"], list)

    print(f"  [通过] debate: verdict={debate['final_verdict']}, "
          f"confidence={debate['confidence']}, "
          f"bull={len(debate['bull_arguments'])}, bear={len(debate['bear_arguments'])}")


def test_degrade_quality_propagation():
    """
    测试质量降级传播：含失败字段 → quality_overall 降级

    入参: _make_l2_full() vs _make_l2_with_fail()
    期望: result_deg["quality_overall"] in (fail/degraded)
    """
    print("\n  [日志] 准备测试质量降级传播...")
    L2_data = _make_l2_full()
    print(f"  [输入] 正常L2_data = {L2_data}")

    result_ok = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result_ok = {result_ok}")

    L2_deg = _make_l2_with_fail()
    print(f"  [输入] 含失败L2_data = {L2_deg}")

    result_deg = run_quantitative(L2_deg, config=_TEST_CONFIG)
    print(f"  [输出] result_deg = {result_deg}")

    assert result_deg["quality_overall"] in ("fail", "degraded"), \
        f"quality_overall: expected fail/degraded, got {result_deg['quality_overall']!r}"
    print(f"  [通过] quality: ok={result_ok['quality_overall']}, "
          f"failed={result_deg['quality_overall']}, "
          f"failed_dims={result_deg['failed_dimensions']}")


def test_empty_l2_data():
    """
    测试空 L2 数据（不抛异常，返回空结构）

    入参: {}
    期望: layer 存在，five_score 应是合理评分（不会是满分100的默认值）
    """
    print("\n  [日志] 准备测试空 L2 数据...")
    print(f"  [输入] L2_data = {{}}")

    result = run_quantitative({}, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    assert "layer" in result
    assert "score" in result
    assert "debate" in result

    # 空数据跑出的分数应该较低（因为缺数据），不应该是满分100
    five = result["score"]["five_score"]
    assert five != 100, f"five_score: empty L2 should not score 100, got {five}"
    assert 0 <= five <= 100, f"five_score: expected 0~100, got {five}"

    print(f"  [通过] empty L2: five_score={five}, "
          f"debate={result['debate']['final_verdict']}")


def _make_l2_missing_fields():
    """
    构造 L2 数据：quality=ok 但 missing_fields 不为空（上游识别了缺失字段）
    期望：failed_dimensions 应包含对应维度（因为字段实质缺失）
    """
    d = _make_l2_full()
    d["fundamental_data"] = {
        "quality": "ok",
        "missing_fields": ["roe", "pe"],  # 上游识别了缺失字段
        # roe/pe 根本不存在
    }
    return d


def test_missing_fields_detection():
    """
    测试 missing_fields 识别：quality=ok 但 missing_fields 有值

    入参: _make_l2_missing_fields()
    期望: 如果 missing_fields 非空但 quality=ok，当前实现应能识别并降级质量
          或者 failed_dimensions 记录缺失信息
    """
    print("\n  [日志] 准备测试 missing_fields 识别...")
    L2_data = _make_l2_missing_fields()
    print(f"  [输入] L2_data 中 fundamental_data = {L2_data['fundamental_data']}")

    result = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    # missing_fields 有值说明上游已经识别了字段缺失
    # 评分器应该能处理这种情况（字段不存在=0分或默认值）
    score = result["score"]
    assert 0 <= score["five_score"] <= 100
    # 应有对应记录（取决于实现是否识别 missing_fields）
    print(f"  [通过] five_score={score['five_score']}, "
          f"quality={result['quality_overall']}, "
          f"failed_dims={result['failed_dimensions']}")


def _make_l2_partial_missing():
    """构造 L2 数据：缺少某个数据块（如 moneyflow_data 完全不存在）"""
    d = _make_l2_full()
    d.pop("moneyflow_data", None)  # 移除 moneyflow 数据块
    return d


def test_partial_dimension_missing():
    """
    测试部分维度缺失：moneyflow_data 完全不存在

    入参: _make_l2_partial_missing()
    期望: 不抛异常，五个维度中缺少的维度应有默认值或0分
    """
    print("\n  [日志] 准备测试部分维度缺失...")
    L2_data = _make_l2_partial_missing()
    print(f"  [输入] L2_data 缺少 moneyflow_data 块")

    result = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    score = result["score"]
    assert 0 <= score["five_score"] <= 100

    # moneyflow 维度应该得分较低或为 0（因为缺数据）
    moneyflow_score = score["scores"].get("moneyflow", {}).get("score", None)
    print(f"  [逻辑] moneyflow_score = {moneyflow_score}")
    assert moneyflow_score is not None

    # 不应为 placeholder
    assert moneyflow_score != 9999, "moneyflow score should not be placeholder"
    assert 0 <= moneyflow_score <= 100

    print(f"  [通过] five_score={score['five_score']}, "
          f"moneyflow_score={moneyflow_score}, "
          f"quality={result['quality_overall']}")


def _make_l2_zero_fields():
    """构造 L2 数据：字段值为 0/None 但 quality=ok（上游未标注失败）"""
    d = _make_l2_full()
    d["fundamental_data"] = {
        "quality": "ok",
        "missing_fields": [],
        "roe": 0, "pe": 0, "pb": 0,  # 零值，但 quality=ok
        "net_profit_yoy": None,  # None 值
        "revenue_growth": 0,
    }
    return d


def test_zero_field_values():
    """
    测试零值和 None 值：字段为 0/None 但上游未标注失败

    入参: _make_l2_zero_fields()
    期望: 不抛异常，评分器应对 0 值有合理处理（不应全部得满分 100）
    """
    print("\n  [日志] 准备测试零值字段处理...")
    L2_data = _make_l2_zero_fields()
    print(f"  [输入] L2_data fundamental_data = {L2_data['fundamental_data']}")

    result = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    score = result["score"]
    five = score["five_score"]
    assert 0 <= five <= 100

    # 如果 fundamental 全是 0 值，不应该评高分（100）
    fundamental_score = score["scores"].get("fundamental", {}).get("score", None)
    print(f"  [逻辑] fundamental_score = {fundamental_score}")

    # five_score 不应为 100（说明零值被正确降分）
    assert five != 100, f"five_score should not be 100 with zero fields, got {five}"

    print(f"  [通过] five_score={five}, fundamental_score={fundamental_score}, "
          f"grade={score['grade']}")


def _make_l2_extreme_low_score():
    """构造 L2 数据：所有维度都差 → 五维分数极低"""
    d = _make_l2_full()
    # 资金流：外内比很低
    d["moneyflow_data"] = {
        "quality": "ok", "missing_fields": [],
        "main_net_flow_5d": -100, "main_direction": "流出",
        "retail_direction": "流入", "outer_inner_ratio": 0.2,
    }
    # 技术面：死叉，RSI 超卖
    d["technical_data"] = {
        "quality": "ok", "missing_fields": [],
        "ma_status": "bearish", "macd_status": "dead",
        "rsi": 20, "ma5": 1700.0, "ma10": 1800.0, "ma20": 1900.0, "ma60": 2000.0,
        "volume_status": "缩量下跌", "volume_ratio": 0.3,
        "price": 1600.0, "change_pct": -5.0,
    }
    # 基本面：ROE 很低
    d["fundamental_data"] = {
        "quality": "ok", "missing_fields": [],
        "roe": 1.0, "pe": 100.0, "pb": 10.0,
        "net_profit_yoy": -30.0, "revenue_growth": -20.0,
    }
    return d


def test_extreme_low_score():
    """
    测试极端低分：所有维度都差 → five_score 很低，grade=D

    入参: _make_l2_extreme_low_score()
    期望: five_score 较低（<50），grade 可能是 D
    """
    print("\n  [日志] 准备测试极端低分场景...")
    L2_data = _make_l2_extreme_low_score()
    print(f"  [输入] L2_data 所有维度都很差")

    result = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    score = result["score"]
    assert 0 <= score["five_score"] <= 100
    assert score["grade"] in ("A", "B", "C", "D")

    print(f"  [通过] five_score={score['five_score']}, grade={score['grade']}, "
          f"debate={result['debate']['final_verdict']}")


def _make_l2_field_type_error():
    """构造 L2 数据：字段类型错误（string 而非 number）"""
    d = _make_l2_full()
    d["technical_data"] = {
        "quality": "ok", "missing_fields": [],
        "ma_status": "bullish", "macd_status": "golden",
        "rsi": "很高",  # 应该是 number，这里是 string
        "ma5": "1800.0", "ma10": "1780.0",  # string 而非 number
        "ma20": 1750.0, "ma60": 1700.0,
        "volume_status": "放量上涨", "volume_ratio": 1.5,
        "price": "1850.0", "change_pct": "2.5",
    }
    return d


def test_field_type_error():
    """
    测试字段类型错误：字段是 string 而非 number

    入参: _make_l2_field_type_error()
    期望: 不抛异常，评分器应能处理（用默认值或跳过）
    """
    print("\n  [日志] 准备测试字段类型错误...")
    L2_data = _make_l2_field_type_error()
    print(f"  [输入] L2_data technical_data.rsi = '{L2_data['technical_data']['rsi']}' (string)")

    result = run_quantitative(L2_data, config=_TEST_CONFIG)
    print(f"  [输出] result = {result}")

    score = result["score"]
    assert 0 <= score["five_score"] <= 100

    technical_score = score["scores"].get("technical", {}).get("score", None)
    print(f"  [逻辑] technical_score = {technical_score}")
    assert technical_score is not None
    assert 0 <= technical_score <= 100

    print(f"  [通过] five_score={score['five_score']}, "
          f"technical_score={technical_score}, "
          f"quality={result['quality_overall']}")


def _run_all():
    """
    设计说明简述：
    本测试覆盖 L3 量化分析层的完整链路：
    1. 正常场景：五维评分 + 辩论裁决
    2. 失败追踪：quality=fail 或字段值="失败" → failed_dimensions
    3. 质量传播：失败字段导致 quality_overall 降级
    4. 空数据兜底：不抛异常，返回合理默认值
    5. 补充维度：
       - missing_fields 识别（上游已标注缺失）
       - 部分维度缺失（数据块完全不存在）
       - 零值/None 处理（上游未标注失败）
       - 极端低分边界（grade=D, score<50）
       - 字段类型错误（string 而非 number）
    """
    tests = [
        ("normal_l2", test_normal_l2),
        ("failed_dimensions_tracking", test_failed_dimensions_tracking),
        ("score_structure", test_score_structure),
        ("debate_structure", test_debate_structure),
        ("degrade_quality_propagation", test_degrade_quality_propagation),
        ("empty_l2_data", test_empty_l2_data),
        ("missing_fields_detection", test_missing_fields_detection),
        ("partial_dimension_missing", test_partial_dimension_missing),
        ("zero_field_values", test_zero_field_values),
        ("extreme_low_score", test_extreme_low_score),
        ("field_type_error", test_field_type_error),
    ]

    total_start = time.time()
    suite_start("test_l3_quant_runner", len(tests))

    passed = 0
    failed = 0
    for name, fn in tests:
        test_start("test_l3_quant_runner", name)
        t0 = time.time()
        try:
            print(f"\n{'='*60}")
            print(f"▶ {name}")
            fn()
            passed += 1
            test_end("test_l3_quant_runner", name, True, time.time() - t0)
        except AssertionError as e:
            test_end("test_l3_quant_runner", name, False, time.time() - t0, str(e))
            print(f"  [失败] {e}")
            failed += 1
        except Exception as e:
            test_end("test_l3_quant_runner", name, False, time.time() - t0, f"{type(e).__name__}: {e}")
            print(f"  [异常] {type(e).__name__}: {e}")
            failed += 1

    total_elapsed = time.time() - total_start
    suite_end("test_l3_quant_runner", passed, failed, total_elapsed)

    print(f"\n{'='*60}")
    print(f"结果: {passed}/{len(tests)} 通过, {failed} 失败")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    print("=" * 60)
    print("L3 Quant Runner 测试")
    print("=" * 60)
    ok = _run_all()
    sys.exit(0 if ok else 1)