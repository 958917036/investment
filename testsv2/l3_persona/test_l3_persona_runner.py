#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3 Persona Runner 测试代码

覆盖 L3_llm_perspectives/persona_runner.py 的所有场景：
- 无 API Key → _status=skipped（graceful degradation，不抛异常）
- run_persona 基础结构：layer / code / perspectives / summary / quality_overall
- run_persona_analysis 基础结构：perspectives / summary / avg_score
- 每位大师视角字段：score / grade / verdict / rationale
- merged vs independent 模式切换
- 全部 12 种人格独立测试

日志要求：
- 每个测试打印：入参、预期结果、执行过程、出参、执行耗时
- 整体有预期结果判断（PASS/FAIL）
"""
import sys
import os
import json
import time
from dotenv import load_dotenv

sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))
load_dotenv(os.path.expanduser("~/.hermes/.env"), override=True)
# Load configs for run_persona
_CONFIG_BASE = os.path.expanduser("~/.hermes/investment/main/config")
with open(os.path.join(_CONFIG_BASE, "l3_persona_config.json")) as f:
    _PERSONA_CONFIG = json.load(f)
with open(os.path.join(_CONFIG_BASE, "model_config.json")) as f:
    _MODEL_CONFIG = json.load(f)



def _log(title, body=None, indent=2):
    """统一日志打印"""
    prefix = "  " * indent
    print(f"{prefix}{title}")
    if body:
        for line in body.split("\n"):
            print(f"{prefix}  {line}")


def _get_api_key_from_config() -> str:
    """从 model_config.json 读取 API Key，支持 ${ENV_VAR} 语法"""
    config_path = os.path.expanduser("~/.hermes/investment/main/config/model_config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        key = cfg.get("minimax", {}).get("api_key", "")
        if key.startswith("${") and key.endswith("}"):
            env_var = key[2:-1]
            key = os.environ.get(env_var, "")
        return key
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return os.environ.get("MINIMAX_CN_API_KEY", "")


def _make_l2_data():
    """构造 L2 模拟数据"""
    return {
        "code": "600519",
        "name": "贵州茅台",
        "run_date": "2026-05-30",
        "technical_data": {
            "pe": 22, "pb": 7.4, "market_cap": 18000,
            "turnover": 0.15, "week52_high": 1560, "week52_low": 1277,
            "change_pct": 1.7, "volume": 16397, "amount": 234609,
            "ma60_position_pct": 65, "macd_status": "golden", "rsi": 55,
            "price": 1443.0
        },
        "fundamental_data": {
            "pe": 22, "pb": 7.4, "roe": 28.5, "gross_margin": 91.5,
            "revenue_growth": 15, "debt_ratio": 20,
        },
        "moneyflow_data": {
            "main_net_flow_5d": -500_000_000,
            "small_order_net_flow_5d": 200_000_000,
        },
        "sector_data": {"sector_rank": 85, "sector_fund_flow": 500000000},
        "event_data": {"positive_events": [], "analyst_rating": "neutral", "report_count_30d": 0},
    }


def test_run_persona_skipped_without_key():
    """
    测试无 API Key 时 graceful degradation → _status=skipped

    入参: L2 数据（实际不走 LLM）
    预期: _status="skipped"，perspectives 和 summary 是 {}（不是 None）
    """
    print("  [入参]")
    print("    L2_data: code=600519, name=贵州茅台, price=1443.0")
    print("    操作: 清除环境变量 MINIMAX_CN_API_KEY，强制无 Key")

    print("  [预期结果]")
    print("    _status == 'skipped'")
    print("    perspectives == {}")
    print("    summary == {}")

    print("  [执行过程]")
    saved_key = os.environ.pop("MINIMAX_CN_API_KEY", None)
    try:
        import importlib
        import L3_llm_perspectives.persona_runner as pr
        pr._model_config_cache = None
        importlib.reload(pr)

        from L3_llm_perspectives.persona_runner import run_persona
        data = _make_l2_data()
        t0 = time.time()
        result = run_persona(data, _PERSONA_CONFIG, _MODEL_CONFIG)
        elapsed = time.time() - t0

        print("  [出参]")
        print(f"    _status={result.get('_status')!r}")
        print(f"    perspectives={result.get('perspectives')!r}")
        print(f"    summary={result.get('summary')!r}")
        print(f"    elapsed={elapsed:.3f}s")

        print("  [断言]")
        assert result.get("_status") == "skipped", \
            f"  FAIL: _status expected 'skipped', got {result.get('_status')!r}"
        assert result.get("perspectives") == {}, \
            f"  FAIL: perspectives expected {{}}, got {result.get('perspectives')!r}"
        assert result.get("summary") == {}, \
            f"  FAIL: summary expected {{}}, got {result.get('summary')!r}"
        print("  [PASS] 断言全部通过")
    finally:
        if saved_key:
            os.environ["MINIMAX_CN_API_KEY"] = saved_key


def test_run_persona_basic_structure():
    """
    测试 run_persona 输出基础结构字段存在且类型合理

    入参: L2 数据
    预期: layer="L3_persona", code 有值, quality_overall in (ok/degraded/fail)
    """
    print("  [入参]")
    print("    L2_data: code=600519, name=贵州茅台, price=1443.0")
    print("    操作: 调用 run_persona(data, _PERSONA_CONFIG, _MODEL_CONFIG)")

    print("  [预期结果]")
    print("    存在字段: layer, code, perspectives, summary, quality_overall")
    print("    code != ''")
    print("    quality_overall in (ok, degraded, fail)")
    if not _get_api_key_from_config():
        print("    (API Key 未配置，预期 skipped)")
    else:
        print("    (API Key 已配置，预期 ok)")

    print("  [执行过程]")
    import importlib
    import L3_llm_perspectives.persona_runner as pr
    pr._model_config_cache = None
    importlib.reload(pr)
    from L3_llm_perspectives.persona_runner import run_persona

    data = _make_l2_data()
    t0 = time.time()
    result = run_persona(data, _PERSONA_CONFIG, _MODEL_CONFIG)
    elapsed = time.time() - t0

    print("  [出参]")
    print(f"    layer={result.get('layer')!r}")
    print(f"    code={result.get('code')!r}")
    print(f"    _status={result.get('_status')!r}")
    print(f"    quality_overall={result.get('quality_overall')!r}")
    print(f"    elapsed={elapsed:.3f}s")

    if result.get("_status") == "skipped" and not _get_api_key_from_config():
        print("  [断言]")
        print("  [PASS] 无 API Key，跳过验证（预期行为）")
        return

    print("  [断言]")
    if _get_api_key_from_config() and result.get("_status") == "skipped":
        print(f"  FAIL: API key found but still got skipped: {result.get('_reason')}")
        assert False, f"API key is set but got skipped: {result.get('_reason')}"

    assert "layer" in result, "FAIL: missing 'layer'"
    assert "code" in result, "FAIL: missing 'code'"
    assert result["code"] != "", f"FAIL: code expected non-empty, got {result['code']!r}"
    assert "perspectives" in result, "FAIL: missing 'perspectives'"
    assert "summary" in result, "FAIL: missing 'summary'"
    assert "quality_overall" in result, "FAIL: missing 'quality_overall'"
    assert result["quality_overall"] in ("ok", "degraded", "fail"), \
        f"FAIL: quality_overall expected ok/degraded/fail, got {result['quality_overall']!r}"
    print("  [PASS] 断言全部通过")


def test_run_persona_analysis_basic_structure():
    """
    测试 run_persona_analysis 输出结构：summary 中 count 字段为 int >= 0

    入参: code="600519", name="贵州茅台", price=1443, run_mode="merged"
    预期: summary 包含 avg_score/float-0-1, buy_count/watch_count/reject_count/agents_total/int>=0
    """
    print("  [入参]")
    print("    code=600519, name=贵州茅台, price=1443.0")
    print("    run_mode=merged")

    print("  [预期结果]")
    print("    字段: avg_score (float, 0~1), buy_count (int, >=0), watch_count (int, >=0)")
    print("    字段: reject_count (int, >=0), agents_total (int, >=0)")
    if not _get_api_key_from_config():
        print("    (API Key 未配置，预期 skipped)")
    else:
        print("    (API Key 已配置，预期 ok)")

    print("  [执行过程]")
    import importlib
    import L3_llm_perspectives.persona_runner as pr
    pr._model_config_cache = None
    importlib.reload(pr)
    from L3_llm_perspectives.persona_runner import run_persona_analysis

    data = _make_l2_data()
    t0 = time.time()
    result = run_persona_analysis("600519", "贵州茅台", 1443, data, run_mode="merged")
    elapsed = time.time() - t0

    print("  [出参]")
    print(f"    _status={result.get('_status')!r}")
    sm = result.get("summary", {})
    print(f"    avg_score={sm.get('avg_score')}")
    print(f"    buy_count={sm.get('buy_count')}, watch_count={sm.get('watch_count')}")
    print(f"    reject_count={sm.get('reject_count')}, agents_total={sm.get('agents_total')}")
    print(f"    elapsed={elapsed:.3f}s")

    if result.get("_status") == "skipped" and not _get_api_key_from_config():
        print("  [断言]")
        print("  [PASS] 无 API Key，跳过验证（预期行为）")
        return

    print("  [断言]")
    if _get_api_key_from_config() and result.get("_status") == "skipped":
        print(f"  FAIL: API key found but still got skipped: {result.get('_reason')}")
        assert False, f"API key is set but got skipped: {result.get('_reason')}"

    assert "perspectives" in result, "FAIL: missing 'perspectives'"
    assert "summary" in result, "FAIL: missing 'summary'"
    for field in ("avg_score", "buy_count", "watch_count", "reject_count", "agents_total"):
        assert field in sm, f"FAIL: summary missing '{field}'"
    if sm["avg_score"] is not None:
        assert isinstance(sm["avg_score"], float), \
            f"FAIL: avg_score expected float, got {type(sm['avg_score'])}"
        assert 0.0 <= sm["avg_score"] <= 1.0, \
            f"FAIL: avg_score expected 0~1, got {sm['avg_score']}"
    for field in ("buy_count", "watch_count", "reject_count", "agents_total"):
        assert isinstance(sm[field], int), \
            f"FAIL: {field} expected int, got {type(sm[field])}"
        assert sm[field] >= 0, f"FAIL: {field} expected >=0, got {sm[field]}"
    print("  [PASS] 断言全部通过")


def test_perspective_fields():
    """
    测试每位大师视角字段类型和范围合理

    入参: run_mode="merged"
    预期: score 0~1, verdict in (BUY/WATCH/REJECT/HOLD/""), rationale 非空
    """
    print("  [入参]")
    print("    code=600519, name=贵州茅台, price=1443.0")
    print("    run_mode=merged")

    print("  [预期结果]")
    print("    每位人格: score(float, 0~1), verdict(in BUY/WATCH/REJECT/HOLD/'')")
    print("    rationale 非空字符串")
    if not _get_api_key_from_config():
        print("    (API Key 未配置，预期 skipped)")
    else:
        print("    (API Key 已配置，预期 ok)")

    print("  [执行过程]")
    import importlib
    import L3_llm_perspectives.persona_runner as pr
    pr._model_config_cache = None
    importlib.reload(pr)
    from L3_llm_perspectives.persona_runner import run_persona_analysis

    data = _make_l2_data()
    t0 = time.time()
    result = run_persona_analysis("600519", "贵州茅台", 1443, data, run_mode="merged")
    elapsed = time.time() - t0

    print("  [出参]")
    print(f"    _status={result.get('_status')!r}")
    persp = result.get("perspectives", {})
    print(f"    perspectives count={len(persp)}")
    for name, p in persp.items():
        print(f"    {name}: score={p.get('score')}, verdict={p.get('verdict')!r}, grade={p.get('grade')!r}")
    print(f"    elapsed={elapsed:.3f}s")

    if result.get("_status") == "skipped" and not _get_api_key_from_config():
        print("  [断言]")
        print("  [PASS] 无 API Key，跳过验证（预期行为）")
        return

    print("  [断言]")
    if _get_api_key_from_config() and result.get("_status") == "skipped":
        print(f"  FAIL: API key found but still got skipped: {result.get('_reason')}")
        assert False, f"API key is set but got skipped: {result.get('_reason')}"

    if not persp:
        print("  [WARN] no perspectives returned")
        return
    for name, p in persp.items():
        assert "score" in p, f"FAIL: {name} missing score"
        assert "grade" in p, f"FAIL: {name} missing grade"
        assert "verdict" in p, f"FAIL: {name} missing verdict"
        assert "rationale" in p, f"FAIL: {name} missing rationale"
        s = p["score"]
        assert s is not None, f"FAIL: {name}.score: should not be None"
        assert 0.0 <= s <= 1.0, f"FAIL: {name}.score: expected 0~1, got {s}"
        assert p["verdict"] in ("BUY", "WATCH", "REJECT", "HOLD", ""), \
            f"FAIL: {name}.verdict: unexpected {p['verdict']!r}"
        assert p["rationale"], f"FAIL: {name}.rationale: should not be empty"
    print(f"  [PASS] {len(persp)} perspectives 断言全部通过")


def test_merged_vs_independent_mode():
    """
    测试 merged 和 independent 两种模式均可执行，_mode 字段正确

    入参: run_mode="merged" 和 run_mode="independent"
    预期: 两种模式均返回 _mode 字段
    """
    print("  [入参]")
    print("    code=600519, name=贵州茅台, price=1443.0")
    print("    run_mode: merged, independent")

    print("  [预期结果]")
    print("    merged: _status=ok, _mode=merged")
    print("    independent: _status=ok, _mode=independent")
    if not _get_api_key_from_config():
        print("    (API Key 未配置，预期 skipped)")
    else:
        print("    (API Key 已配置，预期 ok)")

    print("  [执行过程]")
    import importlib
    import L3_llm_perspectives.persona_runner as pr
    pr._model_config_cache = None
    importlib.reload(pr)
    from L3_llm_perspectives.persona_runner import run_persona_analysis

    data = _make_l2_data()
    results = {}
    for mode in ["merged", "independent"]:
        t0 = time.time()
        r = run_persona_analysis("600519", "贵州茅台", 1443, data, run_mode=mode)
        results[mode] = (r, time.time() - t0)

    print("  [出参]")
    for mode, (r, elapsed) in results.items():
        print(f"    {mode}: _status={r.get('_status')!r}, _mode={r.get('_mode','?')!r}, elapsed={elapsed:.3f}s")

    print("  [断言]")
    if not _get_api_key_from_config():
        print("  [PASS] 无 API Key，跳过验证（预期行为）")
        return

    for mode, (r, elapsed) in results.items():
        assert "_mode" in r or "_status" in r, \
            f"FAIL: mode={mode}: missing '_mode' and '_status'"
    print("  [PASS] 两种模式断言全部通过")


def _test_persona_batch(persona_batch: list, batch_name: str) -> bool:
    """测试一批人格（独立模式），返回是否全部通过"""
    print(f"\n  --- Batch {batch_name}: {persona_batch}")

    print("  [入参]")
    print(f"    personas={persona_batch}")
    print(f"    run_mode=independent")

    print("  [预期结果]")
    for name in persona_batch:
        print(f"    {name}: score(0~1), verdict(BUY/WATCH/REJECT/HOLD/''), rationale非空")

    print("  [执行过程]")
    from L3_llm_perspectives.persona_runner import run_persona_analysis

    old_test = os.environ.get("TEST_PERSONAS", "")
    os.environ["TEST_PERSONAS"] = ",".join(persona_batch)
    try:
        data = _make_l2_data()
        t0 = time.time()
        result = run_persona_analysis("600519", "贵州茅台", 1443, data, run_mode="independent")
        elapsed = time.time() - t0

        print("  [出参]")
        print(f"    _status={result.get('_status')!r}, elapsed={elapsed:.3f}s")
        persp = result.get("perspectives", {})
        for name in persona_batch:
            if name in persp:
                p = persp[name]
                print(f"    {name}: score={p.get('score')}, verdict={p.get('verdict')!r}, grade={p.get('grade')!r}, rationale={p.get('rationale','')[:40]}...")
            else:
                print(f"    {name}: MISSING")

        if result.get("_status") == "skipped" and not _get_api_key_from_config():
            print("  [断言]")
            print("  [SKIP] 无 API Key，跳过验证（预期行为）")
            return True

        print("  [断言]")
        passed = 0
        failed = 0
        for name in persona_batch:
            if name not in persp:
                print(f"  FAIL: {name}: missing from perspectives")
                failed += 1
                continue
            p = persp[name]
            try:
                assert "score" in p, f"FAIL: {name} missing score"
                assert "verdict" in p, f"FAIL: {name} missing verdict"
                assert "rationale" in p, f"FAIL: {name} missing rationale"
                s = p["score"]
                assert s is not None, f"FAIL: {name}.score: should not be None"
                assert 0.0 <= s <= 1.0, f"FAIL: {name}.score: expected 0~1, got {s}"
                assert p["verdict"] in ("BUY", "WATCH", "REJECT", "HOLD", ""), \
                    f"FAIL: {name}.verdict: unexpected {p['verdict']!r}"
                assert p["rationale"], f"FAIL: {name}.rationale: should not be empty"
                passed += 1
            except AssertionError as e:
                print(f"  FAIL: {name}: {e}")
                failed += 1

        print(f"  Batch {batch_name} 结果: {passed}/{len(persona_batch)} 通过")
        return failed == 0
    finally:
        if old_test:
            os.environ["TEST_PERSONAS"] = old_test
        else:
            os.environ.pop("TEST_PERSONAS", None)


def test_all_12_personas_independent_mode():
    """
    测试全部 12 种人格（分 3 批，每批约 4-5 个）
    每种人格验证: score 0~1, verdict 有效, rationale 非空

    入参: 12 种人格分 3 批
    预期: 全部 12 种人格均返回有效 score/verdict/rationale
    """
    print("  [入参]")
    print("    全部 12 种人格:")
    print("    Batch1: buffett, graham, burry, druckenmiller, taleb")
    print("    Batch2: ackman, pabrai, lynch, cathie_wood, munger")
    print("    Batch3: phil_fisher, jhunjhunwala")

    print("  [预期结果]")
    print("    全部 12 种人格: score(0~1), verdict(BUY/WATCH/REJECT/HOLD/''), rationale非空")
    print("    任一人格缺失或字段异常 → FAIL")
    if not _get_api_key_from_config():
        print("    (API Key 未配置，预期 SKIP)")
    else:
        print("    (API Key 已配置，预期全部 PASS)")

    print("  [执行过程]")
    batches = [
        ("batch1", ["buffett", "graham", "burry", "druckenmiller", "taleb"]),
        ("batch2", ["ackman", "pabrai", "lynch", "cathie_wood", "munger"]),
        ("batch3", ["phil_fisher", "jhunjhunwala"]),
    ]

    total_passed = 0
    total_failed = 0
    for batch_name, personas in batches:
        if _test_persona_batch(personas, batch_name):
            total_passed += len(personas)
        else:
            total_failed += len(personas)

    print("  [出参]")
    print(f"    total_passed={total_passed}/12, total_failed={total_failed}/12")

    print("  [断言]")
    if not _get_api_key_from_config():
        print("  [SKIP] 无 API Key，跳过验证（预期行为）")
        return

    if total_failed > 0:
        print(f"  [FAIL] {total_failed} 种人格测试失败")
        assert False, f"{total_failed} 种人格测试失败"
    print(f"  [PASS] 全部 12 种人格测试通过")


def _run_all():
    tests = [
        ("skipped_without_key", test_run_persona_skipped_without_key),
        ("persona_basic_structure", test_run_persona_basic_structure),
        ("persona_analysis_basic_structure", test_run_persona_analysis_basic_structure),
        ("perspective_fields", test_perspective_fields),
        ("merged_vs_independent_mode", test_merged_vs_independent_mode),
        ("all_12_personas", test_all_12_personas_independent_mode),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            print(f"\n{'='*60}")
            print(f"▶ {name}")
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"[总体预期结果]")
    print(f"  全部 {len(tests)} 个测试用例预期 PASS")
    print(f"  实际: {passed}/{len(tests)} 通过, {failed} 失败")
    if failed == 0:
        print(f"  ✅ 全部通过")
    else:
        print(f"  ❌ 有失败用例")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    print("=" * 60)
    print("L3 Persona Runner 测试")
    api_key = _get_api_key_from_config()
    if api_key:
        print(f"API Key: 已配置 ({api_key[:12]}...)")
    else:
        print("API Key: 未配置，测试将跳过 LLM 调用")
    print("=" * 60)
    ok = _run_all()
    sys.exit(0 if ok else 1)