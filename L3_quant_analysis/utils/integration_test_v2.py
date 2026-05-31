#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全链路集成测试 v2 — 使用真实数据源
数据流：实时数据获取器 → 五维评分 → 辩论引擎 → 风控引擎

2026-04-23 实时数据
"""

import sys
import os
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scoring.five_dimension_scorer import FiveDimensionScorer
from debate.debate_engine import DebateEngine
from risk.risk_manager import RiskManager

logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("integration_test")


def run_integration():
    """全链路集成测试"""
    print("=" * 72)
    print("  神农 SHENNONG — 全链路集成测试 (真实数据源)")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 72)

    scorer = FiveDimensionScorer()
    debate = DebateEngine()
    risk_mgr = RiskManager(total_capital=100_000)

    test_stocks = [
        ("600519", "贵州茅台"),
        ("000858", "五粮液"),
        ("601318", "中国平安"),
        ("002594", "比亚迪"),
        ("000002", "万科A"),
    ]

    all_results = []

    for i, (code, name) in enumerate(test_stocks):
        print(f"\n{'─'*72}")
        print(f"  [{i+1}/{len(test_stocks)}] {name} ({code})")
        print(f"{'─'*72}")

        try:
            # STEP 1：实时数据 + 五维评分
            print("  Step 1: 实时数据 + 五维评分...")
            score_result = scorer.score_from_api(code, name)
            score_dict = score_result.to_dict()

            print(f"    综合分: {score_dict['total_score']:.1f} | 等级: {score_dict['grade']}")
            print(f"    否决: {'⚠️ 是' if score_result.veto_triggered else '✓ 否'}")
            if score_result.veto_triggered:
                print(f"    否决原因: {score_result.veto_reason}")
            for k, d in score_dict['scores'].items():
                source = d.get('data_source', '')[:50]
                print(f"    [{k}] {d['dimension_name']}: {d['score']:.1f}×{d['weight']:.0%}={d['weighted_score']:.1f} | {source}")

            # STEP 2：辩论引擎（传入 score_result 对象）
            print("  Step 2: 多Agent辩论...")
            debate_result = debate.debate(code, name, score_result=score_result)
            dr_dict = debate_result.to_dict()

            verdict_dir = dr_dict['final_verdict']
            verdict_emoji = "📈 看多" if verdict_dir == "bull" else "📉 看空" if verdict_dir == "bear" else "⚖️ 中性"
            print(f"    裁决: {verdict_emoji}")
            print(f"    置信度: {dr_dict['confidence']:.1%}")
            print(f"    多方分: {dr_dict['bull_total_score']:.1f} | 空方分: {dr_dict['bear_total_score']:.1f}")
            for opp in dr_dict.get('key_opportunities', []):
                print(f"    🟢 {opp}")
            for risk in dr_dict.get('key_risks', []):
                print(f"    🔴 {risk}")

            verdict = {"direction": verdict_dir, "confidence": dr_dict['confidence'], "reasoning": ""}

            # STEP 3：风控引擎
            print("  Step 3: 风险管理...")
            current_price = 0
            tech_detail = score_dict['scores'].get('technical', {}).get('detail', {})
            if tech_detail and 'price' in tech_detail:
                current_price = tech_detail['price']
            if not current_price or current_price <= 0:
                current_price = score_dict.get('price', 50)

            risk_assessment = risk_mgr.assess_stock_risk(
                stock_code=code, stock_name=name,
                current_price=current_price,
                score_result=score_result,  # 传对象而非dict
            )
            ra_dict = risk_assessment.to_dict()

            print(f"    风险分: {ra_dict['risk_score']:.0f}/100")
            suggested_pct = ra_dict['recommended_weight'] * 100
            suggested_amount = risk_mgr.total_capital * suggested_pct / 100
            print(f"    建议仓位: {suggested_pct:.1f}%")
            print(f"    建议金额: ¥{suggested_amount:.0f}")
            print(f"    止损价: ¥{ra_dict['stop_loss_price']:.2f}")

            all_results.append({
                "code": code, "name": name,
                "score": round(score_dict['total_score'], 1),
                "grade": score_dict['grade'],
                "veto": "⚠️" if score_result.veto_triggered else "✓",
                "veto_reason": score_result.veto_reason,
                "debate_dir": verdict_dir,
                "confidence": f"{dr_dict['confidence']:.0%}",
                "risk_score": round(ra_dict['risk_score']),
                "suggested_pct": f"{ra_dict['recommended_weight']*100:.1f}%",
            })

        except Exception as e:
            print(f"  ❌ 失败 {code}: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({"code": code, "name": name, "error": str(e)})

    # 汇总
    print(f"\n\n{'='*72}")
    print("  全链路集成测试 — 汇总排名")
    print(f"{'='*72}")
    
    valid = [r for r in all_results if 'error' not in r]
    valid.sort(key=lambda r: r['score'], reverse=True)
    
    hdr = f"{'排名':<4} {'名称':<12} {'评分':<6} {'等级':<4} {'否决':<4} {'辩论':<6} {'置信':<8} {'风险分':<6} {'建议仓位':<8}"
    print(hdr)
    print(f"{'─'*72}")
    for i, r in enumerate(valid):
        print(f"{i+1:<4} {r['name']:<12} {r['score']:<6.1f} {r['grade']:<4} {r['veto']:<4} {r['debate_dir']:<6} {r['confidence']:<8} {r['risk_score']:<6d} {r['suggested_pct']:<8}")

    print(f"\n✅ 测试完成! {len(valid)}/{len(test_stocks)} 只股票全链路通过")

    # 保存结果
    output_dir = os.path.expanduser("~/.hermes/investment/L3_quant_analysis/test_output")
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(f"{output_dir}/integration_v2_{ts}.json", "w") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"结果已保存: {output_dir}/integration_v2_{ts}.json")


if __name__ == "__main__":
    run_integration()
