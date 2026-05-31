"""Queue router - handles analysis task queue viewing and cancellation.

单表架构: 所有任务存储在 analysis_records 表
- task_id: 批次号
- step: L1/L2/L3/L4/veto 当前阶段
- priority: 1=人工(高), 3=定时(普通)
- status: PENDING/RUNNING/COMPLETED/FAILED/CANCELLED
"""
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_

from database import get_db
from models import AnalysisRecord, Status, Step

router = APIRouter(prefix="/api", tags=["queue"])
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
        "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        "status": record.status.value if record.status else None,
        "final_decision": record.final_decision.value if record.final_decision else None,
        "judge_score": record.judge_score,
        "cached_at": record.cached_at.isoformat() if record.cached_at else None,
        "force_refresh": bool(record.force_refresh),
        "error_message": record.error_message,
    }


@router.get("/queue")
async def get_queue(
    status: Optional[str] = Query(None, description="Filter by status: pending, running, completed, failed, cancelled"),
    stock_code: Optional[str] = Query(None, description="Filter by stock code"),
    priority: Optional[int] = Query(None, description="Filter by priority: 1=manual, 3=scheduled"),
    task_id: Optional[str] = Query(None, description="Filter by task_id (batch)"),
    step: Optional[str] = Query(None, description="Filter by step: L1, L2, veto, L3, L4"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """
    Get analysis queue from analysis_records table.

    Shows pending and running tasks with priority information.
    priority 1 = manual (high priority), 3 = scheduled (normal priority)
    task_id groups related tasks in the same batch
    """
    stmt = select(AnalysisRecord).order_by(AnalysisRecord.priority.asc(), AnalysisRecord.timestamp.desc())

    conditions = []

    if status:
        try:
            status_enum = Status(status.lower())
            stmt = stmt.where(AnalysisRecord.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if stock_code:
        stmt = stmt.where(AnalysisRecord.stock_code == stock_code.upper())

    if priority:
        stmt = stmt.where(AnalysisRecord.priority == priority)

    if task_id:
        stmt = stmt.where(AnalysisRecord.task_id == task_id)

    if step:
        try:
            step_enum = Step(step.upper())
            stmt = stmt.where(AnalysisRecord.step == step_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid step: {step}")

    # Get total count
    count_stmt = select(func.count(AnalysisRecord.id))
    if status:
        count_stmt = count_stmt.where(AnalysisRecord.status == Status(status.lower()))
    if stock_code:
        count_stmt = count_stmt.where(AnalysisRecord.stock_code == stock_code.upper())
    if priority:
        count_stmt = count_stmt.where(AnalysisRecord.priority == priority)
    if task_id:
        count_stmt = count_stmt.where(AnalysisRecord.task_id == task_id)
    if step:
        count_stmt = count_stmt.where(AnalysisRecord.step == Step(step.upper()))

    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply pagination
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    records = result.scalars().all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [serialize_record(r) for r in records]
    }


@router.delete("/queue/{record_id}")
async def cancel_from_queue(record_id: str, db: AsyncSession = Depends(get_db)):
    """
    Cancel a pending analysis task.
    Only tasks with status=pending can be cancelled.
    Running or completed tasks cannot be cancelled.
    """
    record = await db.get(AnalysisRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis task not found")

    if record.status != Status.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task with status: {record.status.value}. Only pending tasks can be cancelled."
        )

    # Set to cancelled
    await db.execute(
        update(AnalysisRecord)
        .where(AnalysisRecord.id == record_id)
        .values(status=Status.CANCELLED)
    )

    await db.commit()
    logger.info(f"[Queue] Cancelled analysis task {record_id}")
    return {"message": "Analysis task cancelled", "id": record_id}


@router.delete("/queue/batch/{task_id}")
async def cancel_batch_queue(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Cancel all pending tasks in a batch (by task_id).

    单表架构实现:
    - UPDATE analysis_records WHERE task_id AND status=PENDING → status=CANCELLED
    - Does NOT affect RUNNING or COMPLETED tasks

    Returns the count of cancelled items.
    """
    # Find all pending records with this task_id
    pending_records_stmt = select(AnalysisRecord).where(
        AnalysisRecord.task_id == task_id,
        AnalysisRecord.status == Status.PENDING
    )
    pending_records_result = await db.execute(pending_records_stmt)
    pending_records = pending_records_result.scalars().all()

    cancelled_count = 0
    if pending_records:
        record_ids = [r.id for r in pending_records]
        await db.execute(
            update(AnalysisRecord)
            .where(AnalysisRecord.id.in_(record_ids))
            .values(status=Status.CANCELLED)
        )
        cancelled_count = len(record_ids)

    await db.commit()

    logger.info(f"[Queue] Batch {task_id} cancelled: {cancelled_count} records")
    return {
        "message": "Batch cancelled",
        "task_id": task_id,
        "cancelled_count": cancelled_count
    }
