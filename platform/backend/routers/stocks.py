"""Stocks router - handles stock library and search."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from database import get_db
from models import StockProfile

router = APIRouter(prefix="/api", tags=["stocks"])


def serialize_profile(profile: StockProfile) -> dict:
    """Serialize a StockProfile to dict."""
    if not profile:
        return None

    return {
        "stock_code": profile.stock_code,
        "stock_name": profile.stock_name,
        "market": profile.market.value if profile.market else None,
        "analysis_count": profile.analysis_count,
        "last_analysis_date": profile.last_analysis_date.isoformat() if profile.last_analysis_date else None,
        "latest_result_id": profile.latest_record_id,
        "latest_decision": profile.latest_decision.value if profile.latest_decision else None,
    }


@router.get("/stocks")
async def list_stocks(db: AsyncSession = Depends(get_db)):
    """List all stocks that have been analyzed."""
    stmt = select(StockProfile).order_by(StockProfile.last_analysis_date.desc())
    result = await db.execute(stmt)
    profiles = result.scalars().all()

    return [serialize_profile(p) for p in profiles]


@router.get("/stocks/search")
async def search_stocks(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db)
):
    """Search stocks by code or name (fuzzy search)."""
    search_term = f"%{q}%"

    stmt = select(StockProfile).where(
        or_(
            StockProfile.stock_code.like(search_term),
            StockProfile.stock_name.like(search_term)
        )
    ).order_by(StockProfile.analysis_count.desc())

    result = await db.execute(stmt)
    profiles = result.scalars().all()

    return [serialize_profile(p) for p in profiles]


@router.get("/stocks/{stock_code}")
async def get_stock(stock_code: str, db: AsyncSession = Depends(get_db)):
    """Get stock profile by code."""
    profile = await db.get(StockProfile, stock_code)
    if not profile:
        raise HTTPException(status_code=404, detail="Stock not found")

    return serialize_profile(profile)
