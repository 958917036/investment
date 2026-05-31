# main 层规格说明

## 1. 功能定位

**main 层是神农系统的调度层**，负责：

1. **管道编排**：按顺序调用 L1→L2→L3→L4→L5
2. **配置加载**：将 `config/*.json` 注入 `PipelineContext`
3. **外部服务入口**：供 hermes-agent 和 cron 调用，提供统一的 CLI/Web 接口
4. **结果持久化**：写入 platform 数据库（`db_writer.py`）

**main 层自身不实现任何分析/筛选/评分逻辑**，这些全部放在 L1~L5 层。

## 2. 目录结构

```
main/
├── contracts/              # 数据契约（所有层共享的 dataclass 定义）
│   ├── __init__.py         # 统一导出
│   ├── common.py           # Market/Decision/Verdict/Grade 等枚举
│   ├── stock.py            # StockIdentity
│   ├── context.py          # PipelineContext + load_all_config
│   ├── l1.py               # L1Candidate / L1Result
│   ├── l2.py               # L2StockData / L2Result
│   ├── l3.py               # L3StockResult / L3Result
│   ├── l4.py               # L4Decision / L4Result
│   └── l5.py               # DecisionRecord / FreezeState 等
├── l1_runner.py            # L1 调度（调用 L1_screener/l1_runner）
├── l2_runner.py            # L2 调度（调用 L2_data_enrich/l2_runner）
├── l3_runner.py            # L3 调度（调用 L3_quant_analysis/l3_quant_runner）
├── l4_runner.py            # L4 调度（调用 L4_judge/l4_runner）
├── l5_runner.py            # L5 调度（调用 L5_post_review/review_engine）
├── shennong.py             # CLI 入口 + pipeline 编排（for 循环 L1→L2→...→L5）
├── db_writer.py            # 写入 platform 数据库（analysis_records）
├── utils/
│   └── logger.py           # 统一日志工具（L1~L5 共用）
├── config/                 # 配置文件（各层配置汇总于此）
├── freeze_table.json       # 冷冻股名单（L5 终审用）
└── shennong-run.sh         # shell 入口
```

## 3. 接口说明

### PipelineContext（核心数据载体）

```python
from main.contracts import PipelineContext, Market, load_all_config

ctx = PipelineContext(
    run_date="2026-05-31",
    market=Market.CN,
    mode="full"          # full / L1 / L2 / L3 / L4 / L5 / quick
)
ctx = load_all_config(ctx)  # 加载所有 config/*.json
```

PipelineContext 包含：
- **基础信息**：`run_date`、`market`、`mode`
- **各层配置**：从 config/ 加载（`l1_config`、`l2_config` 等）
- **各层结果**：层层累积（`l1_result`、`l2_result` 等）
- **执行状态**：`errors`、`duration_s`

### 各层 Runner（调度代理）

每个 runner 的职责完全相同：
1. 从 `ctx.<layer>_config` 读取配置
2. 调用对应层的底层 runner
3. 将结果写入 `ctx.<layer>_result`
4. 返回修改后的 `ctx`

```python
# main/l1_runner.py 伪代码
def run_l1(ctx: PipelineContext) -> PipelineContext:
    from L1_screener.l1_runner import run_l1 as _run_l1
    raw = _run_l1("by_strategy", params, config=ctx.l1_config)
    ctx.l1_result = L1Result(**raw)
    return ctx
```

| Runner | 底层调用 | 主要职责 |
|--------|----------|----------|
| `l1_runner` | `L1_screener/l1_runner.run_l1()` | 选股 |
| `l2_runner` | `L2_data_enrich/l2_runner.run_l2()` | 数据富化 |
| `l3_runner` | `L3_quant_analysis/l3_quant_runner.run_l3()` | 量化评分 |
| `l4_runner` | `L4_judge/l4_runner.run_l4()` | 风险裁定 |
| `l5_runner` | `L5_post_review/review_engine.run_l5()` | 终审复核 |

### shennong.py（主调度器）

```bash
# 全链路运行
python main/shennong.py --mode full

# 只跑 L1→L2
python main/shennong.py --mode L2

# 指定股票跑 L3
python main/shennong.py --mode L3 --symbols 600519

# 指定市场
python main/shennong.py --mode full --market US
```

核心是 `run_pipeline(ctx)` 函数，用简单的 for 循环编排 L1→L2→L3→L4→L5：

```python
def run_pipeline(ctx) -> dict:
    ctx = run_l1(ctx)
    ctx = run_l2(ctx)
    # veto check...
    for stock in passed_stocks:
        ctx = run_l3(ctx)   # 单股票 L3
        ctx = run_l4(ctx)   # 单股票 L4
    ctx = run_l5(ctx)
    # DB writer (non-blocking)
    from main.db_writer import update_from_pipeline_result
    update_from_pipeline_result(pipeline, market=ctx.market.value)
    return pipeline_dict
```

### db_writer.py（数据库写入）

```python
from main.db_writer import update_from_pipeline_result, write_decision

# 从 pipeline dict 批量写入
update_from_pipeline_result(pipeline, market="CN")

# 单条写入
write_decision(stock_code="600519", stock_name="贵州茅台", ...)
```

## 4. 设计原则

1. **main 层只做编排**：所有业务逻辑在下层，main 层只是胶水代码
2. **双入口模式**：
   - `main/l*_runner.py` — PipelineContext 集成入口（供 shennong.py 调用）
   - `L*_screener/l*_runner.py` — 底层独立入口（供测试和独立调用）
3. **配置全部入 PipelineContext**：runner 从 ctx 读配置，不自行加载 json
4. **结果层层累积**：ctx.l1_result → ctx.l2_result → ... → ctx.l5_result
5. **数据契约统一**：所有层用 `contracts/` 下的 dataclass，不混用 dict
6. **DB 非阻塞写入**：db_writer 失败不影响主流程

## 5. 自检清单

**说"自检"触发**：
```bash
cd ~/.hermes/investment && python3 -c "
import os, sys
BASE = os.path.expanduser('~/.hermes/investment')

# 1. 核心文件存在性
files = [
    'main/l1_runner.py', 'main/l2_runner.py', 'main/l3_runner.py',
    'main/l4_runner.py', 'main/l5_runner.py',
    'main/shennong.py', 'main/db_writer.py',
    'main/contracts/__init__.py', 'main/contracts/context.py',
    'main/shennong-run.sh',
]
print('=== 文件结构 ===')
for f in files:
    p = os.path.join(BASE, f)
    print(f'{'✅' if os.path.exists(p) else '❌'} {f}')

# 2. 跨层引用检查（L5 不应 import L4）
print()
print('=== 跨层引用 ===')
result = os.popen(f'grep -r \"from L4_judge\" {BASE}/L5_post_review/ 2>/dev/null || echo \"无跨层引用 ✅\"').read()
print(result.strip())

# 3. 配置 fallback 检查
print('=== Runner 配置加载 ===')
for runner in ['l1_runner', 'l3_runner', 'l4_runner']:
    p = os.path.join(BASE, f'main/{runner}.py')
    with open(p) as f:
        content = f.read()
    has_context_config = 'ctx.l1_config' in content or 'ctx.l2_config' in content or 'ctx.l3_config' in content
    has_fallback_load = '_load_l' in content and 'open(' in content
    print(f'  {runner}: config_from_ctx={has_context_config}, self_load_json={has_fallback_load}')

# 4. DB writer 可导入
print()
print('=== DB Writer ===')
try:
    sys.path.insert(0, os.path.join(BASE, 'main'))
    from db_writer import update_from_pipeline_result, write_decision
    print('  ✅ db_writer 可导入')
except Exception as e:
    print(f'  ❌ db_writer 导入失败: {e}')

# 5. contracts 可导入
print()
print('=== Contracts ===')
try:
    from main.contracts import PipelineContext, load_all_config
    print('  ✅ contracts 可导入')
except Exception as e:
    print(f'  ❌ contracts 导入失败: {e}')

# 6. shennong.py 可导入
print()
print('=== Shennong ===')
try:
    import runpy
    ns = runpy.run_path(os.path.join(BASE, 'main/shennong.py'), run_name='__main__')
    print('  ✅ shennong.py 可导入')
except Exception as e:
    print(f'  ❌ shennong.py 导入失败: {e}')
"
```

自检通过标准：
1. ✅ 所有核心文件存在
2. ✅ 无跨层引用（L5 → L4 等）
3. ✅ runner 只从 PipelineContext 读配置，不自行加载 json
4. ✅ db_writer 可正常导入
5. ✅ contracts 可正常导入
6. ✅ shennong.py 可正常导入（无语法错误）