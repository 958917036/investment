# L3 Quant Analysis 层规格说明

## 1. 功能说明

L3 量化分析层对 L2 返回的股票数据进行**五维量化评分 + 多空辩论**，输出综合评分结果和辩论裁决，供下游 L4 风险裁决使用。

**两大模块：**
- **五维评分（FiveDimensionScorer）**：资金面(35%) + 技术面(35%) + 基本面(10%) + 板块强度(10%) + 事件驱动(10%)
- **辩论引擎（DebateEngine）**：数据驱动的多空论点生成 + 裁判裁决

**数据质量传导：** L2 层赋值为 `"失败"` 的字段，该维度得 0 分，`failed_dimensions` 记录失败的维度。

## 2. 接口说明

### 入口函数

```python
from L3_quant_analysis.l3_quant_runner import run_quantitative

result = run_quantitative(L2_data: dict) -> dict
```

### 入参

`L2_data`：L2 层输出的完整数据结构（见 L2 规格说明），包含 `moneyflow_data` / `technical_data` / `fundamental_data` / `sector_data` / `event_data` 五个维度。

### 出参结构

```json
{
  "layer": "L3_quantitative",
  "code": "600519",
  "run_date": "2026-05-30",
  "score": {
    "five_score": 72.0,
    "grade": "B",
    "scores": {
      "moneyflow": {
        "dimension_name": "资金面",
        "score": 75.0,
        "weight": 0.35,
        "weighted_score": 26.25,
        "detail": {...}
      },
      "technical": {...},
      "fundamental": {...},
      "sector": {...},
      "event": {...}
    }
  },
  "debate": {
    "bull_arguments": ["主力净流入8亿元", "均线多头排列"],
    "bear_arguments": ["PE偏高", "RSI进入超买区间"],
    "final_verdict": "谨慎看多",
    "confidence": 0.65,
    "_raw": {...}
  },
  "quality_overall": "ok",
  "failed_dimensions": [],
  "duration_ms": 850
}
```

### 五维评分等级

| grade | five_score 范围 | 说明 |
|---|---|---|
| A | ≥ 80 | 强力推荐 |
| B | 65-79 | 关注 |
| C | 50-64 | 观望 |
| D | < 50 | 回避 |

### 辩论裁决（final_verdict）

`看多` / `谨慎看多` / `中性观望` / `谨慎看空` / `看空`，置信度 0.5-0.95。

## 3. 调用示例

```bash
# 执行 L3 量化分析（读取 L2 输出文件，进行五维评分 + 辩论）
python L3_quant_analysis/l3_quant_runner.py

# 直接导入调用（Python 代码中）
python -c "from L3_quant_analysis.l3_quant_runner import run_quantitative; from L2_data_enrich.l2_runner import fetch_market_data; print(run_quantitative(fetch_market_data('600519', 'CN'))['score']['five_score'])"
```

## 4. 涉及配置

| 配置文件 | 路径 | 用途 |
|---|---|---|
| `l3_config.json` | `main/config/l3_config.json` | 五维权重配置、辩论轮次配置 |

### l3_config.json 关键字段

```json
{
  "five_dimension_weights": {
    "moneyflow": 0.35,
    "technical": 0.35,
    "fundamental": 0.10,
    "sector": 0.10,
    "event": 0.10
  },
  "debate": {
    "max_rounds": 2
  }
}
```

## 5. 目录结构与类说明

```
L3_quant_analysis/
├── l3_quant_runner.py           # 统一入口（run_quantitative）
└── scoring/
    ├── __init__.py
    └── five_dimension_scorer.py  # 五维评分引擎
        # FiveDimensionScorer 类
        # score_stock(code, name, data) → StockScoreResult
        # _score_moneyflow(data, code) → (score, detail)
        # _score_technical(data, code) → (score, detail)
        # _score_fundamental(data, code) → (score, detail)
        # _score_sector(data, code) → (score, detail)
        # _score_event(data, code) → (score, detail)
        # StockScoreResult dataclass
        # ScoreDetail dataclass
└── debate/
    ├── __init__.py
    └── debate_engine.py          # 辩论引擎
        # DebateEngine 类
        # debate(code, name, score_result, raw_data) → DebateResult
        # _extract_signals(score_result, raw_data) → {bull, bear}
        # _generate_arguments(side, signals, round_num, prev_result, ...)
        # DebateResult dataclass
        # DebateRound dataclass
        # Argument dataclass
```

### FiveDimensionScorer 评分权重与子维度

| 维度 | 权重 | 子维度（满分） |
|---|---|---|
| 资金面 | 35% | 主力资金流(40) + 千股千评(25) + 北向持股(20) + 北向净买(15) |
| 技术面 | 35% | 均线形态(40) + MACD信号(30) + 成交量验证(30) |
| 基本面 | 10% | 机构持仓(25) + 盈利能力(25) + 成长性(25) + 财务结构(15) + 估值(10) |
| 板块强度 | 10% | 板块排名(50) + 板块资金流(50) |
| 事件驱动 | 10% | 利好事件(60) + 机构关注度(40) |

### DebateEngine 辩论机制

- **数据驱动**：基于五维评分数据中的信号生成多空论点，不需要 LLM 调用
- **可配置轮次**：默认 2 轮，第 1 轮生成原始论点，第 2 轮针对对方高分论点反驳或深化自身论点
- **置信度归一化**：多空得分差 → 归一化到 [0.5, 0.95]

## 6. 外部依赖

| 依赖项 | 用途 | 说明 |
|---|---|---|
| **akshare** | 基本面数据（若无则评 0 分/低分降权） | |
| **baostock** | 技术指标数据（若无则评低分） | |
| **pandas / numpy** | DataFrame 处理、协方差计算 | 用于板块排名百分位计算 |
| **json** | 配置加载 | 标准库 |
| **logging** | 日志输出 | 标准库 |

**注意：** 五维评分器设计为**降级兼容**——某数据源失败时自动用备用数据源或降低权重，不阻塞评分流程。

## 7. 测试代码

测试代码位于 `testsv2/l3/` 目录：

```
testsv2/
└── l3/
    ├── test_l3_quant_runner.py        # run_quantitative 入口测试
    ├── test_five_dimension_scorer.py  # 五维评分器单元测试
    └── test_debate_engine.py          # 辩论引擎单元测试
```

运行方式：
```bash
cd ~/.hermes/investment
python L3_quant_analysis/l3_quant_runner.py   # 内置测试
python L3_quant_analysis/scoring/five_dimension_scorer.py
python L3_quant_analysis/debate/debate_engine.py
```

或独立测试文件：
```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))
from L3_quant_analysis.l3_quant_runner import run_quantitative
from L2_data_enrich.l2_runner import fetch_market_data

# Mock L2 data with failed fields
L2_data = {
    "code": "600519",
    "name": "贵州茅台",
    "run_date": "2026-05-30",
    "moneyflow_data": {"quality": "ok", "main_net_flow_5d": 80000000, "outer_inner_ratio": 1.15},
    "technical_data": {"quality": "ok", "ma_status": "bullish", "macd_status": "golden", "rsi": 55},
    "fundamental_data": {"quality": "fail", "missing_fields": ["roe", "pe"],
                          "roe": "失败", "pe": "失败", "pb": 7.4},
    "sector_data": {"quality": "ok", "sector_rank": 85},
    "event_data": {"quality": "ok", "positive_events": ["业绩预增"], "analyst_rating": "buy", "report_count_30d": 8},
}

result = run_quantitative(L2_data)
assert result["layer"] == "L3_quantitative"
assert result["score"]["five_score"] >= 0
assert result["debate"]["final_verdict"] != ""
print(f"五维={result['score']['five_score']}, 辩论={result['debate']['final_verdict']}")
print(f"失败维度={result['failed_dimensions']}, 质量={result['quality_overall']}")
print("L3 Quant 测试通过")
```