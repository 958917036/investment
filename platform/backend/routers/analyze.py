"""Analyze router - handles single and batch full pipeline analysis requests (L1→L2→L3→L4).

单表架构: 所有任务存储在 analysis_records 表，通过 task_id 批次号分组
"""
import uuid
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, async_session_maker
from models import AnalysisRecord, StockProfile, Market, Status, Decision, Priority, Step
from shennong_client import run_analysis

router = APIRouter(prefix="/api", tags=["analyze"])
logger = logging.getLogger(__name__)


def _strip_market_suffix(code: str) -> str:
    """Strip any market suffix (.HK/.US/.CN/.SH/.SZ) from stock code."""
    code = code.upper().strip()
    for suffix in [".HK", ".US", ".CN", ".SH", ".SZ"]:
        if code.endswith(suffix):
            return code[:-len(suffix)]
    return code


def _detect_market(code: str) -> str:
    """Auto-detect market from stock code, stripping any market suffix (.HK/.US/.CN) first."""
    code = _strip_market_suffix(code)
    # Detect based on the clean code — length is most reliable
    if len(code) == 5 and code.isdigit():
        return "HK"  # HK codes: 5 digits (00700, 09988, 01810...)
    elif len(code) == 4 and code.isdigit():
        return "HK"  # Some HK codes stored as 4 digits
    elif code.isalpha():
        return "US"  # Alphabetic: US stock symbols
    elif code.startswith("00") or code.startswith("60") or code.startswith("68"):
        return "CN"  # A-share: 000xxx, 600xxx, 68xxxx
    return "CN"


async def analyze_task(
    stock_code: str,
    market: str,
    task_id: str,
    record_id: str,
    force_refresh: bool = False,
    priority: int = Priority.SCHEDULED.value
):
    """
    Background task that runs the full shennong analysis pipeline (L1→L2→L3→L4).

    单表架构: 只操作 AnalysisRecord 表

    Steps:
    1. Mark AnalysisRecord as RUNNING
    2. Run full analysis via shennong_client
    3. Update l1_data/l2_data/l3_data/l4_data
    4. Update final_decision, score
    5. Mark AnalysisRecord as COMPLETED/FAILED
    6. Update StockProfile
    """
    import traceback

    logger.info(f"[analyze_task] START | stock={stock_code} market={market} task_id={task_id} record={record_id}")

    async with async_session_maker() as db:
        try:
            # Mark as running
            await db.execute(
                update(AnalysisRecord)
                .where(AnalysisRecord.id == record_id)
                .values(
                    status=Status.RUNNING,
                    step=Step.L1,
                )
            )
            await db.commit()

            # Run the actual analysis in a thread pool
            result = await asyncio.to_thread(run_analysis, stock_code, market=market)
            logger.info(f"[analyze_task] run_analysis returned | keys={list(result.keys())}")

            # Parse results — shennong_client returns data wrapped in "pipeline" key
            pipeline = result.get("pipeline", {})
            l1_data = pipeline.get("L1", {})
            l2_data = pipeline.get("L2", {})
            l3_data = pipeline.get("L3", {})
            l4_data = pipeline.get("L4", {})
            decisions = l4_data.get("decisions", []) if l4_data else []
            five_scores = l4_data.get("five_scores", {}) if l4_data else {}

            # Extract stock name
            stock_name = (
                l1_data.get("stock_name")
                or l2_data.get("stock_name")
                or (decisions[0].get("name") if decisions else None)
                or stock_code
            )

            # Map decision
            raw_decision = (decisions[0].get("decision") if decisions else None) if l4_data else None
            if raw_decision == "BUY":
                mapped_decision = Decision.BUY
            elif raw_decision == "SELL":
                mapped_decision = Decision.SELL
            elif raw_decision == "WATCH":
                mapped_decision = Decision.WATCH
            else:
                mapped_decision = Decision.NO

            # Compute final status: completed if L4 has decisions, else failed
            final_status = Status.COMPLETED if decisions else Status.FAILED
            logger.info(f"[analyze_task] decision={mapped_decision.value} final_status={final_status.value} decisions_count={len(decisions)}")

            # Update analysis record
            await db.execute(
                update(AnalysisRecord)
                .where(AnalysisRecord.id == record_id)
                .values(
                    status=final_status,
                    stock_name=stock_name,
                    step=Step.L4,
                    l1_data=json.dumps(l1_data, ensure_ascii=False) if l1_data else None,
                    l2_data=json.dumps(l2_data, ensure_ascii=False) if l2_data else None,
                    l3_data=json.dumps(l3_data, ensure_ascii=False) if l3_data else None,
                    l4_data=json.dumps(l4_data, ensure_ascii=False) if l4_data else None,
                    final_decision=mapped_decision,
                    score=json.dumps(five_scores, ensure_ascii=False) if five_scores else None,
                    judge_score=decisions[0].get("judge_score") if decisions else None,
                )
            )

            # Update or create stock profile
            profile = await db.get(StockProfile, stock_code)
            if profile:
                profile.analysis_count += 1
                profile.last_analysis_date = datetime.utcnow()
                profile.latest_record_id = record_id
                profile.latest_decision = mapped_decision
                profile.stock_name = stock_name
            else:
                detected = _detect_market(stock_code)
                profile = StockProfile(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    market=Market(detected),
                    analysis_count=1,
                    last_analysis_date=datetime.utcnow(),
                    latest_record_id=record_id,
                    latest_decision=mapped_decision,
                )
                db.add(profile)

            await db.commit()
            logger.info(f"[analyze_task] DONE | {stock_code}: {mapped_decision.value}")

        except Exception as e:
            logger.error(f"[analyze_task] FAILED | {stock_code}: {e}\n{traceback.format_exc()}")
            try:
                # Mark record as failed
                await db.execute(
                    update(AnalysisRecord)
                    .where(AnalysisRecord.id == record_id)
                    .values(
                        status=Status.FAILED,
                        step=Step.L4,
                        error_message=str(e),
                    )
                )
                await db.commit()
                logger.info(f"[analyze_task] Error logged to DB for {stock_code}")
            except Exception as inner_e:
                logger.error(f"[analyze_task] Error logging failed: {inner_e}")


class AnalyzeRequest(BaseModel):
    stock_codes: List[str]
    market: str = "auto"
    force_refresh: bool = Query(default=False, description="Bypass cache and force full re-analysis")
    priority: int = Query(default=Priority.SCHEDULED.value, ge=1, le=3, description="1=manual(high), 3=scheduled(normal)")

    @field_validator("stock_codes")
    def validate_stock_codes(cls, v):
        if not v:
            raise ValueError("stock_codes cannot be empty")
        cleaned = [code.strip().upper() for code in v if code.strip()]
        if not cleaned:
            raise ValueError("stock_codes contains no valid entries")
        return cleaned


class AnalyzeResponse(BaseModel):
    batch_id: str
    tasks: dict  # {stock_code: record_id}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Run full pipeline analysis (L1→L2→L3→L4) for the given stock codes.

    单表架构:
    - 所有记录存储在 analysis_records 表
    - task_id 作为批次号，同批任务共享
    - WorkerPool 从 analysis_records 拉取 PENDING 记录执行

    Features:
    - L1 synchronously triggers BackgroundTask
    - L2-L4 asynchronously via WorkerPool
    - force_refresh: bypass cache
    - priority: 1=manual(high), 3=scheduled(normal)
    - Returns 202 with task_id + record_ids immediately

    Use GET /api/result/{id} to poll for results.
    """
    task_id = str(uuid.uuid4())
    records = {}  # {stock_code: record_id}
    market = request.market if request.market != "auto" else None

    for stock_code in request.stock_codes:
        stock_code = _strip_market_suffix(stock_code.strip().upper())
        if not stock_code:
            continue
        record_id = str(uuid.uuid4())
        detected = market if market else _detect_market(stock_code)

        records[stock_code] = record_id

        # Create AnalysisRecord (单表架构: task_id 作为批次号)
        record = AnalysisRecord(
            id=record_id,
            stock_code=stock_code,
            market=Market(detected),
            status=Status.PENDING,
            task_id=task_id,
            priority=request.priority,
            step=Step.L1,
            force_refresh=1 if request.force_refresh else 0,
        )
        db.add(record)

    await db.commit()

    # Schedule background tasks
    for stock_code in records:
        detected = market if market else _detect_market(stock_code)
        background_tasks.add_task(
            analyze_task,
            stock_code,
            detected,  # Pass actual detected market, not "auto"
            task_id,
            records[stock_code],
            request.force_refresh,
            request.priority
        )

    return AnalyzeResponse(batch_id=task_id, tasks=records)
