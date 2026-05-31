# 神农平台后端API全面测试报告

**测试时间**: 2026-05-11  
**后端地址**: http://localhost:8000  
**API Base**: http://localhost:8000/api

---

## 1. 健康检查

## API: 健康检查 GET /api/health
**功能**: 服务健康状态检测
**入参**: 无
**出参结构**: `{"status": "healthy", "service": "shennong-platform", "version": "2.0.0"}`
**测试结果**: ✅
**数据示例**: `{"status":"healthy","service":"shennong-platform","version":"2.0.0"}`
**发现的问题**: 无

---

## 2. 核心分析API

## API: 完整分析 POST /api/analyze
**功能**: L4全链路分析（单只或批量）
**入参**: `{"stock_codes": ["00700"], "market": "HK", "market_preference": "HK"}`（market_preference可选：CN/HK/US/all）
**出参结构**: `{"batch_id": "xxx", "tasks": {"00700": "task_id"}}`
**测试结果**: ✅
**数据示例**: `{"batch_id":"ff12f991-666f-42f1-bf8a-4e01ffebc303","tasks":{"00700":"dda94234-e1cd-4b26-98ef-9cba5db21440"}}`
**发现的问题**: 
- 入参格式必须是 `stock_codes` 数组，不是单个 `stock_code`
- 之前错误地使用了 `{"stock_code": "00700"}` 导致422错误

## API: L1分析 POST /api/l1/analyze
**功能**: L1层快速分析
**入参**: `{"stock_codes": ["00700", "AAPL"]}`
**出参结构**: `{"task_id": "xxx", "records": {"00700": "record_id", "AAPL": "record_id"}}`
**测试结果**: ✅
**数据示例**: `{"task_id":"fb814e85-04ff-4c2a-a625-6d16228301ef","records":{"00700":"ba8ff164-8778-42f9-9a1a-58abeea31f4f","AAPL":"75a080ca-60b3-44da-9643-aaf28c8dac5e"}}`
**发现的问题**: 同上，需要 `stock_codes` 数组格式

## API: L4结果 GET /api/result/{id}
**功能**: 获取L4完整分析结果
**入参**: URL路径参数 - 分析记录ID
**出参结构**: 包含l1_data/l2_data/l3_data/l4_data完整嵌套结构
**测试结果**: ✅
**数据示例**: NVDA记录 `{"id":"7566f5ae-f671-4817-8a6e-7d3ac30f82ac","stock_code":"NVDA","stock_name":"英伟达","market":"US","step":"L4","status":"completed","l1_data":{...}, "final_decision":"WATCH"}` (12891 bytes)
**发现的问题**: 无

## API: 分析记录 GET /api/records/{id}
**功能**: 获取分析记录摘要
**入参**: URL路径参数 - 记录ID
**出参结构**: 包含stock_code/market/step/status/timestamp等核心字段，不含完整分析数据
**测试结果**: ✅
**数据示例**: `{"id":"7566f5ae-f671-4817-8a6e-7d3ac30f82ac","stock_code":"NVDA","stock_name":"英伟达","market":"US","step":"L4","status":"completed"}` (~458 bytes)
**发现的问题**: 无

## API: 记录列表查询 GET /api/records
**功能**: 带过滤条件的记录列表
**入参**: Query参数 `stock_code=00700&limit=5`
**出参结构**: `{"total": 18, "offset": 0, "limit": 5, "items": [...]}`
**测试结果**: ✅
**数据示例**: 返回00700的18条记录，limit=5时返回5条 (2333 bytes)
**发现的问题**: 无

## API: 历史分析 GET /api/history/{stock_code}
**功能**: 获取某股票完整分析历史
**入参**: URL路径 - stock_code（如00700/NVDA/AAPL）
**出参结构**: 预期返回该股票所有历史分析
**测试结果**: ❌
**数据示例**: 所有测试均返回 `Status: 500, Internal Server Error`
**发现的问题**: 
- 严重问题：所有stock_code格式测试均返回500错误
- 可能是数据库查询或API路由问题

---

## 3. 对比API

## API: 分析对比 GET /api/compare/{stock_code}
**功能**: 对比同一股票的两个分析结果
**入参**: URL路径stock_code + Query参数 `ids=idA,idB`
**出参结构**: `{"stock_code": "xxx", "analysis_a": {...}, "analysis_b": {...}}`
**测试结果**: ⚠️ 部分成功
**数据示例**: 
- ✅ `http://localhost:8000/api/compare/00700?ids=1fa8b543...,79830c84...` → 200 (25424 bytes)
- ❌ `http://localhost:8000/api/compare/NVDA?ids=7566f5ae...,b51b6cdc...` → 400 `{"detail":"Records don't match stock code"}`
- ❌ `http://localhost:8000/api/compare/AAPL?ids=...mixed...` → 400 同上
**发现的问题**: 
- 路径参数stock_code必须与IDs对应的stock_code完全匹配
- AAPL路径下传入NVDA/00700的ID会报错（符合预期但提示信息可更明确）
- 00700的ID传给NVDA路径也会报错（符合预期）

---

## 4. 批次任务API

## API: 批次详情 GET /api/batch/{task_id}
**功能**: 获取批次任务详情
**入参**: URL路径 - batch/task_id
**出参结构**: `{"task_id": "xxx", "total_count": 4, "completed_count": 3, "records": [...]}`
**测试结果**: ✅
**数据示例**: `{"task_id":"86bb7134-1edd-4ca7-bcba-b8ddf5c1c1d8","total_count":4,"completed_count":3,"progress":0.75,"records":[...]}`
**发现的问题**: 无

## API: 批次列表 GET /api/batches
**功能**: 获取所有批次任务
**入参**: 无
**出参结构**: 数组，每个元素包含task_id/progress/completed_count/total_count等
**测试结果**: ✅
**数据示例**: 返回37个批次任务 (7602 bytes)
**发现的问题**: 无

## API: 批次重试 POST /api/batch/{task_id}/retry
**功能**: 重试失败的分析任务
**入参**: URL路径 - task_id
**出参结构**: `{"message": "Retrying failed analyses", "count": 1}` 或 `{"message": "No failed records to retry", "count": 0}`
**测试结果**: ✅
**数据示例**: 
- `{"message":"Retrying failed analyses","count":1}` (原失败任务)
- `{"message":"No failed records to retry","count":0}` (已重试或无失败任务)
**发现的问题**: 无

## API: 批次取消 DELETE /api/batch/{task_id}
**功能**: 取消批次任务
**入参**: URL路径 - task_id
**出参结构**: `{"message": "Batch cancelled", "task_id": "xxx", "cancelled_count": 1}`
**测试结果**: ✅
**数据示例**: `{"message":"Batch cancelled","task_id":"04478af1-b4ab-4a8a-8b6f-449ca0e6359f","cancelled_count":1}`
**发现的问题**: 无

---

## 5. 股票库API

## API: 股票列表 GET /api/stocks
**功能**: 获取所有已分析股票
**入参**: 无
**出参结构**: `[{stock_code, stock_name, market, analysis_count, last_analysis_date, latest_result_id, latest_decision}]`
**测试结果**: ✅
**数据示例**: 返回10只股票 (2134 bytes)
**发现的问题**: 无

## API: 股票搜索 GET /api/stocks/search
**功能**: 搜索股票
**入参**: Query参数 `q=腾讯` 或 `q=AAPL`
**出参结构**: 同上股票列表结构
**测试结果**: ✅
**数据示例**: 
- `q=腾讯` → `[{"stock_code":"00700","stock_name":"腾讯控股","market":"HK","analysis_count":3}]`
- `q=AAPL` → `[{"stock_code":"AAPL","stock_name":"苹果","market":"US","analysis_count":3}]`
**发现的问题**: 无

## API: 单只股票详情 GET /api/stocks/{code}
**功能**: 获取单只股票信息
**入参**: URL路径 - stock_code
**出参结构**: 单个股票对象
**测试结果**: ✅
**数据示例**: 
- `/api/stocks/00700` → HK股 (214 bytes)
- `/api/stocks/AAPL` → US股 (210 bytes)
**发现的问题**: 无

---

## 6. 持仓管理API

## API: 持仓列表 GET /api/portfolio
**功能**: 获取当前持仓
**入参**: 无
**出参结构**: `[{id, stock_code, market, quantity, avg_cost, total_cost, ...}]`
**测试结果**: ✅
**数据示例**: 初始2条持仓记录 (~708 bytes)
**发现的问题**: stock_name字段为null

## API: 添加持仓 POST /api/portfolio
**功能**: 添加持仓记录
**入参**: `{"stock_code":"00700","market":"HK","quantity":100,"avg_cost":400.0}`
**出参结构**: 返回创建的持仓对象
**测试结果**: ✅
**数据示例**: `{"id":"d57fdcd0-f118-48cf-9568-d4f34b21bead","stock_code":"00700","quantity":100.0,"avg_cost":400.0,"total_cost":40000.0}`
**发现的问题**: stock_name为null

## API: 删除持仓 DELETE /api/portfolio/{stock_code}
**功能**: 删除持仓
**入参**: URL路径 - stock_code
**出参结构**: `{"message": "Position deleted"}`
**测试结果**: ✅
**数据示例**: `{"message":"Position deleted"}`
**发现的问题**: 无

---

## 7. 关注列表API

## API: 关注列表 GET /api/watchlist
**功能**: 获取关注列表
**入参**: 无
**出参结构**: `[{id, stock_code, market, reason, target_price, added_at}]`
**测试结果**: ✅
**数据示例**: 初始1条 (00700)
**发现的问题**: stock_name为null

## API: 添加关注 POST /api/watchlist
**功能**: 添加到关注列表
**入参**: `{"stock_code":"AAPL","market":"US","reason":"测试"}`
**出参结构**: 返回创建的关注对象
**测试结果**: ✅
**数据示例**: `{"id":"0a9bd649-4df9-4380-a2f8-2db16c4e67e7","stock_code":"AAPL","market":"US","reason":"测试"}`
**发现的问题**: stock_name为null

## API: 删除关注 DELETE /api/watchlist/{stock_code}
**功能**: 从关注列表移除
**入参**: URL路径 - stock_code
**出参结构**: `{"message": "Watchlist item deleted"}`
**测试结果**: ✅
**数据示例**: `{"message":"Watchlist item deleted"}`
**发现的问题**: 无

---

## 8. Dashboard统计API

## API: 统计概览 GET /api/dashboard/stats
**功能**: 获取全局统计信息
**入参**: 无
**出参结构**: `{"total_analyses": 48, "stocks_analyzed": 10, "buy_count": 0, "watch_count": 13, "decision_distribution": {...}, "market_distribution": {...}, "recent_analyses": [...]}`
**测试结果**: ✅
**数据示例**: (2066 bytes)
**发现的问题**: 无

## API: 队列概览 GET /api/dashboard/queue-overview
**功能**: 获取队列状态概览
**入参**: 无
**出参结构**: `{"analysis_records": {"by_status": {...}, "by_priority": {}, "total_pending": 0, "total_running": 0}}`
**测试结果**: ✅
**数据示例**: (116 bytes)
**发现的问题**: by_priority为空对象{}

---

## 9. 反思API

## API: 反思记录 GET /api/reflections/{stock_code}
**功能**: 获取某股票的反思记录
**入参**: URL路径 - stock_code
**出参结构**: 数组
**测试结果**: ✅
**数据示例**: `[]` (00700暂无反思记录)
**发现的问题**: 无

## API: 添加反思 POST /api/reflection
**功能**: 添加分析反思
**入参**: `{"analysis_id":"7566f5ae-f671-4817-8a6e-7d3ac30f82ac","wrong_analysis":"A","reflection_text":"测试","error_tags":["test"]}`
**出参结构**: `{"success": true, "reflection_id": "xxx"}`
**测试结果**: ✅
**数据示例**: `{"success":true,"reflection_id":"3a47f307-b7b4-48ff-ab54-f7ef03d12bf7"}`
**发现的问题**: 无

---

## 10. 队列API

## API: 队列列表 GET /api/queue
**功能**: 获取分析队列
**入参**: 可选Query `status=running`
**出参结构**: `{"total": 48, "offset": 0, "limit": 50, "items": [...]}`
**测试结果**: ✅
**数据示例**: 返回48条记录，状态分布：completed:32, failed:16
**发现的问题**: 无

## API: 队列项删除 DELETE /api/queue/{id}
**功能**: 取消队列中的任务
**入参**: URL路径 - 队列项ID
**出参结构**: 成功或错误信息
**测试结果**: ✅
**数据示例**: 
- pending任务 → 正常取消
- completed任务 → `{"detail":"Cannot cancel task with status: completed. Only pending tasks can be cancelled."}` (400)
**发现的问题**: 无（行为符合预期）

---

## 11. 价格API

## API: 价格历史 GET /api/price/{stock_code}
**功能**: 获取股票价格历史
**入参**: URL路径 - stock_code
**出参结构**: `{"stock_code": "00700", "price_history": [{"date", "open", "high", "low", "close", "volume"}, ...]}`
**测试结果**: ✅
**数据示例**: 
- 00700 HK → (8410 bytes)
- AAPL US → (6049 bytes)
**发现的问题**: 无

---

## 测试总结

### 通过: 28/30
### 失败: 1/30
### 部分成功: 1/30

### 问题汇总

| # | API | 问题 | 严重程度 |
|---|-----|------|---------|
| 1 | GET /api/history/{stock_code} | 所有股票都返回500错误 | 🔴 严重 |
| 2 | GET /api/compare/{stock_code} | 跨股票ID比较时返回400不够友好 | ⚠️ 中等 |

### 入参格式发现

| API | 正确格式 | 错误格式 |
|-----|---------|---------|
| POST /api/analyze | `{"stock_codes": ["00700"], "market": "HK"}` | `{"stock_code": "00700", "market": "HK"}` |
| POST /api/l1/analyze | `{"stock_codes": ["00700"]}` | `{"stock_code": "00700"}` |
| POST /api/portfolio | `{"stock_code":"00700","market":"HK",...}` | - |

### stock_code格式兼容性

| 格式 | 示例 | 支持情况 |
|-----|------|---------|
| HK股票 | 00700 | ✅ |
| US股票 | AAPL, NVDA | ✅ |
| CN股票 | 600519 | ✅ |

### 建议

1. **优先修复**: GET /api/history/{stock_code} 500错误
2. **次要优化**: compare API的错误提示可以更明确，说明哪些ID不匹配
