"""Reflection router - handles user reflection on analysis results."""
import json
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database import get_db
from models import Reflection, AnalysisRecord

router = APIRouter(prefix="/api", tags=["reflection"])


class ReflectionRequest(BaseModel):
    analysis_id: str
    wrong_analysis: str  # 'A' or 'B'
    reflection_text: str
    error_tags: List[str]
    correct_analysis_id: str = None


@router.post("/reflection")
async def submit_reflection(
    request: ReflectionRequest,
    db: AsyncSession = Depends(get_db)
):
    """Submit a reflection on which analysis was wrong."""
    if request.wrong_analysis not in ['A', 'B']:
        raise HTTPException(status_code=400, detail="wrong_analysis must be 'A' or 'B'")

    # Verify the analysis exists
    analysis = await db.get(AnalysisRecord, request.analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    reflection = Reflection(
        id=str(uuid.uuid4()),
        analysis_id=request.analysis_id,
        wrong_analysis=request.wrong_analysis,
        reflection_text=request.reflection_text,
        error_tags=json.dumps(request.error_tags),
        correct_analysis_id=request.correct_analysis_id,
    )

    db.add(reflection)
    await db.commit()

    return {"success": True, "reflection_id": reflection.id}


@router.get("/reflections/{stock_code}")
async def get_reflections(
    stock_code: str,
    db: AsyncSession = Depends(get_db)
):
    """Get all reflections for a stock code."""
    from sqlalchemy import select

    # Get all analysis IDs for this stock
    stmt = select(AnalysisRecord.id).where(AnalysisRecord.stock_code == stock_code)
    result = await db.execute(stmt)
    analysis_ids = [r[0] for r in result.fetchall()]

    if not analysis_ids:
        return []

    # Get reflections for these analyses
    stmt = select(Reflection).where(
        Reflection.analysis_id.in_(analysis_ids)
    ).order_by(Reflection.created_at.desc())

    result = await db.execute(stmt)
    reflections = result.scalars().all()

    return [
        {
            "id": r.id,
            "analysis_id": r.analysis_id,
            "wrong_analysis": r.wrong_analysis,
            "reflection_text": r.reflection_text,
            "error_tags": json.loads(r.error_tags) if r.error_tags else [],
            "correct_analysis_id": r.correct_analysis_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reflections
    ]
