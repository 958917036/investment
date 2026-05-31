#!/usr/bin/env python3
"""
全链路集成测试 — 验证L1→L2→L3→L4 完整流程+数据+存储
测试股票：贵州茅台(600519) 美的集团(000333) 招商银行(600036)
"""

import sys, os, json, time, logging
from datetime import datetime

# 同shennong.py的路径配置
PROJECT_ROOT = os.path.expanduser("~/.hermes/investment")
os.chdir(PROJECT_ROOT)
for p in [
    os.path.join(PROJECT_ROOT, "L1_screener", "scripts"),
    os.path.join(PROJECT_ROOT, "L2_data_enrich"),
    os.path.join(PROJECT_ROOT, "L3_quant_analysis"),
    os.path.join(PROJECT_ROOT, "L3_quant_analysis", "scoring"),
    os.path.join(PROJECT_ROOT, "L3_quant_analysis", "debate"),
    os.path.join(PROJECT_ROOT, "L3_llm_perspectives"),
    os.path.join(PROJECT_ROOT, "L4_judge"),
    os.path.join(PROJECT_ROOT, "L4_judge", "risk"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("test")

TODAY = datetime.now().strftime("%Y-%m-%d")
TEST_SYMBOLS = ["000333"]  # 先只跑美的集团一只
TEST_NAME = "美的集团"

# 加载环境变量（.env中有MINIMAX_API_KEY）
from dotenv import load_dotenv
env_path = os.path.expanduser("~/.hermes/.env")
if os.path.exists(env_path):
    load_dotenv(env_path)
    logger.info(f"MINIMAX_API_KEY={'已设置 ✓' if os.environ.get('MINIMAX_CN_API_KEY') else '未设置，人格轨将跳过'}")

print("=" * 60)
print(f"🌾 神农全链路集成测试 — {TODAY}")
print(f"测试股票: {', '.join(TEST_SYMBOLS)}")
print("=" * 60)

pipeline = {"run_date": TODAY, "mode": "full", "test": True}
stage_times = {}

# ══════════════════════════════════════════════
# L1 — 跳过扫描，直接用指定股票构造候选
# ══════════════════════════════════════════════
print("\n📡 L1 跳过扫描，直接使用指定股票...")
t0 = time.time()

# 直接用测试股票构造候选列表
candidates = []
name_map = {
    "600519": "贵州茅台", "000333": "美的集团",
    "600036": "招商银行", "000001": "平安银行",
    "601318": "中国平安", "601012": "隆基绿能",
}

for sym in TEST_SYMBOLS:
    candidates.append({
        "code": sym,
        "name": name_map.get(sym, sym),
        "price": 50.0,
        "source": "test",
    })

pipeline["L1"] = {
    "layer": "L1",
    "candidates": candidates,
    "candidate_count": len(candidates),
    "duration_s": 0,
}
print(f"  ✅ L1跳过: {len(candidates)}只指定股票")
for c in candidates:
    print(f"     - {c.get('name', '?')}({c.get('code', '?')})")

stage_times["L1"] = round(time.time() - t0, 2)

# ══════════════════════════════════════════════
# L2 — 数据充实
# ══════════════════════════════════════════════
print("\n📊 L2 数据充实开始...")
t0 = time.time()
try:
    from shennong import run_L2, check_veto
    l2_result = run_L2(candidates)
    pipeline["L2"] = l2_result
    stocks = l2_result.get("stocks", [])
    print(f"  ✅ L2完成: {len(stocks)}只数据充实")
    
    # 检查L2数据完整性
    for s in stocks[:3]:
        code = s.get("code", "?")
        name = s.get("name", "?")
        data = s.get("_data", {})
        price = data.get("price", "N/A")
        pb = data.get("pb", "N/A")
        pe = data.get("pe", "N/A")
        mf = data.get("moneyflow_data", {})
        td = data.get("technical_data", {})
        print(f"  [{name}] 价格={price} PB={pb} PE={pe}")
        print(f"     资金流: main_5d={mf.get('main_net_flow_5d','N/A')}")
        print(f"     技术: macd={td.get('macd_status','N/A')} rsi={td.get('rsi','N/A')}")
    
    # 否决判断
    pipeline["veto"] = check_veto(l2_result)
    passed = pipeline["veto"].get("passed", [])
    rejected = pipeline["veto"].get("rejected", [])
    print(f"  Veto: {len(passed)}通过, {len(rejected)}否决")
    if rejected:
        for r in rejected[:3]:
            print(f"    否决: {r.get('name','?')}({r.get('code','?')}) — {r.get('veto_reason','?')}")
    
    if len(passed) == 0:
        print("  ⚠ 全部否决，终止")
        sys.exit(0)
except Exception as e:
    print(f"  ❌ L2失败: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

stage_times["L2"] = round(time.time() - t0, 2)

# ══════════════════════════════════════════════
# L3 — 量化分析 + 辩论 + 人格轨
# ══════════════════════════════════════════════
print("\n🧠 L3 分析开始（评分+辩论+人格轨）...")
t0 = time.time()
try:
    # 直接导入run_L3而非通过shennong模块（避免argparse冲突）
    from shennong import save_result, make_serializable
    
    veto_result = pipeline["veto"]
    L2_result = pipeline["L2"]
    
    passed_stocks = veto_result.get("passed", [])
    if not passed_stocks:
        print("  ⚠ 无候选股进入L3")
        pipeline["L3"] = {"layer": "L3", "results": [], "duration_s": 0}
    else:
        from five_dimension_scorer import FiveDimensionScorer, StockScoreResult
        from debate_engine import DebateEngine, DebateResult
        from persona_runner import run_persona_analysis
        
        scorer = FiveDimensionScorer()
        debater = DebateEngine(max_rounds=2)
        analysis_results = []
        
        for idx, stock in enumerate(passed_stocks):
            code = stock.get("code", "")
            name = stock.get("name", code)
            data = stock.get("_data", {})
            price = float(data.get("price", stock.get("price", 50.0)))
            
            print(f"\n  [{idx+1}/{len(passed_stocks)}] {name}({code}) @ {price}")
            
            # 评分
            score_result = scorer.score_stock(code, name, {
                "moneyflow_data": data.get("moneyflow_data", {}),
                "technical_data": data.get("technical_data", data),
                "fundamental_data": data.get("fundamental_data", data),
                "sector_data": data.get("sector_data", {}),
                "event_data": data.get("event_data", {}),
            })
            print(f"    ⭐ 评分: {score_result.grade}({score_result.total_score:.0f})")
            
            # 辩论
            debate_result = debater.debate(code, name, score_result=score_result, raw_data=data)
            print(f"    🗣️ 辩论: {debate_result.final_verdict} (置信度{debate_result.confidence:.2f})")
            
            # 人格轨 — 仅测试前3位大师（快速验证）
            print(f"    👤 人格轨: 3位大师独立调用中...")
            persona_result = _test_persona_fast(code, name, price, {
                "moneyflow_data": data.get("moneyflow_data", {}),
                "technical_data": data.get("technical_data", data),
                "fundamental_data": data.get("fundamental_data", data),
                "sector_data": data.get("sector_data", {}),
                "event_data": data.get("event_data", {}),
            })
            
            status = persona_result.get("_status", "?")
            p_summary = persona_result.get("summary", {})
            p_perspectives = persona_result.get("perspectives", {})
            n_buy = p_summary.get("buy_count", 0)
            n_watch = p_summary.get("watch_count", 0)
            n_rej = p_summary.get("reject_count", 0)
            n_hold = p_summary.get("hold_count", 0)
            avg = p_summary.get("avg_score", 0)
            duration_s = persona_result.get("_duration_s", 0)
            n_agents = len(p_perspectives)
            
            print(f"    ✅ 人格轨: 状态={status}, {n_buy}BUY/{n_watch}W/{n_rej}R/{n_hold}H, 均分={avg:.2f}, {duration_s:.1f}s, {n_agents}位大师")
            
            analysis_results.append({
                "code": code,
                "name": name,
                "score": make_serializable(score_result),
                "debate": make_serializable(debate_result),
                "persona": persona_result,
            })
        
        L3_result = {
            "layer": "L3",
            "run_date": TODAY,
            "stock_count": len(analysis_results),
            "results": analysis_results,
            "duration_s": round(time.time() - t0, 2),
        }
        pipeline["L3"] = L3_result
        save_result("L3_analysis_test", L3_result)
    
    print(f"\n  ✅ L3完成: {len(pipeline['L3'].get('results',[]))}只, {pipeline['L3'].get('duration_s',0):.1f}s")
except Exception as e:
    print(f"  ❌ L3失败: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

stage_times["L3"] = round(time.time() - t0, 2)

# ══════════════════════════════════════════════
# L4 — 裁判风控
# ══════════════════════════════════════════════
print("\n🏛️ L4 裁判风控开始...")
t0 = time.time()
try:
    from shennong import run_L4, generate_report
    
    pipeline["L4"] = run_L4(pipeline)
    l4 = pipeline["L4"]
    decisions = l4.get("decisions", [])
    print(f"  ✅ L4完成: {len(decisions)}只")
    for d in decisions:
        print(f"     {d.get('name','?')}({d.get('code','?')}): {d.get('decision','?')} 仓位{d.get('recommended_weight',0):.0%}")
    
    # 汇总报告
    print("\n📋 生成报告...")
    report = generate_report(pipeline)
    print(f"  ✅ 报告生成: {len(report)}字符")
    
except Exception as e:
    print(f"  ❌ L4失败: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

stage_times["L4"] = round(time.time() - t0, 2)
pipeline["stage_times"] = stage_times

# ══════════════════════════════════════════════
# 保存测试结果
# ══════════════════════════════════════════════
print("\n💾 保存测试结果...")
try:
    output_dir = os.path.join(PROJECT_ROOT, "main", "test_output")
    os.makedirs(output_dir, exist_ok=True)
    
    # 保存完整pipeline
    pipeline_clean = make_serializable(pipeline)
    save_path = os.path.join(output_dir, f"test_pipeline_{TODAY}.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(pipeline_clean, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 已保存: {save_path}")
    
    # 保存报告
    report_path = os.path.join(output_dir, f"test_report_{TODAY}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  ✅ 报告保存: {report_path}")
    
    # 输出报告摘要
    print("\n" + "=" * 60)
    print("📄 测试报告摘要")
    print("=" * 60)
    print(report[:2000] + ("\n...(截断)" if len(report) > 2000 else ""))
    
except Exception as e:
    print(f"  ❌ 保存失败: {e}")
    import traceback; traceback.print_exc()

# ══════════════════════════════════════════════
# 结果验证检查
# ══════════════════════════════════════════════
print("\n" + "=" * 60)
print("🔍 结果验证检查")
print("=" * 60)

checks = []

# 1. L1
l1 = pipeline.get("L1", {})
l1_candidates = l1.get("candidates", [])
checks.append(("L1-候选股数量", len(l1_candidates) >= 1, f"{len(l1_candidates)}只"))
checks.append(("L1-候选股含代码", all(c.get("code") for c in l1_candidates), "全部含code"))

# 2. L2
l2 = pipeline.get("L2", {})
l2_stocks = l2.get("stocks", [])
checks.append(("L2-股票数量", len(l2_stocks) >= 1, f"{len(l2_stocks)}只"))
if l2_stocks:
    s0 = l2_stocks[0].get("_data", {})
    checks.append(("L2-含价格数据", bool(s0.get("price")), f"price={s0.get('price','?')}"))
    checks.append(("L2-含PB数据", s0.get("pb") is not None, f"pb={s0.get('pb','?')}"))
    checks.append(("L2-含PE数据", s0.get("pe") is not None, f"pe={s0.get('pe','?')}"))
    checks.append(("L2-含资金流", bool(s0.get("moneyflow_data", {})), "有资金流"))
    checks.append(("L2-含技术数据", bool(s0.get("technical_data", {})), "有技术数据"))
    checks.append(("L2-含基本面数据", bool(s0.get("fundamental_data", {})), "有基本面"))

# 3. Veto
veto = pipeline.get("veto", {})
checks.append(("Veto-有pass字段", "passed" in veto, f"{len(veto.get('passed',[]))}通过/{len(veto.get('rejected',[]))}否决"))

# 4. L3
l3 = pipeline.get("L3", {})
l3_results = l3.get("results", [])
checks.append(("L3-结果数量", len(l3_results) >= 1, f"{len(l3_results)}只"))
if l3_results:
    r0 = l3_results[0]
    checks.append(("L3-含score字段", bool(r0.get("score")), "有"))
    checks.append(("L3-含debate字段", bool(r0.get("debate")), "有"))
    checks.append(("L3-含persona字段", bool(r0.get("persona")), "有"))
    persona = r0.get("persona", {})
    if persona:
        checks.append(("L3-persona含perspectives", bool(persona.get("perspectives")), f"{len(persona.get('perspectives',{}))}位大师"))
        checks.append(("L3-persona含summary", bool(persona.get("summary")), "有汇总"))
        checks.append(("L3-persona含_status", persona.get("_status") in ("ok", "skipped", "error"), persona.get("_status", "?")))

# 5. L4
l4 = pipeline.get("L4", {})
l4_decisions = l4.get("decisions", [])
checks.append(("L4-决策数量", len(l4_decisions) >= 1, f"{len(l4_decisions)}只"))
if l4_decisions:
    d0 = l4_decisions[0]
    checks.append(("L4-含决策", bool(d0.get("decision")), d0.get("decision", "?")))
    checks.append(("L4-含仓位", d0.get("recommended_weight") is not None, f"{d0.get('recommended_weight',0):.0%}"))

# 6. 保存
checks.append(("文件-保存pipeline", os.path.exists(save_path), save_path))
checks.append(("文件-保存report", os.path.exists(report_path), report_path))

# 打印结果
all_pass = True
for name, ok, detail in checks:
    mark = "✅" if ok else "❌"
    if not ok:
        all_pass = False
    print(f"  {mark} {name}: {detail}")

print(f"\n{'='*60}")
if all_pass:
    print("🎉 全部检查通过！")
else:
    print("⚠️ 存在失败检查项，请查看上述❌标记")
print(f"{'='*60}")

# 输出报告全文用于检查
print("\n📄 报告全文:")
print("=" * 60)
print(report)
