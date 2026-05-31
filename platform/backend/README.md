# 神农股票分析平台 API 文档

版本：2.0.0 | 基础路径：`http://localhost:8000/api`

---

## 认证

无需认证。

---

## 通用说明

- 所有接口返回 JSON
- 错误统一格式：`{"detail": "错误描述"}`
- 批量任务返回 202 Accepted，立即返回 `task_id`，用 `GET /batch/{task_id}` 查询进度

---

## 1. 发起全链路分析

**POST** `/analyze`

发起 L1→L2→L3→L4 全链路分析，支持单只或多只股票。

### 请求体

```json
{
  "stock_codes": ["00700", "AAPL", "600519"],
  "market": "auto",
  "force_refresh": false,
  "priority": 1
}
```

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `stock_codes` | string[] | **必填** | 股票代码列表，支持A股（如600519）、港股（如00700）、美股（如AAPL） |
| `market` | string | `"auto"` | 市场：`CN`/`HK`/`US`/`auto`，auto根据代码自动识别 |
| `force_refresh` | boolean | `false` | `true`=绕过缓存强制全量重分析 |
| `priority` | int | `1` | 优先级：1=手动（高），2=普通，3=定时（低） |

### 响应 202

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "records": {
    "00700": "record-uuid-1",
    "AAPL": "record-uuid-2",
    "600519": "record-uuid-3"
  }
}
```

> 拿到 `task_id` 后用 `GET /batch/{task_id}` 查询进度，拿到 `record_id` 后用 `GET /result/{id}` 查询结果。

---

## 2. 查询分析结果详情

**GET** `/result/{id}`

获取单次分析的完整结果（含L1/L2/L3/L4全部数据）。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | string | 分析记录ID，即 `analyze` 接口返回的 `records[stock_code]` |

### 响应 200

```json
{
  "id": "record-uuid",
  "task_id": "batch-uuid",
  "stock_code": "00700",
  "stock_name": "腾讯控股",
  "market": "HK",
  "status": "COMPLETED",
  "step": "L4",
  "final_decision": "BUY",
  "score": {
    "value_score": 82,
    "growth_score": 75,
    "technical_score": 68,
    "sentiment_score": 70,
    "comprehensive_score": 74.0
  },
  "judge_score": 72.5,
  "l1_data": { ... },
  "l2_data": { ... },
  "l3_data": { ... },
  "l4_data": { ... },
  "error_message": null,
  "created_at": "2026-05-10T08:00:00Z",
  "updated_at": "2026-05-10T08:05:00Z"
}
```

### 状态值说明

| status | 说明 |
|--------|------|
| `PENDING` | 排队中 |
| `RUNNING` | 分析中 |
| `COMPLETED` | 完成 |
| `FAILED` | 失败 |

### 决策值说明

| decision | 说明 |
|----------|------|
| `BUY` | 建议买入 |
| `WATCH` | 建议观望 |
| `SELL` | 建议卖出 |
| `NO` | 无明确信号 |

---

## 3. 批量分析进度

**GET** `/batch/{task_id}`

查询批量分析的进度和状态。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | `analyze` 接口返回的 `task_id` |

### 响应 200

```json
{
  "task_id": "batch-uuid",
  "total": 5,
  "pending": 0,
  "running": 1,
  "completed": 3,
  "failed": 1,
  "progress": 80,
  "records": [
    {
      "id": "record-uuid-1",
      "stock_code": "00700",
      "status": "COMPLETED",
      "final_decision": "BUY",
      "error_message": null
    },
    {
      "id": "record-uuid-2",
      "stock_code": "AAPL",
      "status": "RUNNING",
      "final_decision": null,
      "error_message": null
    }
  ]
}
```

---

## 4. 历史分析记录

**GET** `/records`

查询分析记录列表，支持按股票代码筛选。

### 查询参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `stock_code` | string | 可选 | 过滤特定股票 |
| `status` | string | 可选 | 过滤状态 |
| `limit` | int | `20` | 返回条数上限 |
| `offset` | int | `0` | 偏移量 |

### 响应 200

```json
{
  "total": 42,
  "records": [
    {
      "id": "record-uuid",
      "stock_code": "00700",
      "stock_name": "腾讯控股",
      "market": "HK",
      "status": "COMPLETED",
      "final_decision": "BUY",
      "judge_score": 72.5,
      "created_at": "2026-05-10T08:00:00Z"
    }
  ]
}
```

---

## 5. 股票列表

**GET** `/stocks`

获取所有已分析过的股票列表。

### 响应 200

```json
[
  {
    "stock_code": "00700",
    "stock_name": "腾讯控股",
    "market": "HK",
    "analysis_count": 5,
    "last_analysis_date": "2026-05-10T08:00:00Z",
    "latest_result_id": "record-uuid",
    "latest_decision": "BUY"
  }
]
```

---

## 6. 股票搜索

**GET** `/stocks/search?q={keyword}`

按代码或名称模糊搜索股票。

### 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `q` | string | **必填** 搜索关键词 |

### 响应 200

```json
[
  {
    "stock_code": "00700",
    "stock_name": "腾讯控股",
    "market": "HK",
    "analysis_count": 5,
    "last_analysis_date": "2026-05-10T08:00:00Z"
  }
]
```

---

## 7. 股票详情

**GET** `/stocks/{stock_code}`

获取特定股票的详情（含最新分析结果）。

### 响应 200

```json
{
  "stock_code": "00700",
  "stock_name": "腾讯控股",
  "market": "HK",
  "analysis_count": 5,
  "last_analysis_date": "2026-05-10T08:00:00Z",
  "latest_result_id": "record-uuid",
  "latest_decision": "BUY"
}
```

### 错误 404

```json
{
  "detail": "Stock not found"
}
```

---

## 8. 仪表盘

**GET** `/dashboard`

获取平台概览统计。

### 响应 200

```json
{
  "total_records": 42,
  "total_stocks": 15,
  "status_breakdown": {
    "COMPLETED": 35,
    "RUNNING": 2,
    "PENDING": 3,
    "FAILED": 2
  },
  "decision_breakdown": {
    "BUY": 10,
    "WATCH": 15,
    "SELL": 2,
    "NO": 8
  },
  "recent_records": [...]
}
```

---

## 9. 队列状态

**GET** `/queue/stats`

查看 WorkerPool 队列实时状态。

### 响应 200

```json
{
  "pending_count": 3,
  "running_count": 2,
  "worker_count": 3,
  "cache_hits_24h": 15
}
```

---

## 10. L1 快速筛选

**GET** `/l1/{stock_code}`

单独获取 L1 筛选层数据（不触发全链路）。

### 响应 200

```json
{
  "stock_code": "00700",
  "stock_name": "腾讯控股",
  "market": "HK",
  "candidates": [...],
  "timestamp": "2026-05-10T08:00:00Z"
}
```

---

## 11. 健康检查

**GET** `/health`

服务健康检查。

### 响应 200

```json
{
  "status": "healthy",
  "service": "shennong-platform",
  "version": "2.0.0"
}
```

---

## 错误码汇总

| HTTP Status | 场景 |
|-------------|------|
| 200 | 成功 |
| 202 | 请求接受（异步任务已创建） |
| 400 | 参数错误（如 stock_codes 为空） |
| 404 | 资源不存在（如股票/记录未找到） |
| 500 | 服务器内部错误 |

---

## 数据字段说明

### AnalysisRecord 完整字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 记录唯一ID |
| `task_id` | UUID | 批次ID，同批任务共享 |
| `stock_code` | string | 股票代码 |
| `stock_name` | string | 股票名称 |
| `market` | enum | `CN`/`HK`/`US` |
| `status` | enum | `PENDING`/`RUNNING`/`COMPLETED`/`FAILED` |
| `step` | enum | 当前阶段 `L1`/`L2`/`L3`/`L4` |
| `final_decision` | enum | `BUY`/`WATCH`/`SELL`/`NO` |
| `score` | JSON | 五维评分 |
| `judge_score` | float | 综合裁判评分 |
| `l1_data` | JSON | L1 原始数据 |
| `l2_data` | JSON | L2 原始数据 |
| `l3_data` | JSON | L3 原始数据 |
| `l4_data` | JSON | L4 原始数据 |
| `error_message` | string | 错误信息（如有） |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

---

*最后更新：2026-05-10*
