# L3 Persona（人格分析）层规格说明

## 1. 功能说明

L3 人格分析层通过 **12 位投资大师的人格视角** 对股票进行独立判断，输出各大师的评分/等级/裁决/理由，以及 BUY/WATCH/REJECT/HOLD 投票汇总。

**默认 3 位大师（可配置最多 12 位）：**
- 巴菲特（buffett）：价值投资，护城河理念
- 彼得·林奇（lynch）：成长投资，GARP 策略
- 德鲁肯米勒（druckenmiller）：宏观交易，择时与催化

**两种运行模式：**
- `merged`（默认）：1 次 LLM 请求分析全部大师，快速（约 1.5s）
- `independent`：12 次独立 LLM 调用，完全隔离（顺序执行，约 22s）

## 2. 接口说明

### 入口函数

```python
from L3_llm_perspectives.persona_runner import run_persona, run_persona_analysis
```

| 函数 | 入参 | 说明 |
|---|---|---|
| `run_persona(L2_data)` | L2 输出字典 | v4 接口，兼容 L2 数据结构 |
| `run_persona_analysis(code, name, price, data, run_mode)` | 原始参数 | 底层人格分析函数 |

### 入参（run_persona）

`L2_data`：L2 层完整输出，包含 `technical_data` / `fundamental_data` / `moneyflow_data` / `sector_data` / `event_data`。

### 出参结构

```json
{
  "layer": "L3_persona",
  "code": "600519",
  "run_date": "2026-05-30",
  "perspectives": {
    "buffett": {
      "score": 0.3,
      "grade": "D",
      "verdict": "REJECT",
      "rationale": "护城河不足..."
    },
    "lynch": {
      "score": 0.7,
      "grade": "B",
      "verdict": "BUY",
      "rationale": "成长性突出..."
    },
    "druckenmiller": {
      "score": 0.65,
      "grade": "B",
      "verdict": "WATCH",
      "rationale": "短期波动加大..."
    }
  },
  "summary": {
    "avg_score": 0.55,
    "buy_count": 1,
    "watch_count": 1,
    "reject_count": 1,
    "hold_count": 0,
    "agents_ok": 3,
    "agents_total": 3
  },
  "quality_overall": "ok",
  "duration_ms": 2100
}
```

### 大师投票说明

| verdict | 说明 |
|---|---|
| `BUY` | 强烈推荐买入 |
| `WATCH` | 谨慎观望 |
| `REJECT` | 不建议买入 |
| `HOLD` | 继续持有（用于已有持仓） |

## 3. 调用示例

```bash
# 执行人格分析（调用 MiniMax LLM，用默认3位大师：巴菲特/林奇/德鲁肯米勒）
python L3_llm_perspectives/persona_runner.py

# 直接导入调用（Python 代码中）
python -c "from L3_llm_perspectives.persona_runner import run_persona; from L2_data_enrich.l2_runner import fetch_market_data; r=run_persona(fetch_market_data('600519','CN')); print(r['summary'])"
```

## 4. 涉及配置

| 配置文件 | 路径 | 用途 |
|---|---|---|
| `l3_persona_config.json` | `main/config/l3_persona_config.json` | 大师列表、API 参数配置 |

### l3_persona_config.json 关键字段

```json
{
  "default_personas": ["buffett", "lynch", "druckenmiller"],
  "api": {
    "provider": "minimax",
    "max_tokens": 4096,
    "temperature": 0.3,
    "timeout": 120
  }
}
```

### 环境变量

| 变量 | 用途 |
|---|---|
| `MINIMAX_CN_API_KEY` | MiniMax API 密钥（必需） |
| `TEST_PERSONAS` | 调试用，限制激活的大师名单（逗号分隔，覆盖 config） |

## 5. 目录结构与类说明

```
L3_llm_perspectives/
├── persona_runner.py           # 统一入口
│   ├── run_persona(L2_data)           # v4 接口
│   ├── run_persona_analysis(...)       # 底层入口
│   ├── _run_merged_mode(...)          # 合并模式
│   ├── _run_independent_mode(...)     # 独立模式
│   ├── _call_llm(...)                # LLM 调用封装
│   ├── _normalize_persona_result()   # 结果标准化
│   └── PERSONAS / PERSONA_NAMES 常量
└── [各大师目录/]             # 各大师的 system_prompt.md
    ├── buffett/system_prompt.md
    ├── lynch/system_prompt.md
    └── ...
```

### 关键内部函数

| 函数 | 说明 |
|---|---|
| `_load_persona_prompt(name)` | 加载大师的 system_prompt.md |
| `_build_data_summary(code, name, price, data)` | 构建数据摘要（送 LLM） |
| `_build_merged_system_prompt()` | 构建合并调用的系统 prompt |
| `_build_merged_user_prompt(...)` | 构建合并调用的用户 prompt |
| `_call_single_persona(...)` | 单大师并行调用（ThreadPoolExecutor） |
| `_normalize_verdict(verdict)` | 规范化裁决结果 |

### 人格配置常量

```python
PERSONAS = [
    "buffett", "graham", "burry", "druckenmiller",
    "taleb", "ackman", "pabrai", "lynch",
    "cathie_wood", "munger", "phil_fisher", "jhunjhunwala",
]
CONSERVATIVE = ["buffett", "graham", "burry", "taleb", "munger"]
MODERATE = ["druckenmiller", "lynch", "phil_fisher", "jhunjhunwala"]
AGGRESSIVE = ["ackman", "pabrai", "cathie_wood"]
DEFAULT_PERSONAS = ["buffett", "lynch", "druckenmiller"]
```

## 6. 外部依赖

| 依赖项 | 用途 | 说明 |
|---|---|---|
| **requests** | LLM API HTTP 调用 | |
| **MiniMax API** | LLM 模型（`MINIMAX_CN_API_KEY`） | 用户指定，禁用 DeepSeek |
| **json / re** | JSON 解析、正则提取 | 标准库 |
| **logging** | 日志 | 标准库 |

**关键设计：**人格分析依赖 LLM API，API 不可用时返回 `_status: "skipped"` 而不是抛异常，保证流水线不会因此中断。

## 7. 测试代码

测试代码位于 `testsv2/l3_persona/` 目录：

```
testsv2/
└── l3_persona/
    └── test_persona_runner.py   # 人格分析测试
```

运行方式：
```bash
cd ~/.hermes/investment
export MINIMAX_CN_API_KEY="your_key_here"
python L3_llm_perspectives/persona_runner.py   # 内置测试
```

或独立测试文件：
```python
import sys, os, json
sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))
os.environ["MINIMAX_CN_API_KEY"] = "test_key"  # 设为空则跳过
from L3_llm_perspectives.persona_runner import run_persona_analysis

test_data = {
    "technical_data": {"pe": 22, "pb": 7.4, "market_cap": 18000, "rsi": 55},
    "fundamental_data": {"roe": 28.5, "gross_margin": 91.5, "revenue_growth": 15},
    "moneyflow_data": {"main_net_flow_5d": -500_000_000},
}

result = run_persona_analysis("600519", "贵州茅台", 1443, test_data, run_mode="merged")
print(json.dumps(result, indent=2, ensure_ascii=False))
print("L3 Persona 测试通过")
```