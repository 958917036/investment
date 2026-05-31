"""L1 Analyze router - handles L1 screening-only analysis requests with 24h cache.

单表架构: task_id 作为批次号，替代原有的 batch_id
"""
import uuid
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update, select, and_

from database import get_db, async_session_maker
from models import AnalysisRecord, Market, Status, Decision, Priority, Step

router = APIRouter(prefix="/api", tags=["l1"])
logger = logging.getLogger(__name__)

# Cache TTL: 24 hours
L1_CACHE_TTL_HOURS = 24


def _strip_market_suffix(code: str) -> str:
    """Strip any market suffix (.HK/.US/.CN/.SH/.SZ) from stock code."""
    code = code.upper().strip()
    for suffix in [".HK", ".US", ".CN", ".SH", ".SZ"]:
        if code.endswith(suffix):
            return code[:-len(suffix)]
    return code


def _detect_market(code: str) -> str:
    """Auto-detect market from stock code."""
    code = _strip_market_suffix(code.upper().strip())
    if code.startswith("00") or code.startswith("60") or code.startswith("68"):
        return "CN"
    elif code.startswith("HK") or len(code) == 5 or (code.isdigit() and len(code) == 4):
        return "HK"
    elif "." in code or code.isalpha():
        return "US"
    return "CN"


def _make_cache_key(stock_code: str, market: str) -> str:
    """Create a cache key for L1 results based on stock_code, market, and date."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return f"{stock_code}:{market}:{today}"


def _is_l1_cached(record: AnalysisRecord, force_refresh: bool = False) -> bool:
    """
    Check if L1 result is cached and still valid.

    Returns True if:
    - record has l1_data
    - cached_at is within 24 hours
    - force_refresh is False
    """
    if force_refresh:
        return False
    if not record or not record.l1_data:
        return False
    if not record.cached_at:
        return False

    age = datetime.utcnow() - record.cached_at
    return age.total_seconds() < L1_CACHE_TTL_HOURS * 3600


async def l1_analyze_task(
    stock_code: str,
    market: str,
    record_id: str,
    force_refresh: bool = False,
    priority: int = Priority.SCHEDULED.value
):
    """
    Background task that runs L1 screening only with caching.

    Cache logic:
    - If l1_data exists and cached_at < 24h → return cached result
    - force_refresh=True → bypass cache, re-run L1
    """
    import traceback
    import runpy
    import os as _os

    SHENNONG_ROOT = _os.environ.get("SHENNONG_ROOT", _os.path.expanduser("~/.hermes/investment"))
    logger.info(f"[l1_task] START | stock={stock_code} market={market} id={record_id} force_refresh={force_refresh}")

    async with async_session_maker() as db:
        try:
            # Check cache first (unless force_refresh)
            if not force_refresh:
                record = await db.get(AnalysisRecord, record_id)
                if record and record.l1_data and record.cached_at:
                    age = datetime.utcnow() - record.cached_at
                    if age.total_seconds() < L1_CACHE_TTL_HOURS * 3600:
                        logger.info(f"[l1_task] CACHE HIT | {stock_code}: cached at {record.cached_at}, age={age.total_seconds():.0f}s")
                        return  # Already has valid cache

            # Run L1 analysis in thread pool
            def do_l1():
                ns = runpy.run_path(
                    _os.path.join(SHENNONG_ROOT, "main", "shennong.py"),
                    run_name="run_pipeline"
                )
                run_pipeline = ns["run_pipeline"]
                try:
                    return run_pipeline(symbols=[stock_code], market=market, mode="L1")
                except TypeError:
                    return run_pipeline(symbols=[stock_code], market=market, mode="full")

            result = await asyncio.to_thread(do_l1)
            logger.info(f"[l1_task] run_pipeline returned | keys={list(result.keys())}")

            l1_data = result.get("L1", {})

            # Extract stock name from candidates
            candidates = l1_data.get("candidates", []) if l1_data else []
            stock_name = (
                l1_data.get("stock_name")
                or (candidates[0].get("name") if candidates else None)
                or stock_code
            )

            has_candidates = bool(candidates)
            final_status = Status.COMPLETED if has_candidates else Status.FAILED

            # Update record with L1 result and cache timestamp
            await db.execute(
                update(AnalysisRecord)
                .where(AnalysisRecord.id == record_id)
                .values(
                    status=final_status,
                    stock_name=stock_name,
                    step=Step.L1,
                    l1_data=json.dumps(l1_data, ensure_ascii=False) if l1_data else None,
                    cached_at=datetime.utcnow(),
                    cache_key=_make_cache_key(stock_code, market),
                )
            )
            await db.commit()
            logger.info(f"[l1_task] DONE | {stock_code}: status={final_status.value}, candidates={len(candidates)}, cached_at={datetime.utcnow()}")

        except Exception as e:
            logger.error(f"[l1_task] FAILED | {stock_code}: {e}\n{traceback.format_exc()}")
            try:
                await db.execute(
                    update(AnalysisRecord)
                    .where(AnalysisRecord.id == record_id)
                    .values(status=Status.FAILED, step=Step.L1)
                )
                await db.commit()
            except Exception as inner_e:
                logger.error(f"[l1_task] Error logging failed: {inner_e}")


class L1AnalyzeRequest(BaseModel):
    stock_codes: List[str]
    market: str = "auto"
    force_refresh: bool = False
    priority: int = Query(default=Priority.SCHEDULED.value, ge=1, le=3, description="1=manual(high), 3=scheduled(normal)")

    @field_validator("stock_codes")
    def validate_stock_codes(cls, v):
        if not v:
            raise ValueError("stock_codes cannot be empty")
        cleaned = [code.strip().upper() for code in v if code.strip()]
        if not cleaned:
            raise ValueError("stock_codes contains no valid entries")
        return cleaned


class L1AnalyzeResponse(BaseModel):
    task_id: str
    records: dict


@router.post("/l1/analyze", response_model=L1AnalyzeResponse)
async def l1_analyze(
    request: L1AnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Run L1 (screening) analysis only for the given stock codes.

    单表架构: task_id 作为批次号

    Features:
    - 24h L1 cache: same stock_code+market within 24h returns cached result
    - force_refresh=true: bypass cache and force re-run
    - priority: 1=manual(high priority), 3=scheduled(normal)

    Returns immediately with task IDs for tracking (202 Accepted).
    """
    task_id = str(uuid.uuid4())
    records = {}
    market = request.market if request.market != "auto" else None

    for stock_code in request.stock_codes:
        stock_code = _strip_market_suffix(stock_code.strip().upper())
        if not stock_code:
            continue
        record_id = str(uuid.uuid4())
        detected = market if market else _detect_market(stock_code)
        cache_key = _make_cache_key(stock_code, detected)

        # Check for existing record with valid cache (unless force_refresh)
        existing_stmt = select(AnalysisRecord).where(
            and_(
                AnalysisRecord.stock_code == stock_code,
                AnalysisRecord.market == Market(detected),
                AnalysisRecord.cache_key == cache_key,
                AnalysisRecord.l1_data.isnot(None)
            )
        )
        existing_result = await db.execute(existing_stmt)
        existing = existing_result.scalars().first()

        if existing and not request.force_refresh:
            # Check if cache is still valid
            if existing.cached_at:
                age = datetime.utcnow() - existing.cached_at
                if age.total_seconds() < L1_CACHE_TTL_HOURS * 3600:
                    # Use existing cached record
                    records[stock_code] = existing.id
                    logger.info(f"[l1] CACHE HIT | {stock_code}: reusing record {existing.id}, cached_at={existing.cached_at}")
                    continue

        # Create new analysis record
        record = AnalysisRecord(
            id=record_id,
            stock_code=stock_code,
            market=Market(detected),
            status=Status.PENDING,
            task_id=task_id,
            priority=request.priority,
            step=Step.L1,
            cache_key=cache_key,
        )
        db.add(record)
        records[stock_code] = record_id

    await db.commit()

    # Schedule background tasks for new records
    for stock_code, record_id in records.items():
        background_tasks.add_task(
            l1_analyze_task,
            stock_code,
            "auto",
            record_id,
            request.force_refresh,
            request.priority
        )

    return L1AnalyzeResponse(task_id=task_id, records=records)
