#!/usr/bin/env python3
"""
神农主调度器 — 简洁的 for 循环编排 L1→L2→L3→L4→L5

核心思路：
- 所有控制逻辑在 main 组装
- 各层 runner 只消费 context 读配置，写结果
- 配置全部入 PipelineContext

使用方法:
  python shennong.py --mode full              # 全链路运行
  python shennong.py --mode L2                # 只跑L1→L2
  python shennong.py --mode L3 --code 600519  # 指定股票跑L3
"""
import sys
import os
import json
import math
import time
import logging
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

# ── 环境变量加载（必须最早）─────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.hermes/.env"), override=True)

# ── 路径配置 ───────────────────────────────────
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
    PROJECT_ROOT,
]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── 日志 ──────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("shennong")

# ── 常量 ────────────────────────────────────────
TODAY = datetime.now().strftime("%Y-%m-%d")
NOW_TS = datetime.now().strftime("%H:%M:%S")
FREEZE_TABLE = os.path.join(PROJECT_ROOT, "main", "freeze_table.json")

# ── 辅助函数 ────────────────────────────────────

def load_freeze_table() -> dict:
    try:
        with open(FREEZE_TABLE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"frozen_codes": set(), "observing_codes": set(), "observing_list": [], "freeze_records": []}


def _sanitize(data):
    """深度复制并转换所有 numpy/pandas 类型为 Python 原生类型"""
    if isinstance(data, dict):
        return {k: _sanitize(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_sanitize(item) for item in data]
    if isinstance(data, (int, float, str, bool, type(None))):
        return data
    try:
        if hasattr(data, "item"):
            return data.item()
        if hasattr(data, "tolist"):
            return data.tolist()
    except Exception:
        pass
    return str(data)


def make_serializable(obj):
    """将 dataclass/numpy 等转为可 JSON 序列化的 dict"""
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
    except Exception:
        pass
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: make_serializable(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_serializable(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def generate_report(pipeline: dict) -> str:
    """生成可读摘要"""
    l4 = pipeline.get("L4", {})
    decisions = l4.get("decisions", [])
    buy_count = l4.get("buy_count", 0)
    total = l4.get("stock_count", 0)
    buy_decisions = [d for d in decisions if d.get("decision") == "BUY"]
    if buy_decisions:
        names = "、".join([f"{d.get('name', '')}({d.get('code', '')})" for d in buy_decisions[:5]])
        extra = f"等{len(buy_decisions)}只" if len(buy_decisions) > 5 else ""
        return f"✅ {TODAY} BUY {buy_count}/{total} | {names}{extra}"
    return f"⛔ {TODAY} REJECT {total}/{total} | 本日无买入"


# ══════════════════════════════════════════════
#  Pipeline Orchestrator
# ══════════════════════════════════════════════

def run_pipeline(ctx) -> dict:
    """
    全链路编排：L1 → L2 → L3 → L4 → L5

    入口：PipelineContext（run_date, market, mode, configs）
    出口：dict（兼容旧 pipeline 结构）
    """
    from main.contracts import PipelineContext, Market
    from main.l1_runner import run_l1
    from main.l2_runner import run_l2
    from main.l3_runner import run_l3
    from main.l4_runner import run_l4
    from main.l5_runner import run_l5

    stage_times = {}
    pipeline = {"run_date": ctx.run_date, "mode": ctx.mode, "market": ctx.market.value}

    # ── L1 ─────────────────────────────────────────────────────────────
    t0 = time.time()
    ctx = run_l1(ctx)
    stage_times["L1"] = round(time.time() - t0, 2)

    if ctx.l1_result:
        pipeline["L1"] = make_serializable(ctx.l1_result)

    if ctx.mode == "L1":
        return pipeline

    # ── L2 ─────────────────────────────────────────────────────────────
    t0 = time.time()
    ctx = run_l2(ctx)
    stage_times["L2"] = round(time.time() - t0, 2)

    if ctx.l2_result:
        pipeline["L2"] = make_serializable(ctx.l2_result)

    if ctx.l2_result and ctx.l2_result.stock_count == 0:
        pipeline["report"] = f"⛔ {TODAY} L1无候选股票"
        pipeline["stage_times"] = stage_times
        return pipeline

    # ── 极差判断（veto） ───────────────────────────────────────────────
    veto_result = _check_veto(ctx)
    pipeline["veto"] = {
        "passed": veto_result.get("passed", []),
        "vetoed": veto_result.get("vetoed", []),
        "pass_count": veto_result.get("pass_count", 0),
    }

    if veto_result.get("pass_count", 0) == 0:
        pipeline["L3"] = {"layer": "L3", "results": [], "duration_s": 0, "_aborted": True}
        pipeline["L4"] = {"layer": "L4", "decisions": [], "duration_s": 0, "_aborted": True}
        pipeline["report"] = f"⛔ {TODAY} 所有候选股均被否决"
        pipeline["stage_times"] = stage_times
        return pipeline

    if ctx.mode == "L2":
        return pipeline

    # ── L3 + L4（串行for循环）─────────────────────────────────────────
    t0 = time.time()
    l3_results = []
    l4_decisions = []
    passed_stocks = veto_result.get("passed", [])

    logger.info(f"🌱 L3→L4 串行分析: {len(passed_stocks)} 只")

    for stock in passed_stocks:
        try:
            # 为每只股票构建子 context（仅含 L2 数据）
            from main.contracts.l2 import L2StockData
            code = stock.get("code", "")
            name = stock.get("name", "")
            l2_stock_dict = stock.get("_data", {})
            l2_sd = L2StockData.from_dict({"code": code, "name": name, **l2_stock_dict})

            from main.contracts import L2Result
            stock_ctx = PipelineContext(
                run_date=ctx.run_date,
                market=ctx.market,
                l2_result=L2Result(
                    stocks=[l2_sd.to_dict()],
                    stock_count=1,
                    run_date=ctx.run_date,
                ),
                l3_config=ctx.l3_config,
                l3_persona_config=ctx.l3_persona_config,
                l4_risk_config=ctx.l4_risk_config,
            )

            stock_ctx = run_l3(stock_ctx, skip_persona=(ctx.mode == "quick"))
            if stock_ctx.l3_result and stock_ctx.l3_result.results:
                l3_results.extend(stock_ctx.l3_result.results)

                # L4 需要 L3 + L2 数据
                stock_ctx.l2_result = stock_ctx.l2_result
                stock_ctx = run_l4(stock_ctx)
                if stock_ctx.l4_result and stock_ctx.l4_result.decisions:
                    l4_decisions.extend(stock_ctx.l4_result.decisions)
        except Exception as e:
            logger.error(f"  {stock.get('code', '?')} L3/L4 异常: {e}")

    l3_elapsed = time.time() - t0

    # 合并到 ctx
    from main.contracts.l3 import L3Result
    from main.contracts.l4 import L4Result
    ctx.l3_result = L3Result(
        layer="L3", run_date=ctx.run_date, stock_count=len(l3_results),
        results=l3_results, duration_s=l3_elapsed,
    )
    ctx.l4_result = L4Result(
        layer="L4", run_date=ctx.run_date,
        stock_count=len(l4_decisions),
        buy_count=sum(1 for d in l4_decisions if d.decision.value == "BUY"),
        decisions=l4_decisions, duration_s=0.0,
    )

    pipeline["L3"] = make_serializable(ctx.l3_result)
    pipeline["L4"] = make_serializable(ctx.l4_result)
    stage_times["L3"] = round(l3_elapsed, 2)
    stage_times["L4"] = 0.0

    if not l3_results:
        pipeline["report"] = f"⛔ {TODAY} L3无有效分析结果"
        pipeline["stage_times"] = stage_times
        return pipeline

    # L4 mode 需要在返回前生成报告摘要
    if ctx.mode in ("L3", "L4"):
        pipeline["report"] = generate_report(pipeline)
        pipeline["stage_times"] = stage_times
        pipeline["buy_count"] = ctx.l4_result.buy_count if ctx.l4_result else 0
        pipeline["stock_count"] = ctx.l4_result.stock_count if ctx.l4_result else 0
        return pipeline

    # ── L5 ─────────────────────────────────────────────────────────────
    t0 = time.time()
    ctx = run_l5(ctx)
    stage_times["L5"] = round(time.time() - t0, 2)

    if ctx.l5_result:
        pipeline["L5"] = make_serializable(ctx.l5_result)

    # ── 汇总 ──────────────────────────────────────────────────────────────
    pipeline["report"] = generate_report(pipeline)
    pipeline["stage_times"] = stage_times
    pipeline["buy_count"] = ctx.l4_result.buy_count if ctx.l4_result else 0
    pipeline["stock_count"] = ctx.l4_result.stock_count if ctx.l4_result else 0

    # ── 写入平台数据库 ───────────────────────────────
    try:
        from main.db_writer import update_from_pipeline_result
        update_from_pipeline_result(pipeline, market=ctx.market.value)
    except Exception as e:
        logger.warning(f"DB写入失败（非阻塞）: {e}")

    return pipeline


def _check_veto(ctx) -> dict:
    """
    极差判断 — 从 L2 数据中检查是否有直接否决条件
    返回 {"passed": [...], "vetoed": [...], "pass_count": int}
    """
    from main.contracts.l2 import L2StockData

    vetoed = []
    passed = []

    if not ctx.l2_result:
        return {"passed": [], "vetoed": [], "pass_count": 0}

    for stock_dict in ctx.l2_result.stocks:
        code = stock_dict.get("code", "")
        name = stock_dict.get("name", "")
        data = stock_dict  # L2StockData.to_dict() 展开后 code/name 在顶层

        reasons = []
        mf = data.get("moneyflow_data", {})
        if mf:
            mf_5d = mf.get("main_net_flow_5d", 0)
            if isinstance(mf_5d, (int, float)) and mf_5d < -50_000_000:
                reasons.append(f"资金面: 5日主力净流出{abs(mf_5d)/1e4:.0f}万")

        td = data.get("technical_data", {})
        if td.get("ma_status") == "bearish" and td.get("macd_status") in ("death", "death_cross"):
            reasons.append("技术面: 均线空头+MACD死叉共振")

        if reasons:
            vetoed.append({"code": code, "name": name, "reasons": reasons})
            logger.info(f"  ⛔ {name}({code}): {'; '.join(reasons)}")
        else:
            passed.append({"code": code, "name": name, "_data": data})

    logger.info(f"极差判断: 通过 {len(passed)} / 否决 {len(vetoed)}")
    return {"passed": passed, "vetoed": vetoed, "pass_count": len(passed)}


# ══════════════════════════════════════════════
#  CLI 入口
# ══════════════════════════════════════════════

def main():
    from main.contracts import PipelineContext, Market, load_all_config

    parser = argparse.ArgumentParser(description="神农投资分析系统")
    parser.add_argument("--mode", default="full",
                        choices=["full", "L1", "L2", "L3", "L4", "L5", "quick"],
                        help="运行模式 (默认full全链路)")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="指定股票代码")
    parser.add_argument("--market", default="CN",
                        choices=["CN", "HK", "US"],
                        help="市场: CN=A股(默认), HK=港股, US=美股")
    args = parser.parse_args()

    logger.info(f"🌾 神农系统启动 — {TODAY}")
    logger.info(f"市场: {args.market} | 模式: {args.mode}")

    # 构建 PipelineContext
    ctx = PipelineContext(
        run_date=TODAY,
        market=Market(args.market),
        mode=args.mode,
    )
    ctx = load_all_config(ctx)

    result = run_pipeline(ctx)

    L4 = result.get("L4", {})
    buy_count = L4.get("buy_count", 0)
    total = L4.get("stock_count", 0)
    stage_times = result.get("stage_times", {})
    logger.info(f"🌾 神农完成 — BUY {buy_count}/{total} | 耗时: {stage_times}")

    report = result.get("report", "")
    if report:
        print(report)


if __name__ == "__main__":
    main()