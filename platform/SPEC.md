# 神农股票分析平台 — 功能规格文档 (SPEC.md)

> 版本: 3.0.0
> 日期: 2026-05-10
> 状态: 已确认
> 架构: L1/L2解耦 + SQLite单表(analysis_records) + 任务队列 + Worker Pool

---

## 1. 系统架构

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端 (React SPA)                          │
│                    http://localhost:8000/                         │
│                                                                   │
│   /               → Dashboard (全局概览)                          │
│   /analyze        → 股票搜索 + 发起分析                          │
│   /l1             → L1 筛选（独立执行，快速返回）                 │
│   /result/:id     → 单次分析结果详情 (L1→L2→L3→L4)                │
│   /history/:code  → 单只股票历史分析记录                          │
│   /compare/:code  → 两次分析对比                                  │
│   /batch          → 批量任务列表                                 │
│   /batch/:id      → 批量任务详情                                 │
│   /stocks         → 股票库                                       │
│   /portfolio      → 持仓管理                                     │
│   /watchlist      → 关注列表                                     │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP REST API (JSON)
┌────────────────────────────▼────────────────────────────────────┐
│                       后端 (FastAPI)                              │
│                  http://localhost:8000/api/                       │
│                                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ l1_analyze│  │ analyze  │  │  batch   │  │  stocks  │        │
│  │ (L1 only) │  │(L1→L4全链)│  │          │  │          │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │portfolio │  │reflection│  │  queue   │  │  result  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┴───────────────────┐
         │                                       │
┌────────▼────────┐                   ┌──────────▼──────────┐
│  L1 同步层       │                   │  L2-L4 异步层       │
│  (FastAPI       │                   │  (BackgroundTasks   │
│   Background    │                   │   + WorkerPool)     │
│   Tasks)        │                   │                     │
└─────────────────┘                   └─────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              神农分析引擎 (shennong.py)                            │
│            ~/.hermes/investment/main/shennong.py                  │
│                                                                   │
│   L1 → 个股筛选（技术面 + 趋势方向）  [同步, 24h缓存]              │
│   L2 → 资金流分析（主力资金 + 机构资金流向）                        │
│   Veto → 硬过滤（市值/流动性/停牌等）                              │
│   L3 → 基本面综合评分（财务指标 + 估值 + 成长性）                  │
│   L4 → 投资决策 + 概率化方案输出                                  │
│                                                                   │
│   市场支持: CN (沪深) / HK (港股) / US (美股)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│              SQLite 数据库 (platform.db)                          │
│      ~/.hermes/investment/platform/backend/platform.db           │
│                                                                   │
│   analysis_records (单表)  ·  stock_profiles                      │
│   reflections             ·  portfolios  ·  watchlists          │
└───────────────────────────────────────────────────────────────────┘
```

### 1.2 核心架构设计：L1/L2 解耦

**设计原则**：
- **L1 独立**：L1 筛选可单独调用，快速返回候选股票列表（~秒级）
- **L2-L4 异步**：数据采集、财务分析、投资决策通过 Worker Pool 异步执行
- **缓存穿透控制**：L1 结果 24h 缓存，`force_refresh` 参数强制刷新

**两条执行路径**：

| 路径 | 端点 | 执行层 | 缓存策略 | 返回时间 |
|------|------|--------|----------|----------|
| L1 专线 | `POST /api/l1/analyze` | L1 only | 24h 缓存 | ~1-3s |
| 全链路 | `POST /api/analyze` | L1→L2→L3→L4 | force_refresh | ~30-120s |

### 1.3 技术栈

| 层级 | 技术 |
|------|------|
| 前端框架 | React 18 + TypeScript + Vite |
| UI 组件 | shadcn/ui + Tailwind CSS |
| 图表库 | Recharts |
| 状态管理 | React Router (SPA) |
| 后端框架 | FastAPI + Uvicorn |
| ORM | SQLAlchemy (Async) |
| 数据库 | SQLite (aiosqlite) |
| 任务队列 | SQLite `analysis_records` 表 + WorkerPool |
| 分析引擎 | 神农系统 (shennong.py) |
| Python 环境 | ~/.hermes/hermes-agent/venv/bin/python |

### 1.4 异步执行模型

```
请求进来
    │
    ▼
┌──────────────────────────────────────┐
│  FastAPI Endpoint                    │
│  POST /api/analyze                   │
│  - 创建 AnalysisRecord (每只股票)     │
│  - 立即返回 task_id + record_ids     │
└──────────────────────────────────────┘
    │
    ▼ (BackgroundTasks.add_task)
┌──────────────────────────────────────┐
│  L1_analyze_task / analyze_task      │
│  - asyncio.to_thread(do_l1)          │
│  - 更新 AnalysisRecord.l1_data        │
│  - 如果 L1 无候选 → FAILED           │
└──────────────────────────────────────┘
    │ (WorkerPool enqueue_from_db)
    ▼
┌──────────────────────────────────────┐
│  WorkerPool (ThreadPoolExecutor)     │
│  - L2→L3→L4 并行执行                 │
│  - 更新 l2_data/l3_data/l4_data     │
│  - 更新 final_decision               │
└──────────────────────────────────────┘
```

---

## 2. 数据库 Schema

> 数据库文件: `~/.hermes/investment/platform/backend/platform.db`
> SQLite + aiosqlite，所有表通过 SQLAlchemy AsyncSession 操作

### 2.1 ER 图

```
analysis_records ─────┐
   (主分析单表)         ├── task_id ──→ 同一批次任务分组
   (L1/L2/L3/L4 JSON) │    (替代原有的 batch_id + tasks 两表)
                       │
stock_profiles ───────┘
   (股票库索引)

reflections ──────────→ analysis_records (analysis_id)
   (反思记录)

portfolios ──────────── (独立持仓表)
watchlists ──────────── (独立关注表)
```

### 2.2 表结构

#### `analysis_records` — 分析记录（核心单表）

单表架构：所有任务和结果存储在同一张表中，通过以下字段区分和管理：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK, UUID | 主键 |
| stock_code | VARCHAR | INDEX | 股票代码，如 "00700"、"AAPL" |
| stock_name | VARCHAR | NULL | 股票名称 |
| market | ENUM | DEFAULT CN | CN / HK / US |
| task_id | VARCHAR(36) | INDEX, NULL | 批次号，同批任务共享 |
| step | ENUM | DEFAULT L1 | L1 / L2 / veto / L3 / L4 |
| parent_record_id | VARCHAR(36) | NULL | 血缘链父记录 |
| priority | INT | DEFAULT 3, INDEX | 1=人工(高) / 3=定时(普通) |
| cache_key | VARCHAR | NULL | 缓存唯一标识 |
| cached_at | DATETIME | NULL | 缓存时间（24h过期） |
| force_refresh | INT | DEFAULT 0 | 0=否, 1=是 |
| timestamp | DATETIME | DEFAULT NOW, INDEX | 分析时间 |
| status | ENUM | DEFAULT pending | pending / running / completed / failed / cancelled |
| l1_data | TEXT (JSON) | NULL | L1 筛选结果 |
| l2_data | TEXT (JSON) | NULL | L2 资金流结果 |
| l3_data | TEXT (JSON) | NULL | L3 基本面评分 |
| l4_data | TEXT (JSON) | NULL | L4 投资决策 |
| final_decision | ENUM | NULL | BUY / SELL / WATCH / NO |
| score | TEXT (JSON) | NULL | 五维评分对象 |
| judge_score | FLOAT | NULL | L4 裁判评分 |
| error_message | TEXT | NULL | 错误信息 |
| retry_count | INT | DEFAULT 0 | 重试次数 |
| analysis_count | INT | DEFAULT 0 | 该股票累计分析次数 |
| last_analysis_date | DATETIME | NULL | 最近分析时间 |

#### `stock_profiles` — 股票库索引

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| stock_code | VARCHAR | PK | 主键，股票代码 |
| stock_name | VARCHAR | NULL | 股票名称 |
| market | ENUM | DEFAULT CN | 市场 |
| analysis_count | INT | DEFAULT 0 | 分析次数 |
| last_analysis_date | DATETIME | NULL | 最近分析时间 |
| latest_record_id | VARCHAR(36) | NULL | 最近分析记录 ID |
| latest_decision | ENUM | NULL | 最近决策 |

#### `reflections` — 反思记录

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK, UUID | 主键 |
| created_at | DATETIME | DEFAULT NOW | 创建时间 |
| analysis_id | VARCHAR(36) | NOT NULL | 关联的分析记录 ID |
| wrong_analysis | VARCHAR(1) | NOT NULL | 'A' 或 'B'，哪一次分析错了 |
| reflection_text | TEXT | NOT NULL | 反思内容 |
| error_tags | TEXT (JSON) | NULL | 错误标签数组 |
| correct_analysis_id | VARCHAR(36) | NULL | 正确的分析记录 ID |

#### `portfolios` — 持仓管理

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK, UUID | 主键 |
| stock_code | VARCHAR | INDEX | 股票代码 |
| stock_name | VARCHAR | NULL | 股票名称 |
| market | ENUM | DEFAULT CN | 市场 |
| position_type | ENUM | DEFAULT LONG | LONG / SHORT |
| quantity | FLOAT | DEFAULT 0 | 持仓数量 |
| avg_cost | FLOAT | DEFAULT 0.0 | 平均成本 |
| current_price | FLOAT | NULL | 当前价格 |
| notes | TEXT | NULL | 备注 |
| created_at | DATETIME | DEFAULT NOW | 创建时间 |
| updated_at | DATETIME | AUTO | 更新时间 |

#### `watchlists` — 关注列表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK, UUID | 主键 |
| stock_code | VARCHAR | INDEX | 股票代码 |
| stock_name | VARCHAR | NULL | 股票名称 |
| market | ENUM | DEFAULT CN | 市场 |
| reason | TEXT | NULL | 加入理由 |
| target_price | FLOAT | NULL | 目标价格 |
| added_at | DATETIME | DEFAULT NOW | 加入时间 |
| updated_at | DATETIME | AUTO | 更新时间 |

---

## 3. API 设计

> Base URL: `http://localhost:8000/api`
> 所有响应 Content-Type: `application/json`

### 3.1 L1 专线（独立 L1 筛选）

#### `POST /api/l1/analyze` — L1 筛选（快速，24h 缓存）

**Request Body:**
```json
{
  "stock_codes": ["00700", "AAPL", "TSLA"],
  "market": "auto"
}
```

**Response (202 Accepted):**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "records": {
    "00700": "660e8400-e29b-41d4-a716-446655440001",
    "AAPL":  "660e8400-e29b-41d4-a716-446655440002",
    "TSLA":  "660e8400-e29b-41d4-a716-446655440003"
  }
}
```

- **只执行 L1**：不运行 L2/L3/L4
- **24h 缓存**：相同 stock_code + market 在 24h 内不重复执行
- **快速返回**：~1-3s
- `force_refresh=true` 时绕过缓存强制刷新

---

### 3.2 全链路分析（L1→L2→L3→L4）

#### `POST /api/analyze` — 全链路分析（异步执行）

**Request Body:**
```json
{
  "stock_codes": ["00700", "AAPL", "TSLA"],
  "market": "auto",
  "force_refresh": false
}
```

**Response (202 Accepted):**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "records": {
    "00700": "660e8400-e29b-41d4-a716-446655440001",
    "AAPL":  "660e8400-e29b-41d4-a716-446655440002",
    "TSLA":  "660e8400-e29b-41d4-a716-446655440003"
  }
}
```

- **L1 同步**：BackgroundTasks 立即触发 `l1_analyze_task`
- **L2-L4 异步**：L1 完成后，WorkerPool 拉取任务并行执行 L2→L3→L4
- **返回 202**：响应立即返回，完整结果需轮询 `/api/result/{id}`

---

### 3.3 分析结果

#### `GET /api/result/{result_id}` — 获取单次分析结果

**Response (200 OK):**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "stock_code": "00700",
  "stock_name": "腾讯控股",
  "market": "HK",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "step": "L4",
  "timestamp": "2026-05-09T11:04:14",
  "status": "completed",
  "final_decision": "WATCH",
  "score": {
    "total": 68.5,
    "L1": 72,
    "L2": 65,
    "L3": 70,
    "L4": 67
  },
  "l1_data": { "trend": "up", "filters_passed": [...], "stock_name": "腾讯控股" },
  "l2_data": { "money_flow": "inflow", "institutional": {...} },
  "l3_data": { "financial_score": 75, "valuation": {...}, "growth": {...} },
  "l4_data": { "decisions": [{"decision": "WATCH", "probability": 0.72, ...}], "five_scores": {...} },
  "judge_score": 68.5,
  "cached_at": "2026-05-09T11:04:14",
  "force_refresh": false
}
```

- `status=pending/running` 时 l1_data-l4_data 字段为 `null`
- `status=completed` 时包含完整 L1-L4 数据
- `status=failed` 时仅有 error_message 填充

---

#### `GET /api/history/{stock_code}` — 历史分析记录

**Response (200 OK):**
```json
[
  { "id": "...", "timestamp": "2026-05-09T11:04:14", "status": "completed",
    "final_decision": "WATCH", "score": {"total": 68.5}, "l1_data": {...}, ... },
  { "id": "...", "timestamp": "2026-05-08T10:00:00", "status": "completed",
    "final_decision": "BUY", "score": {"total": 72.1}, "l1_data": {...}, ... }
]
```
- 按时间倒序返回

---

#### `GET /api/compare/{stock_code}?ids={id1},{id2}` — 两次分析对比

**Response (200 OK):**
```json
{
  "stock_code": "00700",
  "analysis_a": { ...完整记录A... },
  "analysis_b": { ...完整记录B... },
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
- 必须提供恰好 2 个 ID，否则 400
- ID 对应记录必须同属该股票代码

---

### 3.4 批量任务

#### `GET /api/batches` — 批量任务列表

**Response (200 OK):**
```json
[
  {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "total_count": 2,
    "completed_count": 1,
    "failed_count": 1,
    "pending_count": 0,
    "cancelled_count": 0,
    "buy_count": 0,
    "watch_count": 1,
    "progress": 0.5
  }
]
```

---

#### `GET /api/batch/{task_id}` — 批量任务详情

**Response (200 OK):**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "total_count": 2,
  "completed_count": 1,
  "failed_count": 1,
  "pending_count": 0,
  "records": [
    { "id": "...", "stock_code": "00700", "status": "completed", ... },
    { "id": "...", "stock_code": "AAPL", "status": "failed", ... }
  ]
}
```

---

#### `POST /api/batch/{task_id}/retry` — 重试失败任务

**Response (200 OK):**
```json
{
  "message": "Retrying failed analyses",
  "count": 1
}
```

---

#### `DELETE /api/batch/{task_id}` — 删除/取消批量任务

**Response (200 OK):**
```json
{
  "message": "Batch cancelled",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "cancelled_count": 5
}
```

---

### 3.5 任务队列

#### `GET /api/queue` — 查看队列状态

**Query Parameters:**
- `status`: pending / running / completed / failed / cancelled（可选）
- `stock_code`: 过滤股票代码（可选）
- `priority`: 1=人工(高) / 3=定时(普通)（可选）
- `task_id`: 过滤批次号（可选）
- `step`: L1 / L2 / veto / L3 / L4（可选）
- `limit`: 1-200，默认 50
- `offset`: 默认 0

**Response (200 OK):**
```json
{
  "total": 19,
  "offset": 0,
  "limit": 50,
  "items": [
    { "id": "...", "stock_code": "00700", "task_id": "...", "step": "L2", "status": "pending", "priority": 3, ... }
  ]
}
```

---

#### `DELETE /api/queue/{record_id}` — 取消待处理任务

- 仅 `status=pending` 的任务可取消
- 已 running 的任务不可取消

---

#### `DELETE /api/queue/batch/{task_id}` — 取消整批任务

- 取消 task_id 下所有 `status=pending` 的记录

---

### 3.6 股票库

#### `GET /api/stocks` — 所有分析过的股票

**Response (200 OK):**
```json
[
  {
    "stock_code": "00700",
    "stock_name": "腾讯控股",
    "market": "HK",
    "analysis_count": 3,
    "last_analysis_date": "2026-05-09T11:04:14",
    "latest_decision": "WATCH"
  }
]
```

---

#### `GET /api/stocks/search?q={keyword}` — 搜索股票

- 支持中文股票名称搜索
- 支持代码搜索（大写）

---

#### `GET /api/stocks/{code}` — 股票详情

**Response (200 OK):**
```json
{
  "stock_code": "00700",
  "stock_name": "腾讯控股",
  "market": "HK",
  "analysis_count": 3,
  "last_analysis_date": "2026-05-09T11:04:14",
  "latest_record_id": "...",
  "latest_decision": "WATCH"
}
```

---

### 3.7 仪表盘

#### `GET /api/dashboard/stats` — 仪表盘统计

**Response (200 OK):**
```json
{
  "total_analyses": 19,
  "stocks_analyzed": 10,
  "watch_count": 6,
  "buy_count": 0,
  "recent_analyses": [
    {
      "stock_code": "AAPL",
      "stock_name": "Apple Inc.",
      "timestamp": "2026-05-09T...",
      "final_decision": "WATCH"
    }
  ]
}
```

---

### 3.8 反思系统

#### `POST /api/reflection` — 写入反思

**Request Body:**
```json
{
  "analysis_id": "uuid",
  "wrong_analysis": "A",
  "reflection_text": "低估了L2资金流流出的影响",
  "error_tags": ["L2误判", "资金流"],
  "correct_analysis_id": "uuid"
}
```

---

#### `GET /api/reflections/{stock_code}` — 反思记录

**Response (200 OK):**
```json
[
  {
    "id": "uuid",
    "analysis_id": "...",
    "wrong_analysis": "A",
    "reflection_text": "...",
    "error_tags": ["L2误判"],
    "created_at": "2026-05-10T..."
  }
]
```

---

### 3.9 持仓管理

#### `GET /api/portfolio` — 获取所有持仓

#### `POST /api/portfolio` — 创建持仓

#### `PUT /api/portfolio/{id}` — 更新持仓

#### `DELETE /api/portfolio/{id}` — 删除持仓

---

### 3.10 关注列表

#### `GET /api/watchlist` — 获取关注列表

#### `POST /api/watchlist` — 添加关注

#### `PUT /api/watchlist/{id}` — 更新关注

#### `DELETE /api/watchlist/{id}` — 删除关注

---

## 4. Worker Pool 架构

### 4.1 设计原理（单表架构）

基于 `shennong.py` 的 `_run_batch` 和 `run_pipeline` 逻辑：

```
┌─────────────────────────────────────────────────────┐
│  WorkerPool (ThreadPoolExecutor)                    │
│  max_workers=3, batch_size=50                       │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │ Queue Monitor Loop (后台线程)                 │  │
│  │ - 每 30s 检查 analysis_records 表             │  │
│  │ - enqueue_from_db() 拉取 PENDING 记录        │  │
│  │ - process_batch() 并行处理                    │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌────────┐ ┌────────┐ ┌────────┐                  │
│  │Worker 1│ │Worker 2│ │Worker 3│                  │
│  │ L2→L3→L4│ │ L2→L3→L4│ │ L2→L3→L4│                  │
│  └────────┘ └────────┘ └────────┘                  │
└─────────────────────────────────────────────────────┘
```

### 4.2 执行流程

1. **入队**：API 收到 `POST /api/analyze`，创建 `AnalysisRecord` 记录（status=PENDING, task_id=批次号）
2. **拉取**：Queue Monitor 定时从 `analysis_records` 表拉取 PENDING 记录（按 priority ASC）
3. **标记**：WorkerPool 将记录 status 改为 RUNNING
4. **执行**：`process_batch()` 用 ThreadPoolExecutor 并行执行 L2→L3→L4
5. **回调**：每个 worker 完成后更新 `l2_data/l3_data/l4_data`

### 4.3 L1 结果缓存（24h）

- L1 筛选结果以 `cached_at` 字段判断是否在 24h 内
- `force_refresh=True` 强制重新执行 L1
- 缓存路径：`~/.hermes/investment/main/records/{date}/`

---

## 5. L1/L2 数据流

```
POST /api/l1/analyze
        │
        ▼
┌─────────────────────────────────────┐
│ l1_analyze_task (BackgroundTask)   │
│                                     │
│  1. 检查缓存 (24h)                  │
│     └─ 命中 → 直接返回 l1_data      │
│                                     │
│  2. 执行 L1 (asyncio.to_thread)     │
│     └─ shennong.run_pipeline(mode=L1)│
│                                     │
│  3. 缓存 L1 结果                    │
│                                     │
│  4. 更新 AnalysisRecord.l1_data     │
└─────────────────────────────────────┘
        │
        ▼ (force_refresh || 无缓存)
┌─────────────────────────────────────┐
│ WorkerPool (L2→L3→L4 异步)         │
│                                     │
│  1. enqueue_from_db()              │
│  2. process_batch()                │
│  3. _process_single()              │
│     └─ shennong.run_pipeline(full)  │
│  4. 更新 l2_data/l3_data/l4_data   │
└─────────────────────────────────────┘
```

---

## 6. 错误处理

### 6.1 任务状态流转

```
PENDING → RUNNING → COMPLETED
                    ↘ FAILED
         ↘ CANCELLED
```

### 6.2 重试机制

- `retry_count` 字段记录重试次数
- `POST /api/batch/{task_id}/retry` 重置 failed 记录为 PENDING
- WorkerPool 重新拉取执行

### 6.3 超时控制

- 单股票 L1 超时：120s
- 单股票全链路超时：180s
- Batch 等待超时：300s

---

## 7. 文件结构

```
~/.hermes/investment/platform/
├── SPEC.md                          ← 本文档
├── backend/
│   ├── main.py                      ← FastAPI 入口
│   ├── database.py                  ← SQLAlchemy AsyncSession
│   ├── models.py                    ← AnalysisRecord + 4辅助表
│   ├── worker_pool.py               ← WorkerPool 实现
│   ├── shennong_client.py           ← shennong.py 封装
│   └── routers/
│       ├── analyze.py               ← POST /api/analyze
│       ├── l1.py                    ← POST /api/l1/analyze
│       ├── batch.py                 ← Batch 管理
│       ├── queue.py                 ← 队列查看/取消
│       ├── result.py                ← 结果查询
│       ├── stocks.py                ← 股票库
│       ├── reflection.py            ← 反思系统
│       └── portfolio.py             ← 持仓管理
└── frontend/
    └── dist/                        ← React SPA 构建产物
```

---

## 8. 关键枚举定义

### Status (分析记录状态)
```
pending   → 等待执行
running   → 执行中
completed → 已完成（有结果）
failed    → 执行失败
cancelled → 已取消
```

### Priority (任务优先级)
```
1 = MANUAL    → 人工触发（高优先级）
3 = SCHEDULED → 定时调度（普通优先级）
```

### Step (分析阶段)
```
L1   → 筛选层
L2   → 资金流层
veto → 硬过滤层
L3   → 基本面层
L4   → 决策层
```

### Decision (最终决策)
```
BUY   → 买入
SELL  → 卖出
WATCH → 观察
NO    → 无决策（被否决）
```
