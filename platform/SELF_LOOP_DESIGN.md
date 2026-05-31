# 神农平台自闭环系统设计方案

> 版本: v4.0
> 更新: 2026-05-31
> 状态: 已完成（system_complete=true, completion=100%）

---

## 一、核心设计理念

### 1.1 循环驱动机制

自闭环的本质是一个**永不停歇的改进循环**：

```
发现问题 ──→ 解决问题 ──→ 验证结果 ──→ 发现新问题 ──→ 循环
```

每一轮迭代包含四个核心步骤：

| 步骤 | 动作 | 状态变更 |
|------|------|----------|
| **发现** | 识别系统中的 blocker/问题 | → `pending` |
| **解决** | 委托 Agent 修复代码 | → `running` |
| **验证** | npm run build + API 健康检查 | → `resolved` 或 `failed` |
| **发现新问题** | 修复过程中暴露的新问题 | → 新增 blocker |

当没有新问题可处理时，系统进入**监控模式**（system_complete=true），
当新问题出现时，自动退出监控模式回到**开发模式**。

### 1.2 两种运行状态

| 模式 | system_complete | 行为 |
|------|----------------|------|
| **开发模式** | `false` | 主动修复 blocker，不停歇 |
| **监控模式** | `true` | 只做健康检查，发现问题立即退出监控 |

---

## 二、系统架构

### 2.1 整体架构图

```
用户/外部触发
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Cron Job 自驱动 Agent                        │
│  Job ID: be8040bbffbc  调度: */10 * * * *  累计执行: 1882次      │
│  skills: terminal, file, web, session_search, skills, delegation│
└────────────────────────────┬────────────────────────────────────┘
                             │ 每10分钟触发一次
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    self_loop.py (v4)                            │
│  路径: ~/.hermes/investment/platform/self_loop.py              │
│  核心原则: 1次执行 = 处理完所有 pending blocker 后退出           │
│  防并发: /tmp/hermes_platform.lock (fcntl)                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
    system_complete=true           system_complete=false
              │                             │
              ▼                             ▼
      ┌──────────────┐           ┌──────────────────────────┐
      │ 监控模式      │           │ 开发模式                  │
      │健康检查       │           │读取 blocker[0]           │
      │推送微信      │           │delegate_fix()            │
      └──────────────┘           │npm run build 验证         │
                                 │update state               │
                                 │继续下一个                 │
                                 └──────────────────────────┘
                                          │
                                          ▼
                              ┌──────────────────────────┐
                              │  神农分析引擎             │
                              │  shennong.py             │
                              │  L1→L2→L3→L4             │
                              └──────────────────────────┘
                                          │
                                          ▼
                              ┌──────────────────────────┐
                              │  FastAPI 后端             │
                              │  localhost:8000          │
                              └──────────────────────────┘
                                          │
                                          ▼
                              ┌──────────────────────────┐
                              │  前端 React SPA           │
                              │  localhost:8000          │
                              └──────────────────────────┘
```

### 2.2 文件索引

#### 核心自闭环文件

| 文件路径 | 作用 | 关键内容 |
|---------|------|----------|
| `~/.hermes/investment/platform/self_loop.py` | 自闭环执行器 | 锁管理/委托修复/状态更新/日志 |
| `~/.hermes/investment/platform/platform_state.json` | 系统状态文件 | blockers 列表/completion_percentage |
| `~/.hermes/investment/platform/CRON_SYSTEM_PROMPT.md` | Agent 行动指南 | 开发模式/监控模式切换逻辑 |
| `~/.hermes/investment/platform/TASK_BOARD.md` | Blocker 任务板 | 所有 blocker 清单/进度/完成度 |

#### 平台架构文档（引用）

| 文件路径 | 作用 |
|---------|------|
| `~/.hermes/investment/platform/SPEC.md` | 功能规格文档（架构/API/数据库 Schema）|
| `~/.hermes/investment/platform/SYSTEM_DOCUMENTATION.md` | 系统完整文档（前端/后端/神农引擎/数据库）|
| `~/.hermes/investment/platform/README.md` | 平台 README |
| `~/.hermes/investment/CLAUDE.md` | 神农系统开发规范（Layer 设计/测试规范/日志规范）|

#### 后端文件（FastAPI）

| 文件路径 | 作用 |
|---------|------|
| `~/.hermes/investment/platform/backend/main.py` | FastAPI 入口，路由注册 |
| `~/.hermes/investment/platform/backend/database.py` | SQLite (aiosqlite) 连接管理 |
| `~/.hermes/investment/platform/backend/models.py` | SQLAlchemy 模型（analysis_records 等）|
| `~/.hermes/investment/platform/backend/shennong_client.py` | 调用神农引擎的客户端 |
| `~/.hermes/investment/platform/backend/worker_pool.py` | 异步 WorkerPool（L2→L3→L4 并行执行）|
| `~/.hermes/investment/platform/backend/routers/` | API 路由目录（analyze/result/batch/stocks 等）|

#### 前端文件（React SPA）

| 文件路径 | 作用 |
|---------|------|
| `~/.hermes/investment/platform/frontend/src/App.tsx` | React 路由配置 |
| `~/.hermes/investment/platform/frontend/src/pages/` | 各页面组件目录 |
| `~/.hermes/investment/platform/frontend/dist/` | Vite build 输出（由后端托管，访问 http://localhost:8000）|
| `~/.hermes/investment/platform/frontend/package.json` | 前端依赖/脚本定义 |
| `~/.hermes/investment/platform/frontend/vite.config.ts` | Vite 构建配置 |

#### 神农分析引擎文件

| 文件路径 | 作用 |
|---------|------|
| `~/.hermes/investment/main/shennong.py` | 主调度器（L1→L2→Veto→L3→L4 全链路）|
| `~/.hermes/investment/L1_screener/` | L1 选股（breakout/growth_momentum/garp/pullback/quality_value 五策略）|
| `~/.hermes/investment/L2_data_enrich/` | L2 数据 enrichment（主力资金/机构流向）|
| `~/.hermes/investment/L3_quant_analysis/` | L3 量化分析（财务/估值/成长性评分）|
| `~/.hermes/investment/L4_judge/` | L4 投资决策（五维评分/概率化方案）|
| `~/.hermes/investment/main/config/l1_config.json` | L1 策略参数配置 |
| `~/.hermes/investment/main/utils/logger.py` | 统一日志工具（所有层共享）|

#### Cron 系统文件

| 文件路径 | 作用 |
|---------|------|
| `~/.hermes/cron/jobs.json` | 所有 Cron Job 定义（2017行，约30+个 jobs）|
| `~/.hermes/cron/output/` | 各 job 输出目录 |
| `~/.hermes/cron/output/self_loop_logs/` | 自闭环执行日志（时间戳命名）|
| `~/.hermes/scripts/shennong-l5.sh` | L5 每日冻结算任务（19:00 执行）|

---

## 三、运行机制详解

### 3.1 self_loop.py 执行流程（v4）

```
main()
 │
 ├─ acquire_lock()          # 获取 /tmp/hermes_platform.lock
 │                           # 失败 → 退出（防并发重复执行）
 │
 ├─ 读取 platform_state.json
 │   {
 │     "system_blockers": [...],
 │     "system_complete": false,
 │     "completion_percentage": 65
 │   }
 │
 ├─ 收集所有 state=pending 的 blocker
 │   pending = [b for b in blockers if b.get("state")=="pending"]
 │
 ├─ if not pending:
 │    run_api_check()        # 无待处理 → 只做健康检查
 │    log("自闭环一轮执行完毕")
 │    → 释放锁 → 退出
 │
 ├─ for each blocker in pending:
 │   │
 │   ├─ update_blocker_state(bid, "running")
 │   │
 │   ├─ delegate_fix()
 │   │    ├─ 读取 ~/.claude/settings.json 获取凭证
 │   │    ├─ subprocess.run(["claude", "-p", task, ...])
 │   │    │    stdin=/dev/null（防止等待 tty）
 │   │    │    timeout=600s
 │   │    │    --dangerously-skip-permissions
 │   │    │    --max-turns=60
 │   │    ├─ task 内容来自 CRON_SYSTEM_PROMPT.md 逻辑
 │   │    └─ 返回 (success, detail)
 │   │
 │   ├─ if not fix_ok:
 │   │    update_blocker_state(bid, "failed", error)
 │   │    write_log("FAIL {bid}: ...")
 │   │    continue  # 继续下一个 blocker
 │   │
 │   ├─ run_build()          # npm run build（前端验证）
 │   │    └─ 失败 → update_blocker_state(bid, "failed")
 │   │
 │   ├─ run_api_check()     # curl http://localhost:8000/api/health
 │   │
 │   ├─ remove_blocker()     # 从 system_blockers 移除
 │   │    └─ 若全部移除 → system_complete=true, percentage=100
 │   │
 │   └─ write_log("OK {bid} (severity={sev}, build=ok, api={ok/warn})")
 │
 ├─ 推送微信通知
 │   └─ python3 ~/.hermes/scripts/weixin_push.py "自闭环" "自闭环一轮执行完毕"
 │
 └─ release_lock()           # 释放锁
```

### 3.2 delegate_fix 委托机制

当 `self_loop.py` 需要修复代码时，它通过 `claude -p`（print mode）启动一个独立的 Claude Code 子进程：

```
subprocess.run([
    "claude", "-p", task,
    "--dangerously-skip-permissions",
    "--allowedTools", "Read,Edit,Bash,Terminal",
    "--max-turns", "60",
    "--no-session-persistence"
], stdin=subprocess.DEVNULL, timeout=600)
```

**task 内容包含**：
- blocker_id 和 description
- estimated_fix（建议修复方案）
- 项目路径：`~/.hermes/investment/platform/`
- 必须执行 `npm run build` 验证
- 使用 `patch` 工具进行代码修改

### 3.3 CRON_SYSTEM_PROMPT.md — Agent 行动指南

这是 Agent 收到的 System Prompt，决定其行为模式：

```
模式一：监控模式（system_complete=true）
  → 执行健康检查
  → curl http://localhost:8000/api/health
  → npm run build 验证
  → 推送监控报告

模式二：开发模式（system_complete=false）
  → 读取 platform_state.json
  → 取 blocker[0]（按 severity 排序：high > medium > low）
  → 直接执行修复（不通过 delegate_task）
  → npm run build 验证 0 TypeScript errors
  → 更新 state（移除 blocker，上调 percentage）
  → 自循环处理下一个
  → 全部完成 → system_complete=true → 推送完成报告
```

---

## 四、状态管理

### 4.1 platform_state.json 结构

```json
{
  "system_complete": true,
  "completion_percentage": 100,
  "system_blockers": [
    {
      "id": "BLK-001",
      "description": "Compare 页面骨架屏缺失，加载时页面闪烁",
      "severity": "medium",
      "state": "resolved",
      "updated_at": "2026-05-10T...",
      "resolved_at": "2026-05-10T...",
      "retry_count": 0
    }
  ],
  "completed_features": [...],
  "tasks_completed_this_session": [...],
  "tasks_failed_this_session": [],
  "service_health": {
    "backend": "ok",
    "frontend": "ok"
  }
}
```

### 4.2 Blocker 状态流转

```
pending → running → resolved (成功)
                    → failed  (重试次数过多)
```

### 4.3 完成度计算

```
completion_percentage 初始: 0
每解决一个 blocker 上调:
  - severity=high:   +15
  - severity=medium: +10
  - severity=low:    +5

全部清除 → system_complete=true, completion_percentage=100
```

---

## 五、日志与监控

### 5.1 日志文件

| 日志 | 路径 | 内容 |
|------|------|------|
| 自闭环执行日志 | `~/.hermes/cron/output/self_loop_logs/YYYYMMDD_HHMMSS.log` | 每轮执行详细记录 |
| Gateway 错误日志 | `~/.hermes/logs/gateway.error.log` | 钉钉连接失败（SOCKS proxy）|
| 神农系统日志 | `~/.hermes/investment/logs/hermes.log` | L1→L4 执行记录 |

### 5.2 健康检查端点

```bash
# 后端健康
curl http://localhost:8000/api/health

# Dashboard 统计
curl http://localhost:8000/api/dashboard/stats
```

---

## 六、循环往复的核心机制图

```
                    ┌─────────────────────────────┐
                    │      每 10 分钟触发          │
                    │  Cron Job (be8040bbffbc)     │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │     self_loop.py            │
                    │  读取 platform_state.json  │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
           system_complete=true          system_complete=false
                    │                             │
                    ▼                             ▼
            ┌───────────────┐         ┌─────────────────────────┐
            │   监控模式     │         │      开发模式           │
            │  健康检查      │         │ 发现 blocker[0]        │
            │  推送微信      │         │ 解决问题               │
            └───────────────┘         │ 验证结果               │
                                       │ 发现新问题（循环）     │
                                       └───────────┬─────────────┘
                                                   │
                                     全部解决 ◄────┤
                                       │           │
                                       │     继续下一个
                                       │           │
                                       ▼           ▼
                              ┌────────────────────────┐
                              │ system_complete=true   │
                              │ 推送完成报告            │
                              │ 回到监控模式           │
                              └────────────────────────┘
```

---

## 七、与其他系统的关系

### 7.1 与 Hermes Gateway 的关系

- Hermes Gateway（PID 97698）运行在主机上，负责接收钉钉/微信消息
- 自闭环系统是 Hermes Agent 体系的一部分，运行在 `~/.hermes/investment/platform/` 下
- Gateway 状态：`~/.hermes/gateway_state.json`（钉钉/微信均 connected）

### 7.2 与神农分析引擎的关系

- 自闭环修复的是**平台前端/后端代码**（platform 目录）
- 神农分析引擎（`shennong.py`）是被平台调用的**底层组件**
- 平台是外壳，神农引擎是内核，自闭环负责维护这个外壳

### 7.3 与 Cron Job 系统（jobs.json）的关系

- 所有 Cron Job 集中管理在 `~/.hermes/cron/jobs.json`
- 自闭环是其中一个 Job（be8040bbffbc），调度 `*/10 * * * *`
- 其他 Job 包括：L5 冻结算、L1/L2/L3 批量选股、每周策略报告等

---

## 八、已知问题修复记录

| 日期 | 问题 | 根因 | 修复 |
|------|------|------|------|
| 2026-05-31 | 钉钉无法收发消息 | 缺少 `python-socks` 包 | `pip install python-socks`，重启 Gateway |
| 2026-05-10 | analyze_task 用 result["L1"] (空) | 字段路径错误 | 改为 result["pipeline"]["L1"] |
| 2026-05-10 | 同步 run_analysis 阻塞事件循环 | FastAPI 同步调用 | 加 `asyncio.to_thread()` |
| 2026-05-10 | 空列表返回 500 | 缺少输入校验 | 加 `@field_validator` → 422 |
| 2026-05-10 | Batch stock_codes 存为 JSON 字符串 | SQLite 直接存储 | 改为存储 JSON 字符串数组 |

---

## 九、启动与维护命令

```bash
# 重启后端
lsof -i :8000 -t | xargs kill 2>/dev/null; sleep 1
cd ~/.hermes/investment/platform/backend && nohup ~/.hermes/hermes-agent/venv/bin/python -m uvicorn main:app --port 8000 > ~/.hermes/logs/backend.log 2>&1 &

# 重启前端 dev
lsof -i :3000 -t | xargs kill 2>/dev/null; sleep 1
cd ~/.hermes/investment/platform/frontend && nohup npm run dev > ~/.hermes/logs/frontend.log 2>&1 &

# 查看自闭环日志
tail -f ~/.hermes/cron/output/self_loop_logs/$(ls -t ~/.hermes/cron/output/self_loop_logs/ | head -1)

# 查看 Gateway 状态
cat ~/.hermes/gateway_state.json

# 查看平台状态
cat ~/.hermes/investment/platform/platform_state.json

# 手动触发自闭环
python3 ~/.hermes/investment/platform/self_loop.py
```

---

## 十、附录：架构文档引用

- **平台完整规格** → [SPEC.md](SPEC.md)
- **系统完整文档** → [SYSTEM_DOCUMENTATION.md](SYSTEM_DOCUMENTATION.md)
- **神农系统开发规范** → [~/.hermes/investment/CLAUDE.md](../../investment/CLAUDE.md)
- **Gateway 状态** → `~/.hermes/gateway_state.json`
- **Cron Job 配置** → `~/.hermes/cron/jobs.json`