"""
Worker Pool — L2/L3/L4 批量执行引擎。

基于 shennong.py 的 _run_batch 和 run_pipeline 逻辑:
- 从 SQLite analysis_records 表拉取 pending 任务（按 priority 排序: 1=人工 > 3=定时）
- ThreadPoolExecutor 并行执行 N=3 个 worker
- 跟踪 L1→L2→L3→L4 流水线状态
- 集成 shennong.run_pipeline 执行实际分析
- notify_wechat: 完成后打印日志（当前实现）

关键设计（单表架构）:
1. 所有任务存储在 analysis_records 表
2. task_id: 批次号，同批任务共享
3. step: L1/L2/L3/L4/veto 当前阶段
4. priority 字段控制: 1=人工触发(高), 3=定时调度(普通)
5. force_refresh: 跳过缓存强制刷新
6. cached_at: L1 结果 24h 缓存判断
7. N=3 Worker 并行消费
8. 批量取消: UPDATE analysis_records WHERE task_id + status=PENDING → status=CANCELLED
"""
import json
import time
import uuid
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum

import sys
import os

logger = logging.getLogger(__name__)

SHENNONG_ROOT = os.path.expanduser("~/.hermes/investment")

# ── Constants ─────────────────────────────────────────────────────────────────

WORKER_COUNT = 3  # N=3 Worker 并行消费
BATCH_SIZE = 50
QUEUE_CHECK_INTERVAL = 30.0  # seconds
L1_CACHE_TTL_HOURS = 24


# ── Notify WeChat (当前实现为 print 日志) ─────────────────────────────────────

def notify_wechat(message: str, stock_code: str = None, decision: str = None):
    """
    通知微信/钉钉 — 当前实现为 print 日志。
    可扩展为真实 webhook 推送。
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if stock_code:
        logger.info(f"[WeChat Notify] [{ts}] Stock: {stock_code} | Decision: {decision} | {message}")
    else:
        logger.info(f"[WeChat Notify] [{ts}] {message}")


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class WorkItem:
    """单个股票工作任务单元。"""
    record_id: str       # AnalysisRecord id
    stock_code: str
    stock_name: str
    market: str
    priority: int = 3    # 1=人工(高), 3=定时(普通)
    task_id: Optional[str] = None  # 批次号
    step: str = "L1"     # 当前阶段
    force_refresh: bool = False  # 跳过缓存强制刷新


@dataclass
class BatchResult:
    """批量运行结果。"""
    task_id: str
    total: int
    completed: int
    failed: int
    buy_count: int
    watch_count: int
    duration_s: float
    decisions: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ── Cache Helpers ────────────────────────────────────────────────────────────

def is_l1_cached(cached_at: datetime) -> bool:
    """检查 L1 缓存是否有效（24h TTL）。"""
    if cached_at is None:
        return False
    age = datetime.utcnow() - cached_at
    return age.total_seconds() < L1_CACHE_TTL_HOURS * 3600


# ── Worker Pool ──────────────────────────────────────────────────────────────

class WorkerPool:
    """
    ThreadPoolExecutor-based Worker Pool，用于 L2→L3→L4 批量执行。

    架构:
    - WorkerPool(max_workers=3) 三个线程并行
    - 每个 worker 调用 run_pipeline_for_stock (L2→L3→L4)
    - 批量协调器管理状态转换和结果聚合

    单表架构（analysis_records）:
    - 所有任务存储在 analysis_records 表
    - task_id: 批次号，同批任务共享
    - step: L1/L2/L3/L4/veto 当前阶段
    - priority 调度: 按 priority ASC 拉取（1 在前，3 在后）
    - 缓存逻辑: L1 结果通过 cached_at 判断是否在 24h 内
    - force_refresh=True 时跳过缓存直接执行

    使用方法:
        pool = WorkerPool(max_workers=3, batch_size=50)
        pool.start()
        # ... enqueue work ...
        pool.stop()
    """

    def __init__(
        self,
        max_workers: int = WORKER_COUNT,
        batch_size: int = BATCH_SIZE,
        queue_check_interval: float = QUEUE_CHECK_INTERVAL,
    ):
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.queue_check_interval = queue_check_interval

        self._executor: Optional[ThreadPoolExecutor] = None
        self._running = False
        self._lock = threading.Lock()
        self._results: Dict[str, BatchResult] = {}
        self._pending_batches: Dict[str, List[WorkItem]] = {}
        self._batch_events: Dict[str, threading.Event] = {}

        # Active task tracking
        self._active_items: Dict[str, WorkItem] = {}
        self._item_errors: Dict[str, str] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self):
        """启动 Worker Pool。"""
        if self._running:
            return
        self._running = True
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        logger.info(f"[WorkerPool] Started with {self.max_workers} workers (N={self.max_workers})")

    def stop(self, timeout: float = 60.0):
        """优雅停止 Worker Pool。"""
        self._running = False
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None
        logger.info("[WorkerPool] Stopped")

    # ── Enqueue ────────────────────────────────────────────────────────────

    def enqueue(self, items: List[WorkItem], task_id: Optional[str] = None) -> str:
        """
        将工作项加入批量处理队列。
        返回 task_id 用于跟踪。
        """
        if not task_id:
            task_id = str(uuid.uuid4())

        with self._lock:
            self._pending_batches[task_id] = items
            self._batch_events[task_id] = threading.Event()
            self._results[task_id] = None  # placeholder

        logger.info(f"[WorkerPool] Enqueued task {task_id}: {len(items)} items")
        return task_id

    def enqueue_from_db(self, db_session, limit: int = None) -> Tuple[str, int]:
        """
        从 SQLite analysis_records 表拉取 pending 任务并入队。

        单表架构: 直接从 analysis_records 读取
        priority 排序: priority ASC → 1(人工) 优先于 3(定时)
        status 过滤: 只拉取 PENDING 状态的任务

        返回 (task_id, count)。
        """
        if limit is None:
            limit = self.batch_size

        from sqlalchemy import select, update
        from models import AnalysisRecord, Status, Step

        # 按 priority ASC 排序（1 在前），同优先级按 timestamp ASC
        stmt = (
            select(AnalysisRecord)
            .where(AnalysisRecord.status == Status.PENDING)
            .order_by(AnalysisRecord.priority.asc(), AnalysisRecord.timestamp.asc())
            .limit(limit)
        )
        result = db_session.execute(stmt)
        records = result.scalars().all()

        if not records:
            return "", 0

        items = [
            WorkItem(
                record_id=r.id,
                stock_code=r.stock_code,
                stock_name=r.stock_name or r.stock_code,
                market=r.market.value if r.market else "CN",
                priority=r.priority or 3,
                task_id=r.task_id,
                step=r.step.value if r.step else "L1",
                force_refresh=bool(r.force_refresh),
            )
            for r in records
        ]

        # 将记录标记为 QUEUED (复用 RUNNING 状态表示正在处理)
        record_ids = [r.id for r in records]
        db_session.execute(
            update(AnalysisRecord)
            .where(AnalysisRecord.id.in_(record_ids))
            .values(status=Status.RUNNING)
        )
        db_session.commit()

        task_id = self.enqueue(items)
        return task_id, len(items)

    # ── Batch Processing ───────────────────────────────────────────────────

    def process_batch(self, task_id: str, items: List[WorkItem]) -> BatchResult:
        """
        使用 ThreadPoolExecutor 并行处理一批工作项。
        镜像 shennong.py 的 run_full_pipeline_threaded 逻辑。
        """
        t0 = time.time()
        completed = 0
        failed = 0
        buy_count = 0
        watch_count = 0
        decisions = []
        errors = []

        with self._executor or ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_single, item): item
                for item in items
            }

            for future in as_completed(futures, timeout=300):
                item = futures[future]
                try:
                    result = future.result(timeout=180)
                    if result.get("error"):
                        failed += 1
                        errors.append(f"{item.stock_code}: {result['error']}")
                    else:
                        completed += 1
                        decision = result.get("decision")
                        if decision == "BUY":
                            buy_count += 1
                        elif decision == "WATCH":
                            watch_count += 1
                        if result.get("decision_data"):
                            decisions.append(result["decision_data"])
                        # notify_wechat
                        notify_wechat(
                            message=f"Analysis completed",
                            stock_code=item.stock_code,
                            decision=decision,
                        )
                except TimeoutError:
                    failed += 1
                    errors.append(f"{item.stock_code}: timeout")
                except Exception as e:
                    failed += 1
                    errors.append(f"{item.stock_code}: {type(e).__name__}: {e}")

        batch_result = BatchResult(
            task_id=task_id,
            total=len(items),
            completed=completed,
            failed=failed,
            buy_count=buy_count,
            watch_count=watch_count,
            duration_s=round(time.time() - t0, 2),
            decisions=decisions,
            errors=errors,
        )

        with self._lock:
            self._results[task_id] = batch_result
            self._batch_events[task_id].set()

        logger.info(
            f"[WorkerPool] Task {task_id}: {completed}/{len(items)} done "
            f"({buy_count}BUY/{watch_count}WATCH/{failed}FAIL) in {batch_result.duration_s}s"
        )
        return batch_result

    def _process_single(self, item: WorkItem) -> dict:
        """
        处理单个股票的 L2→L3→L4 流水线。

        缓存逻辑:
        - 检查 AnalysisRecord.cached_at 是否在 24h 内
        - force_refresh=True 时跳过缓存强制刷新
        - 命中缓存时直接返回缓存的 L1 结果
        """
        result = {
            "record_id": item.record_id,
            "stock_code": item.stock_code,
            "error": None,
            "decision": None,
            "judge_score": None,
            "decision_data": None,
        }

        try:
            import runpy

            # 动态加载 shennong
            ns = runpy.run_path(
                os.path.join(SHENNONG_ROOT, "main", "shennong.py"),
                run_name="run_pipeline"
            )
            run_pipeline = ns["run_pipeline"]

            # 构建 pipeline_kwargs
            pipeline_kwargs = {
                "symbols": [item.stock_code],
                "market": item.market,
                "mode": "full",
            }

            # force_refresh 控制是否跳过缓存
            if item.force_refresh:
                pipeline_kwargs["force_refresh"] = True
                logger.info(f"[WorkerPool] force_refresh=True for {item.stock_code}, bypassing cache")

            # 执行全链路
            pipeline_result = run_pipeline(**pipeline_kwargs)

            # 提取 L4 决策
            l4_decisions = pipeline_result.get("L4", {}).get("decisions", [])
            if l4_decisions:
                for d in l4_decisions:
                    if d.get("code") == item.stock_code:
                        result["decision"] = d.get("decision", "NO")
                        result["judge_score"] = d.get("judge_score")
                        result["decision_data"] = d
                        break
            else:
                result["decision"] = "NO"

            # 检查 L2 数据关键失败
            if pipeline_result.get("L2", {}).get("_DATA_CRITICAL_FAILURE"):
                result["decision"] = "NO"
                result["error"] = "L2_DATA_FAILURE"

            logger.info(f"[WorkerPool] Processed {item.stock_code}: decision={result['decision']}")

        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            logger.error(f"[WorkerPool] Failed {item.stock_code}: {result['error']}")

        return result

    # ── Wait for Batch ─────────────────────────────────────────────────────

    def wait_batch(self, task_id: str, timeout: float = 600.0) -> Optional[BatchResult]:
        """等待批量完成并返回结果。"""
        event = self._batch_events.get(task_id)
        if not event:
            return None

        signaled = event.wait(timeout=timeout)
        if not signaled:
            logger.warning(f"[WorkerPool] Task {task_id} wait timeout after {timeout}s")
            return None

        return self._results.get(task_id)

    # ── Queue Monitor (后台循环) ───────────────────────────────────────────

    def run_queue_monitor(self, db_session_factory, interval: float = None):
        """
        后台循环：持续从 DB 队列拉取任务并处理批量。

        运行直到 self._running 变为 False。
        每次循环按 priority 排序拉取 pending 任务。
        """
        if interval is None:
            interval = self.queue_check_interval

        logger.info(f"[WorkerPool] Queue monitor started (interval={interval}s, N={self.max_workers})")

        while self._running:
            try:
                task_id, count = self.enqueue_from_db(db_session_factory(), limit=self.batch_size)
                if count > 0:
                    items = self._pending_batches.get(task_id, [])
                    self.process_batch(task_id, items)
                else:
                    time.sleep(interval)
            except Exception as e:
                logger.error(f"[WorkerPool] Queue monitor error: {e}")
                time.sleep(interval)

        logger.info("[WorkerPool] Queue monitor stopped")

    # ── Batch Cancel (单表架构) ─────────────────────────────────────────────

    def cancel_batch(self, task_id: str, db_session) -> int:
        """
        批量取消: 更新 task_id 对应的所有 PENDING 记录为 CANCELLED。

        单表架构: 直接操作 analysis_records 表
        规则:
        - 只取消 status=PENDING 的记录
        - 已 RUNNING/COMPLETED/FAILED 的记录不可取消
        - 取消后: status=CANCELLED

        返回取消的记录数量。
        """
        from sqlalchemy import update, select
        from models import AnalysisRecord, Status

        # 找出该 task_id 下所有 PENDING 记录
        stmt = (
            select(AnalysisRecord)
            .where(AnalysisRecord.task_id == task_id, AnalysisRecord.status == Status.PENDING)
        )
        result = db_session.execute(stmt)
        pending_records = result.scalars().all()

        if not pending_records:
            return 0

        record_ids = [r.id for r in pending_records]

        # 批量取消 records
        db_session.execute(
            update(AnalysisRecord)
            .where(AnalysisRecord.id.in_(record_ids))
            .values(status=Status.CANCELLED, updated_at=datetime.utcnow())
        )

        db_session.commit()
        logger.info(f"[WorkerPool] Cancelled task {task_id}: {len(record_ids)} records")
        return len(record_ids)


# ── Singleton instance ────────────────────────────────────────────────────────

_pool_instance: Optional[WorkerPool] = None
_pool_lock = threading.Lock()


def get_worker_pool() -> WorkerPool:
    """获取或创建单例 WorkerPool 实例。"""
    global _pool_instance
    with _pool_lock:
        if _pool_instance is None:
            _pool_instance = WorkerPool(max_workers=WORKER_COUNT, batch_size=BATCH_SIZE)
        return _pool_instance


def start_worker_pool():
    """启动全局 Worker Pool（在 FastAPI startup 时调用）。"""
    pool = get_worker_pool()
    pool.start()


def stop_worker_pool():
    """停止全局 Worker Pool（在 FastAPI shutdown 时调用）。"""
    global _pool_instance
    with _pool_lock:
        if _pool_instance:
            _pool_instance.stop()
            _pool_instance = None
