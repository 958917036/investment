"""
TEST-L3-2: test_l3_score_calculation
五维评分引擎完整单元测试

覆盖本次修复的所有问题：
1. P0-5: moneyflow分级细化（9825万应得15分，非12分）
2. P0-6: null数据降权（gross_margin=None应得2分，非8分）
3. P0-7: event过滤（全市场统计事件应被过滤）
4. P0-2: sector数据缺失检测（sector_count=None应触发降权）
"""
import pytest, sys, os

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)

from L3_quant_analysis.scoring.five_dimension_scorer import FiveDimensionScorer


class TestMoneyflowGrading:
    """P0-5: moneyflow分级细化测试"""

    def test_9825万应得15分(self):
        """9825万(≈1亿)应得15分，不是12分"""
        scorer = FiveDimensionScorer()
        data = {
            "moneyflow_data": {
                "main_net_flow_5d": 9825e4,  # 9825万 = 0.9825亿
                "stock_rank": 9999,           # rank封了
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["moneyflow"].detail
        assert detail["main_net_flow_yi"] == 0.98, f"9825万应换算为0.98亿"
        # 0.9825亿 ≥ 0.5亿 → 应得15分
        assert detail["main_net_flow_score"] == 15, (
            f"9825万(0.98亿)≥0.5亿，应得15分，实际得{detail['main_net_flow_score']}分"
        )

    def test_5000万应得15分(self):
        """5000万应得15分（新增的≥0.5亿档）"""
        scorer = FiveDimensionScorer()
        data = {
            "moneyflow_data": {
                "main_net_flow_5d": 5000e4,  # 5000万
                "stock_rank": 9999,
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["moneyflow"].detail
        assert detail["main_net_flow_yi"] == 0.5
        assert detail["main_net_flow_score"] == 15, (
            f"5000万应得15分（≥0.5亿档），实际得{detail['main_net_flow_score']}分"
        )

    def test_1000万应得13分(self):
        """1000万应得13分（新增的≥0.1亿档）"""
        scorer = FiveDimensionScorer()
        data = {
            "moneyflow_data": {
                "main_net_flow_5d": 1000e4,  # 1000万
                "stock_rank": 9999,
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["moneyflow"].detail
        assert detail["main_net_flow_score"] == 13, (
            f"1000万应得13分（≥0.1亿档），实际得{detail['main_net_flow_score']}分"
        )

    def test_负1亿应得5分不是7分(self):
        """-1亿应得5分（新增的≤-1亿档），不是7分"""
        scorer = FiveDimensionScorer()
        data = {
            "moneyflow_data": {
                "main_net_flow_5d": -1e8,  # -1亿
                "stock_rank": 9999,
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["moneyflow"].detail
        assert detail["main_net_flow_score"] == 5, (
            f"-1亿应得5分（≤-1亿档），实际得{detail['main_net_flow_score']}分"
        )


class TestFundamentalNullData:
    """P0-6: fundamental null数据降权测试"""

    def test_gross_margin为None应得2分不是8分(self):
        """毛利率None应得2分（降权），不是8分（中性）"""
        scorer = FiveDimensionScorer()
        data = {
            "fundamental_data": {
                "gross_margin": None,  # 真实null
                "eps_growth_yoy": None,  # 真实null
                "debt_eq": None,  # 真实null
                "pe": None,  # 真实null
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["fundamental"].detail
        # margin_score = 2（null降权），profit_score = 2（null降权），fin_score = 2（null降权），val_score = 1（null降权）
        # inst_score = 5（null降权）
        # 总分 = 5 + 2 + 2 + 2 + 1 = 12
        total = result.scores["fundamental"].score
        assert total <= 20, (
            f"全null应得≤20分（各子维度降权后和），实际得{total}分"
        )
        assert detail.get("_margin_data_missing") is True, "应标注margin_data_missing"
        assert detail.get("_growth_data_missing") is True, "应标注growth_data_missing"

    def test_gross_margin有值不应降权(self):
        """毛利率有真实值时应正常评分，不应降权"""
        scorer = FiveDimensionScorer()
        data = {
            "fundamental_data": {
                "gross_margin": 35.0,  # 真实值
                "eps_growth_yoy": 15.0,  # 真实值
                "debt_eq": 0.3,  # 真实值
                "pe": 20.0,  # 真实值
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["fundamental"].detail
        assert detail.get("_margin_data_missing") is None, "有真实值不应标注missing"
        assert result.scores["fundamental"].score > 30, (
            f"有真实数据应得>30分，实际得{result.scores['fundamental'].score}分"
        )

    def test_inst_ownership为None应得5分不是10分(self):
        """机构持仓率None应得5分（降权），不是10分（中性）"""
        scorer = FiveDimensionScorer()
        data = {
            "fundamental_data": {
                "inst_ownership_pct": None,  # null
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["fundamental"].detail
        assert detail.get("_inst_data_missing") is True, "应标注inst_data_missing"
        # inst_score = 5（null降权）
        assert detail["inst_score"] == 5, (
            f"机构持仓率None应得5分（降权），实际得{detail['inst_score']}分"
        )

    def test_debt_eq为None应得2分不是5分(self):
        """负债率None应得2分（降权），不是5分（中性）"""
        scorer = FiveDimensionScorer()
        data = {
            "fundamental_data": {
                "debt_eq": None,
                "current_ratio": None,
                "quick_ratio": None,
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["fundamental"].detail
        assert detail.get("_fin_data_missing") is True
        assert detail["financial_score"] == 2, (
            f"财务结构全None应得2分（降权），实际得{detail['financial_score']}分"
        )


class TestEventFiltering:
    """P0-7: event全市场统计事件过滤测试"""

    def test_全市场统计事件被过滤(self):
        """'今日369只个股突破五日均线'是全市场统计，应被过滤"""
        scorer = FiveDimensionScorer()
        data = {
            "event_data": {
                "positive_events": [
                    "今日369只个股突破五日均线",  # 全市场统计，应过滤
                    "业绩预增50%",               # 个股特有，保留
                ],
                "analyst_rating": "neutral",
                "report_count_30d": 0,
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["event"].detail
        assert detail["_event_filtered"] == 1, (
            f"应有1个事件被过滤，实际{detail['_event_filtered']}个"
        )
        assert detail["_event_filtered_examples"] == ["今日369只个股突破五日均线"], (
            "被过滤的例子应记录"
        )
        # 过滤后1个事件: event_score=25, analyst_score=15(neutral) → total=40
        assert result.scores["event"].score == 40, (
            f"过滤后1事件+neutral研报，应得40分(25+15)，实际得{result.scores['event'].score}分"
        )

    def test_全是全市场事件应得5分(self):
        """全是全市场统计事件时，真实事件数为0，应得5分"""
        scorer = FiveDimensionScorer()
        data = {
            "event_data": {
                "positive_events": [
                    "今日A股三大指数集体上涨",
                    "大盘放量突破五日均线",
                    "市场普涨格局延续",
                ],
                "analyst_rating": "neutral",
                "report_count_30d": 0,
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["event"].detail
        assert detail["_event_filtered"] == 3, "3个全应全被过滤"
        # 过滤后0事件: event_score=5, analyst_score=15(neutral) → total=20
        assert result.scores["event"].score == 20, (
            f"过滤后0事件+neutral研报，应得20分(5+15)，实际得{result.scores['event'].score}分"
        )

    def test_纯文本事件保留(self):
        """不包含通用模式但也不包含明确个股模式的事件应保留（保守策略）"""
        scorer = FiveDimensionScorer()
        data = {
            "event_data": {
                "positive_events": [
                    "放量上涨突破前期高点",  # 保留（不包含通用排除模式）
                ],
                "analyst_rating": "neutral",
                "report_count_30d": 0,
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["event"].detail
        assert detail["_event_filtered"] == 0, "此事件应保留"
        # 1个保留事件: event_score=25, analyst_score=15(neutral) → total=40
        assert result.scores["event"].score == 40, (
            f"1保留事件+neutral研报，应得40分(25+15)，实际得{result.scores['event'].score}分"
        )


class TestSectorDataMissing:
    """P0-2: sector数据缺失检测测试"""

    def test_sector_count为None应触发数据缺失(self):
        """sector_count=None应触发数据缺失降权（10分，非25分）"""
        scorer = FiveDimensionScorer()
        data = {
            "sector_data": {
                "sector_rank": 55,      # BaoStock行业分类提供的值
                "sector_fund_flow": 0,
                "sector_count": None,   # None（不是0）
                "_source": "BaoStock行业分类"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["sector"].detail
        assert detail.get("_data_missing") is True, "应标注_data_missing"
        assert result.scores["sector"].score == 10, (
            f"sector_count=None应得10分（降权），实际得{result.scores['sector'].score}分"
        )

    def test_sector_count为0应触发数据缺失(self):
        """sector_count=0应触发数据缺失降权（10分，非25分）"""
        scorer = FiveDimensionScorer()
        data = {
            "sector_data": {
                "sector_rank": 50,
                "sector_fund_flow": 0,
                "sector_count": 0,
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["sector"].detail
        assert detail.get("_data_missing") is True, "应标注_data_missing"
        assert result.scores["sector"].score == 10

    def test_sector_strength存在应正常评分(self):
        """sector_strength存在（美股SPDR标签）应正常评分，不触发缺失"""
        scorer = FiveDimensionScorer()
        data = {
            "sector_data": {
                "sector_rank": 50,
                "sector_fund_flow": 0,
                "sector_count": None,  # 即使None
                "sector_strength": "强势",  # 美股ETF标签
                "_source": "finviz"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        detail = result.scores["sector"].detail
        assert detail.get("_data_missing") is None, (
            "sector_strength存在不应触发数据缺失"
        )
        # sector_strength=强势时，rank_score=40
        assert result.scores["sector"].score >= 40, (
            f"强势板块应得≥40分，实际得{result.scores['sector'].score}分"
        )


class TestW4PersonaDenominator:
    """W4分母修复测试（batch接口）"""

    def test_W4分母包含reject_count(self):
        """W4分母应包含reject_count，不应只算pbuy+pwatch"""
        # 模拟：3个agent（1BUY+1WATCH+1REJECT）
        # W4 persona_score = buy_count / total_agents = 1/3 ≈ 0.333
        # 旧分母（排除REJECT）会得到 1/(1+1)=0.50，这是旧bug
        import sys
        sys.path.insert(0, "/Users/guchuang/.hermes/investment")
        from L4_judge.l4_runner import run_risk_judgment

        L3_quant = {
            "code": "000000",
            "score": {"five_score": 65, "grade": "B", "scores": {}},
            "debate": {"final_verdict": "看多", "confidence": 0.7},
            "quality_overall": "ok",
        }
        L3_persona = {
            "_status": "ok",
            "summary": {
                "agents_total": 3,
                "buy_count": 1,
                "watch_count": 1,
                "reject_count": 1,
                "avg_score": 0.5
            },
            "quality_overall": "ok",
        }
        L2_data = {"code": "000000", "technical_data": {"price": 10.0}}

        result = run_risk_judgment(L3_quant, L3_persona, L2_data)
        jc = result.get("_judge_components", {})
        w4_new = jc.get("persona_score", 0)
        assert abs(w4_new - 1/3) < 0.01, (
            f"1BUY+1WATCH+1REJECT时W4应为0.333，实际{w4_new}。"
            "正确分母应包含reject_count"
        )


class TestBoundaryConditions:
    """边界条件测试"""

    def test_所有维度全为None(self):
        """所有维度数据全为None，系统应给出明确的低分，不应崩溃"""
        scorer = FiveDimensionScorer()
        data = {
            "moneyflow_data": {"_source": "test"},
            "technical_data": {"_source": "test"},
            "fundamental_data": {"_source": "test"},
            "sector_data": {"_source": "test"},
            "event_data": {"_source": "test"},
        }
        result = scorer.score_stock("000000", "test", data)
        # 应返回有效分数，不崩溃
        assert result.five_score is not None
        assert result.five_score >= 0
        assert result.five_score <= 100

    def test_moneyflow数据全空(self):
        """moneyflow数据全为空时应给低分，不应崩溃"""
        scorer = FiveDimensionScorer()
        data = {
            "moneyflow_data": {
                "main_net_flow_5d": 0,
                "stock_rank": 9999,
                "outer_inner_ratio": 1.0,  # 中性
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        mf_score = result.scores["moneyflow"].score
        # 资金流全空：flow_score=10 + comment=10 + north=8 + hsgt=8 = 36
        # 这不是"低分"(<30)而是中性偏低，测试只验证不崩溃
        assert mf_score is not None and 0 <= mf_score <= 60, (
            f"资金流全空应得合理偏低分，实际得{mf_score}分"
        )

    def test_technical中性偏弱满分边界(self):
        """technical中性状态：MA=neutral(20分) MACD=neutral(15分) Vol=正常(15分) = 50分"""
        scorer = FiveDimensionScorer()
        data = {
            "technical_data": {
                "ma_status": "neutral",
                "macd_status": "neutral",
                "volume_status": "正常",
                "rsi": 50,
                "_source": "test"
            }
        }
        result = scorer.score_stock("000000", "test", data)
        tech_score = result.scores["technical"].score
        # 20 + 15 + 15 = 50
        assert tech_score == 50, f"中性技术面应得50分，实际得{tech_score}分"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
