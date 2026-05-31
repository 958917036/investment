# 神农股票分析平台

AI驱动的多市场股票筛选与量化分析系统 Web UI

## 功能特性

- **多市场支持**: A股(沪/深)、港股、美股
- **全链路分析**: L1筛选 → L2数据 → L3量化 → L4裁判
- **智能决策**: BUY/SELL/WATCH/NO 信号
- **历史追踪**: 完整的分析历史记录
- **对比分析**: 两个时间点的分析结果对比
- **反思机制**: 用户反馈帮助系统持续改进
- **批量分析**: 一次提交多个股票分析任务

## 技术栈

### 后端
- FastAPI (Python)
- SQLAlchemy + SQLite
- 集成神农分析系统

### 前端
- React 18 + TypeScript
- TailwindCSS + shadcn/ui
- Recharts 图表
- React Router

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt

cd ../frontend
npm install
```

### 2. 启动后端服务

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 3. 启动前端开发服务器

```bash
cd frontend
npm run dev
```

### 4. 访问

- 前端: http://localhost:3000
- API文档: http://localhost:8000/docs

## 页面说明

| 页面 | 路径 | 说明 |
|------|------|------|
| 首页 | `/` | 统计概览、最近任务 |
| 分析 | `/analyze` | 单只/批量股票分析 |
| 结果详情 | `/result/:id` | 单次分析完整报告 |
| 历史记录 | `/history/:code` | 某股票的所有历史分析 |
| 对比分析 | `/compare/:code` | 两份分析的对比 |
| 批次管理 | `/batch` | 所有批量任务状态 |
| 股票库 | `/stocks` | 已分析股票列表 |

## API 端点

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/analyze` | 启动分析 |
| GET | `/api/result/:id` | 获取分析结果 |
| GET | `/api/history/:code` | 获取历史记录 |
| GET | `/api/compare/:code` | 对比分析 |
| GET | `/api/batch/:id` | 批次状态 |
| GET | `/api/batches` | 所有批次 |
| POST | `/api/batch/:id/retry` | 重试失败任务 |
| DELETE | `/api/batch/:id` | 取消批次 |
| GET | `/api/stocks` | 股票列表 |
| GET | `/api/stocks/search` | 搜索股票 |
| POST | `/api/reflection` | 提交反思 |

## 股票代码格式

- **A股**: 6位数字 (如 `600519`, `000858`)
- **港股**: 5位数字 (如 `00700`, `09988`) 或加 `HK` 前缀
- **美股**: 英文代码 (如 `NVDA`, `AAPL`) 或加 `US` 前缀
