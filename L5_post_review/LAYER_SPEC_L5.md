# L5 Post Review 层规格说明

## 1. 功能说明

L5 层进行**事后复盘与系统优化**，不参与实时交易决策。

**职责：**
1. **策略有效性追踪** — 记录 L4 决策信号，跟踪后续表现
2. **交易复盘分析** — 分析已平仓交易的胜率、模式、过拟合风险
3. **CPCV 防过拟合验证** — 评估策略是否过度优化
4. **冷冻状态管理** — 管理股票的冷冻/解冻状态（CN/HK/US 多市场）
5. **持仓追踪** — 监控持仓的止损/止盈触发，追踪实际表现
6. **定期报告生成** — 生成每日/每周复盘报告（Markdown 格式）
7. **参数调参建议** — 基于复盘结果，给出 L1-L4 参数调整建议

## 2. 目录结构

```
L5_post_review/
├── core/
│   └── position_tracker.py      # 持仓追踪模块
├── utils/
│   ├── report_generator.py      # 定期报告模块
│   └── parameter_advisor.py     # 参数调参建议模块
├── review_engine.py             # 复盘引擎（策略追踪 + CPCV 验证）
├── freeze_manager.py            # 冷冻状态管理器（CN/HK/US 多市场）
└── LAYER_SPEC_L5.md             # 本文档
```

## 3. 模块说明

### 3.1 ReviewEngine（review_engine.py）

**入口类：** `ReviewEngine`

**核心方法：**

| 方法 | 入参 | 出参 | 说明 |
|------|------|------|------|
| `record_decision(...)` | code, decision, judge_score, date, price, name, reason, market | decision_id | 记录 L4 决策信号 |
| `record_decision_from_l4(l4_result)` | dict | List[str] | 从 L4 结果批量提取并记录决策 |
| `evaluate_outcomes(...)` | horizon_days, price_func | None | 评估所有持仓信号的后续表现 |
| `get_effectiveness_report()` | 无 | EffectivenessMetrics | 生成策略有效性指标报告 |
| `print_effectiveness_report(metrics)` | EffectivenessMetrics | None | 打印策略有效性报告 |
| `load_closed_trades()` | 无 | List[TradeRecord] | 从 freeze_table.json 加载已平仓交易 |
| `run_review(trades)` | List[TradeRecord] | dict | 执行完整复盘流程（CPCV + 模式分析） |
| `approve_changes(review_id)` | str | bool | 审批通过复盘建议的参数变更 |

**有效性指标：**

| 指标 | 计算方式 | 健康阈值 |
|------|---------|---------|
| BUY 命中率 | BUY 中最终盈利的比例 | >55% |
| BUY 平均收益 | BUY 信号后 N 日平均收益 | >0% |
| WATCH 转化率 | WATCH 升级 BUY 后的收益 | 参考 |
| REJECT 有效率 | REJECT 后继续下跌比例 | >70% |
| 盈亏比 | 盈利均值 / 亏损均值 | >1.5x |
| 模拟夏普 | (收益率均值 - 无风险利率) / 收益率标准差 | >0 |

**CPCV 验证：**

| 指标 | 含义 | 阈值 |
|------|------|------|
| PBO | Probability of Backtest Overfitting | <15% |
| Hit Rate Delta | 验证期 vs 训练期命中率差异 | <10% |
| Return Delta | 验证期 vs 训练期收益率差异 | <25% |

### 3.2 FreezeManager（freeze_manager.py）

**职责：** 管理股票冷冻状态（10天/3个月冷冻规则，支持 CN/HK/US 多市场）

**冷冻规则：**
- 10天冷冻：初筛失败 1 次
- 3个月冷冻：10天到期重跑仍失败，或 3 条件同时触发

**3条件同时触发（直接3个月冷冻）：**
1. 主力近5日净流出 > 1亿
2. 均线空头排列（MA5 < MA10 < MA20）
3. 外内盘比 < 0.75

**核心方法：**

| 方法 | 入参 | 出参 | 说明 |
|------|------|------|------|
| `add_freeze(code, name, level, reason)` | str, str, str, List[str] | bool | 添加冷冻记录（10days/3months） |
| `unfreeze(code)` | str | bool | 解冻股票 |
| `get_frozen_codes()` | 无 | Set[str] | 获取当前冷冻股票代码集合 |
| `get_summary()` | 无 | dict | 获取冷冻状态摘要 |
| `check_and_update_freeze()` | market | dict | 每日收盘后检查冷冻到期并更新状态 |
| `record_buy_signal(...)` | code, name, judge_score, price, stop_loss, take_profit, kelly, reason | bool | 记录买入信号 |
| `get_buy_signals()` | 无 | List[dict] | 获取待推送买入信号 |

### 3.3 PositionTracker（core/position_tracker.py）★新增

**职责：** 跟踪持仓状态变化，检查止损/止盈触发

**状态机：**

```
pending → executed（实际成交）
               ↓
    ┌──────────┼──────────┐
    ↓          ↓          ↓
stopped   take_profit expired（>60天）
```

**核心方法：**

| 方法 | 入参 | 出参 | 说明 |
|------|------|------|------|
| `check_triggers(date)` | str | Dict[str, List[PositionRecord]] | 检查止损/止盈/过期触发 |
| `update_position_status(code, status, ...)` | str, str, float, str, str | bool | 更新持仓状态 |
| `record_execution(code, price, date)` | str, float, str | bool | 记录实际成交 |
| `get_positions(status)` | str | List[PositionRecord] | 获取持仓列表 |
| `get_position_summary()` | 无 | PositionStatus | 获取持仓状态汇总 |

**数据模型：**

```python
@dataclass
class PositionRecord:
    stock_code: str
    stock_name: str
    entry_date: str
    entry_price: float
    stop_loss: float
    take_profit: float
    kelly_fraction: float
    judge_score: float
    reason: str
    status: str  # pending / executed / stopped / take_profit / expired
    signal_date: str
    exit_date: Optional[str]
    exit_price: Optional[float]
    exit_reason: Optional[str]

@dataclass
class PositionStatus:
    total_count: int
    pending_count: int
    executed_count: int
    stopped_count: int
    take_profit_count: int
    expired_count: int
    total_pnl_pct: float
    avg_holding_days: float
```

### 3.4 ReportGenerator（utils/report_generator.py）★新增

**职责：** 生成每日/每周复盘报告（Markdown 格式）

**核心方法：**

| 方法 | 入参 | 出参 | 说明 |
|------|------|------|------|
| `generate_daily_report(date)` | str | GeneratedReport | 生成每日报告 |
| `generate_weekly_report(week_start)` | str | GeneratedReport | 生成每周报告 |
| `generate_multi_market_report(date, markets)` | str, List[str] | GeneratedReport | 生成多市场综合报告 |
| `save_report(report, format)` | GeneratedReport, str | str | 保存报告 |

**报告章节：**
1. 操作回顾 — 当日 BUY/WATCH/REJECT 决策汇总
2. 持仓状态 — 各状态数量统计、总收益、平均持仓天数
3. 策略有效性 — BUY 命中率、WATCH 升级率、盈亏比、夏普等
4. 冷冻状态 — 冷冻中/观察池数量
5. CPCV 防过拟合验证 — PBO、训练/验证期指标对比
6. 参数调参建议 — 来自 ParameterAdvisor 的调参建议

### 3.5 ParameterAdvisor（utils/parameter_advisor.py）★新增

**职责：** 基于 CPCV/有效性指标生成 L1-L4 调参建议

**调参决策规则：**

| 条件 | 层级 | 参数 | 操作 |
|------|------|------|------|
| BUY 命中率 < 55% | L1 | thresholds[1] | +0.05 放宽筛选 |
| PBO > 15% | L1 | thresholds[0] | +0.02 收紧初筛 |
| WATCH 升级率 < 30% | L4 | watch_to_buy.upgrade_threshold | -0.02 |
| 止损触发 > 40% | L4 | stop_loss_pct | +0.01 放宽止损 |
| 止盈触发 < 10% | L4 | take_profit_pct | -0.05 收紧止盈 |

**核心方法：**

| 方法 | 入参 | 出参 | 说明 |
|------|------|------|------|
| `analyze_and_suggest(cpcv, metrics, positions, date)` | dict, dict, List, str | List[ParameterSuggestion] | 主入口，生成调参建议 |
| `suggest_l1_adjustments(cpcv, metrics)` | dict, dict | List[ParameterSuggestion] | L1 调参建议 |
| `suggest_l4_adjustments(cpcv, positions, metrics)` | dict, List, dict | List[ParameterSuggestion] | L4 调参建议 |
| `save_advice_report(advice)` | ParameterAdviceReport | str | 保存建议报告 |
| `get_pending_advice(type)` | str | List[ParameterAdviceReport] | 获取待审批建议 |
| `approve_advice(review_id, approved_by)` | str, str | bool | 审批建议 |
| `apply_advice(review_id)` | str | bool | 应用已审批建议 |

## 4. 数据存储

| 文件 | 路径 | 用途 |
|------|------|------|
| `strategy_tracker.json` | `main/records/` | L4 决策追踪数据 |
| `freeze_table.json` | `main/` | CN 冷冻股记录 + buy_signals |
| `freeze_table_hk.json` | `main/` | HK 冷冻股记录 |
| `freeze_table_us.json` | `main/` | US 冷冻股记录 |
| `review_pending/*.json` | `main/config/` | 待审批复盘结果 + 调参建议 |
| `report_*.md` | `main/records/{date}/` | 生成的复盘报告 |

## 5. 与 L4 的关系

```
L4 裁决层（热路径）:
├── run_risk_judgment()     → 选股决策（BUY/WATCH/REJECT）
├── check_portfolio_triggers() → 持仓监控（止损/止盈/追加检查）
└── RiskManager             → 风控引擎

L5 复盘层（冷路径）:
├── FreezeManager           → 冷冻状态管理 + BUY 信号记录
├── PositionTracker         → 持仓追踪（止损/止盈触发检查） ★新增
├── ReviewEngine            → 复盘分析 + 策略追踪 + CPCV 验证
├── ParameterAdvisor        → 参数调参建议 ★新增
└── ReportGenerator         → 定期报告生成 ★新增
```

**调用关系：**
- L4 决策时 → `FreezeManager.record_buy_signal()` 记录信号
- 每日收盘后 → `FreezeManager.check_and_update_freeze()` 更新冷冻状态
- 每日收盘后 → `PositionTracker.check_triggers()` 检查止损/止盈触发
- 每日收盘后 → `ReviewEngine.evaluate_outcomes()` 更新结果
- 定期 → `ReviewEngine.run_review()` 执行复盘
- L4 检测到3条件触发 → `FreezeManager.add_freeze()` 添加冷冻
- 定期 → `ParameterAdvisor.analyze_and_suggest()` 生成调参建议
- 每日/每周 → `ReportGenerator.generate_*_report()` 生成报告

## 6. L5Result 扩展字段

```python
@dataclass
class L5Result:
    # 基础字段
    layer: str = "L5"
    run_date: str = ""
    review_count: int = 0
    decisions_recorded: int = 0
    freeze_updated: bool = False
    duration_s: float = 0.0

    # 已有字段
    effectiveness: dict = field(default_factory=dict)
    cpcv: dict = field(default_factory=dict)
    freeze_state: dict = field(default_factory=dict)

    # L5 扩展字段（新增）
    position_summary: dict = field(default_factory=dict)      # PositionStatus.to_dict()
    trigger_results: dict = field(default_factory=dict)        # {stop_loss[], take_profit[], expired[], unchanged[]}
    report_path: Optional[str] = None # 生成的报告路径
    parameter_advice: List[dict] = field(default_factory=list) # ParameterSuggestion.to_dict()
    errors: List[dict] = field(default_factory=list)          # [{module, error}]
```

## 7. 使用示例

```python
# 持仓追踪
from L5_post_review.position_tracker import PositionTracker
pt = PositionTracker(market="CN")
result = pt.check_triggers(check_date="2026-05-31")
print(f"止损触发: {len(result['stop_loss'])}")
summary = pt.get_position_summary()
print(f"总持仓: {summary.total_count}, 已执行: {summary.executed_count}")

# 生成报告
from L5_post_review.report_generator import ReportGenerator
rg = ReportGenerator(market="CN")
report = rg.generate_daily_report("2026-05-31")
print(f"报告已生成: {report.file_path}")

# 调参建议
from L5_post_review.parameter_advisor import ParameterAdvisor
advisor = ParameterAdvisor(market="CN")
suggestions = advisor.analyze_and_suggest(
    cpcv_result=cpcv_dict,
    effectiveness_metrics=metrics_dict,
    positions=positions,
    date="2026-05-31"
)
for s in suggestions:
    print(f"{s.layer} {s.parameter_path}: {s.current_value} → {s.suggested_value}")
```

## 8. 测试代码

```bash
# L5 各模块自检
python -m L5_post_review.position_tracker --action status
python -m L5_post_review.report_generator --action daily
python -m L5_post_review.parameter_advisor --action status

# 测试套件（testsv2/l5/）
python testsv2/l5/test_l5_freeze_manager.py
python testsv2/l5/test_l5_review_engine.py
python testsv2/l5/test_l5_position_tracker.py
python testsv2/l5/test_l5_report_generator.py
python testsv2/l5/test_l5_parameter_advisor.py
```

## 9. 外部依赖

| 依赖项 | 用途 |
|--------|------|
| baostock | 获取历史价格数据（冷冻验证） |
| numpy | 统计计算（CPCV/夏普） |
| json | 数据持久化 |
| logging | 日志记录 |