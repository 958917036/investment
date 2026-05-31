"""Batch router - handles batch task management with proper cancel logic.

单表架构: analysis_records 表通过 task_id 字段实现批次管理
- 同一批次的记录共享相同的 task_id
- 批量取消: UPDATE analysis_records WHERE task_id AND status=PENDING → CANCELLED
- 批量重试: UPDATE analysis_records WHERE task_id AND status=FAILED → PENDING
"""
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from database import get_db, async_session_maker
from models import AnalysisRecord, Status, Step

router = APIRouter(prefix="/api", tags=["batch"])
logger = logging.getLogger(__name__)


def serialize_record(record: AnalysisRecord) -> dict:
    """Serialize an AnalysisRecord to dict."""
    if not record:
        return None
    return {
        "id": record.id,
        "stock_code": record.stock_code,
        "stock_name": record.stock_name,
        "market": record.market.value if record.market else None,
        "task_id": record.task_id,
        "step": record.step.value if record.step else None,
        "priority": record.priority,
        "status": record.status.value if record.status else None,
        "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        "final_decision": record.final_decision.value if record.final_decision else None,
        "judge_score": record.judge_score,
        "error_message": record.error_message,
        "retry_count": record.retry_count,
    }


def serialize_batch_summary(task_id: str, records: list) -> dict:
    """Generate batch summary from a list of records with same task_id."""
    total = len(records)
    completed = sum(1 for r in records if r.status == Status.COMPLETED)
    failed = sum(1 for r in records if r.status == Status.FAILED)
    pending = sum(1 for r in records if r.status == Status.PENDING)
    running = sum(1 for r in records if r.status == Status.RUNNING)
    cancelled = sum(1 for r in records if r.status == Status.CANCELLED)

    # Get decision counts
    buy_count = sum(1 for r in records if r.final_decision and r.final_decision.value == "BUY")
    watch_count = sum(1 for r in records if r.final_decision and r.final_decision.value == "WATCH")

    return {
        "task_id": task_id,
        "total_count": total,
        "completed_count": completed,
        "failed_count": failed,
        "pending_count": pending,
        "running_count": running,
        "cancelled_count": cancelled,
        "buy_count": buy_count,
        "watch_count": watch_count,
        "progress": completed / total if total > 0 else 0,
    }


@router.get("/batch/{task_id}")
async def get_batch(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get batch task status by task_id.

    Returns batch summary and all records in the batch.
    """
    stmt = select(AnalysisRecord).where(AnalysisRecord.task_id == task_id)
    result = await db.execute(stmt)
    records = result.scalars().all()

    if not records:
        raise HTTPException(status_code=404, detail="Batch not found")

    summary = serialize_batch_summary(task_id, records)
    summary["records"] = [serialize_record(r) for r in records]

    return summary


@router.get("/batches")
async def list_batches(
    status: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """
    List all batches (grouped by task_id).

    Returns batch summaries with counts per status.
    """
    # Get all unique task_ids with their records
    stmt = select(AnalysisRecord).order_by(AnalysisRecord.timestamp.desc()).limit(limit * 5)
    result = await db.execute(stmt)
    all_records = result.scalars().all()

    # Group by task_id
    batches: Dict[str, List[AnalysisRecord]] = {}
    for record in all_records:
        tid = record.task_id or record.id  # Use id if task_id is None (single record batch)
        if tid not in batches:
            batches[tid] = []
        batches[tid].append(record)

    summaries = []
    for task_id, records in batches.items():
        summaries.append(serialize_batch_summary(task_id, records))

    # Filter by status if provided
    if status:
        try:
            status_enum = Status(status.lower())
            summaries = [s for s in summaries if s.get(f"{status.lower()}_count", 0) > 0]
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    return summaries[:limit]


@router.post("/batch/{task_id}/retry")
async def retry_batch(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retry all failed analyses in a batch.
    Resets failed records to PENDING and restarts the WorkerPool processing.

    单表架构: 直接更新 analysis_records 表
    """
    # Find failed records
    failed_stmt = select(AnalysisRecord).where(
        AnalysisRecord.task_id == task_id,
        AnalysisRecord.status == Status.FAILED
    )
    failed_result = await db.execute(failed_stmt)
    failed_records = failed_result.scalars().all()

    if not failed_records:
        return {"message": "No failed records to retry", "count": 0}

    # Reset failed records to PENDING
    record_ids = [r.id for r in failed_records]
    await db.execute(
        update(AnalysisRecord)
        .where(AnalysisRecord.id.in_(record_ids))
        .values(
            status=Status.PENDING,
            error_message=None,
            retry_count=AnalysisRecord.retry_count + 1
        )
    )

    await db.commit()

    count = len(failed_records)
    logger.info(f"[Batch] Retry batch {task_id}: {count} records reset to PENDING")
    return {"message": "Retrying failed analyses", "count": count}


@router.delete("/batch/{task_id}")
async def cancel_batch(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Cancel all pending tasks in a batch (only PENDING tasks can be cancelled).

    单表架构实现:
    1. UPDATE analysis_records WHERE task_id AND status=PENDING → status=CANCELLED
    2. Does NOT touch RUNNING or COMPLETED tasks

    Returns the count of cancelled tasks.
    """
    # Find pending records for this batch
    pending_stmt = select(AnalysisRecord).where(
        AnalysisRecord.task_id == task_id,
        AnalysisRecord.status == Status.PENDING
    )
    pending_result = await db.execute(pending_stmt)
    pending_records = pending_result.scalars().all()

    cancelled_count = 0

    if pending_records:
        record_ids = [r.id for r in pending_records]
        # Cancel all pending records
        await db.execute(
            update(AnalysisRecord)
            .where(AnalysisRecord.id.in_(record_ids))
            .values(status=Status.CANCELLED)
        )
        cancelled_count = len(record_ids)

    await db.commit()

    logger.info(f"[Batch] Cancelled batch {task_id}: {cancelled_count} records")
    return {
        "message": "Batch cancelled",
        "task_id": task_id,
        "cancelled_count": cancelled_count
    }
