#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L4 Judge Runner 测试代码

覆盖 L4_judge/l4_runner.py 的所有场景：
- run_risk_judgment 基础输出：layer / code / judge_score / decision / risk_score
- decision 三值：BUY / WATCH / REJECT
- _judge_components：veto_score / debate_score / persona_score 及权重
- 质量降级传导：degraded → judge_score 降低
- risk_level 三值：normal / warning / high
- 各出参字段完整性断言

验证策略：
- judge_score 范围应在 0~1，decision 三值
- risk_score 应 >= 0
- recommended_weight 应 >= 0（持仓比例不能为负）
- stop_loss_pct 应为负数（止损是负数）
- take_profit_pct 应为正数（止盈是正数）
- 权重和应为 1.0
- 检查 placeholder 值：如 risk_score=999 应是异常标记
"""
import sys
import os
import time

sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from test_logger import suite_start, suite_end, test_start, test_end
from L4_judge.l4_runner import run_risk_judgment



_L4_CONFIG = {'_comment': '风控模块配置 v1（2026-05-04）', '_description': '风险管理器的配置参数，从文件加载而非硬编码', 'total_capital': 100000, 'risk': {'max_single_position': 0.2, 'max_top3_concentration': 0.5, 'max_sector_concentration': 0.35, 'stop_loss_default': -0.08, 'take_profit_default': 0.2, 'var_95_limit': 0.03, 'volatility_warning': 0.4, 'volatility_danger': 0.6, 'max_correlation': 0.7, 'kelly_fraction_limit': 0.25, 'margin_call_threshold': 0.85}, 'position_levels': [{'threshold': 0.3, 'label': '重仓'}, {'threshold': 0.2, 'label': '中等仓位'}, {'threshold': 0.15, 'label': '轻仓'}, {'threshold': 0.1, 'label': '试探仓位'}, {'threshold': 0.05, 'label': '迷你仓位'}, {'threshold': 0.0, 'label': '不建议买入'}], 'kelly_win_rates': {'default_kelly': 0.1, 'score_80_plus': 0.65, 'score_65_plus': 0.55, 'score_50_plus': 0.45, 'score_below_50': 0.35}, 'atr_multiplier': 1.5, 'default_volatility': 0.3}
_L3_CONFIG = {'_comment': 'L3量化分析层统一配置 v1（2026-05-04）', '_description': 'L3评分权重、交易成本、veto规则等硬编码参数迁移至此', 'five_dimension_weights': {'moneyflow': 0.35, 'technical': 0.35, 'fundamental': 0.1, 'sector': 0.1, 'event': 0.1}, 'l3_gate': {'_comment': '五维度评分gate：低于阈值时跳过辩论和人格分析', 'five_score_threshold': 60}, 'debate': {'max_rounds': 1, 'confidence_default': 0.5}, 'trading': {'commission_rate': 0.0003, 'slippage': 0.001, 'tax_rate': 0.001}, 'backtest': {'commission_rate': 0.0003, 'slippage': 0.001, 'tax_rate': 0.001, 'position_limits': {'main': 0.1, 'chinext': 0.2, 'star': 0.2, 'bj': 0.3}}, 'defaults': {'price_fallback': 50.0, 'five_score_fallback': 50, 'grade_fallback': 'C', 'verdict_fallback': '中性观望'}, 'veto': {'moneyflow_threshold': -50000000, '_comment': '资金流veto阈值：main_net_flow_5d < -5000万则veto'}}
def _mock_l3_quant(quality_overall="ok"):
    d = {
        "layer": "L3_quantitative",
        "code": "600519",
        "run_date": "2026-05-30",
        "score": {
            "five_score": 72,
            "grade": "B",
            "scores": {
                "moneyflow": {"score": 80, "weight": 0.35, "weighted_score": 28.0},
                "technical": {"score": 75, "weight": 0.35, "weighted_score": 26.25},
                "fundamental": {"score": 65, "weight": 0.10, "weighted_score": 6.5},
                "sector": {"score": 70, "weight": 0.10, "weighted_score": 7.0},
                "event": {"score": 55, "weight": 0.10, "weighted_score": 5.5},
            },
        },
        "debate": {
            "bull_arguments": ["业绩稳定增长", "行业龙头地位稳固"],
            "bear_arguments": ["估值偏高", "RSI进入超买区间"],
            "final_verdict": "谨慎看多",
            "confidence": 0.65,
        },
        "technical_data": {"rsi": 72},
        "quality_overall": quality_overall,
        "duration_ms": 850,
    }
    return d


def _mock_l3_persona():
    return {
        "layer": "L3_persona",
        "code": "600519",
        "run_date": "2026-05-30",
        "perspectives": {
            "buffett": {"score": 0.3, "verdict": "REJECT", "rationale": "护城河不足"},
            "lynch": {"score": 0.8, "verdict": "BUY", "rationale": "成长性突出"},
            "druckenmiller": {"score": 0.65, "verdict": "WATCH", "rationale": "短期波动加大"},
        },
        "summary": {
            "buy_count": 1,
            "watch_count": 1,
            "reject_count": 1,
            "hold_count": 0,
            "agents_total": 3,
            "avg_score": 0.58,
        },
        "_status": "ok",
        "quality_overall": "ok",
        "duration_ms": 2100,
    }


def _mock_l2_data():
    return {
        "layer": "L2",
        "code": "600519",
        "market": "CN",
        "run_date": "2026-05-30",
        "technical_data": {"price": 1850.0, "rsi": 72},
        "moneyflow_data": {"main_net_flow_5d": 123456789},
        "duration_ms": 1200,
    }


def test_run_risk_judgment():
    """
    测试 run_risk_judgment 基础输出结构完整且值合理

    入参: _mock_l3_quant() / _mock_l3_persona() / _mock_l2_data()
    期望: judge_score 0~1, decision in (BUY/WATCH/REJECT),
          risk_score >= 0, recommended_weight >= 0,
          stop_loss_pct < 0（止损）, take_profit_pct > 0（止盈）
    """
    L3_quant = _mock_l3_quant()
    L3_persona = _mock_l3_persona()
    L2_data = _mock_l2_data()

    result = run_risk_judgment(L3_quant, L3_persona, L2_data, l4_config=_L4_CONFIG, l3_config=_L3_CONFIG)

    assert result["layer"] == "L4"
    assert result["code"] == "600519"
    assert "judge_score" in result
    assert "decision" in result
    assert result["decision"] in ("BUY", "WATCH", "REJECT")
    assert "risk_score" in result
    assert "risk_level" in result
    assert result["risk_level"] in ("normal", "warning", "high")

    # judge_score 应在 0~1
    js = result["judge_score"]
    assert 0.0 <= js <= 1.0, f"judge_score: expected 0~1, got {js}"

    # risk_score 应 >= 0，不能是 placeholder（如 999）
    rs = result["risk_score"]
    assert rs >= 0, f"risk_score: expected >=0, got {rs}"
    assert rs != 999, f"risk_score: got placeholder 999"

    # recommended_weight 应 >= 0（持仓比例不能为负）
    rw = result["recommended_weight"]
    assert rw >= 0, f"recommended_weight: expected >=0, got {rw}"

    # stop_loss 应为负数（亏损是负的）
    sl = result["stop_loss_pct"]
    assert sl < 0, f"stop_loss_pct: expected <0, got {sl}"

    # take_profit 应为正数（盈利是正的）
    tp = result["take_profit_pct"]
    assert tp > 0, f"take_profit_pct: expected >0, got {tp}"

    assert "risk_factors" in result
    assert "quality_overall" in result
    assert "duration_ms" in result

    print(f"  [PASS] decision={result['decision']}, judge_score={js:.3f}, "
          f"risk_score={rs}, risk_level={result['risk_level']}, "
          f"weight={rw}, stop_loss={sl}%, take_profit={tp}%")


def test_judge_components():
    """
    测试 _judge_components 三个评分及权重和

    入参: 同上 mock 数据
    期望: veto/debate/persona_score 0~1，权重和 = 1.0
    """
    L3_quant = _mock_l3_quant()
    L3_persona = _mock_l3_persona()
    L2_data = _mock_l2_data()

    result = run_risk_judgment(L3_quant, L3_persona, L2_data, l4_config=_L4_CONFIG, l3_config=_L3_CONFIG)
    comp = result["_judge_components"]

    for field in ("veto_score", "debate_score", "persona_score"):
        assert field in comp, f"missing '{field}'"
        s = comp[field]
        assert 0.0 <= s <= 1.0, f"{field}: expected 0~1, got {s}"

    for field in ("veto_weight", "debate_weight", "persona_weight"):
        assert field in comp, f"missing '{field}'"
        w = comp[field]
        assert 0.0 <= w <= 1.0, f"{field}: expected 0~1, got {w}"

    total_weight = comp["veto_weight"] + comp["debate_weight"] + comp["persona_weight"]
    assert abs(total_weight - 1.0) < 0.001, \
        f"weights sum: expected 1.0, got {total_weight}"

    print(f"  [PASS] veto={comp['veto_score']:.3f}×{comp['veto_weight']} + "
          f"debate={comp['debate_score']:.3f}×{comp['debate_weight']} + "
          f"persona={comp['persona_score']:.3f}×{comp['persona_weight']} = {result['judge_score']:.3f}")


def test_quality_degraded_lowers_score():
    """
    测试质量降级传导：degraded → judge_score 降低

    入参: _mock_l3_quant("ok") vs _mock_l3_quant("degraded")
    期望: result_deg["judge_score"] <= result_ok["judge_score"]
    """
    L3_persona = _mock_l3_persona()
    L2_data = _mock_l2_data()

    result_ok = run_risk_judgment(_mock_l3_quant("ok"), L3_persona, L2_data, l4_config=_L4_CONFIG, l3_config=_L3_CONFIG)
    result_deg = run_risk_judgment(_mock_l3_quant("degraded"), L3_persona, L2_data, l4_config=_L4_CONFIG, l3_config=_L3_CONFIG)

    assert result_deg["judge_score"] <= result_ok["judge_score"], \
        f"degraded ({result_deg['judge_score']}) should be <= ok ({result_ok['judge_score']})"
    print(f"  [PASS] degraded({result_deg['judge_score']:.3f}) <= ok({result_ok['judge_score']:.3f})")


def test_decision_thresholds():
    """
    测试 decision 裁决阈值：高 five_score → BUY

    入参: _mock_l3_quant() five_score=80 → 高分 → Accept
    期望: decision="Accept"
    """
    L3_persona = _mock_l3_persona()
    L2_data = _mock_l2_data()

    L3_high = _mock_l3_quant()
    L3_high["score"]["five_score"] = 80
    result = run_risk_judgment(L3_high, L3_persona, L2_data, l4_config=_L4_CONFIG, l3_config=_L3_CONFIG)

    assert result["decision"] == "BUY", \
        f"decision: expected 'BUY', got {result['decision']!r} (judge_score={result['judge_score']})"
    print(f"  [PASS] score=80 → decision={result['decision']} (judge_score={result['judge_score']:.3f})")


def _run_all():
    tests = [
        ("run_risk_judgment", test_run_risk_judgment),
        ("judge_components", test_judge_components),
        ("quality_degraded_lowers_score", test_quality_degraded_lowers_score),
        ("decision_thresholds", test_decision_thresholds),
    ]

    total_start = time.time()
    suite_start("test_l4_runner", len(tests))

    passed = 0
    failed = 0
    for name, fn in tests:
        test_start("test_l4_runner", name)
        t0 = time.time()
        try:
            print(f"\n{'='*60}")
            print(f"▶ {name}")
            fn()
            passed += 1
            test_end("test_l4_runner", name, True, time.time() - t0)
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
            test_end("test_l4_runner", name, False, time.time() - t0, str(e))
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed += 1
            test_end("test_l4_runner", name, False, time.time() - t0, f"{type(e).__name__}: {e}")

    total_elapsed = time.time() - total_start
    suite_end("test_l4_runner", passed, failed, total_elapsed)

    print(f"\n{'='*60}")
    print(f"结果: {passed}/{len(tests)} 通过, {failed} 失败")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    print("=" * 60)
    print("L4 Judge Runner 测试")
    print("=" * 60)
    ok = _run_all()
    sys.exit(0 if ok else 1)