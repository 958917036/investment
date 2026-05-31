"""Database connection and session management."""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite+aiosqlite:///" + os.path.expanduser("~/.hermes/investment/platform/backend/platform.db")
)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_db():
    """Dependency for FastAPI endpoints."""
    async with async_session_maker() as session:
        yield session


async def init_db():
    """
    Initialize all database tables.
    Imports all models to ensure their Base is registered before create_all.

    Single-table architecture: analysis_records + 4 auxiliary tables
    """
    # Import all models to ensure their Base is registered
    from models import (
        AnalysisRecord, StockProfile, Reflection,
        Portfolio, Watchlist, Market, Status, Decision, Priority, Step
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
