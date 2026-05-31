"""Main FastAPI application."""
import os
import sys
import logging
from contextlib import asynccontextmanager

# Add shennong to path
SHENNONG_ROOT = os.path.expanduser("~/.hermes/investment")
if SHENNONG_ROOT not in sys.path:
    sys.path.insert(0, SHENNONG_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path

from database import init_db
from worker_pool import start_worker_pool, stop_worker_pool
from routers import analyze, result, batch, stocks, reflection, portfolio, queue as queue_router, l1_api as l1_router, dashboard as dashboard_router, records as records_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — startup and shutdown hooks."""
    # Startup
    logger.info("[Platform] Initializing database...")
    await init_db()
    logger.info("[Platform] Database initialized")

    # Start WorkerPool
    logger.info("[Platform] Starting WorkerPool (N=3)...")
    start_worker_pool()
    logger.info("[Platform] WorkerPool started")

    yield

    # Shutdown
    logger.info("[Platform] Stopping WorkerPool...")
    stop_worker_pool()
    logger.info("[Platform] WorkerPool stopped")


app = FastAPI(
    title="Shennong Stock Analysis Platform",
    description="AI-driven multi-market stock screening and quantitative analysis platform",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(dashboard_router.router)
app.include_router(records_router.router)
app.include_router(analyze.router)
app.include_router(result.router)
app.include_router(batch.router)
app.include_router(stocks.router)
app.include_router(reflection.router)
app.include_router(portfolio.router)
app.include_router(queue_router.router)
app.include_router(l1_router.router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "shennong-platform", "version": "2.0.0"}


# Serve frontend for all non-API routes (SPA catch-all)
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
index_html = frontend_dist / "index.html"


@app.get("/{path:path}")
async def serve_spa(path: str):
    """Serve the SPA for any path that isn't an API route."""
    if path.startswith("api"):
        from fastapi.exceptions import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")
    if path == "":
        return FileResponse(str(index_html))
    # Check if it's a file request (has extension)
    if "." in path:
        file_path = frontend_dist / path
        if file_path.exists():
            return FileResponse(str(file_path))
    # Otherwise serve the SPA
    return FileResponse(str(index_html))


@app.get("/")
async def serve_root():
    """Serve root index.html."""
    return FileResponse(str(index_html))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
