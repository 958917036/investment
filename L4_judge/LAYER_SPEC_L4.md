# L4 Judge 层规格说明

## 1. 功能说明

L4 层对 L3 量化结果 + L3 人格分析结果进行**综合风险裁决**，输出：
- **judge_score**：综合裁决分（0-1）
- **decision**：BUY / WATCH / REJECT
- **risk_score**：风险评分（0-100）
- **stop_loss_pct / take_profit_pct**：止损/止盈百分比
- **recommended_weight**：建议仓位

**裁决公式：**
```
judge_score = veto_score × 0.50 + debate_score × 0.25 + persona_score × 0.25
veto_score = five_score / 100
debate_score = verdict映射值 × (0.5 + 0.5 × confidence)
persona_score = BUY票数 / 总大师数
```

## 2. 接口说明

### 入口函数

```python
from L4_judge.l4_runner import run_risk_judgment

result = run_risk_judgment(L3_quant: dict, L3_persona: dict, L2_data: dict) -> dict
```

### 入参

| 参数 | 类型 | 说明 |
|---|---|---|
| `L3_quant` | dict | L3 量化分析结果（`run_quantitative` 输出） |
| `L3_persona` | dict | L3 人格分析结果（`run_persona` 输出） |
| `L2_data` | dict | L2 市场数据（用于提取 price） |

### 出参结构

```json
{
  "layer": "L4",
  "code": "600519",
  "run_date": "2026-05-30",
  "judge_score": 0.68,
  "decision": "BUY",
  "decision_label": "建议买入",
  "risk_score": 35,
  "risk_level": "normal",
  "volatility": 0.25,
  "kelly_fraction": 0.18,
  "recommended_weight": 0.15,
  "stop_loss_pct": -0.08,
  "take_profit_pct": 0.20,
  "risk_factors": ["PE偏高", "RSI偏高压70"],
  "quality_overall": "ok",
  "duration_ms": 150,
  "missing_fields": [],
  "_judge_components": {
    "veto_score": 0.72,
    "debate_score": 0.60,
    "persona_score": 0.33,
    "veto_weight": 0.50,
    "debate_weight": 0.25,
    "persona_weight": 0.25
  }
}
```

### decision 裁决规则

| decision | 条件 | 说明 |
|---|---|---|
| `BUY` | judge_score ≥ 0.55 且数据完整 | 建议买入 |
| `WATCH` | 0.35 ≤ judge_score < 0.55 且数据完整 | 谨慎观望 |
| `REJECT` | judge_score < 0.35 或 数据缺失 或 quality=fail | 不建议买入 |

> **数据缺失强制拒绝**：L3_quant/L3_persona 为空、缺少关键字段（five_score/final_verdict/agents_total）或 price 缺失时，强制 REJECT，missing_fields 记录缺失项。quality_overall 设为 fail。

### risk_level 分类

| risk_level | 条件 | 说明 |
|---|---|---|
| `normal` | alert_level != danger/warning 且 risk_score ≤ 40 | 正常 |
| `warning` | alert_level == warning 或 40 < risk_score ≤ 70 | 预警 |
| `high` | alert_level == danger 或 risk_score > 70 | 高风险 |

## 3. 调用示例

```bash
# 执行 L4 风险裁决（综合 L3量化 + L3人格 + L2市场数据）
python L4_judge/l4_runner.py

# 直接导入调用（Python 代码中）
python -c "from L4_judge.l4_runner import run_risk_judgment; from L3_quant_analysis.l3_quant_runner import run_quantitative; from L3_llm_perspectives.persona_runner import run_persona; from L2_data_enrich.l2_runner import fetch_market_data; L2=fetch_market_data('600519','CN'); print(run_risk_judgment(run_quantitative(L2), run_persona(L2), L2)['decision'])"
```

> **主流程调用方式**：`main/shennong.py` 中的 `_run_L4_for_batch()` 直接接收 `batch_stocks / l3_result / l1_result`，在流程内部完成数据整合后调用 RiskManager，不依赖此入口函数。`run_risk_judgment()` 用于 L4 层独立调用场景。

## 4. 涉及配置

| 配置文件 | 路径 | 用途 |
|---|---|---|
| `l4_weights.json` | `main/config/l4_weights.json` | 裁决权重（veto/debate/persona 各 0.50/0.25/0.25） |
| `l4_risk_config.json` | `main/config/l4_risk_config.json` | 风控参数（止损/止盈/波动率阈值/Kelly上限等） |

### l4_weights.json 关键字段

```json
{
  "veto_weight": 0.50,
  "debate_weight": 0.25,
  "persona_weight": 0.25,
  "decision_thresholds": {
    "accept_min": 0.55,
    "watch_min": 0.35
  },
  "verdict_map": {
    "看多": 1.0,
    "谨慎看多": 0.6,
    "中性观望": 0.3,
    "谨慎看空": 0.1,
    "看空": 0.0
  }
}
```

### l4_risk_config.json 关键字段

```json
{
  "total_capital": 100000,
  "risk": {
    "max_single_position": 0.20,
    "max_top3_concentration": 0.50,
    "max_sector_concentration": 0.35,
    "stop_loss_default": -0.08,
    "take_profit_default": 0.20,
    "var_95_limit": 0.03,
    "volatility_warning": 0.40,
    "volatility_danger": 0.60,
    "max_correlation": 0.70,
    "kelly_fraction_limit": 0.25,
    "margin_call_threshold": 0.85
  }
}
```

## 5. 目录结构与类说明

```
L4_judge/
├── l4_runner.py              # 统一入口（run_risk_judgment / check_portfolio_triggers）
├── risk/
│   ├── __init__.py
│   ├── risk_manager.py       # 风险管理引擎（RiskManager）
│   │   ├── RiskManager 类
│   │   │   ├── assess_stock_risk(...)  → RiskAssessment
│   │   │   ├── assess_portfolio(...)  → PortfolioRisk
│   │   │   ├── can_buy(...)            → (bool, reason)
│   │   │   └── should_sell(...)        → (bool, reason, action)
│   │   ├── RiskAssessment dataclass
│   │   ├── Position dataclass
│   │   └── PortfolioRisk dataclass
│   └── risk_metrics.py       # 风险指标计算函数
│       ├── compute_historical_var()
│       ├── compute_cvar()
│       ├── compute_sortino()
│       ├── compute_calmar()
│       ├── compute_max_drawdown_from_prices()
│       ├── compute_correlation_matrix()
│       ├── compute_portfolio_var()
│       └── compute_liquidity_metrics()
└── execution/
    ├── __init__.py
    ├── order.py              # Order/Trade/Position/AccountInfo 数据类
    ├── gateway.py            # ExecutionGateway 抽象基类 + GatewayError
    ├── mocksim.py           # MockGateway 模拟撮合网关
    └── router.py            # BrokerRouter 多网关路由器
```

### RiskManager 三级风控架构

| 级别 | 职责 | 关键方法 |
|---|---|---|
| Level 1 — 个股级 | 止损/止盈/波动率/Kelly仓位 | `assess_stock_risk()` |
| Level 2 — 组合级 | 集中度/相关性/组合VaR | `assess_portfolio()` |
| Level 3 — 系统级 | 市场环境/宏观风险 | 集成在 `assess_stock_risk` 的 liquidity_alert 中 |

### 关键输出字段

| 字段 | 说明 |
|---|---|
| `kelly_fraction` | 凯利公式仓位（f* = (b·p - q) / b） |
| `recommended_weight` | 综合建议仓位（凯利 × 波动率因子 × 评分因子 × VaR因子） |
| `stop_loss_pct` | ATR 自适应止损百分比（1.5×ATR 或固定 8% 兜底） |
| `volatility` | 30 日年化波动率（来自 BaoStock 日线） |
| `liquidity_alert` | 流动性告警（green/yellow/red） |

## 6. 外部依赖

| 依赖项 | 用途 | 说明 |
|---|---|---|
| **baostock** | 个股波动率计算、VaR/MaxDrawdown 等风险指标 | |
| **pandas / numpy** | DataFrame 处理、协方差矩阵计算 | |
| **math** | 年化波动率计算（std × √252） | 标准库 |
| **L3_quant** | 五维评分数据 | 上游 L3_quant_runner |
| **L3_persona** | 大师投票数据 | 上游 persona_runner |
| **L2_data** | 市场数据（提取 price） | 上游 l2_runner |

## 7. 测试代码

测试代码位于 `testsv2/l4/` 目录：

```
testsv2/
└── l4/
    ├── test_l4_runner.py           # run_risk_judgment 测试（含边界用例）
    ├── test_risk_manager.py        # RiskManager 单元测试
    ├── test_l4_config.py           # L4 配置加载测试
    ├── test_execution_gateway.py   # Execution/MockGateway/BrokerRouter 测试
    └── test_l4_portfolio_triggers.py  # check_position_triggers 持仓监控测试
```

运行方式：
```bash
cd ~/.hermes/investment
python testsv2/l4/test_l4_runner.py      # run_risk_judgment 测试
python testsv2/l4/test_risk_manager.py    # RiskManager 单元测试
python testsv2/l4/test_l4_config.py       # 配置加载测试
python testsv2/l4/test_execution_gateway.py # 执行层网关测试
```

或独立测试文件：
```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))
from L4_judge.l4_runner import run_risk_judgment

# Mock L3 and L2 data
L3_quant = {
    "code": "600519",
    "score": {"five_score": 72, "grade": "B", "scores": {}},
    "debate": {"final_verdict": "谨慎看多", "confidence": 0.65},
    "technical_data": {"rsi": 72},
    "quality_overall": "ok"
}
L3_persona = {
    "summary": {"buy_count": 2, "watch_count": 1, "reject_count": 0, "agents_total": 3},
    "_status": "ok", "quality_overall": "ok"
}
L2_data = {
    "code": "600519",
    "technical_data": {"price": 1850.0, "rsi": 72},
    "moneyflow_data": {"main_net_flow_5d": 123456789}
}

result = run_risk_judgment(L3_quant, L3_persona, L2_data)
assert result["layer"] == "L4"
assert result["decision"] in ("BUY", "WATCH", "REJECT")
print(f"decision={result['decision']}, judge_score={result['judge_score']:.3f}")
print(f"risk_score={result['risk_score']}, recommended_weight={result['recommended_weight']:.1%}")
print("L4 测试通过")
```