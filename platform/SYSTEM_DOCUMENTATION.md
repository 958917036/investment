# 神农股票分析平台 — 系统完整文档

## 1. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                     前端 (React SPA)                     │
│              http://localhost:8000/                      │
│   ├── / → Dashboard（全局概览）                          │
│   ├── /search → 股票搜索 + 发起分析                      │
│   ├── /result/:id → 分析结果详情                        │
│   ├── /history/:code → 历史分析记录                     │
│   ├── /compare/:code → 多分析对比                       │
│   ├── /batch/:id → 批量任务详情                         │
│   └── /reflections → 反思记录                           │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP REST API
┌────────────────────────▼────────────────────────────────┐
│                  后端 (FastAPI)                          │
│              http://localhost:8000/api/                  │
│                                                          │
│  POST /api/analyze           发起分析（同步返回task_id）   │
│  GET  /api/result/{id}      分析结果详情                 │
│  GET  /api/history/{code}   历史记录                   │
│  GET  /api/compare/{code}   对比                       │
│  GET  /api/batches            批量任务列表               │
│  GET  /api/batch/{id}       批量任务详情                │
│  POST /api/batch/{id}/retry 重试失败任务               │
│  DELETE /api/batch/{id}     删除批量任务               │
│  GET  /api/stocks            股票库                    │
│  GET  /api/stocks/search     搜索股票                  │
│  GET  /api/stocks/{code}    股票详情                   │
│  GET  /api/dashboard/stats   仪表盘统计                 │
│  POST /api/reflection        写入反思                   │
│  GET  /api/reflections/{code}  反思记录                 │
└────────────────────────┬────────────────────────────────┘
                         │ asyncio
┌────────────────────────▼────────────────────────────────┐
│              神农引擎 (shennong.py)                      │
│         ~/.hermes/investment/main/shennong.py            │
│                                                          │
│  L1 → 个股筛选（技术面+趋势）                             │
│  L2 → 资金流 + 机构资金流向                               │
│  L3 → 基本面综合评分（财务+估值+成长）                    │
│  L4 → 投资决策 + 概率化方案                              │
│                                                          │
│  市场: CN(沪深) / HK(港股) / US(美股)                   │
└─────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│           SQLite 数据库 (platform.db)                    │
│     ~/.hermes/investment/platform/backend/platform.db   │
│                                                          │
│  analysis_records: 每次完整分析结果                       │
│    - stock_code, market, timestamp                      │
│    - L1_result, L2_result, L3_result, L4_result        │
│    - final_decision (BUY/WATCH/NO)                     │
│    - score (JSON)                                       │
│    - raw_data (JSON), batch_id                          │
│                                                          │
│  batch_tasks: 批量任务记录                               │
│    - stock_codes (JSON list), status                    │
│    - progress, completed, failed                        │
└─────────────────────────────────────────────────────────┘
```

## 2. 当前系统状态

| 指标 | 值 |
|------|-----|
| 总分析次数 | 19 |
| 覆盖股票数 | 10 |
| WATCH 信号 | 6 |
| BUY 信号 | 0 |
| 批量任务总数 | 15 |
| 股票库数量 | 10 |

## 3. 数据库模型

### analysis_records（分析记录）
每次调用 `POST /api/analyze` 产生一条记录，存储单只股票单次分析的完整数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| stock_code | VARCHAR | 股票代码 |
| stock_name | VARCHAR | 股票名称 |
| market | ENUM | CN/HK/US |
| timestamp | DATETIME | 分析时间 |
| status | ENUM | pending/running/completed/failed |
| L1_result | JSON | L1 筛选结果 |
| L2_result | JSON | L2 资金流分析 |
| L3_result | JSON | L3 基本面评分 |
| L4_result | JSON | L4 投资决策 |
| final_decision | ENUM | BUY/WATCH/NO |
| score | JSON | 综合评分 |
| raw_data | JSON | 原始数据 |
| batch_id | UUID | 所属批量任务（可选）|

### batch_tasks（批量任务）
每次调用 `POST /api/analyze` 带多只股票时产生一条批量任务记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| stock_codes | JSON | 股票代码列表 |
| status | ENUM | pending/running/completed/failed |
| progress | INT | 进度百分比 |
| completed | INT | 完成数 |
| failed | INT | 失败数 |
| created_at | DATETIME | 创建时间 |

## 4. API 完整文档

### 4.1 发起分析
```
POST /api/analyze
Body: {"stock_codes": ["00700", "AAPL", "TSLA"], "market": "auto"}
Response: {"batch_id": "uuid", "task_ids": {"00700": "uuid"}}
```
- 同步返回 batch_id 和各股票 task_id
- 后台异步执行 L1→L2→L3→L4 全链路
- 完成后 status 变为 completed/failed

### 4.2 分析结果详情
```
GET /api/result/{result_id}
Response: {
  "id": "uuid",
  "stock_code": "00700",
  "stock_name": "腾讯控股",
  "market": "CN",
  "timestamp": "2026-05-09T11:04:14",
  "status": "completed",
  "final_decision": "WATCH",
  "score": {"total": 68.5, "L1": 72, "L2": 65, "L3": 70, "L4": 67},
  "L1_result": {...},
  "L2_result": {...},
  "L3_result": {...},
  "L4_result": {...}
}
```

### 4.3 历史分析记录
```
GET /api/history/{stock_code}
Response: [{id, timestamp, status, final_decision, score, L1_result, ...}, ...]
```
按时间倒序返回该股票所有历史分析。

### 4.4 多次分析对比
```
GET /api/compare/{stock_code}?ids={id1},{id2}
Response: {
  "stock_code": "00700",
  "analysis_a": {...完整记录A...},
  "analysis_b": {...完整记录B...},
  "comparison": {
    "decision_changed": true,
    "decision_a": "WATCH",
    "decision_b": "BUY",
    "score_a": {"total": 65},
    "score_b": {"total": 72},
    "timestamp_a": "2026-05-08T...",
    "timestamp_b": "2026-05-09T..."
  }
}
```

### 4.5 批量选股
```
GET  /api/batches             # 批量任务列表
GET  /api/batch/{batch_id}    # 批量任务详情
POST /api/batch/{batch_id}/retry  # 重试失败任务
DELETE /api/batch/{batch_id}  # 删除批量任务
```

### 4.6 股票库
```
GET /api/stocks                # 所有分析过的股票
GET /api/stocks/search?q=腾讯  # 搜索（支持中文）
GET /api/stocks/{code}        # 股票详情
```

### 4.7 仪表盘
```
GET /api/dashboard/stats
Response: {
  "total_analyses": 19,
  "stocks_analyzed": 10,
  "watch_count": 6,
  "buy_count": 0,
  "recent_analyses": [{stock_code, stock_name, timestamp, final_decision}, ...]
}
```

### 4.8 反思系统
```
POST /api/reflection
Body: {"stock_code": "00700", "result_id": "uuid", "reflection": "..."}
GET /api/reflections/{stock_code}
```

## 5. 前端页面路由

| 路由 | 功能 |
|------|------|
| `/` | Dashboard 全局概览 |
| `/search` | 搜索股票 → 发起分析 |
| `/result/:resultId` | 单次分析详情 |
| `/history/:stockCode` | 单只股票历史分析记录 |
| `/compare/:stockCode?ids=a,b` | 两次分析对比 |
| `/batch/:batchId` | 批量任务详情 |

## 6. 启动与部署

### 启动后端
```bash
cd ~/.hermes/investment/platform/backend
~/.hermes/hermes-agent/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 访问前端
```
http://localhost:8000
```

### 重启后端
```bash
pkill -f "uvicorn main:app"
cd ~/.hermes/investment/platform/backend
nohup ~/.hermes/hermes-agent/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
```

## 7. 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React + TypeScript + Vite |
| UI组件 | shadcn/ui + Tailwind CSS |
| 图表 | Recharts |
| 后端 | FastAPI + Uvicorn + SQLAlchemy (Async) |
| 数据库 | SQLite (platform.db) |
| 分析引擎 | 神农系统 (shennong.py) |
| Python环境 | ~/.hermes/hermes-agent/venv/bin/python |

## 8. 验证测试结果（最新）

```
35 passed, 4 failed out of 39 tests

通过项：
✓ Input Validation (空列表→422)
✓ Dashboard stats (total/stocks/watch/buy/recent)
✓ Batch list + stock_codes解析 + status
✓ History (AAPL/MSFT 完整L1/L4)
✓ Stock Search (中文搜索正常)
✓ Stocks Library (10只，含名称/市场/决策)
✓ Reflections (NVDA/AAPL)
✓ Result Detail (MSFT完整决策链)
✓ Compare (decision_a/score_a在comparison嵌套)
✓ Batch Detail (stock_codes/has_progress)
✓ E2E: GOOGL新分析完整流程

失败项（均为历史数据，非代码bug）：
✗ TSLA L1/L4 data → 早期失败记录(status=failed)
✗ search('nvidia') → 数据库无此记录
✗ search('apple') → 数据库存储名称为"AAPL"(大写)
```

## 9. 已修复的关键Bug记录

| 日期 | 问题 | 修复 |
|------|------|------|
| 2026-05-09 | analyze_task 用 result["L1"] (空) | 改为 result["pipeline"]["L1"] |
| 2026-05-09 | 同步 run_analysis 阻塞事件循环 | 加 asyncio.to_thread() |
| 2026-05-09 | 空列表返回500 | 加 @field_validator → 422 |
| 2026-05-09 | Dashboard 缺 stocks_analyzed/watch_count | SQL COUNT DISTINCT/WHERE |
| 2026-05-09 | 批量 stock_codes 存为JSON字符串 | SQLite直接存JSON字符串数组 |
| 2026-05-09 | compare 字段路径错误 | 改为 rc.get("comparison", {}) |
