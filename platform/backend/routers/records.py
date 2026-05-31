"""Records router - handles analysis history record queries with filtering.

单表架构: 使用 task_id (替代 batch_id), l1_data/l2_data/l3_data/l4_data (替代 L1_result 等)
"""
import json
import math
from typing import Optional, List, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from database import get_db
from models import AnalysisRecord, Status, Decision, Market, Step

router = APIRouter(prefix="/api", tags=["records"])


def _clean_nan(value: Any) -> Any:
    """Replace NaN and infinity values with None."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    return value


def _safe_json_loads(data: Any) -> Any:
    """Safely parse JSON string, replacing NaN/Infinity with None."""
    if not data:
        return None
    try:
        import re
        # Replace Python NaN/Infinity literals with valid JSON null before parsing
        cleaned = re.sub(r'\bNaN\b', 'null', str(data))
        cleaned = re.sub(r'\bInfinity\b', 'null', cleaned)
        cleaned = re.sub(r'\b-\Infinity\b', 'null', cleaned)
        return json.loads(cleaned)
    except (json.JSONDecodeError, Exception):
        return None


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
        "parent_record_id": record.parent_record_id,
        "priority": record.priority,
        "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        "status": record.status.value if record.status else None,
        "l1_data": _safe_json_loads(record.l1_data),
        "l2_data": _safe_json_loads(record.l2_data),
        "l3_data": _safe_json_loads(record.l3_data),
        "l4_data": _safe_json_loads(record.l4_data),
        "final_decision": record.final_decision.value if record.final_decision else None,
        "score": json.loads(record.score) if record.score else None,
        "judge_score": _clean_nan(record.judge_score),
        "cached_at": record.cached_at.isoformat() if record.cached_at else None,
        "force_refresh": bool(record.force_refresh),
        "error_message": record.error_message,
        "retry_count": record.retry_count,
    }


class RecordDetail(BaseModel):
    """Detailed record response."""
    id: str
    stock_code: str
    stock_name: Optional[str] = None
    market: Optional[str] = None
    task_id: Optional[str] = None
    step: Optional[str] = None
    parent_record_id: Optional[str] = None
    priority: Optional[int] = None
    timestamp: Optional[str] = None
    status: Optional[str] = None
    l1_data: Optional[dict] = None
    l2_data: Optional[dict] = None
    l3_data: Optional[dict] = None
    l4_data: Optional[dict] = None
    final_decision: Optional[str] = None
    score: Optional[dict] = None
    judge_score: Optional[float] = None
    cached_at: Optional[str] = None
    force_refresh: Optional[bool] = None
    error_message: Optional[str] = None
    retry_count: Optional[int] = None


@router.get("/records")
async def query_records(
    stock_code: Optional[str] = Query(None, description="Filter by stock code"),
    market: Optional[str] = Query(None, description="Filter by market: CN, HK, US"),
    status: Optional[str] = Query(None, description="Filter by status: pending, running, completed, failed"),
    decision: Optional[str] = Query(None, description="Filter by decision: BUY, SELL, WATCH, NO"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
    task_id: Optional[str] = Query(None, description="Filter by task_id (batch)"),
    step: Optional[str] = Query(None, description="Filter by step: L1, L2, veto, L3, L4"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """
    Query analysis history records with flexible filtering.
    Returns paginated results ordered by timestamp descending.
    """
    stmt = select(AnalysisRecord)
    count_stmt = select(func.count(AnalysisRecord.id))

    conditions = []

    if stock_code:
        conditions.append(AnalysisRecord.stock_code == stock_code.upper())

    if market:
        try:
            market_enum = Market(market.upper())
            conditions.append(AnalysisRecord.market == market_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid market: {market}")

    if status:
        try:
            status_enum = Status(status.lower())
            conditions.append(AnalysisRecord.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if decision:
        try:
            decision_enum = Decision(decision.upper())
            conditions.append(AnalysisRecord.final_decision == decision_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid decision: {decision}")

    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            conditions.append(AnalysisRecord.timestamp >= start_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid start_date format: {start_date}")

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            conditions.append(AnalysisRecord.timestamp <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid end_date format: {end_date}")

    if task_id:
        conditions.append(AnalysisRecord.task_id == task_id)

    if step:
        try:
            step_enum = Step(step.upper())
            conditions.append(AnalysisRecord.step == step_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid step: {step}")

    if conditions:
        stmt = stmt.where(and_(*conditions))
        count_stmt = count_stmt.where(and_(*conditions))

    # Get total count
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Order by timestamp descending (newest first)
    stmt = stmt.order_by(AnalysisRecord.timestamp.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    records = result.scalars().all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [serialize_record(r) for r in records]
    }


@router.get("/records/{record_id}")
async def get_record_detail(record_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get detailed information for a single analysis record by ID.
    Returns the full record including all L1-L4 data.
    """
    record = await db.get(AnalysisRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    return serialize_record(record)


@router.get("/records/stock/{stock_code}")
async def get_stock_records(
    stock_code: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all analysis records for a specific stock code.
    Returns records ordered by timestamp descending.
    """
    stmt = (
        select(AnalysisRecord)
        .where(AnalysisRecord.stock_code == stock_code.upper())
        .order_by(AnalysisRecord.timestamp.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    return {
        "stock_code": stock_code.upper(),
        "total": len(records),
        "items": [serialize_record(r) for r in records]
    }
