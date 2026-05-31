"""Integration with the shennong stock analysis system."""
import os
import sys
import json
import logging
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)
SHENNONG_ROOT = os.environ.get("SHENNONG_ROOT", os.path.expanduser("~/.hermes/investment"))


def _fetch_stock_name(code: str, market: str) -> Optional[str]:
    """Fetch stock name from Tencent API. Returns None on failure."""
    try:
        if market == "HK":
            url = f"https://qt.gtimg.cn/q=hk{code.strip().zfill(5)}"
        elif market == "US":
            ticker = code.strip().upper()
            if "." not in ticker:
                ticker = f"us{ticker}"
            url = f"https://qt.gtimg.cn/q={ticker}"
        else:
            # CN
            code_clean = code.strip().lstrip("0").lstrip("6").zfill(6)
            if code_clean.startswith("688"):
                url = f"https://qt.gtimg.cn/q=sh{code_clean}"
            else:
                url = f"https://qt.gtimg.cn/q=sh{code_clean}"
        result = subprocess.run(["curl", "-s", "-m", "5", url], capture_output=True)
        raw = result.stdout.decode("gb18030", errors="replace")
        parts = raw.split("~")
        if len(parts) > 1:
            return parts[1]
    except Exception:
        pass
    return None


def _strip_market_suffix(code: str) -> str:
    """Strip any market suffix (.HK/.US/.CN/.SH/.SZ) from stock code."""
    code = code.strip().upper()
    for suffix in [".HK", ".US", ".CN", ".SH", ".SZ"]:
        if code.endswith(suffix):
            return code[:-len(suffix)]
    return code


def detect_market(code: str) -> str:
    """Auto-detect market from stock code."""
    code = _strip_market_suffix(code.strip().upper())
    if len(code) == 5 and code.isdigit():
        return "HK"
    if code.isalpha():
        return "US"
    if code.startswith("00") or code.startswith("60") or code.startswith("68"):
        return "CN"
    return "CN"


def run_analysis(stock_code: str, market: Optional[str] = None) -> Dict[str, Any]:
    """
    Run full pipeline analysis on a single stock via the shennong system.

    Returns dict with:
    - L1_result, L2_result, L3_result, L4_result (as dicts)
    - final_decision: BUY/SELL/WATCH/NO/REJECT
    - score: 5-dimension scores
    - raw_data: backup of raw market data
    - veto_info: if stock was rejected before L4
    """
    if market is None or market == "auto":
        market = detect_market(stock_code)

    logger.info(f"Running analysis for {stock_code} (market: {market})")

    # Import shennong using runpy (it's a script, not a module)
    import runpy
    ns = runpy.run_path(
        os.path.join(SHENNONG_ROOT, "main", "shennong.py"),
        run_name="run_pipeline"
    )
    run_pipeline = ns["run_pipeline"]

    # Normalize stock code for shennong
    clean_code = _strip_market_suffix(stock_code)

    if market == "HK":
        symbols = [clean_code.zfill(5)]
    elif market == "US":
        symbols = [clean_code.upper()]
    else:
        symbols = [clean_code.zfill(6)]

    try:
        result = run_pipeline(symbols=symbols, market=market, mode="full")
    except Exception as e:
        logger.error(f"run_pipeline raised: {e}")
        raise

    # === Parse the ACTUAL shennong return structure ===
    # shennong returns: {run_date, mode, pool, market, L1, L2, veto, L3, L4, report, stage_times}
    # NOT wrapped in a "pipeline" key

    # Extract L4 decisions
    final_decision = "NO"
    l4_decisions = result.get("L4", {}).get("decisions", []) if result.get("L4") else []
    if l4_decisions:
        for d in l4_decisions:
            if d.get("code") == clean_code or d.get("stock_code") == clean_code:
                final_decision = d.get("decision", "NO")
                break

    # Extract veto info (stock rejected before L4)
    veto_info = None
    if final_decision == "NO" and not l4_decisions:
        veto = result.get("veto", {}) or {}
        if clean_code in veto:
            veto_info = veto[clean_code]
            final_decision = veto_info.get("decision", "NO")
            logger.info(f"Stock {clean_code} vetoed at {veto_info.get('layer')}: {veto_info.get('reason')}")

    # Extract 5-dimension score from L3 results
    score = {}
    l3_results = result.get("L3", {}).get("results", []) if result.get("L3") else []
    for r in l3_results:
        if r.get("code") == clean_code:
            score = r.get("scores", r.get("five_dimension_scores", {}))
            break

    # Build response
    return {
        "pipeline": {
            "L1": result.get("L1", {}),
            "L2": result.get("L2", {}),
            "L3": result.get("L3", {}),
            "L4": result.get("L4", {}),
        },
        "final_decision": final_decision,
        "score": score,
        "veto_info": veto_info,
        "report": result.get("report", ""),
    }
