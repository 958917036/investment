#!/usr/bin/env python3
"""
DB Writer — 将 pipeline 结果写入 platform 数据库

每个 L4 决策完成后写入 analysis_records，
L1/L2/L3 完成后增量更新。
"""
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("db_writer")

# ── DB 路径配置 ──────────────────────────────────
DB_PATH = os.path.expanduser("~/.hermes/investment/platform/backend/platform.db")
_has_db = os.path.exists(DB_PATH)


def _get_conn():
    """获取 SQLite 连接（lazy）"""
    if not _has_db:
        return None
    import sqlite3
    return sqlite3.connect(DB_PATH)


def _json_str(data: Any) -> str:
    """安全序列化为 JSON string"""
    if data is None:
        return None
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        return None


# ── 核心写入函数 ──────────────────────────────────

def write_analysis_record(
    stock_code: str,
    stock_name: str,
    market: str,
    run_date: str,
    step: str,           # L1/L2/L3/L4/veto
    status: str,         # COMPLETED/FAILED
    l1_data: Dict = None,
    l2_data: Dict = None,
    l3_data: Dict = None,
    l4_data: Dict = None,
    task_id: str = None,
    error_message: str = None,
) -> bool:
    """
    写入或更新一条分析记录。

    策略：先查是否有同 (stock_code, run_date, step) 的记录，有则 UPDATE，无则 INSERT。
    """
    conn = _get_conn()
    if conn is None:
        return False

    c = conn.cursor()
    now = datetime.utcnow().isoformat()

    # 尝试 UPDATE 已存在记录
    c.execute(
        "SELECT id FROM analysis_records WHERE stock_code=? AND run_date=? AND step=? LIMIT 1",
        (stock_code, run_date, step)
    )
    row = c.fetchone()

    def _to_json(d):
        return json.dumps(d, ensure_ascii=False, default=str) if d else None

    if row:
        # UPDATE
        sets = ["timestamp=?", "status=?", "l1_data=?", "l2_data=?", "l3_data=?", "l4_data=?", "error_message=?"]
        vals = [now, status, _to_json(l1_data), _to_json(l2_data), _to_json(l3_data), _to_json(l4_data), error_message]
        if task_id is not None:
            sets.append("task_id=?")
            vals.append(task_id)
        vals.append(row[0])
        c.execute(f"UPDATE analysis_records SET {','.join(sets)} WHERE id=?", vals)
    else:
        # INSERT
        c.execute(
            """INSERT INTO analysis_records
               (id, stock_code, stock_name, market, run_date, step, status,
                task_id, timestamp, l1_data, l2_data, l3_data, l4_data, error_message)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"auto_{stock_code}_{run_date}_{step}", stock_code, stock_name, market, run_date, step,
             status, task_id, now, _to_json(l1_data), _to_json(l2_data), _to_json(l3_data), _to_json(l4_data), error_message)
        )

    conn.commit()
    conn.close()
    return True


def update_from_pipeline_result(pipeline: dict, market: str = "CN") -> None:
    """
    从 pipeline 结果 dict 批量提取并写入 DB。

    在 shennong.py 的 run_pipeline() 完成后调用。

    写入内容：
    - L1 汇总：candidate_count, strategy_counts, price, change_pct
    - 每只股票 L2/L3/L4：展开关键指标字段
    """
    conn = _get_conn()
    if conn is None:
        return

    run_date = pipeline.get("run_date", "")
    task_id = pipeline.get("task_id", "")

    # ── L1 汇总 ────────────────────────────────────
    l1 = pipeline.get("L1", {})
    if l1:
        stocks = l1.get("stocks", [])
        if stocks and len(stocks) > 0:
            first = stocks[0]
            write_analysis_record(
                stock_code="__L1_BATCH__",
                stock_name=f"{market} L1 batch",
                market=market,
                run_date=run_date,
                step="L1",
                status="COMPLETED",
                l1_data=l1,
                task_id=task_id,
            )
        # 写入每只候选股 L1
        for s in stocks:
            code = s.get("code", "")
            name = s.get("name", "")
            write_analysis_record(
                stock_code=code,
                stock_name=name,
                market=market,
                run_date=run_date,
                step="L1",
                status="COMPLETED",
                l1_data={"stocks": [s]},
                task_id=task_id,
            )

    # ── L2 汇总 ────────────────────────────────────
    l2 = pipeline.get("L2", {})
    if l2:
        l2_stocks = l2.get("stocks", [])
        for s in l2_stocks:
            code = s.get("code", "")
            name = s.get("name", "")
            td = s.get("technical_data", {})
            fd = s.get("fundamental_data", {})
            mf = s.get("moneyflow_data", {})
            write_analysis_record(
                stock_code=code,
                stock_name=name,
                market=market,
                run_date=run_date,
                step="L2",
                status="COMPLETED",
                l2_data=s,
                task_id=task_id,
            )

    # ── L3/L4 决策 ────────────────────────────────
    l3 = pipeline.get("L3", {})
    l4 = pipeline.get("L4", {})

    if l4 and l4.get("decisions"):
        for d in l4["decisions"]:
            code = d.get("code", "")
            name = d.get("name", "")
            write_analysis_record(
                stock_code=code,
                stock_name=name,
                market=market,
                run_date=run_date,
                step="L4",
                status="COMPLETED",
                l4_data={"decisions": [d]},
                task_id=task_id,
            )

    conn.close()
    logger.info(f"[db_writer] Pipeline {run_date} 已写入 DB")


# ── 便捷函数 ─────────────────────────────────────

def write_decision(
    stock_code: str,
    stock_name: str,
    market: str,
    run_date: str,
    decision: str,       # BUY/WATCH/REJECT
    judge_score: float,
    l3_five_score: float = None,
    l2_price: float = None,
    l2_pe: float = None,
    l2_roe: float = None,
    l2_rsi: float = None,
    l4_risk_score: float = None,
    l4_stop_loss: float = None,
    l4_take_profit: float = None,
    l4_volatility: float = None,
    l4_kelly_fraction: float = None,
    l4_recommended_weight: float = None,
    l3_grade: str = None,
    l3_debate_verdict: str = None,
    l3_persona_verdict: str = None,
) -> bool:
    """直接写入一条决策记录（单股）"""
    conn = _get_conn()
    if conn is None:
        return False

    c = conn.cursor()
    c.execute(
        """INSERT OR REPLACE INTO analysis_records
           (id, stock_code, stock_name, market, run_date, step, status,
            l4_decision, l4_judge_score, l3_five_score,
            l2_price, l2_pe, l2_roe, l2_rsi,
            l4_risk_score, l4_stop_loss, l4_take_profit, l4_volatility,
            l4_kelly_fraction, l4_recommended_weight,
            l3_grade, l3_debate_verdict, l3_persona_verdict,
            timestamp)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            f"{stock_code}_{run_date}",
            stock_code, stock_name, market, run_date, "L4", "COMPLETED",
            decision, judge_score, l3_five_score,
            l2_price, l2_pe, l2_roe, l2_rsi,
            l4_risk_score, l4_stop_loss, l4_take_profit, l4_volatility,
            l4_kelly_fraction, l4_recommended_weight,
            l3_grade, l3_debate_verdict, l3_persona_verdict,
            datetime.utcnow().isoformat(),
        )
    )
    conn.commit()
    conn.close()
    return True