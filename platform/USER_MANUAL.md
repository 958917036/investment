# 神农股票分析平台 — 使用手册

> 版本: 1.0.0
> 日期: 2026-05-10
> 前端地址: http://localhost:3000
> 后端API: http://localhost:8000/api

---

## 目录

1. [快速启动](#1-快速启动)
2. [功能概览](#2-功能概览)
3. [页面详解](#3-页面详解)
4. [API 参考](#4-api-参考)
5. [数据说明](#5-数据说明)
6. [故障排查](#6-故障排查)

---

## 1. 快速启动

### 启动服务

```bash
cd ~/.hermes/investment/platform
./start.sh
```

- **前端**: http://localhost:3000
- **后端API**: http://localhost:8000/api

### 停止服务

```bash
# 查找进程
lsof -i :8000  # 后端
lsof -i :3000  # 前端

# 终止
kill <PID>
```

---

## 2. 功能概览

| 功能 | 路径 | 说明 |
|------|------|------|
| 首页仪表盘 | `/` | 全局概览：统计、分析记录入口 |
| 发起分析 | `/analyze` | 单只或多只股票全链路 L1→L4 分析 |
| L1 专线 | `/l1` | 仅执行 L1 初筛，快速返回（~3s） |
| 分析结果详情 | `/result/:id` | 单次分析的完整报告 |
| 历史分析记录 | `/history` | 按股票查看所有历史分析 |
| 对比分析 | `/compare/:code?ids=a,b` | 两次分析对比，差异可视化 |
| 批次任务列表 | `/batch` | 批量任务状态监控 |
| 股票库 | `/stocks` | 所有分析过的股票 |
| 持仓管理 | `/portfolio` | 持仓盈亏跟踪 |
| 关注列表 | `/watchlist` | 关注股票池 |

---

## 3. 页面详解

### 3.1 首页仪表盘 `/`

**功能**: 全局数据概览 + 快捷入口

**显示内容**:
- 累计分析次数、覆盖股票数、决策分布（BUY/WATCH/SELL/NO）
- 近 10 条分析记录（股票代码、名称、市场、时间、决策）
- 鼠标悬停预取实时价格

**操作**: 点击任意记录 → 跳转详情页 `/result/:id`

---

### 3.2 发起分析 `/analyze`

#### 单只股票分析

1. 输入股票代码（支持自动识别市场）
   - A股: `600519`、`000858`
   - 港股: `00700`、`09988`
   - 美股: `NVDA`、`AAPL`
2. 点击「开始分析」
3. 自动跳转到 `/batch` 页面监控进度

#### 批量分析

1. 切换到「批量分析」标签
2. 每行输入一只股票代码
3. 点击「批量分析」

**执行链路**: L1(同步) → L2 → L3 → L4(异步，WorkerPool N=3 并行)

---

### 3.3 L1 专线 `/l1`

**功能**: 仅运行 L1 初筛层，快速返回候选股票（~3s）

- 支持单只或批量股票代码输入
- L1 结果 24h 缓存（相同代码不重复执行）
- 可勾选「强制刷新」跳过缓存

---

### 3.4 分析结果详情 `/result/:id`

**展示内容**:

| Section | 内容 |
|---------|------|
| 基本信息 | 股票代码、名称、市场、时间、状态 |
| 五维评分 | 资金面/技术面/基本面/板块/事件 5维度评分 |
| 价格走势 | 近90交易日K线 + 均线 |
| L1 筛选 | 候选股票列表 |
| L2 资金流 | 主力净流入、MFI、机构资金方向 |
| L3 基本面 | 五维综合评分 + 辩论引擎输出 |
| L4 投资方案 | 决策(REJECT/BUY/SELL)、目标价、止损价、胜率、建议仓位 |

**操作按钮**:
- 「加入关注」→ 添加到关注列表
- 「加入持仓」→ 添加到持仓管理
- 「刷新」→ 重新获取最新数据
- 「历史记录」→ 跳转该股票历史页

---

### 3.5 历史分析记录 `/history`

1. 搜索框输入股票代码或名称
2. 从下拉列表选择
3. 显示该股票所有历史分析记录

**操作**:
- 点击记录 → 跳转 `/result/:id`
- 勾选 2 条 → 点击「对比分析」

---

### 3.6 对比分析 `/compare/:code?ids=a,b`

**功能**: 两次分析记录的差异对比

**对比维度**:
- 决策变化（是否有变化）
- 评分变化（上升/下降 N 分）
- 各维度指标差异
- 反思记录（如果提交过）

---

### 3.7 批次任务 `/batch`

**显示内容**:
- 所有批次列表（task_id 前8位、状态、进度百分比）
- 完成/失败/总计数量

**操作**:
- 「刷新」→ 重新获取最新状态
- 「重试 (N)」→ 重新执行失败的股票
- 「取消」→ 取消进行中的批次

---

### 3.8 股票库 `/stocks`

- 所有被分析过的股票索引
- 搜索框快速过滤
- 点击股票 → 跳转历史页

---

### 3.9 持仓管理 `/portfolio`

- 显示持仓市值、总成本、盈亏金额、收益率
- 持仓明细表（代码/数量/成本价/当前价/市值/盈亏）
- 添加/编辑/删除持仓

---

### 3.10 关注列表 `/watchlist`

- 关注总数、买入信号数、观望信号数、无信号数
- 从分析结果页「加入关注」自动添加
- 手动添加（代码 + 理由 + 目标价）

---

## 4. API 参考

> Base URL: `http://localhost:8000/api`

### 4.1 分析

```bash
# L1 专线筛选（快速，3s，24h缓存）
POST /api/l1/analyze
Body: {"stock_codes": ["00700"], "market": "auto", "force_refresh": false}

# 全链路分析（L1→L4，异步）
POST /api/analyze
Body: {"stock_codes": ["00700"], "market": "auto", "force_refresh": false}

# 获取分析结果
GET /api/result/{record_id}

# 股票历史记录
GET /api/records/stock/{code}

# 两次分析对比
GET /api/compare/{code}?ids={id1},{id2}
```

### 4.2 批量任务

```bash
GET  /api/batches                     # 批次列表
GET  /api/batch/{task_id}             # 批次详情
POST /api/batch/{task_id}/retry       # 重试失败任务
DELETE /api/batch/{task_id}           # 取消批次
```

### 4.3 队列管理

```bash
GET    /api/queue
DELETE /api/queue/{record_id}         # 取消单个任务
DELETE /api/queue/batch/{task_id}    # 取消整批任务
```

### 4.4 股票数据

```bash
GET /api/stocks              # 股票库列表
GET /api/stocks/search?q=    # 搜索股票
GET /api/price/{code}        # 实时价格 + K线
```

### 4.5 持仓与关注

```bash
# 持仓
GET    /api/portfolio
POST   /api/portfolio         Body: {"stock_code":"00700","market":"HK","quantity":100,"avg_cost":380.0}
PUT    /api/portfolio/{id}
DELETE /api/portfolio/{id}

# 关注
GET    /api/watchlist
POST   /api/watchlist        Body: {"stock_code":"00700","market":"HK","reason":"等待更低价格"}
PUT    /api/watchlist/{id}
DELETE /api/watchlist/{id}
```

### 4.6 反思系统

```bash
POST /api/reflection
Body: {
  "analysis_id": "uuid",
  "wrong_analysis": "A",
  "reflection_text": "低估了资金流流出的影响",
  "error_tags": ["资金流误判"],
  "correct_analysis_id": "uuid"
}

GET /api/reflections/{stock_code}
```

### 4.7 仪表盘

```bash
GET /api/dashboard/stats
```

---

## 5. 数据说明

### 分析层级

| 层级 | 功能 | 执行方式 |
|------|------|----------|
| L1 | 技术面过滤、趋势方向 | 同步（~3s）|
| L2 | 主力资金、机构资金 | 异步 |
| L3 | 财务指标、估值、成长性 | 异步 |
| L4 | 投资方案、概率化建议 | 异步 |

### 决策类型

| 决策 | 含义 |
|------|------|
| BUY | 买入信号 |
| WATCH | 观察 |
| SELL | 卖出信号 |
| NO / REJECT | 否决 |
| null | 分析未完成 |

### 市场代码

| 代码 | 市场 |
|------|------|
| CN | A股 |
| HK | 港股 |
| US | 美股 |

### 缓存策略

- **L1 结果**: 24h 缓存，`force_refresh=true` 绕过
- **价格数据**: session 级缓存（刷新页面获取最新）
- **K线数据**: 优先从分析结果取（daily_30d）

---

## 6. 故障排查

### 页面空白

```bash
# 1. 检查后端
curl http://localhost:8000/api/dashboard/stats

# 2. 检查前端
curl http://localhost:3000

# 3. 查看 Console JS errors
```

### 分析卡住不完成

```bash
# 查看队列状态
curl "http://localhost:8000/api/queue?status=pending"

# 查看具体记录错误信息
curl http://localhost:8000/api/result/{id} | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error_message','no error'))"
```

### Build 失败（TS 错误）

```bash
cd ~/.hermes/investment/platform/frontend && npm run build 2>&1 | grep "error TS"
```

### 重启服务

```bash
# 后端
pkill -f "uvicorn main:app"
cd ~/.hermes/investment/platform/backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &

# 前端
cd ~/.hermes/investment/platform/frontend && npm run dev
```

---

## 附录: 文件结构

```
~/.hermes/investment/platform/
├── start.sh                     # 一键启动脚本
├── SPEC.md                      # 功能规格文档
├── USER_MANUAL.md               # 本文档
├── platform.db                  # SQLite 数据库
├── backend/
│   ├── main.py                  # FastAPI 入口
│   ├── database.py              # SQLAlchemy 配置
│   ├── models.py                # 数据模型
│   ├── worker_pool.py           # 异步任务池
│   └── routers/
│       ├── analyze.py           # 全链路分析
│       ├── l1_api.py           # L1 专线
│       ├── batch.py             # 批次管理
│       ├── queue.py             # 队列管理
│       ├── result.py            # 结果查询/对比
│       ├── stocks.py            # 股票库
│       ├── dashboard.py         # 仪表盘
│       ├── reflection.py        # 反思系统
│       └── portfolio.py         # 持仓/关注
└── frontend/
    ├── src/
    │   ├── pages/               # 页面组件
    │   ├── components/           # 可复用组件
    │   ├── lib/api.ts           # API 调用封装
    │   └── types/index.ts       # TypeScript 类型
    └── dist/                    # 生产构建产物
```
