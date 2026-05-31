# L1 Screener 层规格说明

## 1. 功能说明

L1 层负责**股票初选**，从全市场或指定股票池中按策略/名称/代码/板块筛选出候选股票列表。不做深度分析，只返回满足筛选条件的股票基础行情数据。

**核心能力：**
- 5 种量化策略筛选（breakout / growth_momentum / garp / pullback / quality_value）
- 按股票名称模糊查询
- 按股票代码精确查询
- 按行业板块查询

## 2. 接口说明

### 入口函数

```python
from L1_screener.l1_runner import run_l1

result = run_l1(input_type: str, params: dict) -> dict
```

### 入参种类

| input_type | params 示例 | 说明 |
|---|---|---|
| `by_strategy` | `{"strategy": "breakout", "pool": "index800"}` | 按策略执行，pool 可选 `full`/`index800` |
| `by_name` | `{"name": "茅台"}` | 按名称模糊查询 |
| `by_code` | `{"code": "600519"}` | 按代码精确查询 |
| `by_sector` | `{"sector": "白酒"}` | 按行业板块查询 |

`strategy` 字段支持 `breakout`/`growth_momentum`/`garp`/`pullback`/`quality_value`，或传 `"all"` 执行全部策略。

### 出参结构

```json
{
  "layer": "L1",
  "run_date": "2026-05-30",
  "input_type": "by_strategy",
  "input_params": {"strategy": "breakout", "pool": "index800"},
  "stock_count": 25,
  "stocks": [
    {
      "code": "600519",
      "name": "贵州茅台",
      "price": 1850.0,
      "change_pct": 2.5,
      "market_cap": 2320,
      "source": "腾讯行情",
      "strategy_matched": "breakout"
    }
  ],
  "duration_ms": 3200
}
```

每只股票的字段：
| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | str | 股票代码 |
| `name` | str | 股票名称 |
| `price` | float | 当前价格（元） |
| `change_pct` | float | 涨跌幅（%） |
| `market_cap` | float | 市值（亿元） |
| `source` | str | 数据来源（固定 `"腾讯行情"`） |
| `strategy_matched` | str | 匹配策略名称 |

## 3. 调用示例

```bash
# 按单一策略执行（breakout 策略，默认 index800 股票池）
python L1_screener/l1_runner.py

# 按股票名称模糊查询（参数通过 stdin 或环境变量传入）
python L1_screener/l1_runner.py by_name 茅台

# 按股票代码精确查询
python L1_screener/l1_runner.py by_code 600519

# 按行业板块查询
python L1_screener/l1_runner.py by_sector 白酒

# 执行全部5种策略（全市场模式）
python L1_screener/l1_runner.py by_strategy all full

# 直接导入调用（Python 代码中）
python -c "from L1_screener.l1_runner import run_l1; print(run_l1('by_code', {'code': '600519'}))"
```

## 4. 涉及配置

| 配置文件 | 路径 | 用途 |
|---|---|---|
| `l1_config.json` | `main/config/l1_config.json` | L1 全局配置，含 prefilter/signals/cn 参数 |
| `freeze_table.json` | `main/freeze_table.json` | 冷冻股名单，被各策略引用以排除已冻结股票 |

### l1_config.json 关键字段

```json
{
  "cn": {
    "batch_size": 30,
    "request_timeout": 15,
    "request_interval": 0.3,
    "per_strategy_limit": 200
  },
  "prefilter": {
    "min_market_cap_yuan": 30000000000,
    "max_pe": 50
  },
  "signals": {
    "momentum": {"thresholds": [0.25, 0.40, 0.55]},
    "graham": {"thresholds": [0.25, 0.40, 0.55]},
    "lynch": {"thresholds": [0.25, 0.4, 0.6]},
    "reversion": {"thresholds": [0.25, 0.40, 0.55]},
    "buffett": {"thresholds": [0.3, 0.45, 0.65]}
  }
}
```

## 5. 目录结构与类说明

```
L1_screener/
├── l1_runner.py          # 统一入口（run_l1 函数）
├── strategies/          # 策略子目录
│   ├── __init__.py
│   ├── breakout.py       # 放量突破前高策略（RSI 40-70 + 均线多头）
│   ├── growth_momentum.py  # 成长动量策略（营收增速≥20% + EPS增长）
│   ├── garp.py           # GARP 合理价格成长策略（PEG≤1.2 + PE≤35）
│   ├── pullback.py       # 回调反弹策略（超卖 RSI<45 + 布林下轨）
│   ├── quality_value.py  # 质量价值策略（ROE≥15% + PE≤25）
│   ├── by_name.py        # 按股票名称模糊查询（AkShare + 腾讯API）
│   ├── by_code.py        # 按股票代码精确查询（腾讯API）
│   └── by_sector.py      # 按行业板块查询（AkShare + 腾讯API）
├── scripts/              # 独立运行脚本（调用 l1_runner.py）
│   ├── breakout_screener.py   # breakout 独立运行（CLI）
│   ├── growth_momentum_screener.py
│   ├── garp_screener.py
│   ├── pullback_screener.py
│   ├── quality_value_screener.py
│   ├── us_screener.py     # 美股独立筛选（不走 AkShare）
│   ├── hk_screener.py     # 港股独立筛选
│   ├── hk_short_screener.py  # 港股做空候选筛选
│   └── run_all.py         # 批量运行5种策略（调用 l1_runner.py）
└── utils/                # 公共工具（跨策略复用）
    ├── hard_filters.py    # 硬约束过滤器
    └── composite_scorer.py  # 多策略综合评分器
```

### 各策略核心逻辑

| 策略文件 | 核心函数 | 策略核心思想 |
|---|---|---|
| `breakout.py` | `screen(pool)` | 放量突破前高 + RSI 40-70 + 均线多头，信号阈值 0.25/0.40/0.55 |
| `growth_momentum.py` | `screen(pool)` | 营收增速≥20% + 动量确认 + EPS增长，Graham 评分 |
| `garp.py` | `screen(pool)` | PEG≤1.2 + PE≤35 + 成长确认，Lynch 评分 |
| `pullback.py` | `screen(pool)` | 超卖 RSI<45/布林下轨 + 上升趋势未破，P/E 极低优先 |
| `quality_value.py` | `screen(pool)` | ROE≥15% + PE≤25 + 护城河稳定，Buffett 评分 |
| `by_name.py` | `search_by_name(name)` | AkShare 模糊匹配名称 → 腾讯API批量查行情 |
| `by_code.py` | `query_by_code(code)` | 腾讯API精确查单只股票 |
| `by_sector.py` | `search_by_sector(sector)` | AkShare 获取板块成分股 → 腾讯API批量查行情 |

### 公共工具函数（跨策略复用）

| 函数 | 所在文件 | 说明 |
|---|---|---|
| `get_l1_config()` | 各策略文件 | 加载 `l1_config.json`，全局单例缓存 |
| `load_freezes()` | 各策略文件 | 加载冷冻股名单 |
| `get_all(scope)` | breakout/pullback/garp 等 | 获取候选股票列表（支持 hs300/zz500/full） |
| `fetch_quotes()` / `batch_fetch_quotes()` | 各策略文件 | 腾讯API批量查行情，分 batch 并带请求间隔 |

### 扩展工具（高级功能）

| 模块 | 文件 | 说明 |
|---|---|---|
| 硬约束过滤 | `utils/hard_filters.py` | `check_hard_filters()` / `apply_hard_filters_to_candidates()` |
| 综合评分 | `utils/composite_scorer.py` | `merge_and_score()` / `build_composite_output()` |

## 6. 外部依赖

| 依赖项 | 用途 | 说明 |
|---|---|---|
| **akshare** | 获取股票列表（hs300/zz500/全市场）、板块成分股 | `pip install akshare` |
| **腾讯行情 API** (`qt.gtimg.cn`) | 实时行情（价格/PE/PB/市值/成交量） | 免费，无需 API Key，分 batch 请求防限流 |
| **pandas** | DataFrame 处理，concat 去重 | |
| **requests** | HTTP 请求腾讯 API | |

### 腾讯 API 字段映射（parts 数组索引）

| 索引 | 字段 |
|---|---|
| 1 | name |
| 2 | code |
| 3 | price |
| 4 | prev_close |
| 5 | open |
| 6 | volume |
| 16 | amount |
| 33 | high |
| 34 | low |
| 39 | pe |
| 45 | market_cap |
| 46 | pb |

### 请求限流配置

`l1_config.json` 中 `cn.request_interval = 0.3`（秒），`batch_size = 30`。每 30 只股票一组请求，组间 sleep 0.3s。

## 7. 测试代码

测试代码位于 `testsv2/l1/` 目录：

```
testsv2/l1/
├── __init__.py
├── test_l1_runner.py          # 测试 L1_screener/l1_runner.py 所有入口模式
└── test_l1_context_runner.py  # 测试 main/l1_runner.py（PipelineContext 集成）
```

运行方式：
```bash
cd ~/.hermes/investment && python3 testsv2/l1/test_l1_runner.py
python3 testsv2/l1/test_l1_context_runner.py  # PipelineContext 集成测试
```

或直接运行内置测试：
```bash
cd ~/.hermes/investment && python L1_screener/l1_runner.py by_code 600519
```