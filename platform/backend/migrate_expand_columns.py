#!/usr/bin/env python3
"""
Migration script: Add expanded columns to analysis_records and stock_profiles.

Safe to run multiple times - uses IF NOT EXISTS / IF NOT NULL checks.
"""
import sqlite3
import sys

DB_PATH = "~/.hermes/investment/platform/backend/platform.db"
COLUMNS_ANALYSIS_RECORDS = [
    # L1
    ("l1_strategy_counts", "TEXT"),
    ("l1_candidate_count", "INTEGER DEFAULT 0"),
    ("l1_filtered_count", "INTEGER DEFAULT 0"),
    ("l1_total_scanned", "INTEGER DEFAULT 0"),
    ("l1_source", "TEXT"),
    ("l1_price", "REAL"),
    ("l1_change_pct", "REAL"),
    ("l1_market_cap", "REAL"),
    # L2 核心指标
    ("l2_price", "REAL"),
    ("l2_pe", "REAL"),
    ("l2_pb", "REAL"),
    ("l2_roe", "REAL"),
    ("l2_eps", "REAL"),
    ("l2_market_cap", "REAL"),
    ("l2_main_net_flow_5d", "REAL"),
    ("l2_rsi", "REAL"),
    ("l2_ma_status", "TEXT"),
    ("l2_macd_status", "TEXT"),
    ("l2_data_quality", "TEXT"),
    # L3 五维评分
    ("l3_five_score", "REAL"),
    ("l3_grade", "TEXT"),
    ("l3_score_technical", "REAL"),
    ("l3_score_fundamental", "REAL"),
    ("l3_score_moneyflow", "REAL"),
    ("l3_score_sector", "REAL"),
    ("l3_score_event", "REAL"),
    ("l3_debate_verdict", "TEXT"),
    ("l3_debate_confidence", "REAL"),
    ("l3_persona_verdict", "TEXT"),
    ("l3_persona_avg_score", "REAL"),
    # L4 决策
    ("l4_judge_score", "REAL"),
    ("l4_decision", "TEXT"),
    ("l4_risk_score", "REAL"),
    ("l4_volatility", "REAL"),
    ("l4_kelly_fraction", "REAL"),
    ("l4_recommended_weight", "REAL"),
    ("l4_stop_loss", "REAL"),
    ("l4_take_profit", "REAL"),
    # Meta
    ("run_date", "TEXT"),
]

COLUMNS_STOCK_PROFILES = [
    ("sector", "TEXT"),
    ("industry", "TEXT"),
    ("latest_judge_score", "REAL"),
    ("latest_price", "REAL"),
]


def get_columns(cursor, table):
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def main():
    db_path = __file__.replace("/fix_stock_code_migration.py", "/platform.db")
    if db_path == __file__:
        db_path = "/Users/guchuang/.hermes/investment/platform/backend/platform.db"
    db_path = db_path.replace("~", __import__('os').path.expanduser("~").replace("/", "\\\\" if sys.platform == "win32" else ""))
    db_path = "/Users/guchuang/.hermes/investment/platform/backend/platform.db"

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Migrate analysis_records
    existing = get_columns(c, "analysis_records")
    added = 0
    for col_name, col_type in COLUMNS_ANALYSIS_RECORDS:
        if col_name not in existing:
            try:
                c.execute(f"ALTER TABLE analysis_records ADD COLUMN {col_name} {col_type}")
                added += 1
                print(f"  ✅ Added {col_name}")
            except sqlite3.OperationalError as e:
                print(f"  ⚠️  {col_name}: {e}")
    if added == 0:
        print("  ✅ analysis_records: no new columns needed")
    else:
        print(f"  ✅ analysis_records: added {added} columns")

    # Migrate stock_profiles
    existing_sp = get_columns(c, "stock_profiles")
    added_sp = 0
    for col_name, col_type in COLUMNS_STOCK_PROFILES:
        if col_name not in existing_sp:
            try:
                c.execute(f"ALTER TABLE stock_profiles ADD COLUMN {col_name} {col_type}")
                added_sp += 1
                print(f"  ✅ Added {col_name}")
            except sqlite3.OperationalError as e:
                print(f"  ⚠️  {col_name}: {e}")
    if added_sp == 0:
        print("  ✅ stock_profiles: no new columns needed")
    else:
        print(f"  ✅ stock_profiles: added {added_sp} columns")

    conn.commit()
    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()