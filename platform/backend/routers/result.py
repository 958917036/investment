"""Result router - handles analysis result retrieval.

单表架构: 使用 task_id (替代 batch_id), l1_data/l2_data/l3_data/l4_data (替代 L1_result 等)
"""
import os
import json
from typing import Optional, Any
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import AnalysisRecord, Status

router = APIRouter(prefix="/api", tags=["result"])


def _safe_json_loads(data: Any) -> Any:
    """Safely parse JSON string, replacing NaN/Infinity with None."""
    if not data:
        return None
    try:
        # Replace Python NaN/Infinity literals with valid JSON null before parsing
        cleaned = re.sub(r'\bNaN\b', 'null', str(data))
        cleaned = re.sub(r'\bInfinity\b', 'null', cleaned)
        cleaned = re.sub(r'\b-Infinity\b', 'null', cleaned)
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
        "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        "status": record.status.value if record.status else None,
        "l1_data": _safe_json_loads(record.l1_data),
        "l2_data": _safe_json_loads(record.l2_data),
        "l3_data": _safe_json_loads(record.l3_data),
        "l4_data": _safe_json_loads(record.l4_data),
        "final_decision": record.final_decision.value if record.final_decision else None,
        "score": json.loads(record.score) if record.score else None,
        "judge_score": record.judge_score,
        "cached_at": record.cached_at.isoformat() if record.cached_at else None,
        "force_refresh": bool(record.force_refresh),
        "error_message": record.error_message,
    }


@router.get("/price/{stock_code}")
async def get_price_history(stock_code: str):
    """
    Get price history using Tencent Finance kline API.
    Returns last ~90 trading days OHLCV data.
    Falls back to qt (quote) endpoint for US stocks if kline is empty.
    """
    try:
        # Set proxy for yfinance US stock access
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"
        os.environ["https_proxy"] = "http://127.0.0.1:7897"
        os.environ["http_proxy"] = "http://127.0.0.1:7897"

        code = stock_code.strip().upper()

        # Normalize code to Tencent prefix
        if code.startswith("HK"):
            prefix = f"hk{code[2:].zfill(5)}"
        elif "." in code:
            prefix = f"us{code.replace('.', '')}"
        elif len(code) == 5:
            prefix = f"hk{code.zfill(5)}"
        elif code.startswith("00") or code.startswith("60") or code.startswith("68"):
            prefix = f"sh{code.zfill(6)}"
        else:
            prefix = f"sh{code.zfill(6)}"

        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

        # Try kline endpoint first
        url = (
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?_var=kline_dayqfq"
            f"&param={prefix},day,{start_date},{end_date},90,qfq&r=0.5"
        )

        import subprocess, json as _json
        result = subprocess.run(
            ["curl", "-s", "-m", "10", url],
            capture_output=True, text=True
        )
        raw = result.stdout

        if raw.startswith("kline_dayqfq="):
            raw = raw[len("kline_dayqfq="):]

        data = _json.loads(raw)

        # Find day array - try "day" key first, then "qfqday"
        bars = []
        data_section = data.get("data", {})
        if isinstance(data_section, dict):
            for ticker_key, ticker_value in data_section.items():
                if isinstance(ticker_value, dict):
                    if "day" in ticker_value and ticker_value["day"]:
                        bars = ticker_value["day"]
                        break
                    elif "qfqday" in ticker_value and ticker_value["qfqday"]:
                        bars = ticker_value["qfqday"]
                        break

        price_history = []
        for bar in bars:
            if isinstance(bar, list) and len(bar) >= 6:
                try:
                    price_history.append({
                        "date": str(bar[0]),
                        "open": round(float(bar[1]), 2),
                        "high": round(float(bar[2]), 2),
                        "low": round(float(bar[3]), 2),
                        "close": round(float(bar[4]), 2),
                        "volume": int(float(bar[5])),
                    })
                except (ValueError, TypeError):
                    continue

        # If bars is empty (e.g. US stocks on Tencent), try yfinance with proxy
        if not bars and ("." in code or (len(code) <= 5 and not code.startswith("HK") and not code.startswith("0") and not code.startswith("6"))):
            try:
                import yfinance as _yf
                ticker_symbol = code.replace(".", "-")  # yfinance uses GOOGL not GOOGL.OQ
                _ticker = _yf.Ticker(ticker_symbol)
                _hist = _ticker.history(period="3mo")
                if not _hist.empty:
                    for dt, row in _hist.iterrows():
                        price_history.append({
                            "date": dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10],
                            "open": round(float(row["Open"]), 2),
                            "high": round(float(row["High"]), 2),
                            "low": round(float(row["Low"]), 2),
                            "close": round(float(row["Close"]), 2),
                            "volume": int(row["Volume"]),
                        })
            except Exception:
                pass

        # If still no data, at least get current price from qt endpoint
        if not price_history:
            qt_url = f"https://qt.gtimg.cn/q={prefix}"
            qt_result = subprocess.run(
                ["curl", "-s", "-m", "5", qt_url],
                capture_output=True, text=True
            )
            qt_raw = qt_result.stdout.decode("gb18030", errors="replace")
            if qt_raw and "~" in qt_raw:
                parts = qt_raw.split("~")
                if len(parts) > 5:
                    try:
                        current_price = float(parts[3])
                        current_date = datetime.now().strftime("%Y-%m-%d")
                        price_history.append({
                            "date": current_date,
                            "open": current_price,
                            "high": current_price,
                            "low": current_price,
                            "close": current_price,
                            "volume": 0,
                        })
                    except (ValueError, TypeError):
                        pass

        return {"stock_code": stock_code, "price_history": price_history}

    except Exception as e:
        # Return empty array instead of 500 on failure
        return {"stock_code": stock_code, "price_history": []}


@router.get("/result/{result_id}")
async def get_result(result_id: str, db: AsyncSession = Depends(get_db)):
    """Get full analysis result by ID."""
    result = await db.get(AnalysisRecord, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    return serialize_record(result)


@router.get("/debug/shennong/{stock_code}")
async def debug_shennong(stock_code: str, db: AsyncSession = Depends(get_db)):
    """Debug endpoint - directly call shennong and return raw structure."""
    import runpy, os
    SHENNONG_ROOT = os.environ.get("SHENNONG_ROOT", os.path.expanduser("~/.hermes/investment"))
    ns = runpy.run_path(os.path.join(SHENNONG_ROOT, "main", "shennong.py"), run_name="run_pipeline")
    result = ns["run_pipeline"](symbols=[stock_code], market="auto", mode="full")
    return {"top_keys": list(result.keys()), "L1_keys": list(result.get("L1",{}).keys()), "L2_keys": list(result.get("L2",{}).keys()), "L3_keys": list(result.get("L3",{}).keys()), "L4_keys": list(result.get("L4",{}).keys())}


@router.get("/history/{stock_code}")
async def get_history(stock_code: str, db: AsyncSession = Depends(get_db)):
    """Get all historical analyses for a stock code."""
    stmt = select(AnalysisRecord).where(
        AnalysisRecord.stock_code == stock_code
    ).order_by(AnalysisRecord.timestamp.desc())

    result = await db.execute(stmt)
    records = result.scalars().all()

    return {"records": [serialize_record(r) for r in records]}


@router.get("/compare/{stock_code}")
async def compare(
    stock_code: str,
    ids: str,  # comma-separated two IDs
    db: AsyncSession = Depends(get_db)
):
    """Compare two analysis results for the same stock."""
    id_list = ids.split(",")
    if len(id_list) != 2:
        raise HTTPException(status_code=400, detail="Must provide exactly 2 IDs")

    id_a, id_b = id_list[0].strip(), id_list[1].strip()

    record_a = await db.get(AnalysisRecord, id_a)
    record_b = await db.get(AnalysisRecord, id_b)

    if not record_a or not record_b:
        raise HTTPException(status_code=404, detail="One or both records not found")

    if record_a.stock_code != stock_code or record_b.stock_code != stock_code:
        raise HTTPException(status_code=400, detail="Records don't match stock code")

    # Build comparison data
    return {
        "stock_code": stock_code,
        "analysis_a": serialize_record(record_a),
        "analysis_b": serialize_record(record_b),
        "comparison": {
            "decision_changed": record_a.final_decision != record_b.final_decision,
            "decision_a": record_a.final_decision.value if record_a.final_decision else None,
            "decision_b": record_b.final_decision.value if record_b.final_decision else None,
            "score_a": json.loads(record_a.score) if record_a.score else {},
            "score_b": json.loads(record_b.score) if record_b.score else {},
            "timestamp_a": record_a.timestamp.isoformat() if record_a.timestamp else None,
            "timestamp_b": record_b.timestamp.isoformat() if record_b.timestamp else None,
        }
    }
