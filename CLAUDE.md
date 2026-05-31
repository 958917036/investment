# Hermes Investment System

## 项目概述
AI 驱动的多市场股票筛选与量化分析系统，L1→L5 全链路。

## 目录结构
```
~/.hermes/investment/
├── L1_screener/          # L1 选股（5种策略 + 3种查询模式）
│   └── l1_runner.py      # 底层独立入口（8种模式：5策略 + by_name + by_code + by_sector）
├── L2_data_enrich/       # L2 数据 enrichment
├── L3_quant_analysis/     # L3 量化分析
├── L3_llm_perspectives/  # L3 LLM 多空视角
├── L4_judge/             # L4 裁定
├── L5_post_review/       # L5 终审
├── main/                 # 调度层（统一入口）
│   ├── contracts/         # 数据契约（dataclass 定义）
│   ├── config/           # 配置文件（l1_config.json 等）
│   ├── l1_runner.py     # L1 PipelineContext 集成入口
│   ├── l2_runner.py     # L2 PipelineContext 集成入口
│   ├── l3_runner.py     # L3 PipelineContext 集成入口
│   ├── l4_runner.py     # L4 PipelineContext 集成入口
│   ├── l5_runner.py     # L5 PipelineContext 集成入口
│   ├── shennong.py      # 主调度器（CLI 入口）
│   ├── db_writer.py      # 写入 platform 数据库
│   ├── freeze_table.json # 冷冻股表（L5 终审用）
│   └── shennong-run.sh   # shell 入口
├── logs/                 # 日志文件（hermes.log）
├── testsv2/              # 测试代码（按层分组）
└── docs/                 # 文档
```

## 核心规范

### Layer 设计原则
1. **每层双入口**：每层有两层入口——`main/` 下 PipelineContext 集成入口（如 `main/l1_runner.py`），和各层自己 `*_runner.py`（如 `L1_screener/l1_runner.py`）供独立调用。`main/` 下有 `l1~l5_runner.py` 共 5 个 PipelineContext 集成入口。
2. **子目录命名**：`core/`、`utils/`、`strategies/`、`adapters/`、`scoring/`、`debate/`、`risk/`、`execution/`
3. **层间调用**：上层调用下层，数据流 L1→L2→L3→L4→L5，不允许反向引用
4. **失败可识别**：`"失败"` 标记字段失败，`missing_fields` 记录缺失，`quality: ok|degraded|fail`
5. **配置与代码分离**：参数放 `main/config/*.json`，不硬编码
6. **测试隔离**：`testsv2/` 目录放测试代码，不混入正式代码
7. **市场数据统一入口**：`fetch_market_data(code, market)`，CN(纯数字)/HK(5位)/US(字母)
8. **LLM graceful degradation**：不可用时返回 `_status: "skipped"`
9. **统一日志工具**：`main/utils/logger.py` 所有层共享，外部调用必须使用
10. **配置从 PipelineContext 获取**：所有 runner 的 config 参数必须从 PipelineContext 传入，**不允许 fallback 自行加载配置文件**。若 config 为 None，runner 应抛出 `ValueError`。

### 测试规范
- 每个测试必须有 assert 语句
- 每个测试必须有 docstring 说明入参
- 测试覆盖度对照接口规格检查
- **测试不是交差，是质量门禁**：测试结果必须关注输出 JSON 的完整性和正确性，不是一次性应付
- **测试需持续完善**：每次发现边界问题后生成 plan 补充测试用例，覆盖新发现的 edge case
- **测试分层**：
  - `testsv2/l1/` — L1 选股策略测试
  - `testsv2/l2/` — L2 数据 enrichment 测试
  - `testsv2/l3/` — L3 量化分析测试
  - 以此类推
- **日志规范**：每个测试必须打印以下4项：
  1. `输入:` 调用入参（input_type + params）
  2. `预期:` 期望的返回结果（stock_count 范围或特定值）
  3. `实际:` 真实的返回结果
  4. `耗时:` 执行时间（秒），方便发现性能问题
- **L2 测试输出结构**（每次运行必须包含）：
  ```json
  {
    "用例": "CN(600519贵州茅台)",
    "耗时": "22.66s",
    "输入": {"code": "600519", "market": "CN"},
    "完整输出": { ... full L2 data ... },
    "字段校验": { "price": {"期望": ">0", "实际": 1326.0, "结果": "✅"}, ... },
    "失败字段检测": [],
    "结果": "PASS"
  }
  ```
- **断言规则**：
  - 关键字段（price/roe/pe）必须为有效数字，不允许 "失败"
  - `quality` 字段必须为 ok/degraded/fail 之一
  - `missing_fields` 必须为 list
  - CN 股票数据完整时 fundamental quality 必须为 ok

### 测试执行日志规范

**所有测试必须通过 `testsv2/test_logger.py` 写入 hermes.log**，不允许仅 print 到 stdout。

每个测试文件执行前调用 `suite_start()`，结束后调用 `suite_end()`，每个用例前后调用 `test_start()` / `test_end()`：

```python
# 在测试文件顶部
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from test_logger import suite_start, suite_end, test_start, test_end

# _run_all() 函数开始处
tests = [("用例名", test_fn), ...]
total_start = time.time()
suite_start("test_l2_runner", len(tests))   # 写入 hermes.log + stdout

for name, fn in tests:
    test_start("test_l2_runner", name)      # 写入 hermes.log + stdout
    t0 = time.time()
    try:
        fn()
        test_end("test_l2_runner", name, True, time.time() - t0)
    except (AssertionError, Exception) as e:
        test_end("test_l2_runner", name, False, time.time() - t0, str(e))

suite_end("test_l2_runner", passed, failed, time.time() - total_start)
```

**hermes.log 中的标记格式**：
```
[2026-05-31 17:14:34.123] [TEST] test_l2_runner ▶ START  tests=9
[2026-05-31 17:14:34.456] [TEST] test_l2_runner::CN(600519贵州茅台) ▶ START
[2026-05-31 17:14:47.891] [TEST] test_l2_runner::CN(600519贵州茅台) ▶ END  elapsed=13.4s  status=PASS
...
[2026-05-31 17:15:02.123] [TEST] test_l2_runner ▶ END  passed=9 failed=0 elapsed=28.3s  status=PASS
```

**用途**：从 hermes.log 可直接定位每个测试用例的起止时间、耗时、是否通过，解决"30分钟不知道去哪了"的问题。

**筛选命令**：
```bash
grep "\[TEST\]" ~/.hermes/investment/logs/hermes.log       # 所有测试执行标记
grep "\[TEST\].*▶ START" ~/.hermes/investment/logs/hermes.log | grep test_l2_runner  # L2测试开始
grep "\[TEST\].*▶ END" ~/.hermes/investment/logs/hermes.log   # 所有测试结束（含 passed/failed）
```

**run_all_tests.py 优先解析 TEST suite_end 行**，格式稳定，不依赖测试文件输出格式。
- 示例：
  ```python
  print(f"  输入: by_code, code=600519")
  print(f"  预期: stock_count=1, name=贵州茅台")
  print(f"  实际: stock_count={r['stock_count']}, name={r['stocks'][0]['name']}")
  print(f"  耗时: {elapsed:.2f}秒")
  ```

### 外部调用日志规范
- **必须使用** `main/utils/logger.py`（所有层共享），不允许直接 print
- 每个层脚本需要在开头添加 `main/utils/` 到 sys.path：
  ```python
  import sys, os
  BASE = os.path.expanduser("~/.hermes/investment")
  sys.path.insert(0, os.path.join(BASE, "main", "utils"))
  from logger import log_start, log_end, log_fail, log_source, info
  ```
- 日志同时输出到 stdout 和文件 `~/.hermes/investment/logs/hermes.log`
- **数据源日志必须包含 source 标识**，方便按数据源筛选和复盘：
  ```python
  # 通用格式：log_source(module, source, operation, success, detail)
  log_source("l2_runner", "akshare", "获取股票列表", True, "800条")
  log_source("l2_runner", "tencent", "获取实时行情", False, "Connection timeout")
  ```
- 日志输出格式：
  - 成功：`[INFO] [module] [source=akshare] 获取股票列表成功 - 800条`
  - 失败：`[ERROR] [module] [source=tencent] 获取行情失败 - Connection timeout`
- 可用 `grep "\[source=xxx\]" logs/hermes.log` 快速筛选特定数据源的所有日志
- 工具函数：
  - `log_start(module, operation, detail)` - 标记操作开始
  - `log_end(module, operation, result)` - 标记操作完成
  - `log_fail(module, operation, reason)` - 标记操作失败
  - `log_source(module, source, operation, success, detail)` - **数据源调用**（必须标注 source）
  - `info(module, message)` - 普通信息
  - `warn(module, message)` - 警告
  - `error(module, message)` - 错误

### 日志排查
常用排查命令：
```bash
# 按数据源筛选成功/失败日志
grep "\[source=akshare\]" ~/.hermes/investment/logs/hermes.log
grep "\[source=tencent\]" ~/.hermes/investment/logs/hermes.log
grep "\[source=yahoo\]" ~/.hermes/investment/logs/hermes.log
grep "\[source=baostock\]" ~/.hermes/investment/logs/hermes.log

# 查看失败日志（方便定位问题）
grep "\[ERROR\]" ~/.hermes/investment/logs/hermes.log

# 按层筛选
grep "\[l1_runner\]" ~/.hermes/investment/logs/hermes.log
grep "\[l2_runner\]" ~/.hermes/investment/logs/hermes.log
```

数据源标识：`akshare`（股票列表/财务数据）、`tencent`（实时行情）、`yahoo`（美股）、`baostock`（A股技术指标）。

### API 健康监控日志
**`data_fetcher.py` 使用 `_api_log()` 写入 hermes.log**，格式为每行：
```
[2026-05-31 14:00:26.395] [source=tencent] fetch_qq_realtime ✅ - code=600519, price=1326.0
[2026-05-31 14:00:53.215] [source=akshare] fetch_fund_flow ✅ - code=600519, has_main_net_flow_5d=False
[2026-05-31 14:00:54.721] [source=baostock] fetch_technical ✅ - code=600519, ma_status=neutral
```

**用途**：快速判断 API 失败是代码 bug（该 API 总是失败）还是网络问题（间歇性）。
**筛选命令**：
```bash
grep "\[source=tencent\]" ~/.hermes/investment/logs/hermes.log   # 腾讯行情
grep "\[source=akshare\]" ~/.hermes/investment/logs/hermes.log  # AkShare 系列
grep "❌" ~/.hermes/investment/logs/hermes.log                  # 所有失败
```

### 数据源 Fallback 原则
**默认所有数据源应稳定可用，fallback 是健壮性设计而非日常路径。**

数据源故障时必须切换到其它数据源，**禁止虚假默认值**：
- **允许**：切换到备用数据源（如 AkShare → BaoStock → 腾讯 API）
- **允许**：动态计算合理估算值（如 MFI 失败时用成交量×价格动态估算资金流向）
- **禁止**：硬编码虚假默认值（如 price=0、pe=15、mfi=50 等静默填充）
- **必须**：数据源切换时记录 `_source` 字段标注来源，故障时 `quality=fail`，`missing_fields` 记录缺失字段
- **无兜底**：所有可用数据源均失败时，本维度 `quality=fail`（不伪造数据影响上层判断）

**日常路径原则**：
- 正常情况下数据走主数据源（AkShare），**不应频繁走到 fallback**
- 如果某数据源经常触发 fallback → 说明该接口有 bug，应直接修复接口，而非依赖 fallback 凑合
- Fallback 是对极端情况（网络抖动、接口临时不可用）的防御，不是对数据源不稳定性的妥协

**已知 bug（已修复）**：
- ~~`fetch_fund_flow`（AkShare）返回 `main_net_flow`（单日净额），但 `fetch_all` 检查的是 `main_net_flow_5d`，导致字段名不匹配，fallback 条件永远为 True，AkShare 数据被跳过。~~ ✅ 2026-05-31 已修复：EM 直连 API 提供 `main_net_flow_5d`，fallback 条件改为同时检查两者

### 当前配置（l1_config.json）
```json
"signals": {
    "buffett": {"thresholds": [0.40, 0.50, 0.65]},
    "lynch": {"thresholds": [0.40, 0.50, 0.65]},
    "graham": {"thresholds": [0.40, 0.50, 0.65]},
    "momentum": {"thresholds": [0.40, 0.50, 0.65]},
    "reversion": {"thresholds": [0.40, 0.50, 0.65]}
}
```

## 常用命令
```bash
# 运行 L1 测试
cd ~/.hermes/investment && python3 testsv2/l1/test_l1_runner.py

# 运行单个策略
python3 -c "from L1_screener.l1_runner import run_l1; print(run_l1('by_strategy', {'strategy': 'breakout'}))"

# 运行全部测试
python3 testsv2/run_all_tests.py
# 运行单个层
python3 testsv2/run_all_tests.py --layer L2
# 查看日志
tail -f ~/.hermes/investment/logs/hermes.log
```

### 系统自检（每次代码修改后执行）

**快速自检命令**：
```bash
# 检查所有 runner 文件完整性
cd ~/.hermes/investment && python3 -c "
import os
files=['L1_screener/l1_runner.py','L2_data_enrich/l2_runner.py','L3_quant_analysis/l3_quant_runner.py','L3_llm_perspectives/persona_runner.py','L4_judge/l4_runner.py','L5_post_review/freeze_manager.py','L5_post_review/review_engine.py','L5_post_review/position_tracker.py','L5_post_review/report_generator.py','L5_post_review/parameter_advisor.py','main/l1_runner.py','main/l2_runner.py','main/l3_runner.py','main/l4_runner.py','main/l5_runner.py']
for f in files:
    p=os.path.expanduser(f'~/.hermes/investment/{f}')
    print(f'{'✅' if os.path.exists(p) else '❌'} {f}')
"

# 检查跨层引用（L5 不应 import L4）
grep -r "from L4_judge" ~/.hermes/investment/L5_post_review/ 2>/dev/null || echo "无跨层引用 ✅"

# 检查配置 fallback 加载
grep -n "_load_l3_config\|_load_l4_weights" ~/.hermes/investment/L3_quant_analysis/l3_quant_runner.py ~/.hermes/investment/L4_judge/l4_runner.py

# 检查测试文件命名（以 test_ 开头）
ls ~/.hermes/investment/testsv2/l1/test_*.py | head -5

# 检查测试类名（以 Test 开头）
grep -rh "^class Test" ~/.hermes/investment/testsv2/ 2>/dev/null | head -10
```

**自检清单**（说"自检"触发）：
1. 源代码结构：15 个 runner 文件存在
2. 跨层引用：L5 不应 import L4
3. 配置加载：runner 必须从 PipelineContext 获取配置
4. 测试覆盖：每个正式类有对应测试类（1:1 镜像）
5. 分层设计：上层调用下层，数据流 L1→L2→L3→L4→L5
6. 类/包命名规范：正式类 PascalCase，测试类 Test 开头
7. 测试文件路径：testsv2/<layer>/test_<正式类名>.py

详细自检报告见：[system-health-check.md](~/.claude/projects/-Users-guchuang--hermes/memory/system-health-check.md)

### 实现备忘（方便后续理解）
- **`data_fetcher.py` 头部 import 完整列表**：`os as _log_os`, `os as _os`, `json`, `time`, `re`, `subprocess`, `logging`, `typing.Dict/Any/List/Optional`, `datetime/timedelta`。新增标准库模块时容易忘记在这里补 import，导致 `NameError` 在运行时才暴露。
- **测试文件 `_show()` 必须 flush**：`testsv2/` 下测试重定向了 `sys.stdout`/`sys.stderr`，`_show()` 恢复后若不主动 `flush()`，buffer 会截断后续输出，导致用例耗时显示缺失。修复方式：
  ```python
  def _show():
      sys.stdout = _orig_stdout
      sys.stderr = _orig_stderr
      sys.stdout.flush()   # 关键：清空 buffer
      sys.stderr.flush()
  ```
- **`_fetch_single_fund_flow_eastmoney(code)`** 只接收 `code`，不需要传 `name`。调用处 `batch_query_fund_flow` 中 `name` 变量已存在但不应传入。
- **`batch_query_fund_flow` 串行调用**：每只股票间隔 0.3-0.6s 防限流，1747 只股票批量查询预计耗时 ~15-30 分钟。

## 联系方式
神农系统：AI 驱动的多市场股票筛选与量化分析系统（L1→L5 全链路）