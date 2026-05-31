"""Portfolio router - handles position management."""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models import Portfolio, Watchlist, Market, PositionType
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["portfolio"])


class PortfolioCreate(BaseModel):
    stock_code: str
    stock_name: Optional[str] = None
    market: Market = Market.CN
    position_type: PositionType = PositionType.LONG
    quantity: float = 0
    avg_cost: float = 0.0
    current_price: Optional[float] = None
    notes: Optional[str] = None


class PortfolioUpdate(BaseModel):
    stock_code: Optional[str] = None
    stock_name: Optional[str] = None
    market: Optional[Market] = None
    position_type: Optional[PositionType] = None
    quantity: Optional[float] = None
    avg_cost: Optional[float] = None
    current_price: Optional[float] = None
    notes: Optional[str] = None


class WatchlistCreate(BaseModel):
    stock_code: str
    stock_name: Optional[str] = None
    market: Market = Market.CN
    reason: Optional[str] = None
    target_price: Optional[float] = None


class WatchlistUpdate(BaseModel):
    stock_code: Optional[str] = None
    stock_name: Optional[str] = None
    market: Optional[Market] = None
    reason: Optional[str] = None
    target_price: Optional[float] = None


def serialize_portfolio(p: Portfolio) -> dict:
    """Serialize a Portfolio to dict."""
    if not p:
        return None
    total_cost = p.quantity * p.avg_cost if p.quantity and p.avg_cost else 0
    current_value = p.quantity * p.current_price if p.quantity and p.current_price else 0
    profit_loss = current_value - total_cost if p.current_price else None
    profit_loss_pct = (profit_loss / total_cost * 100) if total_cost > 0 and profit_loss is not None else None

    return {
        "id": p.id,
        "stock_code": p.stock_code,
        "stock_name": p.stock_name,
        "market": p.market.value if p.market else None,
        "position_type": p.position_type.value if p.position_type else None,
        "quantity": p.quantity,
        "avg_cost": p.avg_cost,
        "current_price": p.current_price,
        "total_cost": round(total_cost, 2),
        "current_value": round(current_value, 2),
        "profit_loss": round(profit_loss, 2) if profit_loss is not None else None,
        "profit_loss_pct": round(profit_loss_pct, 2) if profit_loss_pct is not None else None,
        "notes": p.notes,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# === Portfolio CRUD ===

@router.get("/portfolio")
async def list_portfolio(db: AsyncSession = Depends(get_db)):
    """List all positions in portfolio."""
    stmt = select(Portfolio).order_by(Portfolio.updated_at.desc())
    result = await db.execute(stmt)
    positions = result.scalars().all()
    return [serialize_portfolio(p) for p in positions]


@router.get("/portfolio/summary")
async def get_portfolio_summary(db: AsyncSession = Depends(get_db)):
    """Get portfolio summary statistics."""
    stmt = select(Portfolio)
    result = await db.execute(stmt)
    positions = result.scalars().all()

    total_cost = 0.0
    total_value = 0.0
    by_market = {}

    for p in positions:
        cost = p.quantity * p.avg_cost if p.quantity and p.avg_cost else 0
        value = p.quantity * p.current_price if p.quantity and p.current_price else cost
        total_cost += cost
        total_value += value

        market_key = p.market.value if p.market else "UNKNOWN"
        if market_key not in by_market:
            by_market[market_key] = {"cost": 0, "value": 0, "count": 0}
        by_market[market_key]["cost"] += cost
        by_market[market_key]["value"] += value
        by_market[market_key]["count"] += 1

    return {
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "profit_loss": round(total_value - total_cost, 2),
        "profit_loss_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost > 0 else 0,
        "position_count": len(positions),
        "by_market": {k: {"cost": round(v["cost"], 2), "value": round(v["value"], 2), "count": v["count"]} for k, v in by_market.items()},
    }


@router.get("/portfolio/{position_id}")
async def get_portfolio_position(position_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific portfolio position."""
    position = await db.get(Portfolio, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    return serialize_portfolio(position)


@router.post("/portfolio")
async def create_portfolio_position(
    body: PortfolioCreate,
    db: AsyncSession = Depends(get_db)
):
    """Add a new position to portfolio."""
    position = Portfolio(
        stock_code=body.stock_code,
        stock_name=body.stock_name,
        market=body.market,
        position_type=body.position_type,
        quantity=body.quantity,
        avg_cost=body.avg_cost,
        current_price=body.current_price,
        notes=body.notes,
    )
    db.add(position)
    await db.commit()
    await db.refresh(position)
    return serialize_portfolio(position)


@router.put("/portfolio/{position_id}")
async def update_portfolio_position(
    position_id: str,
    body: PortfolioUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update an existing portfolio position."""
    position = await db.get(Portfolio, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None and hasattr(position, field):
            setattr(position, field, value)

    position.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(position)
    return serialize_portfolio(position)


@router.delete("/portfolio/{position_id}")
async def delete_portfolio_position(position_id: str, db: AsyncSession = Depends(get_db)):
    """Remove a position from portfolio. Accepts stock_code (string) as position_id for convenience."""
    # Allow deleting by stock_code for simplicity
    stmt = select(Portfolio).where(Portfolio.stock_code == position_id)
    result = await db.execute(stmt)
    position = result.scalars().first()
    if not position:
        # Try UUID lookup
        position = await db.get(Portfolio, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    await db.delete(position)
    await db.commit()
    return {"message": "Position deleted"}


# === Watchlist CRUD ===

def serialize_watchlist(w: Watchlist) -> dict:
    """Serialize a Watchlist item to dict."""
    if not w:
        return None
    return {
        "id": w.id,
        "stock_code": w.stock_code,
        "stock_name": w.stock_name,
        "market": w.market.value if w.market else None,
        "reason": w.reason,
        "target_price": w.target_price,
        "added_at": w.added_at.isoformat() if w.added_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


@router.get("/watchlist")
async def list_watchlist(
    market: Optional[Market] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all stocks in watchlist, optionally filtered by market."""
    stmt = select(Watchlist)
    if market:
        stmt = stmt.where(Watchlist.market == market)
    stmt = stmt.order_by(Watchlist.added_at.desc())
    result = await db.execute(stmt)
    items = result.scalars().all()
    return [serialize_watchlist(item) for item in items]


@router.get("/watchlist/{item_id}")
async def get_watchlist_item(item_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific watchlist item."""
    item = await db.get(Watchlist, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return serialize_watchlist(item)


@router.post("/watchlist")
async def create_watchlist_item(
    body: WatchlistCreate,
    db: AsyncSession = Depends(get_db)
):
    """Add a stock to watchlist."""
    # Check if already exists
    stmt = select(Watchlist).where(Watchlist.stock_code == body.stock_code)
    result = await db.execute(stmt)
    existing = result.scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="Stock already in watchlist")

    item = Watchlist(
        stock_code=body.stock_code,
        stock_name=body.stock_name,
        market=body.market,
        reason=body.reason,
        target_price=body.target_price,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return serialize_watchlist(item)


@router.put("/watchlist/{item_id}")
async def update_watchlist_item(
    item_id: str,
    body: WatchlistUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a watchlist item."""
    item = await db.get(Watchlist, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None and hasattr(item, field):
            setattr(item, field, value)

    item.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(item)
    return serialize_watchlist(item)


@router.delete("/watchlist/{item_id}")
async def delete_watchlist_item(item_id: str, db: AsyncSession = Depends(get_db)):
    """Remove a stock from watchlist. Accepts stock_code (string) as item_id for convenience."""
    # Try stock_code lookup first
    stmt = select(Watchlist).where(Watchlist.stock_code == item_id)
    result = await db.execute(stmt)
    item = result.scalars().first()
    if not item:
        # Try UUID lookup
        item = await db.get(Watchlist, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    await db.delete(item)
    await db.commit()
    return {"message": "Watchlist item deleted"}
