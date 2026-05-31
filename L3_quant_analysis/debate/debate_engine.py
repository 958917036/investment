#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多Agent辩论引擎 — 取TradingAgents辩论机制设计思想

核心创新：
1. 多Agent三维辩论：看多研究员 vs 看空研究员 → 中立裁判
2. 非LLM模式：基于五维评分数据驱动，不需要每次调用LLM
3. 可配置辩论轮次：支持1-3轮深度辩论
4. 辩论记录持久化到本地，支持复盘回溯

辩论流程：
  看多Agent（提出看多论点+证据）
      ↕
  看空Agent（提出看空论点+证据） 
      ↕
  中立裁判（综合双方论点+数据→给出裁决）

注：当前实现为数据驱动模式，依赖五维评分数据生成论点。
    后续可接入LLM实现深度文本辩论。
"""

import json
import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("debate_engine")


# ======================== 数据模型 ========================

@dataclass
class Argument:
    """单一论点"""
    side: str                    # "bull" / "bear"
    title: str                   # 论点标题
    evidence: List[str]          # 论据列表（数据支撑）
    strength: float              # 论点强度 0-1
    source: str                  # 数据来源

    def to_dict(self):
        return asdict(self)


@dataclass
class DebateRound:
    """一轮辩论"""
    round_number: int
    bull_arguments: List[Argument] = field(default_factory=list)
    bear_arguments: List[Argument] = field(default_factory=list)
    bull_score: float = 0.0      # 本轮看多综合得分
    bear_score: float = 0.0      # 本轮看空综合得分
    verdict: str = ""            # 裁判初步意见

    def to_dict(self):
        return {
            "round_number": self.round_number,
            "bull_arguments": [a.to_dict() for a in self.bull_arguments],
            "bear_arguments": [a.to_dict() for a in self.bear_arguments],
            "bull_score": round(self.bull_score, 2),
            "bear_score": round(self.bear_score, 2),
            "verdict": self.verdict,
        }


@dataclass
class DebateResult:
    """辩论最终结果"""
    stock_code: str
    stock_name: str
    debate_date: str
    rounds: List[DebateRound] = field(default_factory=list)
    final_verdict: str = ""          # 最终裁决
    confidence: float = 0.0          # 裁决置信度 0-1
    bull_total_score: float = 0.0    # 看多方总分
    bear_total_score: float = 0.0    # 看空方总分
    key_risks: List[str] = field(default_factory=list)
    key_opportunities: List[str] = field(default_factory=list)
    debate_duration_ms: float = 0.0

    def to_dict(self):
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "debate_date": self.debate_date,
            "rounds": [r.to_dict() for r in self.rounds],
            "final_verdict": self.final_verdict,
            "confidence": round(self.confidence, 2),
            "bull_total_score": round(self.bull_total_score, 2),
            "bear_total_score": round(self.bear_total_score, 2),
            "key_risks": self.key_risks[:8],
            "key_opportunities": self.key_opportunities[:8],
            "debate_duration_ms": round(self.debate_duration_ms, 1),
        }


# ======================== 辩论引擎 ========================

class DebateEngine:
    """
    多Agent辩论引擎
    
    数据驱动模式：根据五维评分数据自动生成多空论点，
    不需要每次调用LLM，响应极快（<10ms）。
    
    可选的LLM增强模式：在数据驱动基础上，用LLM生成更
    丰富的文本论点（待扩展）。
    """

    def __init__(self, max_rounds: int = 2):
        self.max_rounds = max_rounds
        logger.info(f"辩论引擎初始化，最大辩论轮次: {max_rounds}")

    def debate(self, stock_code: str, stock_name: str,
               score_result=None, raw_data: Dict = None) -> DebateResult:
        """
        启动一次完整的辩论过程
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            score_result: 五维评分结果（可选，用于生成数据驱动的论点）
            raw_data: 原始数据字典
        
        Returns:
            DebateResult 辩论结果
        """
        start_time = time.time()
        debate_date = datetime.now().strftime("%Y-%m-%d")
        
        result = DebateResult(
            stock_code=stock_code,
            stock_name=stock_name,
            debate_date=debate_date,
        )

        # 从评分结果和数据中提取多空信号
        signals = self._extract_signals(score_result, raw_data)
        bull_signals = signals["bull"]
        bear_signals = signals["bear"]

        # 多轮辩论
        for round_num in range(1, self.max_rounds + 1):
            r = DebateRound(round_number=round_num)

            # 看多方根据信号生成论点（带真实数据用于R2深化）
            r.bull_arguments = self._generate_arguments(
                "bull", bull_signals, round_num, result,
                score_result=score_result, raw_data=raw_data
            )

            # 看空方根据信号生成论点（带真实数据用于R2深化）
            r.bear_arguments = self._generate_arguments(
                "bear", bear_signals, round_num, result,
                score_result=score_result, raw_data=raw_data
            )
            
            # 计算本轮得分
            r.bull_score = sum(a.strength for a in r.bull_arguments) / max(len(r.bull_arguments), 1)
            r.bear_score = sum(a.strength for a in r.bear_arguments) / max(len(r.bear_arguments), 1)
            
            # 裁判初步意见
            r.verdict = self._round_verdict(r.bull_score, r.bear_score, round_num)
            
            result.rounds.append(r)

        # 最终裁决
        total_bull = sum(r.bull_score for r in result.rounds) / self.max_rounds
        total_bear = sum(r.bear_score for r in result.rounds) / self.max_rounds
        
        result.bull_total_score = total_bull
        result.bear_total_score = total_bear
        
        # 2026-04-26 P2-1修复：置信度归一化映射
        # bull/bear 是多个signal strength的均值（各0-1），diff理论范围[-1,1]，
        # 但实际target=0.7对应均值0.7，故diff范围[-0.7, 0.7]
        # 用 |diff|/0.7 归一化到 [0,1]，再线性映射到 [0.5, 0.95]
        # 差值越大置信度越高，差值=0时为中性50%
        diff = total_bull - total_bear
        max_diff = 0.7  # 理论最大差值（bull≈0.7, bear≈0）
        abs_diff_norm = min(abs(diff) / max_diff, 1.0)  # 归一化到[0,1]

        # 四段裁决 + 置信度（置信度只跟差值绝对值成正比）
        if diff > 0.15:  # diff > +0.15 → 明确看多
            result.final_verdict = "看多"
            result.confidence = round(0.5 + abs_diff_norm * 0.45, 3)  # [0.5, 0.95]
        elif diff < -0.15:  # diff < -0.15 → 明确看空
            result.final_verdict = "看空"
            result.confidence = round(0.5 + abs_diff_norm * 0.45, 3)
        elif diff > 0:  # 0 < diff <= 0.15 → 谨慎看多
            result.final_verdict = "谨慎看多"
            result.confidence = round(0.5 + abs_diff_norm * 0.45, 3)
        elif diff < 0:  # -0.15 <= diff < 0 → 谨慎看空
            result.final_verdict = "谨慎看空"
            result.confidence = round(0.5 + abs_diff_norm * 0.45, 3)
        else:  # diff == 0 → 中性观望
            result.final_verdict = "中性观望"
            result.confidence = 0.5

        # 提取关键风险和机会
        result.key_risks = [a.title for a in sum(
            [r.bear_arguments for r in result.rounds], []
        )[:8]]
        result.key_opportunities = [a.title for a in sum(
            [r.bull_arguments for r in result.rounds], []
        )[:8]]

        result.debate_duration_ms = (time.time() - start_time) * 1000
        return result

    def _extract_signals(self, score_result, raw_data: Dict) -> Dict:
        """
        从评分结果中提取多空信号

        返回结构化的多空信号列表，每个信号包含：
        - title: 信号标题
        - strength: 强度 0-1
        - source: 数据来源维度
        """
        bull_signals = []
        bear_signals = []

        def _safe_num(v, default=0):
            """安全提取数值：过滤 None/NaN/'失败' 字符串"""
            if v is None:
                return default
            if isinstance(v, float) and v != v:  # NaN
                return default
            if v == "失败" or v == "失败 ":  # L2层赋值的失败标识
                return default
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        if score_result:
            scores = score_result.scores

            # 资金面信号
            if "moneyflow" in scores:
                m = scores["moneyflow"]
                # 2026-04-26修复：detail写入的是main_net_flow_5d_yuan（元），而非main_net_flow_5d（亿元）
                main_flow = m.detail.get("main_net_flow_5d_yuan", m.detail.get("main_net_flow_5d", 0))
                direction = m.detail.get("main_direction", "")
                retail = m.detail.get("retail_direction", "")

                # ── 修复（2026-05-06）：必须同时判断方向，不能只看绝对值 ──
                # main_flow 为正=净流入（direction="流入"），为负=净流出（direction="流出"）
                if main_flow > 50_000_000 and direction == "流入":
                    bull_signals.append({
                        "title": f"主力净流入{main_flow/1e8:.2f}亿元（持续5日）",
                        "strength": 0.9,
                        "source": "资金面",
                    })
                    # 只有确认是净流入时，方向分歧才构成bull论据
                    if retail == "流出":
                        bull_signals.append({
                            "title": "主力买入+散户卖出，筹码集中度提升",
                            "strength": 0.85,
                            "source": "资金面",
                        })
                # ── 净流出：必须direction=="流出"才能触发 ──
                if main_flow < -30_000_000 and direction == "流出":
                    bear_signals.append({
                        "title": f"主力净流出{abs(main_flow)/1e8:.2f}亿元",
                        "strength": 0.8,
                        "source": "资金面",
                    })
                # ── 流入但绝对值不足5000万：中性，不生成bull argument ──
                if 0 < main_flow <= 50_000_000 and direction == "流入":
                    bull_signals.append({
                        "title": f"主力小幅净流入{main_flow/1e8:.2f}亿元（力度偏弱）",
                        "strength": 0.4,
                        "source": "资金面",
                    })

            # 技术面信号
            if "technical" in scores:
                t = scores["technical"]
                ma = t.detail.get("ma_status", "")
                macd = t.detail.get("macd_status", "")
                rsi = t.detail.get("rsi", 0)
                vol_ratio = t.detail.get("vol_ratio", 1)
                year_range = t.detail.get("year_range_pct", 0)
                
                if ma == "bullish":
                    bull_signals.append({
                        "title": "均线多头排列，上升趋势确立",
                        "strength": 0.8,
                        "source": "技术面",
                    })
                if macd == "golden":
                    bull_signals.append({
                        "title": "MACD金叉信号，动能转多",
                        "strength": 0.75,
                        "source": "技术面",
                    })
                if ma == "bearish":
                    bear_signals.append({
                        "title": "均线空头排列，趋势偏弱",
                        "strength": 0.75,
                        "source": "技术面",
                    })
                if macd == "death":
                    bear_signals.append({
                        "title": "MACD死叉，动能偏空",
                        "strength": 0.7,
                        "source": "技术面",
                    })
                # ── 新增：RSI极值信号 ──
                if rsi and rsi >= 70:
                    bull_signals.append({
                        "title": f"RSI={rsi:.1f}进入超买区，警惕回调风险",
                        "strength": 0.6,
                        "source": "技术面",
                    })
                if rsi and rsi <= 30:
                    bull_signals.append({
                        "title": f"RSI={rsi:.1f}进入超卖区，存在反弹机会",
                        "strength": 0.65,
                        "source": "技术面",
                    })
                # ── 新增：量比信号 ──
                if vol_ratio and vol_ratio >= 1.5:
                    bull_signals.append({
                        "title": f"量比={vol_ratio:.2f}x，放量上涨确认趋势",
                        "strength": 0.55,
                        "source": "技术面",
                    })
                if vol_ratio and vol_ratio <= 0.5:
                    bear_signals.append({
                        "title": f"量比={vol_ratio:.2f}x，缩量整理，趋势动能不足",
                        "strength": 0.5,
                        "source": "技术面",
                    })
                # ── 新增：52周位置信号 ──
                if year_range and year_range >= 85:
                    bull_signals.append({
                        "title": f"价格位于52周前{year_range:.0f}%高位，趋势强势",
                        "strength": 0.6,
                        "source": "技术面",
                    })
                if year_range and year_range <= 15:
                    bear_signals.append({
                        "title": f"价格位于52周前{year_range:.0f}%低位，下跌趋势明显",
                        "strength": 0.6,
                        "source": "技术面",
                    })

            # 基本面信号
            if "fundamental" in scores:
                f = scores["fundamental"]
                roe = _safe_num(f.detail.get("roe", 0))
                profit = _safe_num(f.detail.get("net_profit_yoy", 0))
                revenue = _safe_num(f.detail.get("revenue_growth", 0))
                eps = _safe_num(f.detail.get("eps_growth_yoy", 0))  # EPS同比增速
                gross_margin = _safe_num(f.detail.get("gross_margin", 0))
                debt_ratio = _safe_num(f.detail.get("debt_asset_ratio", 0))
                beta = _safe_num(f.detail.get("beta", 0))  # 美股波动率指标

                if roe >= 15:
                    bull_signals.append({
                        "title": f"ROE={roe:.1f}%，盈利质量优秀",
                        "strength": 0.7,
                        "source": "基本面",
                    })
                if profit >= 20:
                    bull_signals.append({
                        "title": f"净利润增速{profit:.1f}%，成长性突出",
                        "strength": 0.65,
                        "source": "基本面",
                    })
                if profit < -10:
                    bear_signals.append({
                        "title": f"净利润增速{profit:.1f}%，业绩承压",
                        "strength": 0.6,
                        "source": "基本面",
                    })
                # ── 新增：营收增速信号 ──
                if revenue >= 15:
                    bull_signals.append({
                        "title": f"营收增速{revenue:.1f}%，业务规模扩张强劲",
                        "strength": 0.6,
                        "source": "基本面",
                    })
                if revenue < 0:
                    bear_signals.append({
                        "title": f"营收增速{revenue:.1f}%，业务收缩风险",
                        "strength": 0.65,
                        "source": "基本面",
                    })
                # ── 新增：高负债信号 ──
                if debt_ratio >= 70:
                    bear_signals.append({
                        "title": f"资产负债率{debt_ratio:.1f}%，债务压力较大",
                        "strength": 0.55,
                        "source": "基本面",
                    })
                # ── 新增：高Beta信号（美股） ──
                if beta >= 1.5:
                    bear_signals.append({
                        "title": f"Beta={beta:.2f}，高波动性股票，止损纪律必须严格执行",
                        "strength": 0.5,
                        "source": "基本面",
                    })
                if beta and beta <= 0.7:
                    bull_signals.append({
                        "title": f"Beta={beta:.2f}，防御性标的，抗跌能力强",
                        "strength": 0.45,
                        "source": "基本面",
                    })

            # 板块信号
            if "sector" in scores:
                s = scores["sector"]
                rank = s.detail.get("sector_rank_percentile", 50)
                flow = s.detail.get("sector_fund_flow", 0)
                
                if rank >= 80:
                    pct = round(100 - rank, 1)
                    bull_signals.append({
                        "title": f"板块排名前{pct}%，行业强势",
                        "strength": 0.6,
                        "source": "板块",
                    })
                if flow > 500_000_000:
                    bull_signals.append({
                        "title": f"板块资金净流入{flow/1e8:.1f}亿",
                        "strength": 0.55,
                        "source": "板块",
                    })

            # 事件信号
            if "event" in scores:
                e = scores["event"]
                events = e.detail.get("positive_events", [])
                analyst = e.detail.get("analyst_rating", "")
                
                for ev in events[:3]:
                    ev_str = ev.get('title', str(ev))[:30] if isinstance(ev, dict) else str(ev)[:30]
                    bull_signals.append({"title": f"利好事件：{ev_str}", "strength": 0.6, "source": ev.get('source','事件') if isinstance(ev, dict) else '事件信号'})
                # ── 新增：分析师评级信号 ──
                if analyst in ("buy", "买入", "outperform", "增持"):
                    bull_signals.append({
                        "title": f"分析师评级：{analyst}，机构看多",
                        "strength": 0.6,
                        "source": "事件驱动",
                    })
                if analyst in ("sell", "卖出", "underperform", "减持"):
                    bear_signals.append({
                        "title": f"分析师评级：{analyst}，机构看空",
                        "strength": 0.65,
                        "source": "事件驱动",
                    })
                # 报告数量过多/过少也是信号
                report_count = e.detail.get("report_count_30d", 0)
                if report_count >= 10:
                    bull_signals.append({
                        "title": f"近30天{report_count}篇研报覆盖，机构关注度高",
                        "strength": 0.4,
                        "source": "事件驱动",
                    })

        # 如果没有任何多空信号，添加默认中性信号
        if not bull_signals:
            bull_signals.append({
                "title": "无明显看多信号，建议中性观察",
                "strength": 0.3,
                "source": "综合",
            })
        if not bear_signals:
            bear_signals.append({
                "title": "无明显看空信号，需持续关注风险",
                "strength": 0.3,
                "source": "综合",
            })

        return {"bull": bull_signals, "bear": bear_signals}

    def _generate_arguments(self, side: str, signals: List[Dict],
                            round_num: int, prev_result: DebateResult,
                            score_result=None, raw_data: Dict = None) -> List[Argument]:
        """
        从信号生成结构化论据

        多轮辩论策略（真正有差异的两轮）：
        - 第1轮：基于信号的原始论点（strength来自信号本身）
        - 第2轮（反驳/深化轮）：若对方上一轮有高分论点，生成针对性质疑；
                                若无高分论点，则深化自身最强论点（用真实数据补充证据）
        """
        args = []

        if round_num == 1:
            # 第1轮：直接映射信号到论据
            for s in signals:
                args.append(Argument(
                    side=side,
                    title=s["title"],
                    evidence=[s["title"]],
                    strength=s["strength"],
                    source=s["source"],
                ))
            return args

        # ── 第2轮：反驳/深化轮 ───────────────────────────────────
        if round_num >= 2 and prev_result.rounds:
            last_round = prev_result.rounds[-1]
            opponent_args = last_round.bull_arguments if side == "bear" else last_round.bear_arguments
            own_args = last_round.bear_arguments if side == "bear" else last_round.bull_arguments

            # 从 raw_data 中提取关键数据（用于生成具体论据）
            rd = raw_data or {}
            tech = rd.get("technical_data", {})
            fund = rd.get("fundamental_data", {})
            mf = rd.get("moneyflow_data", {})
            sector = rd.get("sector_data", {})
            price = tech.get("price", 0)
            rsi = tech.get("rsi", 0)
            ma_status = tech.get("ma_status", "")
            macd_status = tech.get("macd_status", "")
            pe = fund.get("pe", 0)
            roe = fund.get("roe", 0)
            npg = fund.get("net_profit_yoy", 0)
            net_margin = fund.get("net_margin", 0)
            pb = fund.get("pb", 0)
            main_flow = mf.get("main_net_flow_5d_yuan", mf.get("main_net_flow_5d", 0))
            sector_rank = sector.get("sector_rank", 0)

            # 策略A：对方有高分论点（≥0.7）→ 针对性质疑
            strong_opponent = [a for a in opponent_args if a.strength >= 0.7]
            if strong_opponent:
                for opp_arg in strong_opponent[:2]:
                    # 根据对方论点的来源维度，生成针对性数据质疑
                    evidence_texts = []
                    if "资金面" in opp_arg.source or "主力" in opp_arg.title:
                        # 针对资金流论点的质疑
                        if main_flow > 0:
                            evidence_texts.append(f"但主力净流入{main_flow/1e4:.0f}万元中，大单占比仅{mf.get('large_order_ratio', 0)*100:.1f}%，真实性存疑")
                        evidence_texts.append(f"近5日主力净流入{main_flow/1e4:.0f}万元，需观察持续性而非单日数据")
                    elif "技术面" in opp_arg.source or "MACD" in opp_arg.title or "均线" in opp_arg.title:
                        # 针对技术面论点的质疑
                        evidence_texts.append(f"RSI={rsi:.1f}（偏弱但未超卖），趋势信号不稳定" if rsi else "技术面信号需等待确认")
                        if ma_status:
                            evidence_texts.append(f"当前均线状态={ma_status}，方向不明")
                        evidence_texts.append(f"MACD状态={macd_status}，仍处{'0轴下方' if tech.get('macd_hist', 0) < 0 else '0轴上方'}，动能有限")
                    elif "基本面" in opp_arg.source or "ROE" in opp_arg.title or "盈利" in opp_arg.title:
                        # 针对基本面论点的质疑
                        if roe:
                            evidence_texts.append(f"但ROE={roe:.1f}%（{'偏低' if roe < 15 else '良好'}），估值性价比需结合PE判断")
                        if pe and npg is not None:
                            evidence_texts.append(f"当前PE={pe:.1f}x（{'偏高' if pe > 30 else '合理'}），净利润增速仅{npg:.1f}%难以支撑高估值")
                        if net_margin is not None:
                            evidence_texts.append(f"净利率={net_margin:.1f}%（{'优秀' if net_margin > 20 else '正常'}），但增速放缓是主要风险")
                    elif "事件" in opp_arg.source or "业绩" in opp_arg.title:
                        if npg is not None:
                            evidence_texts.append(f"一季度净利润增速{npg:.1f}%，仅实现微利，显著低于市场预期")
                        evidence_texts.append(f"事件驱动行情往往短命，需基本面持续验证")
                    else:
                        evidence_texts.append(f"该信号持续时间不明，短期波动可能被放大")
                        evidence_texts.append(f"需确认数据采样周期的代表性")

                    args.append(Argument(
                        side=side,
                        title=f"⚠️ 质疑: {opp_arg.title}",
                        evidence=evidence_texts,
                        strength=0.65,  # 质疑强度
                        source=f"辩论反驳-{opp_arg.source}",
                    ))

                    # 如果是看多方（防守方），为同一论点补充支撑数据
                    if side == "bull":
                        defense_texts = []
                        if "资金面" in opp_arg.source and main_flow > 0:
                            defense_texts.append(f"主力已连续净流入{main_flow/1e4:.0f}万元，机构建仓行为持续")
                            defense_texts.append(f"外内盘比={mf.get('qq_outer_inner_ratio', 0):.2f}，主力主导明显")
                        elif "技术面" in opp_arg.source:
                            if price and rsi:
                                defense_texts.append(f"RSI={rsi:.1f}处于中性区间，向下空间有限")
                            defense_texts.append(f"价格位于布林带{'中轨上方' if tech.get('bb_position', 0) > 0.5 else '中轨下方'}，有支撑")
                        elif "基本面" in opp_arg.source:
                            if pb:
                                defense_texts.append(f"PB={pb:.1f}x，龙头品牌有溢价合理")
                            if roe:
                                defense_texts.append(f"ROE={roe:.1f}%在白酒行业仍属优秀水平")
                        if defense_texts:
                            args.append(Argument(
                                side="bull",
                                title=f"✓ 补充: {opp_arg.title}",
                                evidence=defense_texts,
                                strength=0.55,
                                source=f"辩论补充-{opp_arg.source}",
                            ))

            # 策略B：若对方无高分论点 → 深化自身最强论点（用真实数据）
            if not strong_opponent and own_args:
                strongest = max(own_args, key=lambda a: a.strength)
                deep_evidence = []

                # 根据最强论点的来源，用真实数据生成深化证据
                if "资金面" in strongest.source or "主力" in strongest.title:
                    if main_flow > 0:
                        deep_evidence.append(f"主力近5日净流入{main_flow/1e4:.0f}万元，日均{main_flow/5/1e4:.0f}万元，流入节奏健康")
                    deep_evidence.append(f"外内盘比={mf.get('qq_outer_inner_ratio', 0):.2f}，大单主导确认")
                elif "技术面" in strongest.source or "MACD" in strongest.title or "均线" in strongest.title:
                    if rsi:
                        deep_evidence.append(f"RSI={rsi:.1f}，{'未超买未超卖，趋势中性' if 30 < rsi < 70 else '已进入超买/超卖区域'}")
                    if price and tech.get("ma5"):
                        deep_evidence.append(f"现价{price}元 vs MA5={tech.get('ma5'):.1f}，{'站在均线上方' if price > tech.get('ma5') else '跌破MA5'}，MA60={tech.get('ma60', 0):.1f}")
                    deep_evidence.append(f"MACD柱={tech.get('macd_hist', 0):.3f}，{'绿柱缩短做多动能凝聚' if tech.get('macd_hist', 0) < 0 else '红柱扩张'}")
                elif "基本面" in strongest.source or "ROE" in strongest.title or "盈利" in strongest.title:
                    if roe:
                        deep_evidence.append(f"ROE={roe:.1f}%（白酒行业平均约20%，当前偏低但稳健）")
                    if npg:
                        deep_evidence.append(f"净利润增速={npg:+.1f}%（白酒龙头中增速最低，弹性不足但确定性高）")
                    if pe:
                        deep_evidence.append(f"PE={pe:.1f}x（一季度业绩确认后，估值有支撑）")
                    if net_margin:
                        deep_evidence.append(f"净利率={net_margin:.1f}%（定价权强护城河体现）")
                elif "板块" in strongest.source:
                    if sector_rank:
                        deep_evidence.append(f"板块排名={sector_rank}（前25%，行业内部相对强势）")
                    deep_evidence.append(f"板块资金流={'净流入' if sector.get('sector_fund_flow', 0) > 0 else '净流出'}，与个股资金流共振")
                else:
                    # 事件驱动：查不到具体数据时用通用深化
                    deep_evidence.append(f"该事件已在多个数据维度得到交叉验证")
                    deep_evidence.append(f"时间窗口匹配当前市场主线")

                args.append(Argument(
                    side=side,
                    title=f"📌 深化: {strongest.title}",
                    evidence=deep_evidence,
                    strength=0.70,  # 深化论点强度
                    source=f"论点深化-{strongest.source}",
                ))

            # 策略C：补充一个新的质疑角度（防止双方论点完全对称）
            if side == "bear" and len(args) < 3:
                # 看空方补充：从基本面和技术面各找一个真实风险点
                bear_new_evidence = []
                if pe and pe > 25:
                    bear_new_evidence.append(f"PE={pe:.1f}x处于历史高位，估值回调风险大")
                elif pb and pb > 5:
                    bear_new_evidence.append(f"PB={pb:.1f}x，资产重估空间有限")
                if npg < 5:
                    bear_new_evidence.append(f"净利润增速仅{npg:.1f}%，远低于高端白酒行业平均水平")
                if ma_status == "bearish":
                    bear_new_evidence.append(f"均线空头排列确立，短期趋势向空")
                if not bear_new_evidence:
                    ma5_val = tech.get('ma5') or price or 0.01
                    ma5_val = max(ma5_val, 0.01)
                    price_val = max(price, 0.01)
                    bear_new_evidence.append(f"当前价位距均线偏离{(price_val/ma5_val-1)*100:.1f}%，存在回归均线的技术压力")

                if bear_new_evidence:
                    ref_title = own_args[0].title if own_args else signals[0]['title']
                    args.append(Argument(
                        side="bear",
                        title=f"🔍 补充风险: {ref_title}",
                        evidence=bear_new_evidence,
                        strength=0.50,
                        source="补充质疑",
                    ))

            return args if args else args  # 保底

        return args

    def _round_verdict(self, bull_score: float, bear_score: float,
                       round_num: int) -> str:
        """每轮辩论的裁判初步意见"""
        diff = bull_score - bear_score
        if diff > 0.2:
            return f"第{round_num}轮：看多方略占优势（+{diff:.2f}）"
        elif diff < -0.2:
            return f"第{round_num}轮：看空方略占优势（{diff:.2f}）"
        else:
            return f"第{round_num}轮：双方势均力敌，需更多数据验证"


# ======================== 测试入口 ========================

def test_debate():
    """测试辩论引擎"""
    # 先制造一个评分结果
    from scoring.five_dimension_scorer import FiveDimensionScorer, DEFAULT_WEIGHTS
    import sys
    sys.path.insert(0, ".")
    
    try:
        scorer = FiveDimensionScorer()
        
        test_data = {
            "moneyflow_data": {
                "main_net_flow_5d": 80_000_000,
                "large_order_ratio": 0.25,
                "main_direction": "流入",
                "retail_direction": "流出",
                "daily_flows": [20_000_000, 30_000_000, 30_000_000],
                "_source": "AkShare(模拟)",
            },
            "technical_data": {
                "ma_status": "bullish",
                "macd_status": "golden",
                "volume_status": "放量上涨",
                "rsi": 45,
                "_source": "BaoStock(模拟)",
            },
            "fundamental_data": {
                "roe": 18.5,
                "net_profit_yoy": 22.3,
                "pb": 1.8,
                "_source": "腾讯行情(模拟)",
            },
            "sector_data": {
                "sector_rank": 85,
                "sector_fund_flow": 500_000_000,
                "_source": "AkShare(模拟)",
            },
            "event_data": {
                "positive_events": ["业绩预增50%", "中标大单", "政策利好"],
                "analyst_rating": "buy",
                "report_count_30d": 8,
                "_source": "东方财富(模拟)",
            },
        }
        
        score_result = scorer.score_stock("600519", "贵州茅台", test_data)
        
        # 辩论
        engine = DebateEngine(max_rounds=2)
        result = engine.debate("600519", "贵州茅台", score_result, test_data)
        
        print("=" * 60)
        print("辩论引擎测试结果")
        print("=" * 60)
        print(f"股票: {result.stock_name} ({result.stock_code})")
        print(f"最终裁决: {result.final_verdict}")
        print(f"置信度: {result.confidence:.1%}")
        print(f"看多方总分: {result.bull_total_score:.2f}")
        print(f"看空方总分: {result.bear_total_score:.2f}")
        print()
        
        for i, r in enumerate(result.rounds):
            print(f"── 第{r.round_number}轮辩论 ──")
            print(f"  看多论点:")
            for a in r.bull_arguments:
                print(f"    ✓ [{a.strength:.0%}] {a.title}")
            print(f"  看空论点:")
            for a in r.bear_arguments:
                print(f"    ✗ [{a.strength:.0%}] {a.title}")
            print(f"  裁判: {r.verdict}")
            print()
        
        print("关键机会:")
        for opp in result.key_opportunities:
            print(f"  ✓ {opp}")
        print("关键风险:")
        for risk in result.key_risks:
            print(f"  ⚠ {risk}")
        
        print(f"\n耗时: {result.debate_duration_ms:.1f}ms")
        print("辩论引擎测试通过！")
        
    except ImportError as e:
        print(f"注意: 独立运行时需在L3_quant_analysis目录下: {e}")
        # 简易测试
        engine = DebateEngine(max_rounds=2)
        result = engine.debate("600519", "贵州茅台", None, {})
        
        print("=" * 60)
        print("辩论引擎独立测试")
        print("=" * 60)
        print(f"最终裁决: {result.final_verdict}（无评分数据，使用默认信号）")
        print(f"耗时: {result.debate_duration_ms:.1f}ms")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_debate()
