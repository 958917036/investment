# 神农系统 — 用户手册

## 1. 入口

```bash
cd ~/.hermes/investment
python3 main/shennong.py [OPTIONS]
```

---

## 2. 参数说明

### `--mode` 运行模式

| 值 | 说明 |
|---|---|
| `full` | 全链路 L1→L2→L3→L4→L5（默认） |
| `L1` | 仅 L1 选股，返回候选股票列表 |
| `L2` | L1→L2，仅数据充实 |
| `L3` | L3 量化分析 |
| `L4` | L4 风险裁定 |
| `L5` | L5 终审复核 |
| `quick` | 全链路，跳过 LLM 人格分析，加快速度 |

### `--market` 市场

| 值 | 说明 |
|---|---|
| `CN` | A股（默认） |
| `HK` | 港股 |
| `US` | 美股 |

### `--query` L1 查询模式

指定 L1 的查询方式，决定 `--symbols` 的含义。

| 值 | `--symbols` 含义 | 示例 |
|---|---|---|
| `by_code` | 股票代码（默认） | `--symbols 600519` |
| `by_name` | 股票名称关键字（模糊匹配） | `--symbols 茅台` |
| `by_sector` | 板块名称关键字 | `--symbols 白酒` |
| `by_strategy` | 选股策略名称 | `--symbols breakout` |

> 若不指定 `--query`，默认用 `by_code`（按代码精确查询）。
> `by_name` / `by_sector` 只支持单个关键字，多余参数会被忽略。

### `--strategy` 选股策略

指定 `--query by_strategy` 时的策略名称，是 `--query by_strategy --symbols xxx` 的简写。

| 值 | 说明 |
|---|---|
| `breakout` | 突破策略：价格突破均线 + 成交量放大 |
| `growth_momentum` | 成长动量：净利润增速 + 股价动量 |
| `garp` | GARP 策略：PE/G 合理，增长稳健 |
| `pullback` | 回撤策略：超买回撤修复，均值回归 |
| `quality_value` | 质量价值：ROE + 估值综合评分 |

不指定时默认运行全部 5 种策略。

### `--symbols` 参数

配合 `--query` 使用，指定查询目标。

| 市场 | 代码格式 | 示例 |
|---|---|---|
| CN | 6位数字 | `600519`、`000858` |
| HK | 5位数字 | `09999`、`00700` |
| US | 字母 ticker | `TSM`、`AAPL` |

可指定多个（空格分隔）：`--symbols 600519 000858`

---

## 3. 命令示例与验证结果

### by_code（L1 层）

| 命令 | 验证结果 |
|---|---|
| `--mode L1 --market CN --symbols 600519` | ✅ L1 返回 1 只（贵州茅台） |
| `--mode L1 --market CN --symbols 600519 000858` | ✅ L1 返回 2 只 |
| `--mode L1 --market HK --symbols 09999` | ✅ L1 返回 1 只（邮储银行） |
| `--mode L1 --market US --symbols TSM` | ✅ L1 返回 1 只（台积电） |

### by_name（L1 层）

| 命令 | 验证结果 |
|---|---|
| `--mode L1 --market CN --query by_name --symbols 茅台` | ✅ L1 返回 1+ 只 |
| `--mode L1 --market HK --query by_name --symbols 邮储` | ⚠️ 网络依赖（akshare API） |
| `--mode L1 --market US --query by_name --symbols Apple` | ⚠️ 网络依赖（akshare API） |

### by_sector（L1 层）

| 命令 | 验证结果 |
|---|---|
| `--mode L1 --market CN --query by_sector --symbols 白酒` | ⚠️ 网络依赖（akshare API） |
| `--mode L1 --market CN --query by_sector --symbols 医药` | ⚠️ 网络依赖（akshare API） |
| `--mode L1 --market HK --query by_sector --symbols 银行` | ⚠️ 网络依赖（akshare API） |

### by_strategy（L1 层）

| 命令 | 验证结果 |
|---|---|
| `--mode L1 --market CN --strategy breakout` | ✅ L1 返回 3 只（test_limit=3） |
| `--mode L1 --market CN --query by_strategy --symbols growth_momentum` | ✅ 同上 |
| `--mode L1 --market CN --query by_strategy` | ✅ L1 返回 15 只（5策略×3） |

### 全链路

| 命令 | 验证结果 |
|---|---|
| `--mode L4 --market CN --symbols 600519` | ✅ BUY 1/1，judge=0.578 |
| `--mode full --market CN --strategy breakout` | ✅ BUY 1/3（天孚通信），L5终审完成 |

---

## 4.完整命令示例

```bash
# A股全链路（当日候选股全跑）
python3 main/shennong.py --mode full --market CN

# A股指定股票快速裁定（跳过L1筛选）
python3 main/shennong.py --mode L4 --market CN --symbols 600519

# 港股全链路
python3 main/shennong.py --mode full --market HK

# 美股全链路
python3 main/shennong.py --mode full --market US

# A股只看候选股（不跑后续层）
python3 main/shennong.py --mode L1 --market CN

# 按名称查询（模糊匹配）
python3 main/shennong.py --mode L1 --market CN --query by_name --symbols 茅台

# 按板块查询
python3 main/shennong.py --mode L1 --market CN --query by_sector --symbols 白酒

# 按策略选股（单一策略）
python3 main/shennong.py --mode L1 --market CN --strategy breakout

# 多只批量分析
python3 main/shennong.py --mode L4 --market CN --symbols 600519 000858

# 快速模式（跳过LLM人格分析）
python3 main/shennong.py --mode quick --market CN --symbols 600519
```

---

## 5. L4 判定结果说明

| 决策 | 说明 |
|------|------|
| `BUY` | 买入信号，建议执行 |
| `WATCH` | 观察，暂不买入 |
| `REJECT` | 拒绝，不建议 |

**BUY 条件**：
- 五维度评分 ≥ 55（可在 `l3_weights.json` 配置）
- judge_score ≥ 0.55
- 未触发 veto（否决条件见下）

**Veto 否决条件**（满足任一即 REJECT）：
- `main_net_flow_5d < -5000万`（主力资金大幅流出）
- `ma_status == bearish` 且 `macd_status in (death, death_cross)`（技术面破位）

---

## 6. 数据输出

所有结果写入 **platform 数据库**（`platform/backend/platform.db`），不再写 JSON 文件。

| 表 | 说明 |
|---|---|
| `analysis_records` | 完整 L1/L2/L3/L4 分析结果 |
| `decisions` | L4 裁定决策（BUY/WATCH/REJECT） |

---

## 7. 冻结管理

冻结表为文件：`main/freeze_table.json`

```bash
python3 -c "
import json
with open('main/freeze_table.json') as f:
    d = json.load(f)
print(f'冻结: {len(d[\"freeze_records\"])} 只')
print(f'观察: {len(d[\"observing_list\"])} 只')
print(f'买入信号: {len(d[\"buy_signals\"])} 只')
"
```

---

## 8. 日志

```bash
# 实时跟踪
tail -f ~/.hermes/investment/logs/hermes.log

# 按数据源筛选
grep "[source=tencent]" ~/.hermes/investment/logs/hermes.log
grep "[source=akshare]" ~/.hermes/investment/logs/hermes.log
grep "[ERROR]" ~/.hermes/investment/logs/hermes.log
```

---

## 9. 配置文件

所有参数均在 `main/config/` 下，代码不硬编码。

| 文件 | 说明 |
|---|---|
| `l1_config.json` | L1 选股：市场批次大小、阈值、策略开关 |
| `l2_config.json` | L2 数据：并发控制、超时、字段映射 |
| `l3_config.json` | L3 量化：五维度权重、LLM gate、交易成本 |
| `l3_persona_config.json` | LLM persona：可用角色列表、API 参数 |
| `l4_weights.json` | L4 裁判：判定阈值、权重分配、verdict 映射 |
| `l4_risk_config.json` | 风控：单股上限、仓位限制、止损止盈默认 |
| `l4_batch_config.json` | 批处理：批次大小、缓存、重试 |
| `model_config.json` | LLM API：模型、key、endpoint |

---

## 10. Cron 定时任务

在 `~/.hermes/cron/jobs.json` 中配置：

```json
{
  "script": "cd /Users/guchuang/.hermes/investment && python3 main/shennong.py --mode full --market CN",
  "prompt": null,
  "deliver": "local"
}
```

---

## 11. 测试验证

```bash
# 三市场全链路测试
python3 testsv2/tmp/integration/test_main_pipeline.py --market ALL

# 单市场测试
python3 testsv2/tmp/integration/test_main_pipeline.py --market CN
python3 testsv2/tmp/integration/test_main_pipeline.py --market HK
python3 testsv2/tmp/integration/test_main_pipeline.py --market US
```

---

## 12. 关键文件

```
~/.hermes/investment/
  main/shennong.py                   # 统一入口
  main/db_writer.py                  # 数据库写入
  main/freeze_table.json            # 冷冻股表
  main/config/                       # 所有配置文件
  platform/backend/platform.db        # SQLite 数据库
  logs/hermes.log                    # 日志
  testsv2/tmp/integration/test_main_pipeline.py  # 全链路测试
```