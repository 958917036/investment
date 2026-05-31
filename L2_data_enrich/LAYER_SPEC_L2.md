# L2 Data Enrich 层规格说明

## 1. 功能说明

L2 层负责**市场数据统一获取**，对单只股票（A股/港股/美股）一次性查询全部所需数据，按五个维度组织输出：资金流、技术面、基本面、板块、事件。

**数据质量设计：**
- 失败字段 → 字符串 `"失败"`
- `missing_fields` → 本次获取失败的字段列表
- `quality` → `ok` / `degraded` / `fail`

## 2. 接口说明

### 入口函数

```python
from L2_data_enrich.l2_runner import fetch_market_data

data = fetch_market_data(code: str, market: str) -> dict
```

### 入参

| 参数 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `code` | str | `"600519"` / `"00700"` / `"SMCI"` | 股票代码，CN 为纯数字，HK 自动补 5 位，US 为字母代码 |
| `market` | str | `"CN"` / `"HK"` / `"US"` | 市场代码，大小写不敏感 |

### 出参结构

```json
{
  "layer": "L2",
  "code": "600519",
  "market": "CN",
  "run_date": "2026-05-30",
  "moneyflow_data": {
    "source": "腾讯API+东方财富",
    "quality": "ok",
    "missing_fields": [],
    "main_net_flow_5d": 80000000,
    "main_direction": "流入",
    "outer_inner_ratio": 1.15,
    "large_order_ratio": 0.25,
    "retail_direction": "流出",
    "daily_flows": [...],
    "stock_rank": 85
  },
  "technical_data": {
    "source": "BaoStock日线",
    "quality": "ok",
    "missing_fields": [],
    "ma_status": "bullish",
    "macd_status": "golden",
    "rsi": 55,
    "ma5": 1800.0,
    "ma10": 1780.0,
    "ma20": 1750.0,
    "ma60": 1700.0,
    "volume_status": "放量上涨",
    "volume_ratio": 1.5,
    "price": 1850.0,
    "change_pct": 2.5,
    "bb_upper": 1920.0,
    "bb_mid": 1850.0,
    "bb_lower": 1780.0,
    "bb_position": 0.5,
    "dif": 15.5,
    "dea": 10.2,
    "macd_hist": 5.3
  },
  "fundamental_data": {
    "source": "AkShare财务+腾讯API",
    "quality": "ok",
    "missing_fields": [],
    "roe": 28.5,
    "pe": 22.0,
    "pb": 7.4,
    "net_profit_yoy": 15.2,
    "eps_growth_yoy": 12.8,
    "gross_margin": 91.5,
    "net_margin": 54.2,
    "revenue_growth": 18.0,
    "eps": 18.5,
    "debt_eq": 0.25,
    "inst_ownership_pct": 75.5,
    "inst_trans": 2.3
  },
  "sector_data": {
    "source": "AkShare板块",
    "quality": "ok",
    "missing_fields": [],
    "sector_rank": 85,
    "sector_fund_flow": 500000000,
    "sector_strength": "强势",
    "related_sector": "白酒"
  },
  "event_data": {
    "source": "AkShare新闻",
    "quality": "ok",
    "missing_fields": [],
    "positive_events": ["业绩预增50%", "中标大单"],
    "analyst_rating": "buy",
    "report_count_30d": 8
  },
  "duration_ms": 1200
}
```

### 五维度质量判断规则

| 维度 | 关键缺失字段 | 质量降级规则 |
|---|---|---|
| `moneyflow_data` | `main_net_flow_5d`, `outer_inner_ratio`, `large_order_ratio` | 缺失≥70%关键字段 → `fail`，≥30% → `degraded` |
| `technical_data` | `ma_status`, `macd_status`, `rsi` | 同上 |
| `fundamental_data` | `roe`, `pe` | 同上 |
| `sector_data` | `sector_rank`（无板块数据时默认50） | 无板块成分股 → `fail` |
| `event_data` | `positive_events` | 无研报覆盖 → `degraded` |

## 3. 调用示例

```bash
# 获取A股（600519）全部维度数据
python L2_data_enrich/l2_runner.py 600519 CN

# 获取港股（00700）全部维度数据
python L2_data_enrich/l2_runner.py 00700 HK

# 获取美股（SMCI）全部维度数据
python L2_data_enrich/l2_runner.py SMCI US

# 直接导入调用（Python 代码中）
python -c "from L2_data_enrich.l2_runner import fetch_market_data; print(fetch_market_data('600519', 'CN')['fundamental_data']['quality'])"
```

## 4. 涉及配置

| 配置文件 | 路径 | 用途 |
|---|---|---|
| `.env` | `~/.hermes/.env` | 环境变量，LLM API Key 等 |
| `main/config/` 下各配置文件 | `main/config/` | L3/L4 层配置（由 L2 调用但非 L2 自身配置） |

L2 层自身**无独立配置文件**，数据获取逻辑全部硬编码，通过返回字段中的 `quality` 和 `missing_fields` 表达数据质量。

## 5. 目录结构与类说明

```
L2_data_enrich/
├── data_fetcher.py        # 统一导出（fetch_batch/fetch_all/fetch_one_stock）
├── l2_runner.py           # 统一入口（fetch_market_data）
├── core/
│   ├── market_fetcher.py # 核心实现（fetch_market_data / fetch_cn / fetch_hk / fetch_us）
│   └── data_fetcher.py   # 批获取实现（fetch_batch / fetch_all / fetch_one_stock）
└── adapters/              # 市场适配器
    └── us/
        └── us_fetcher_adapter.py  # 美股数据适配器
```

> **外部调用注意**：`main/shennong.py` 等通过 `from L2_data_enrich.data_fetcher import fetch_batch` 使用，`data_fetcher.py` 是对 `core/data_fetcher.py` 的重导出。

### market_fetcher.py 关键函数

| 函数 | 说明 |
|---|---|
| `fetch_market_data(code, market)` | 统一入口，分发到 CN/HK/US |
| `fetch_cn(code)` | A股数据获取，调用 `data_fetcher.fetch_all()` |
| `fetch_hk(code)` | 港股数据获取，腾讯实时 + AkShare 日线 + MFI |
| `fetch_us(code)` | 美股数据获取，调用 `us_fetcher_adapter.fetch_us_data()` |
| `_fetch_hk_realtime(code5)` | 腾讯港股实时行情（hk 前缀） |
| `_fetch_hk_daily(code5)` | AkShare 港股日线 |
| `_calc_hk_mfi(df)` | 港股 MFI-14 计算 |
| `_calc_hk_technicals(df)` | 基于日线 DataFrame 计算技术指标 |
| `_fetch_hk_financial(code5)` | AkShare 港股财务指标 |
| `_fetch_hk_events(code5)` | AkShare 港股券商评级 |

### 辅助函数

| 函数 | 说明 |
|---|---|
| `_safe_float(val, default)` | 安全转浮点，过滤 NaN |
| `_mark_missing(result, fields, quality)` | 将字段标记为 "失败" |
| `_determine_quality(missing_fields, total_critical)` | 根据缺失比例判断质量等级 |

## 6. 外部依赖

| 依赖项 | 用途 | 说明 |
|---|---|---|
| **akshare** | A股日线、财务数据、板块成分股、港股/美股行情 | `pip install akshare` |
| **baostock** | A股日线技术指标（MA/MACD/RSI/布林带） | `pip install baostock` |
| **pandas** | DataFrame 处理 | |
| **requests** | HTTP 请求 | |
| **腾讯行情 API** | 实时行情（所有市场） | 免费，分 batch 请求 |
| **us_fetcher_adapter** | 美股统一数据适配器（内部封装 Yahoo Finance / finviz） | L2 子目录 adapter |

### 市场数据源对应关系

| 市场 | 实时行情 | 技术指标 | 财务数据 | 资金流 |
|---|---|---|---|---|
| CN | 腾讯 API | BaoStock | AkShare | 东方财富（经 BaoStock 估算） |
| HK | 腾讯 API（hk 前缀） | AkShare 日线计算 | AkShare financial_indicator | AkShare MFI 估算 |
| US | 腾讯 API（us 前缀） | Yahoo Finance Chart | AkShare + finviz | Yahoo Finance MFI |

## 7. 测试代码

测试代码位于 `testsv2/l2/` 目录：

```
testsv2/
└── l2/
    ├── test_l2_runner.py       # 入口测试
    └── test_market_fetcher.py  # 各市场 fetch 函数测试
```

运行方式：
```bash
cd ~/.hermes/investment
python L2_data_enrich/l2_runner.py 600519 CN
python L2_data_enrich/l2_runner.py 00700 HK
python L2_data_enrich/l2_runner.py SMCI US
```

或独立测试文件：
```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/.hermes/investment"))
from L2_data_enrich.l2_runner import fetch_market_data

# Test CN
data = fetch_market_data("600519", "CN")
assert data["layer"] == "L2"
assert data["market"] == "CN"
assert "moneyflow_data" in data
assert "technical_data" in data
print(f"CN quality: {data['fundamental_data']['quality']}")

# Test HK
data = fetch_market_data("00700", "HK")
assert data["market"] == "HK"
print(f"HK quality: {data['fundamental_data']['quality']}")

# Test US
data = fetch_market_data("SMCI", "US")
assert data["market"] == "US"
print(f"US quality: {data['fundamental_data']['quality']}")

print("L2 测试通过")
```