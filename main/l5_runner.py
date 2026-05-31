#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 Runner — 统一入口（扩展后）

调用现有 L5 模块 + 新增 PositionTracker / ReportGenerator / ParameterAdvisor，
将结果写入 context.l5_result。
"""
import sys
import os
import time
from datetime import datetime, timedelta
from dataclasses import asdict

BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))

from logger import info, warn

from main.contracts import PipelineContext
from main.contracts.context import L5Result


def run_l5(ctx: PipelineContext) -> PipelineContext:
    """
    L5 终审

    入口：ctx.l4_result.decisions[]
    出口：ctx.l5_result = L5Result（扩展后）

    调用流程：
        1. FreezeManager.record_buy_signal()  — 记录 BUY 信号
        2. FreezeManager.check_and_update_freeze() — 更新冷冻状态
        3. PositionTracker.check_triggers() — 检查止损/止盈触发
        4. ReviewEngine.run_review() — 执行复盘
        5. ParameterAdvisor.analyze_and_suggest() — 生成调参建议
        6. ReportGenerator.generate_daily/weekly_report() — 生成报告
    """
    t0 = time.time()
    info("l5_runner", f"开始L5终审: {ctx.l4_result.buy_count} 只BUY决策")

    if ctx.l4_result is None or ctx.l4_result.stock_count == 0:
        warn("l5_runner", "L4无决策，跳过L5")
        ctx.l5_result = L5Result(layer="L5", run_date=ctx.run_date, review_count=0)
        return ctx

    errors = []

    try:
        # ── Step 1: FreezeManager — 记录 BUY 信号 ────────────
        from L5_post_review.freeze_manager import FreezeManager
        fm = FreezeManager(market=ctx.market.value)

        decisions_recorded = 0
        for decision in ctx.l4_result.decisions:
            if decision.decision.value == "BUY":
                try:
                    ok = fm.record_buy_signal(
                        stock_code=decision.code,
                        stock_name=decision.name,
                        judge_score=decision.judge_score,
                        price=decision.price,
                        stop_loss=decision.stop_loss,
                        take_profit=decision.take_profit,
                        kelly_fraction=decision.kelly_fraction,
                        reason=f"l4_judge:{decision.verdict}",
                    )
                    if ok:
                        decisions_recorded += 1
                except Exception as e:
                    errors.append({"module": "FreezeManager.record_buy_signal",
                                   "code": decision.code, "error": str(e)})

        # ── Step 2: FreezeManager — 更新冷冻状态 ──────────────
        freeze_state_serialized = {}
        try:
            freeze_state = fm.check_and_update_freeze()
            freeze_state_serialized = {
                "expired": freeze_state.get("expired", []),
                "upgraded": freeze_state.get("upgraded", []),
                "unfrozen": freeze_state.get("unfrozen", []),
            }
        except Exception as e:
            errors.append({"module": "FreezeManager.check_and_update_freeze",
                           "error": str(e)})

        # ── Step 3: PositionTracker — 持仓追踪检查 ────────────
        from L5_post_review.core.position_tracker import PositionTracker
        pt = PositionTracker(market=ctx.market.value)

        trigger_results = {"stop_loss": [], "take_profit": [], "expired": [], "unchanged": []}
        position_summary_dict = {}

        try:
            trigger_results = pt.check_triggers(check_date=ctx.run_date)
            # 序列化 trigger_results
            trigger_results_serialized = {
                k: [asdict(r) for r in v] for k, v in trigger_results.items()
            }

            # 更新触发止损/止盈/过期的持仓状态
            for record in trigger_results.get("stop_loss", []):
                pt.update_position_status(
                    stock_code=record.stock_code,
                    status="stopped",
                    exit_price=getattr(record, 'exit_price', None),
                    exit_date=ctx.run_date,
                    exit_reason="stop_loss"
                )

            for record in trigger_results.get("take_profit", []):
                pt.update_position_status(
                    stock_code=record.stock_code,
                    status="take_profit",
                    exit_price=getattr(record, 'exit_price', None),
                    exit_date=ctx.run_date,
                    exit_reason="take_profit"
                )

            for record in trigger_results.get("expired", []):
                pt.update_position_status(
                    stock_code=record.stock_code,
                    status="expired",
                    exit_date=ctx.run_date,
                    exit_reason="expired"
                )

            position_summary = pt.get_position_summary()
            position_summary_dict = asdict(position_summary) if position_summary else {}

        except Exception as e:
            errors.append({"module": "PositionTracker", "error": str(e)})
            trigger_results_serialized = trigger_results

        # ── Step 4: ReviewEngine — 复盘 ─────────────────────
        from L5_post_review.review_engine import ReviewEngine
        re = ReviewEngine(market=ctx.market.value)

        review_raw = {"trades_reviewed": 0}
        cpcv = {}
        effectiveness = {}

        try:
            re.evaluate_outcomes()
            review_raw = re.run_review()
            cpcv = review_raw.get("cpcv_validation", {})
            effectiveness = review_raw.get("effectiveness", {})
        except Exception as e:
            errors.append({"module": "ReviewEngine", "error": str(e)})

        # ── Step 5: ParameterAdvisor — 参数调参建议 ───────────
        from L5_post_review.utils.parameter_advisor import ParameterAdvisor
        advisor = ParameterAdvisor(market=ctx.market.value)

        suggestions = []
        try:
            from L5_post_review.review_engine import CPCVResult, EffectivenessMetrics

            cpcv_result = None
            if cpcv:
                try:
                    cpcv_result = CPCVResult(**cpcv)
                except Exception:
                    pass

            metrics = None
            if effectiveness:
                try:
                    metrics = EffectivenessMetrics(
                        total_decisions=effectiveness.get("total_decisions", 0),
                        buy_count=effectiveness.get("buy_count", 0),
                        watch_count=effectiveness.get("watch_count", 0),
                        reject_count=effectiveness.get("reject_count", 0),
                        buy_hit_rate=effectiveness.get("buy_hit_rate", 0),
                        buy_avg_return=effectiveness.get("buy_avg_return", 0),
                        watch_to_buy_upgrade_rate=effectiveness.get("watch_to_buy_upgrade_rate", 0),
                        reject_keep_dropping_rate=effectiveness.get("reject_keep_dropping_rate", 0),
                        sharpe_like=effectiveness.get("sharpe_like", 0),
                        win_loss_ratio=effectiveness.get("win_loss_ratio", 0),
                    )
                except Exception:
                    pass

            if cpcv_result or metrics:
                positions = pt.get_positions()
                suggestions = advisor.analyze_and_suggest(
                    cpcv_result=cpcv,
                    effectiveness_metrics=effectiveness,
                    positions=positions,
                    date=ctx.run_date
                )
        except Exception as e:
            errors.append({"module": "ParameterAdvisor.analyze_and_suggest", "error": str(e)})

        # ── Step 6: ReportGenerator — 生成定期报告 ────────────
        from L5_post_review.utils.report_generator import ReportGenerator
        rg = ReportGenerator(market=ctx.market.value)

        report_path = None
        try:
            if _is_end_of_week(ctx.run_date):
                report = rg.generate_weekly_report(week_start=_get_week_start(ctx.run_date))
            else:
                report = rg.generate_daily_report(report_date=ctx.run_date)
            report_path = report.file_path if report else None
        except Exception as e:
            errors.append({"module": "ReportGenerator", "error": str(e)})

        # ── Step 7: 组装 L5Result ─────────────────────────────
        elapsed = time.time() - t0

        ctx.l5_result = L5Result(
            layer="L5",
            run_date=ctx.run_date,
            review_count=review_raw.get("trades_reviewed", 0),
            decisions_recorded=decisions_recorded,
            freeze_updated=True,
            effectiveness=effectiveness,
            cpcv=cpcv,
            freeze_state=freeze_state_serialized,
            position_summary=position_summary_dict,
            trigger_results=trigger_results_serialized if 'trigger_results_serialized' in dir() else trigger_results,
            report_path=report_path,
            parameter_advice=[asdict(s) for s in suggestions],
            duration_s=elapsed,
            errors=errors,
        )

        info("l5_runner",
             f"L5终审完成: 记录{decisions_recorded}个BUY，复盘{review_raw.get('trades_reviewed', 0)}笔，"
             f"调参建议{len(suggestions)}条，报告{report_path or '未生成'}")
        return ctx

    except Exception as e:
        info("l5_runner", f"L5终审异常: {e}")
        ctx.add_error("L5", "", str(e))
        ctx.l5_result = L5Result(
            layer="L5",
            run_date=ctx.run_date,
            errors=[{"module": "l5_runner", "error": str(e)}]
        )
        return ctx


# ── 辅助函数 ──────────────────────────────────────────────────

def _is_end_of_week(date_str: str) -> bool:
    """判断是否为周末（可用于确定是否生成周报）"""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.weekday() == 4  # Friday
    except Exception:
        return False


def _get_week_start(date_str: str) -> str:
    """获取周起始日期（周一）"""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        monday = d - timedelta(days=d.weekday())
        return monday.strftime("%Y-%m-%d")
    except Exception:
        return date_str