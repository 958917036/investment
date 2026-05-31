#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 Report Generator（定期报告模块）

职责：
1. 生成每日/每周复盘报告（Markdown 格式）
2. 包含操作回顾、持仓状态、策略有效性、冷冻状态、CPCV、参数调参建议
3. 保存到 main/records/{date}/ 目录
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional

import sys
BASE = os.path.expanduser("~/.hermes/investment")
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import info, warn, error

# ======================== 路径配置 ========================

PROJECT_ROOT = Path(os.path.expanduser("~/.hermes/investment"))
RECORDS_DIR = PROJECT_ROOT / "main" / "records"
REVIEW_OUTPUT_DIR = PROJECT_ROOT / "main" / "config" / "review_pending"


# ======================== 数据模型 ========================

@dataclass
class ReportSection:
    """报告章节"""
    title: str
    content: str
    order: int
    level: int = 2


@dataclass
class GeneratedReport:
    """生成的报告"""
    report_id: str
    report_type: str                    # daily / weekly
    date: str                           # 报告日期
    week_start: Optional[str] = None # 周起始日期（周报用）
    week_end: Optional[str] = None      # 周结束日期（周报用）
    sections: List[ReportSection] = field(default_factory=list)
    file_path: Optional[str] = None
    generated_at: str = ""
    markets: List[str] = field(default_factory=list)


# ======================== Report Generator ========================

class ReportGenerator:
    """
    定期报告生成器

    职责：
    1. 生成每日/每周复盘报告（Markdown 格式）
    2. 包含操作回顾、持仓状态、策略有效性、冷冻状态、CPCV、参数调参建议
    3. 保存到 main/records/{date}/ 目录
    """

    def __init__(self, market: str = "CN"):
        self.market = market.upper()
        self._engine = None
        self._freeze_mgr = None
        self._tracker = None

    # ── 懒加载子模块 ──────────────────────────────────────────

    @property
    def review_engine(self):
        """懒加载 ReviewEngine"""
        if self._engine is None:
            from L5_post_review.review_engine import ReviewEngine
            self._engine = ReviewEngine(market=self.market)
        return self._engine

    @property
    def freeze_manager(self):
        """懒加载 FreezeManager"""
        if self._freeze_mgr is None:
            from L5_post_review.freeze_manager import FreezeManager
            self._freeze_mgr = FreezeManager(market=self.market)
        return self._freeze_mgr

    @property
    def position_tracker(self):
        """懒加载 PositionTracker"""
        if self._tracker is None:
            from L5_post_review.core.position_tracker import PositionTracker
            self._tracker = PositionTracker(market=self.market)
        return self._tracker

    # ── 主入口 ────────────────────────────────────────────────

    def generate_daily_report(self, report_date: str = None) -> GeneratedReport:
        """
        生成每日报告

        Args:
            report_date: 报告日期 YYYY-MM-DD，默认为今天

        Returns:
            GeneratedReport
        """
        if report_date is None:
            report_date = date.today().strftime("%Y-%m-%d")

        report_id = f"{report_date}_daily"

        sections = []
        sections.append(self._build_operations_section(report_date))
        sections.append(self._build_positions_section(report_date))
        sections.append(self._build_effectiveness_section())
        sections.append(self._build_freeze_section())
        sections.append(self._build_cpcv_section())
        sections.append(self._build_parameter_advice_section(report_date))

        report = GeneratedReport(
            report_id=report_id,
            report_type="daily",
            date=report_date,
            sections=sections,
            generated_at=datetime.now().isoformat(),
            markets=[self.market],
        )

        report.file_path = self.save_report(report)
        return report

    def generate_weekly_report(self, week_start: str = None) -> GeneratedReport:
        """
        生成每周报告

        Args:
            week_start: 周起始日期 YYYY-MM-DD（周一），默认为上一周

        Returns:
            GeneratedReport
        """
        if week_start is None:
            today = date.today()
            week_start = (today - timedelta(days=today.weekday() + 7)).strftime("%Y-%m-%d")

        week_end = (datetime.strptime(week_start, "%Y-%m-%d").date() + timedelta(days=6)).strftime("%Y-%m-%d")
        report_id = f"{week_start}_weekly"

        sections = []
        sections.append(self._build_weekly_summary_section(week_start, week_end))
        sections.append(self._build_positions_section(week_end))
        sections.append(self._build_effectiveness_section())
        sections.append(self._build_freeze_section())
        sections.append(self._build_cpcv_section())
        sections.append(self._build_parameter_advice_section(week_end))

        report = GeneratedReport(
            report_id=report_id,
            report_type="weekly",
            date=week_end,
            week_start=week_start,
            week_end=week_end,
            sections=sections,
            generated_at=datetime.now().isoformat(),
            markets=[self.market],
        )

        report.file_path = self.save_report(report)
        return report

    def generate_multi_market_report(
        self,
        report_date: str,
        markets: List[str] = None
    ) -> GeneratedReport:
        """
        生成多市场综合报告

        Args:
            report_date: 报告日期
            markets: 市场列表，默认 ["CN", "HK", "US"]

        Returns:
            GeneratedReport
        """
        if markets is None:
            markets = ["CN", "HK", "US"]

        report_id = f"{report_date}_multi_market"

        sections = []
        for market in markets:
            sections.append(self._build_market_section(market, report_date))

        report = GeneratedReport(
            report_id=report_id,
            report_type="multi_market",
            date=report_date,
            sections=sections,
            generated_at=datetime.now().isoformat(),
            markets=markets,
        )

        report.file_path = self.save_report(report)
        return report

    # ── 章节构建 ──────────────────────────────────────────────

    def _build_operations_section(self, report_date: str) -> ReportSection:
        """构建操作回顾章节"""
        lines = []

        # 获取当日的 BUY决策记录
        tracker = self.position_tracker
        positions = tracker.get_positions()

        if positions:
            lines.append("| 股票代码 | 名称 | 状态 | 买入价 | 止损价 | 止盈价 | 评分 |")
            lines.append("|---------|------|------|--------|--------|--------|------|")
            for p in positions:
                lines.append(f"| {p.stock_code} | {p.stock_name} | {p.status} | "
                           f"{p.entry_price:.2f} | {p.stop_loss:.2f} | {p.take_profit:.2f} | "
                           f"{p.judge_score:.3f} |")
        else:
            lines.append("当日无操作记录。")

        return ReportSection(
            title="一、操作回顾",
            content="\n".join(lines),
            order=1,
        )

    def _build_positions_section(self, report_date: str) -> ReportSection:
        """构建持仓状态章节"""
        tracker = self.position_tracker
        summary = tracker.get_position_summary()

        lines = []
        lines.append(f"|状态 | 数量 |")
        lines.append("|------|------|")
        lines.append(f"| 待执行（pending） | {summary.pending_count} |")
        lines.append(f"| 已执行（executed） | {summary.executed_count} |")
        lines.append(f"| 止损触发（stopped） | {summary.stopped_count} |")
        lines.append(f"| 止盈触发（take_profit） | {summary.take_profit_count} |")
        lines.append(f"| 已过期（expired） | {summary.expired_count} |")
        lines.append("")
        lines.append(f"**总持仓**: {summary.total_count} 个")
        lines.append(f"**总收益/亏损**: {summary.total_pnl_pct:.2%}")
        lines.append(f"**平均持仓天数**: {summary.avg_holding_days:.1f} 天")

        return ReportSection(
            title="二、持仓状态",
            content="\n".join(lines),
            order=2,
        )

    def _build_effectiveness_section(self) -> ReportSection:
        """构建策略有效性章节"""
        try:
            metrics = self.review_engine.get_effectiveness_report()
        except Exception:
            return ReportSection(
                title="三、策略有效性",
                content="（数据不可用）",
                order=3,
            )

        lines = []
        lines.append("| 指标 | 值 | 健康阈值 | 状态 |")
        lines.append("|------|-----|----------|------|")

        # BUY 命中率
        hit_rate = metrics.buy_hit_rate
        status = "✅" if hit_rate > 0.55 else "⚠️"
        lines.append(f"| BUY 命中率 | {hit_rate:.1%} | >55% | {status} |")

        # BUY 平均收益
        avg_ret = metrics.buy_avg_return
        status = "✅" if avg_ret > 0 else "⚠️"
        lines.append(f"| BUY 平均收益 | {avg_ret:.2%} | >0% | {status} |")

        # WATCH 升级率
        watch_rate = metrics.watch_to_buy_upgrade_rate
        lines.append(f"| WATCH 升级率 | {watch_rate:.1%} | >30% | - |")

        # REJECT 有效率
        reject_rate = metrics.reject_keep_dropping_rate
        status = "✅" if reject_rate > 0.70 else "⚠️"
        lines.append(f"| REJECT 有效率 | {reject_rate:.1%} | >70% | {status} |")

        # 盈亏比
        wl_ratio = metrics.win_loss_ratio
        status = "✅" if wl_ratio > 1.5 else "⚠️"
        lines.append(f"| 盈亏比 | {wl_ratio:.2f}x | >1.5x | {status} |")

        # 模拟夏普
        sharpe = metrics.sharpe_like
        status = "✅" if sharpe > 0 else "⚠️"
        lines.append(f"| 模拟夏普 | {sharpe:.2f} | >0 | {status} |")

        return ReportSection(
            title="三、策略有效性",
            content="\n".join(lines),
            order=3,
        )

    def _build_freeze_section(self) -> ReportSection:
        """构建冷冻状态章节"""
        fm = self.freeze_manager
        summary = fm.get_summary()

        lines = []
        lines.append(f"| 类型 | 数量 |")
        lines.append("|------|------|")
        lines.append(f"| 冷冻中 | {summary['frozen_count']} |")
        lines.append(f"| 观察池 | {summary['observing_count']} |")
        lines.append(f"| 买入信号 | {summary['buy_signals_count']} |")

        if summary.get("frozen_codes"):
            lines.append("")
            lines.append(f"**冷冻股票**: {', '.join(summary['frozen_codes'])}")

        return ReportSection(
            title="四、冷冻状态",
            content="\n".join(lines),
            order=4,
        )

    def _build_cpcv_section(self) -> ReportSection:
        """构建 CPCV 防过拟合验证章节"""
        try:
            review_raw = self.review_engine.run_review()
            cpcv = review_raw.get("cpcv_validation", {})
        except Exception:
            return ReportSection(
                title="五、CPCV 防过拟合验证",
                content="（数据不可用）",
                order=5,
            )

        if not cpcv:
            return ReportSection(
                title="五、CPCV 防过拟合验证",
                content="（无复盘数据）",
                order=5,
            )

        lines = []
        verdict = cpcv.get("verdict", "UNKNOWN")
        verdict_icon = "✅" if verdict == "PASS" else "❌" if verdict == "FAIL" else "⚠️"

        lines.append(f"**验证结论**: {verdict} {verdict_icon}")
        lines.append("")
        lines.append("| 指标 | 训练期 | 验证期 | 差异 | 阈值 | 判定 |")
        lines.append("|------|--------|--------|------|------|------|")

        hit_train = cpcv.get("hit_rate_train", 0)
        hit_val = cpcv.get("hit_rate_validate", 0)
        hit_delta = abs(hit_train - hit_val)
        hit_icon = "✅" if hit_delta < 0.10 else "⚠️"
        lines.append(f"| 命中率 | {hit_train:.1%} | {hit_val:.1%} | {hit_delta:.1%} | <10% | {hit_icon} |")

        ret_train = cpcv.get("return_train_avg", 0)
        ret_val = cpcv.get("return_validate_avg", 0)
        if ret_train != 0:
            ret_delta = abs(ret_val - ret_train) / abs(ret_train)
        else:
            ret_delta = 0
        ret_icon = "✅" if ret_delta < 0.25 else "⚠️"
        lines.append(f"| 收益率 | {ret_train:.2%} | {ret_val:.2%} | {ret_delta:.1%} | <25% | {ret_icon} |")

        pbo = cpcv.get("pbo", 0)
        pbo_icon = "✅" if pbo < 0.15 else "❌"
        lines.append("")
        lines.append(f"**PBO**: {pbo:.1%} (<15% {pbo_icon})")
        lines.append("")
        lines.append(f"> {cpcv.get('notes', '')}")

        return ReportSection(
            title="五、CPCV 防过拟合验证",
            content="\n".join(lines),
            order=5,
        )

    def _build_parameter_advice_section(self, report_date: str = None) -> ReportSection:
        """构建参数调参建议章节"""
        lines = []
        lines.append("*（基于本次复盘生成，具体调整需人工审批）*")
        lines.append("")

        # 尝试加载 review_pending 中的建议
        pending_dir = REVIEW_OUTPUT_DIR
        if pending_dir.exists():
            pending_files = list(pending_dir.glob("advice_*.json"))
            if pending_files:
                lines.append("### 待审批建议")
                for pf in pending_files[-3:]:
                    try:
                        with open(pf, "r", encoding="utf-8") as f:
                            advice = json.load(f)
                        suggestions = advice.get("suggestions", [])
                        if suggestions:
                            lines.append(f"- {pf.name}: {len(suggestions)} 条建议")
                    except Exception:
                        pass

        if len(lines) == 2:
            lines.append("（暂无调参建议）")

        return ReportSection(
            title="六、参数调参建议",
            content="\n".join(lines),
            order=6,
        )

    def _build_weekly_summary_section(self, week_start: str, week_end: str) -> ReportSection:
        """构建周报汇总章节"""
        lines = []
        lines.append(f"**周期**: {week_start} ~ {week_end}")
        lines.append("")

        tracker = self.position_tracker
        positions = tracker.get_positions()

        # 统计各状态数量
        status_counts = {}
        for p in positions:
            status_counts[p.status] = status_counts.get(p.status, 0) + 1

        lines.append(f"| 状态 | 数量 |")
        lines.append("|------|------|")
        for status, count in sorted(status_counts.items()):
            lines.append(f"| {status} | {count} |")

        return ReportSection(
            title="一、周度汇总",
            content="\n".join(lines),
            order=1,
        )

    def _build_market_section(self, market: str, report_date: str) -> ReportSection:
        """构建单市场章节"""
        lines = []
        lines.append(f"**市场**: {market}")
        lines.append("")

        # 获取该市场的持仓数据
        from L5_post_review.position_tracker import PositionTracker
        pt = PositionTracker(market=market)
        summary = pt.get_position_summary()

        lines.append(f"- 总持仓: {summary.total_count}")
        lines.append(f"- 已执行: {summary.executed_count}")
        lines.append(f"- 止损触发: {summary.stopped_count}")
        lines.append(f"- 止盈触发: {summary.take_profit_count}")

        return ReportSection(
            title=f"二、市场 {market}",
            content="\n".join(lines),
            order=2,
        )

    # ── 报告渲染与保存 ────────────────────────────────────────

    def _render_markdown(self, report: GeneratedReport) -> str:
        """
        将 GeneratedReport 渲染为 Markdown 字符串

        Args:
            report: 报告对象

        Returns:
            str: Markdown 格式字符串
        """
        lines = []
        lines.append(f"# 神农系统 L5 复盘报告 - {report.date}")
        lines.append("")

        if report.report_type == "weekly":
            lines.append(f"*周期*: {report.week_start} ~ {report.week_end}")
            lines.append("")

        # 按 order 排序输出章节
        for section in sorted(report.sections, key=lambda s: s.order):
            if section.level:
                lines.append(f"{'#' * section.level} {section.title}")
                lines.append("")
            lines.append(section.content)
            lines.append("")

        lines.append("---")
        lines.append(f"*生成时间*: {report.generated_at}")
        if report.file_path:
            lines.append(f"*报告路径*: {report.file_path}")

        return "\n".join(lines)

    def _get_report_path(self, report_date: str, report_type: str) -> Path:
        """获取报告保存路径"""
        records_date_dir = RECORDS_DIR / report_date
        records_date_dir.mkdir(parents=True, exist_ok=True)
        return records_date_dir / f"report_{report_type}.md"

    def save_report(
        self,
        report: GeneratedReport,
        fmt: str = "markdown"
    ) -> str:
        """
        保存报告到文件

        Args:
            report: 报告对象
            fmt: 保存格式（markdown / json）

        Returns:
            str: 保存的文件路径
        """
        if fmt == "markdown":
            content = self._render_markdown(report)
            path = self._get_report_path(report.date, report.report_type)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            info("report_generator", f"报告已保存: {path}")
            return str(path)
        else:
            path = self._get_report_path(report.date, f"{report.report_type}.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(report), f, ensure_ascii=False, indent=2)
            info("report_generator", f"报告已保存: {path}")
            return str(path)


# ─── CLI 自检 ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="L5 Report Generator")
    parser.add_argument("--action", "-a", default="daily",
                        choices=["daily", "weekly", "multi_market"],
                        help="报告类型")
    parser.add_argument("--market", "-m", default="CN",
                        choices=["CN", "HK", "US"],
                        help="市场标识")
    parser.add_argument("--date", "-d", default=None,
                        help="报告日期 YYYY-MM-DD")
    parser.add_argument("--week-start", "-w", default=None,
                        help="周起始日期 YYYY-MM-DD（周一）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    rg = ReportGenerator(market=args.market)

    if args.action == "daily":
        report = rg.generate_daily_report(report_date=args.date)
        print(f"\n每日报告已生成: {report.file_path}")
    elif args.action == "weekly":
        report = rg.generate_weekly_report(week_start=args.week_start)
        print(f"\n周报已生成: {report.file_path}")
    elif args.action == "multi_market":
        report = rg.generate_multi_market_report(report_date=args.date or date.today().strftime("%Y-%m-%d"))
        print(f"\n多市场报告已生成: {report.file_path}")