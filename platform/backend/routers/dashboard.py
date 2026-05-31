"""Dashboard router — platform statistics and overview."""
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from models import AnalysisRecord, StockProfile, Watchlist, Status, Decision

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    days: int = Query(7, ge=1, le=90, description="Time window in days"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get dashboard statistics for the platform overview.

    Returns:
    - total_analyses: 总分析次数
    - stocks_analyzed: 独立股票数量
    - buy_count: BUY 决策数量
    - watch_count: WATCH 决策数量
    - week_analyses: 本周分析次数
    - active_tasks: 活跃任务数
    - recent_analyses: 最近分析记录
    - decision_distribution: 决策分布
    - market_distribution: 市场分布
    """
    # Time window
    cutoff = datetime.utcnow() - timedelta(days=days)

    # Total analyses
    total_stmt = select(func.count(AnalysisRecord.id))
    total_result = await db.execute(total_stmt)
    total_analyses = total_result.scalar() or 0

    # Distinct stocks analyzed
    stocks_stmt = select(func.count(func.distinct(AnalysisRecord.stock_code)))
    stocks_result = await db.execute(stocks_stmt)
    stocks_analyzed = stocks_result.scalar() or 0

    # Decision counts
    buy_stmt = select(func.count(AnalysisRecord.id)).where(
        AnalysisRecord.final_decision == Decision.BUY
    )
    buy_result = await db.execute(buy_stmt)
    buy_count = buy_result.scalar() or 0

    watch_stmt = select(func.count(AnalysisRecord.id)).where(
        AnalysisRecord.final_decision == Decision.WATCH
    )
    watch_result = await db.execute(watch_stmt)
    watch_count = watch_result.scalar() or 0

    sell_stmt = select(func.count(AnalysisRecord.id)).where(
        AnalysisRecord.final_decision == Decision.SELL
    )
    sell_result = await db.execute(sell_stmt)
    sell_count = sell_result.scalar() or 0

    no_stmt = select(func.count(AnalysisRecord.id)).where(
        AnalysisRecord.final_decision == Decision.NO
    )
    no_result = await db.execute(no_stmt)
    no_count = no_result.scalar() or 0

    # Recent window analyses
    recent_stmt = select(func.count(AnalysisRecord.id)).where(
        AnalysisRecord.timestamp >= cutoff
    )
    recent_result = await db.execute(recent_stmt)
    window_analyses = recent_result.scalar() or 0

    # Recent analyses (last 10 COMPLETED, distinct per stock_code, latest first)
    # Uses DISTINCT ON to keep only the most recent record per stock_code
    from sqlalchemy import distinct, literal_column
    recent_list_stmt = (
        select(AnalysisRecord)
        .where(AnalysisRecord.status == Status.COMPLETED)
        .order_by(AnalysisRecord.stock_code, AnalysisRecord.timestamp.desc())
        .distinct(AnalysisRecord.stock_code)
        .order_by(AnalysisRecord.stock_code, AnalysisRecord.timestamp.desc())
    )
    # Reorder by timestamp globally, then limit
    recent_list_stmt = (
        select(AnalysisRecord)
        .where(AnalysisRecord.status == Status.COMPLETED)
        .where(
            AnalysisRecord.id.in_(
                select(func.max(AnalysisRecord.id))
                .where(AnalysisRecord.status == Status.COMPLETED)
                .where(AnalysisRecord.step == "L4")
                .group_by(AnalysisRecord.stock_code)
            )
        )
        .order_by(AnalysisRecord.timestamp.desc())
        .limit(10)
    )
    recent_list_result = await db.execute(recent_list_stmt)
    recent_list = recent_list_result.scalars().all()

    # Active tasks (pending + running)
    active_stmt = select(func.count(AnalysisRecord.id)).where(
        AnalysisRecord.status.in_([Status.PENDING, Status.RUNNING])
    )
    active_result = await db.execute(active_stmt)
    active_tasks = active_result.scalar() or 0

    # Market distribution
    market_dist_stmt = (
        select(
            AnalysisRecord.market,
            func.count(AnalysisRecord.id).label("count")
        )
        .group_by(AnalysisRecord.market)
    )
    market_dist_result = await db.execute(market_dist_stmt)
    market_distribution = {
        row[0].value if row[0] else "UNKNOWN": row[1]
        for row in market_dist_result.fetchall()
    }

    # Status distribution
    status_dist_stmt = (
        select(
            AnalysisRecord.status,
            func.count(AnalysisRecord.id).label("count")
        )
        .group_by(AnalysisRecord.status)
    )
    status_dist_result = await db.execute(status_dist_stmt)
    status_distribution = {
        row[0].value if row[0] else "UNKNOWN": row[1]
        for row in status_dist_result.fetchall()
    }

    # Completed analyses in window
    completed_stmt = select(func.count(AnalysisRecord.id)).where(
        AnalysisRecord.timestamp >= cutoff,
        AnalysisRecord.status == Status.COMPLETED
    )
    completed_result = await db.execute(completed_stmt)
    completed_count = completed_result.scalar() or 0

    return {
        "total_analyses": total_analyses,
        "stocks_analyzed": stocks_analyzed,
        "buy_count": buy_count,
        "watch_count": watch_count,
        "sell_count": sell_count,
        "no_count": no_count,
        "window_analyses": window_analyses,
        "completed_count": completed_count,
        "active_tasks": active_tasks,
        "decision_distribution": {
            "BUY": buy_count,
            "WATCH": watch_count,
            "SELL": sell_count,
            "NO": no_count,
        },
        "market_distribution": market_distribution,
        "status_distribution": status_distribution,
        "recent_analyses": [
            {
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "market": r.market.value if r.market else None,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "status": r.status.value if r.status else None,
                "final_decision": r.final_decision.value if r.final_decision else None,
            }
            for r in recent_list
        ],
    }


@router.get("/dashboard/queue-overview")
async def get_queue_overview(db: AsyncSession = Depends(get_db)):
    """
    Get an overview of the task queue status (单表架构).

    Shows counts by status and priority from analysis_records table.
    """
    # Queue stats by status
    status_stmt = (
        select(
            AnalysisRecord.status,
            func.count(AnalysisRecord.id).label("count")
        )
        .group_by(AnalysisRecord.status)
    )
    status_result = await db.execute(status_stmt)
    status_dist = {
        row[0].value if row[0] else "UNKNOWN": row[1]
        for row in status_result.fetchall()
    }

    # Queue by priority (pending only)
    priority_stmt = (
        select(
            AnalysisRecord.priority,
            func.count(AnalysisRecord.id).label("count")
        )
        .where(AnalysisRecord.status == Status.PENDING)
        .group_by(AnalysisRecord.priority)
    )
    priority_result = await db.execute(priority_stmt)
    priority_dist = {str(row[0]): row[1] for row in priority_result.fetchall()}

    return {
        "analysis_records": {
            "by_status": status_dist,
            "by_priority": priority_dist,
            "total_pending": sum(
                v for k, v in status_dist.items()
                if k in (Status.PENDING.value,)
            ),
            "total_running": sum(
                v for k, v in status_dist.items()
                if k in (Status.RUNNING.value,)
            ),
        },
    }
