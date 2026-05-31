# 神农系统产品设计书 v4.0

> 更新时间：2026-05-30
> 适用版本：v4.0
> 定位：系统架构设计原则、分层职责、数据契约、主入口规范

---

## 一、核心设计原则

### 1.1 铁律

1. **资金流有一票否决权**：Money Flow > 叙事逻辑，资金面恶化直接 REJECT
2. **严禁数据编造**：宁可显示"数据暂缺"，也不输出虚假 0 值或推测值
3. **层层串行，层内并行**：L1→L2→L3→L4 串行执行，每层内部支持并行处理
4. **A股有T+1和涨跌停限制**：中国市场特色约束

### 1.2 主入口架构

**核心文件**：`main/shennong.py` — 全链路编排器（唯一主入口）

```
main/shennong.py
├── run_pipeline()          # 主入口，全链路编排（mode/full/init-queue/batch等）
├── run_pipeline_for_stock() # 单只股票全链路（L2→L3→L4），用于并行
├── run_full_pipeline_threaded()  # ThreadPoolExecutor 并行多只股票
├── run_L1() / run_L2() / run_L3() / run_L4()  # 各层调度函数
├── check_veto()            # 极差判断（资金流+技术面快速过滤）
├── generate_report()        # 生成可读报告（report.md）
└── CLI main()              # 命令行入口（--mode / --market / --symbols 等）
```

**main/batch_runner.py** — 独立批处理运行器，支持手动触发和断点恢复。

### 1.3 数据流架构

```
                    ┌─ run_pipeline() ──────────────────────────────┐
                    │                                            │
                    │  ┌─ L1初筛 ──────────────────────────────────┐
                    │  │  run_L1(pool) → candidates[]              │  (5策略并行)
                    │  └───────────────────────────────────────────┘
                    │                    ↓ candidates[]
                    │  ┌─ L2充实 ──────────────────────────────────┐
                    │  │  run_L2(candidates) → stocks{_data}       │  (分批fetch)
                    │  └───────────────────────────────────────────┘
                    │                    ↓ stocks[]
                    │  ┌─ veto检查 ───────────────────────────────  │
                    │  │  check_veto() → passed[] / vetoed[]       │  (快速过滤)
                    │  └───────────────────────────────────────────┘
                    │                    ↓ passed[]
                    │  ┌─ L3分析 ──────────────────────────────────┐
                    │  │  run_L3()                                 │  (双轨并行)
                    │  │    ├─ 量化轨: FiveDimensionScorer + Debate │
                    │  │    └─ 人格轨: run_persona (12大师)         │
                    │  └───────────────────────────────────────────┘
                    │                    ↓ results[]
                    │  ┌─ L4裁决 ──────────────────────────────────┐
                    │  │  run_L4() / _run_L4_for_batch()           │  (RiskManager)
                    │  │    ├─ judge_score 计算
                    │  │    ├─ decision: BUY/WATCH/REJECT
                    │  │    └─ 止损止盈/Kelly仓位
                    │  └───────────────────────────────────────────┘
                    │                    ↓ decisions[]
                    │  ┌─ L5复盘（冷路径，由L4 BUY触发）─────────────  │
                    │  │  FreezeManager.record_buy_signal()         │
                    │  └───────────────────────────────────────────┘
                    │                    ↓
                    │  ┌─ generate_report() ─────────────────────  │
                    │  │  report.md + 分层JSON文件                 │
                    │  └───────────────────────────────────────────┘
                    └──────────────────────────────────────────────┘
```

### 1.4 目录结构

```
investment/
├── main/
│   ├── shennong.py          # 主入口（run_pipeline / run_pipeline_for_stock）
│   ├── batch_runner.py      # 独立批处理运行器（断点恢复）
│   ├── cache_manager.py     # 缓存管理
│   ├── freeze_table.json   # 冷冻股票表
│   ├── records/            # 每日结果（records/{date}/）
│   │   ├── index.json      # 标的索引（按code聚合历史裁决）
│   │   └── {date}/
│   │       ├── L1_candidates.json
│   │       ├── L2_data.json
│   │       ├── L3_analysis.json
│   │       ├── L4_decision.json
│   │       └── report.md
│   └── config/             # 配置文件
│       ├── l1_config.json
│       ├── l2_config.json
│       ├── l3_weights.json
│       ├── l4_weights.json
│       └── l3_persona_config.json
│
├── L1_screener/            # L1 初筛（5策略）
│   ├── l1_runner.py        # 入口（run_l1）
│   ├── LAYER_SPEC_L1.md
│   └── strategies/        # breakout/growth_momentum/garp/pullback/quality_value
│       └── scripts/        # 各策略可独立运行
│
├── L2_data_enrich/         # L2 数据充实
│   ├── data_fetcher.py    # fetch_batch / fetch_all / fetch_one_stock
│   ├── l2_runner.py       # fetch_market_data(code, market)
│   ├── LAYER_SPEC_L2.md
│   └── adapters/           # 市场适配器
│
├── L3_quant_analysis/     # L3 量化轨
│   ├── l3_quant_runner.py
│   ├── scoring/           # FiveDimensionScorer（五维评分）
│   ├── debate/            # DebateEngine（辩论引擎）
│   └── LAYER_SPEC_L3_QUANT.md
│
├── L3_llm_perspectives/   # L3 人格轨
│   ├── persona_runner.py  # run_persona / run_persona_analysis
│   └── LAYER_SPEC_L3_PERSONA.md
│
├── L4_judge/              # L4 风险裁决
│   ├── l4_runner.py       # run_risk_judgment（独立调用）
│   ├── risk/              # RiskManager（风控引擎）
│   └── LAYER_SPEC_L4.md
│
├── L5_post_review/        # L5 复盘（冷路径）
│   ├── review_engine.py   # ReviewEngine（策略有效性追踪）
│   ├── freeze_manager.py  # FreezeManager（冷冻状态管理）
│   └── LAYER_SPEC_L5.md
│
├── testsv2/               # 测试代码（按层分组）
│   ├── l1/
│   ├── l2/
│   ├── l3/
│   ├── l3_persona/
│   ├── l4/
│   └── l5/
│
└── docs/
    ├── OPERATION_GUIDE.md  # 操作指南
    ├── PRODUCT-DESIGN.md   # 本文档
    ├── INDEX.md            # 文档索引
    └── RECORDS-INDEX.md    # 存储结构规范
```

---

## 二、各层职责

### Layer 1 — 初筛层（L1_screener/）

**职责**：技术面初筛，按策略/名称/代码/板块筛选候选股，**不做深度分析**

**入口**：`run_l1(input_type, params)` 或直接运行 `l1_runner.py`

**4种入参模式**：

| input_type | params 示例 | 说明 |
|---|---|---|
| `by_strategy` | `{"strategy": "breakout", "pool": "index800"}` | 按策略执行 |
| `by_name` | `{"name": "茅台"}` | 按名称模糊查询 |
| `by_code` | `{"code": "600519"}` | 按代码精确查询 |
| `by_sector` | `{"sector": "白酒"}` | 按行业板块查询 |

**5种选股策略**：

| 策略 | 核心逻辑 |
|---|---|
| `breakout` | 放量突破前高 + RSI 40-70 + 均线多头 |
| `growth_momentum` | 营收增速≥20% + EPS增长 + Graham评分 |
| `garp` | PEG≤1.2 + PE≤35 + Lynch评分 |
| `pullback` | RSI<45 + 布林带下轨 + 上升趋势未破 |
| `quality_value` | ROE≥15% + PE≤25 + Buffett评分 |

**主流程中的行为**：`run_L1()` 在 `main/shennong.py` 中被调用：
1. 并行运行5策略 screener（subprocess）
2. 读取缓存（当日优先）
3. 去重 + freeze表过滤
4. 策略轮询平衡，返回候选股列表

---

### Layer 2 — 数据充实层（L2_data_enrich/）

**职责**：获取股票多维度数据（资金流/技术面/基本面/板块/事件），市场隔离

**入口**：
- `fetch_market_data(code, market)` — 独立使用
- `fetch_batch(stock_list, max_stocks)` — 批获取
- `fetch_one_stock(code, name)` — 单只获取

**3市场支持**：

| 市场 | 代码格式 | 数据源 |
|---|---|---|
| A股 CN | 纯数字 `600519` | 腾讯实时 + BaoStock日线 + AkShare财务 |
| 港股 HK | 5位 `00700` | 腾讯港股 + AkShare日线 + MFI |
| 美股 US | 字母 `SMCI` | Yahoo Finance + finviz |

**返回格式**：统一五维度结构 `{moneyflow_data, technical_data, fundamental_data, sector_data, event_data}`，每个维度含 `_quality: ok/degraded/fail` 和 `_missing_fields: []`

**主流程中的行为**：`run_L2()` 在 `main/shennong.py` 中被调用：
1. 分批调用 `fetch_batch`（每批 L2_BATCH_SIZE 只）
2. 资金流缺失率>50% → 整日中止（不输出假数据）
3. 数据写入 `L2_data.json`

---

### Layer 3 — 多视角分析（L3_*/）

**职责**：量化分析 + 人格分析，双轨并行

**量化轨**（`run_L3` 内部调用 `FiveDimensionScorer + DebateEngine`）：

五维评分权重：资金35% + 技术35% + 基本面10% + 板块10% + 事件10%

辩论引擎：多空观点交锋，输出 `final_verdict` + `confidence`

| verdict | 映射值 |
|---|---|
| 看多 | 1.0 |
| 谨慎看多 | 0.6 |
| 中性观望 | 0.3 |
| 谨慎看空 | 0.1 |
| 看空 | 0.0 |

**人格轨**（`run_persona_analysis`）：12大师 Agent（Buffett/Lynch/Druckenmiller等），可配置默认3位大师，API不可用时返回 `_status: "skipped"`

**主流程中的行为**：`run_L3(veto_result, L2_result)` 在 `main/shennong.py` 中被调用：
1. 遍历 `passed` 股票
2. 五维度 gate（分数低于阈值时跳过辩论+人格）
3. 辩论裁决（必跑）+ 人格分析（条件触发）
4. 结果写入 `L3_analysis.json`

---

### Layer 4 — 风险裁决层（L4_judge/）

**职责**：综合 L3 分析，输出投资决策 + 风控参数

**入口**：
- `run_risk_judgment(L3_quant, L3_persona, L2_data)` — 独立调用接口
- `_run_L4_for_batch(batch_stocks, l3_result, l1_result)` — 内部批处理

**judge_score 公式**：
```
judge_score = veto_score × 0.50 + debate_score × 0.25 + persona_score × 0.25
```
- `veto_score` = five_score / 100
- `debate_score` = verdict映射值 × (0.5 + 0.5 × confidence)
- `persona_score` = BUY票数 / 总大师数

**决策阈值**：

| judge_score | 决策 |
|---|---|
| ≥ 0.55 | BUY |
| ≥ 0.35 | WATCH |
| < 0.35 | REJECT |

**风控输出**：止损价格 / 止盈价格 / Kelly仓位 / 建议仓位 / 波动率

**主流程中的行为**：`run_L4()` 或 `_run_L4_for_batch()` 在 `main/shennong.py` 中被调用：
1. 遍历 L3 结果，逐只计算 judge_score
2. 调用 `RiskManager.assess_stock_risk()` 获取风控参数
3. BUY 决策 → 调用 `FreezeManager.record_buy_signal()`（L5 冷冻表）
4. 组合风控评估
5. 结果写入 `L4_decision.json`（自动更新 `index.json`）

---

### Layer 5 — 复盘层（L5_post_review/）

**职责**：事后复盘与系统优化，**冷路径，不参与实时决策**

**由 L4 BUY 触发（L5落库）**：`FreezeManager.record_buy_signal()` 在 L4 裁决 BUY 时被调用，将信号写入冻结表（`main/freeze_table.json`）

**独立复盘流程**（每日 19:00 cron）：
1. `ReviewEngine.evaluate_outcomes()` — 跟踪持仓表现
2. `ReviewEngine.get_effectiveness_report()` — 策略有效性指标
3. `ReviewEngine.run_review()` — CPCV 防过拟合验证

**冷冻规则**：
- 10天冷冻：初筛失败1次
- 3个月冷冻：3条件同时触发（主力净流出>1亿 + 均线空头 + 外内盘比<0.75）

**有效性健康阈值**：BUY命中率>55%、BUY平均收益>0%、盈亏比>1.5x、PBO<15%

---

## 三、运行模式

| 模式 | 说明 | 典型用途 |
|---|---|---|
| `full` | 初始化 queue → 逐批 L2/L3/L4 → 生成报告 | 每日早晨全自动 |
| `init-queue` | 仅跑 L1 扫描，初始化当日 queue | 每日 6:00 cron |
| `batch` | 从 queue 消费下一批（50只） | 每5分钟 cron |
| `verify-batch` | 从验证队列消费，用于测试验证 | 手动触发 |
| `manual-batch` | 手动批处理（任意时间，断点可恢复） | 手动分析 |
| `init-verify-queue` | 从 L1 候选池采样初始化验证队列 | 测试用 |

**三市场**：`--market CN/HK/US`，各自独立 queue

---

## 四、数据质量标识

**三档质量**：`.ok` / `.degraded` / `.fail`

- `ok`：数据完整
- `degraded`：部分字段失败，有默认值
- `fail`：核心数据完全失败

**失败字段标记**：
- 字段赋值为字符串 `"失败"`
- `_missing_fields` 列表记录本次获取失败的字段名

---

## 五、配置体系

所有硬编码参数集中在 `main/config/`：

| 配置文件 | 影响范围 |
|---|---|
| `l1_config.json` | L1 预过滤阈值、请求间隔、批大小 |
| `l2_config.json` | L2 采集批大小/超时/最大股数 |
| `l3_weights.json` | 五维权重、辩论参数、decision_thresholds |
| `l4_weights.json` | judge_score 权重、verdict映射、阈值 |
| `l3_persona_config.json` | LLM大师列表、API参数 |
| `l4_risk_config.json` | 风控参数（总资金/仓位限制/Kelly上限） |

---

## 六、核心差异化能力

### 评分体系（L3 + L4）

- **五维评分**：资金流 + 技术面 + 基本面 + 板块 + 事件
- **辩论引擎**：多空观点交锋，输出置信度
- **人格轨**：12大师 Agent 代表不同投资风格

### 风控能力（L4）

| 功能 | 说明 |
|---|---|
| 历史 VaR | 基于真实收益率分布 |
| CVaR | Expected Shortfall |
| Sortino Ratio | 下行标准差版夏普 |
| Calmar Ratio | 年化收益 / 最大回撤 |
| Kelly 仓位 | `(bp-q)/b` 公式 |
| ATR 自适应止损 | `min(ATR×1.5, 8%)` 兜底 |
| 流动性风控 | Amihud 比率 / 变现天数 |

---

## 七、版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v4.0 | 2026-05-30 | 每层单一入口 + `main/shennong.py` 主编排 + 批处理 + 三市场统一 |
| v3.5 | 2026-05-05 | 期货/外汇多资产、KDJ 技术指标、策略有效性追踪 |
| v3.4 | 2026-05-05 | 因子计算引擎、Sortino/Calmar/历史 VaR/CVaR、EventEngine |
| v3.3 | 2026-05-04 | L2 适配器层重构、回测引擎、因子研究、执行层框架 |