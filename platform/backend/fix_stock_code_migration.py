#!/usr/bin/env python3
"""
SQL Migration Script: Standardize stock_code in platform.db

This script removes market suffixes (.HK/.US/.CN/.SH/.SZ) from all stock_code
fields across all tables to ensure consistent formatting.

For stock_profiles table (which has unique constraint on stock_code):
- If stripping creates a duplicate, merge the profiles keeping the one with higher analysis_count
- Delete the duplicate and update the survivor with the stripped code

Tables affected:
- analysis_records (update stock_code)
- stock_profiles (merge duplicates then update)
- portfolios (update stock_code)
- watchlists (update stock_code)

Before running: BACKUP your database!
After running: Restart the backend service.

Usage:
    python fix_stock_code_migration.py
"""

import sqlite3
import os
import shutil
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "platform.db")
BACKUP_PATH = os.path.join(os.path.dirname(__file__), f"platform.db.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}")


def strip_market_suffix(code: str) -> str:
    """Strip market suffix from stock code."""
    if not code:
        return code
    code = code.upper().strip()
    for suffix in [".HK", ".US", ".CN", ".SH", ".SZ"]:
        if code.endswith(suffix):
            return code[:-len(suffix)]
    return code


def has_market_suffix(code: str) -> bool:
    """Check if code has a market suffix."""
    if not code:
        return False
    code = code.upper().strip()
    return code.endswith(".HK") or code.endswith(".US") or code.endswith(".CN") or code.endswith(".SH") or code.endswith(".SZ")


def get_tables(cursor) -> list:
    """Get all table names in the database."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    return [row[0] for row in cursor.fetchall()]


def get_stock_code_columns(cursor, table_name: str) -> list:
    """Get columns that contain stock_code data."""
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = [row[1] for row in cursor.fetchall()]
    stock_code_cols = []
    for col in columns:
        if col == "stock_code":
            stock_code_cols.append(col)
    return stock_code_cols


def find_duplicates(cursor, table_name: str) -> dict:
    """Find stock_codes that will become duplicates after stripping suffix."""
    stock_code_cols = get_stock_code_columns(cursor, table_name)
    if not stock_code_cols:
        return {}
    
    duplicates = {}
    for col in stock_code_cols:
        cursor.execute(f"SELECT {col} FROM {table_name};")
        codes = [row[0] for row in cursor.fetchall()]
        suffix_codes = [c for c in codes if has_market_suffix(c)]
        
        # Group by stripped code
        groups = {}
        for code in suffix_codes:
            stripped = strip_market_suffix(code)
            if stripped not in groups:
                groups[stripped] = []
            groups[stripped].append(code)
        
        # Find groups with duplicates
        for stripped, original_codes in groups.items():
            if len(original_codes) > 1 and stripped in codes:
                # Will create duplicate after update
                if stripped not in duplicates:
                    duplicates[stripped] = []
                duplicates[stripped].extend(original_codes)
    
    return duplicates


def migrate_analysis_records(cursor, dry_run: bool = False) -> dict:
    """Migrate analysis_records table - simply update all stock_codes with suffix."""
    result = {"table": "analysis_records", "updates": 0, "errors": []}
    
    # Get all records with suffix
    cursor.execute("""
        SELECT rowid, stock_code FROM analysis_records 
        WHERE stock_code LIKE '%.HK' OR stock_code LIKE '%.US' 
           OR stock_code LIKE '%.CN' OR stock_code LIKE '%.SH' 
           OR stock_code LIKE '%.SZ';
    """)
    rows = cursor.fetchall()
    
    for rowid, old_code in rows:
        new_code = strip_market_suffix(old_code)
        if old_code != new_code:
            result["updates"] += 1
            if not dry_run:
                try:
                    cursor.execute(
                        "UPDATE analysis_records SET stock_code = ? WHERE rowid = ?;",
                        (new_code, rowid)
                    )
                except Exception as e:
                    result["errors"].append(f"Row {rowid}: {e}")
    
    return result


def migrate_stock_profiles(cursor, dry_run: bool = False) -> dict:
    """
    Migrate stock_profiles table - handle unique constraint by merging duplicates.
    
    For each set of duplicates (e.g., 00700 and 00700.HK):
    - Keep the one with higher analysis_count as the survivor
    - Update survivor's stock_code to stripped version
    - Delete the others
    """
    result = {"table": "stock_profiles", "updates": 0, "deletes": 0, "errors": []}
    
    # First, find all unique stripped codes that have multiple entries
    cursor.execute("""
        SELECT stock_code FROM stock_profiles 
        WHERE stock_code LIKE '%.HK' OR stock_code LIKE '%.US' 
           OR stock_code LIKE '%.CN' OR stock_code LIKE '%.SH' 
           OR stock_code LIKE '%.SZ';
    """)
    suffix_rows = cursor.fetchall()
    
    # Group by stripped code
    groups = {}
    for (old_code,) in suffix_rows:
        stripped = strip_market_suffix(old_code)
        if stripped not in groups:
            groups[stripped] = []
        groups[stripped].append(old_code)
    
    # For each stripped code, check if there's already a clean entry
    for stripped, suffix_codes in groups.items():
        # Check if there's already a clean entry for this stripped code
        cursor.execute(
            "SELECT COUNT(*) FROM stock_profiles WHERE stock_code = ? AND stock_code NOT LIKE '%.HK' AND stock_code NOT LIKE '%.US' AND stock_code NOT LIKE '%.CN' AND stock_code NOT LIKE '%.SH' AND stock_code NOT LIKE '%.SZ';",
            (stripped,)
        )
        has_clean_entry = cursor.fetchone()[0] > 0
        
        if has_clean_entry:
            # There's already a clean entry - just update/remove the suffix entries
            for old_code in suffix_codes:
                cursor.execute(
                    "SELECT rowid, analysis_count FROM stock_profiles WHERE stock_code = ?;",
                    (old_code,)
                )
                row = cursor.fetchone()
                if row:
                    rowid, analysis_count = row
                    # Delete the suffix version (it's a duplicate now)
                    result["deletes"] += 1
                    if not dry_run:
                        try:
                            cursor.execute("DELETE FROM stock_profiles WHERE rowid = ?;", (rowid,))
                        except Exception as e:
                            result["errors"].append(f"Delete row {rowid}: {e}")
        else:
            # No clean entry yet - need to update one of the suffix entries
            # Get all rows for this stripped code
            all_codes = suffix_codes + [stripped]
            cursor.execute(
                "SELECT stock_code, analysis_count, latest_record_id, latest_decision, stock_name, market, last_analysis_date, rowid FROM stock_profiles WHERE stock_code IN (%s) ORDER BY analysis_count DESC;" % ",".join("?" * len(all_codes)),
                all_codes
            )
            rows = cursor.fetchall()
            
            if len(rows) <= 1:
                # Single entry - just update
                old_code, analysis_count, latest_record_id, latest_decision, stock_name, market, last_analysis_date, rowid = rows[0]
                new_code = stripped
                if old_code != new_code:
                    result["updates"] += 1
                    if not dry_run:
                        try:
                            cursor.execute("UPDATE stock_profiles SET stock_code = ? WHERE rowid = ?;", (new_code, rowid))
                        except Exception as e:
                            result["errors"].append(f"Update row {rowid}: {e}")
            else:
                # Multiple entries - keep the one with highest analysis_count, delete others
                survivor = rows[0]
                survivors_to_delete = rows[1:]
                
                # Update survivor's stock_code to stripped
                survivor_old_code = survivor[0]
                survivor_rowid = survivor[7]
                result["updates"] += 1
                if not dry_run:
                    try:
                        cursor.execute("UPDATE stock_profiles SET stock_code = ? WHERE rowid = ?;", (stripped, survivor_rowid))
                    except Exception as e:
                        result["errors"].append(f"Update survivor row {survivor_rowid}: {e}")
                
                # Delete duplicates
                for dup in survivors_to_delete:
                    dup_rowid = dup[7]
                    result["deletes"] += 1
                    if not dry_run:
                        try:
                            cursor.execute("DELETE FROM stock_profiles WHERE rowid = ?;", (dup_rowid,))
                        except Exception as e:
                            result["errors"].append(f"Delete row {dup_rowid}: {e}")
    
    return result


def migrate_portfolios(cursor, dry_run: bool = False) -> dict:
    """Migrate portfolios table - simply update all stock_codes with suffix."""
    result = {"table": "portfolios", "updates": 0, "errors": []}
    
    cursor.execute("""
        SELECT rowid, stock_code FROM portfolios 
        WHERE stock_code LIKE '%.HK' OR stock_code LIKE '%.US' 
           OR stock_code LIKE '%.CN' OR stock_code LIKE '%.SH' 
           OR stock_code LIKE '%.SZ';
    """)
    rows = cursor.fetchall()
    
    for rowid, old_code in rows:
        new_code = strip_market_suffix(old_code)
        if old_code != new_code:
            result["updates"] += 1
            if not dry_run:
                try:
                    cursor.execute(
                        "UPDATE portfolios SET stock_code = ? WHERE rowid = ?;",
                        (new_code, rowid)
                    )
                except Exception as e:
                    result["errors"].append(f"Row {rowid}: {e}")
    
    return result


def migrate_watchlists(cursor, dry_run: bool = False) -> dict:
    """Migrate watchlists table - simply update all stock_codes with suffix."""
    result = {"table": "watchlists", "updates": 0, "errors": []}
    
    cursor.execute("""
        SELECT rowid, stock_code FROM watchlists 
        WHERE stock_code LIKE '%.HK' OR stock_code LIKE '%.US' 
           OR stock_code LIKE '%.CN' OR stock_code LIKE '%.SH' 
           OR stock_code LIKE '%.SZ';
    """)
    rows = cursor.fetchall()
    
    for rowid, old_code in rows:
        new_code = strip_market_suffix(old_code)
        if old_code != new_code:
            result["updates"] += 1
            if not dry_run:
                try:
                    cursor.execute(
                        "UPDATE watchlists SET stock_code = ? WHERE rowid = ?;",
                        (new_code, rowid)
                    )
                except Exception as e:
                    result["errors"].append(f"Row {rowid}: {e}")
    
    return result


def verify_migration(cursor) -> dict:
    """Verify that no stock_codes have market suffixes."""
    tables = get_tables(cursor)
    issues = []
    
    for table in tables:
        stock_code_cols = get_stock_code_columns(cursor, table)
        for col in stock_code_cols:
            cursor.execute(f"""
                SELECT COUNT(*) FROM {table} 
                WHERE {col} LIKE '%.HK' OR {col} LIKE '%.US' 
                   OR {col} LIKE '%.CN' OR {col} LIKE '%.SH' 
                   OR {col} LIKE '%.SZ';
            """)
            count = cursor.fetchone()[0]
            if count > 0:
                issues.append(f"Table '{table}', column '{col}': {count} rows still have market suffix")
    
    return {
        "is_clean": len(issues) == 0,
        "issues": issues
    }


def print_report(results: list, verify_result: dict, dry_run: bool):
    """Print a summary report of the migration."""
    print("\n" + "="*60)
    print("STOCK CODE MIGRATION REPORT")
    print("="*60)
    
    if dry_run:
        print("\n[DRY RUN - No changes were made]")
    
    total_updates = sum(r.get("updates", 0) for r in results)
    total_deletes = sum(r.get("deletes", 0) for r in results)
    total_errors = sum(len(r.get("errors", [])) for r in results)
    
    print(f"\nTotal updates: {total_updates}")
    print(f"Total deletes: {total_deletes}")
    print(f"Total errors: {total_errors}")
    
    print("\n--- Table Results ---")
    for r in results:
        status = "UPDATED" if r.get("updates", 0) > 0 or r.get("deletes", 0) > 0 else "CLEAN"
        if r.get("errors"):
            status = "ERRORS"
        details = []
        if r.get("updates", 0) > 0:
            details.append(f"{r['updates']} updates")
        if r.get("deletes", 0) > 0:
            details.append(f"{r['deletes']} deletes")
        if r.get("errors"):
            details.append(f"{len(r['errors'])} errors")
        print(f"  {r['table']}: {status} ({', '.join(details) if details else 'no changes'})")
        if r.get("errors"):
            for err in r["errors"][:5]:
                print(f"    - {err}")
    
    print("\n--- Verification ---")
    if verify_result["is_clean"]:
        print("  ✓ Database is CLEAN - no market suffixes found in stock_code fields")
    else:
        print("  ✗ Database has ISSUES:")
        for issue in verify_result["issues"]:
            print(f"    - {issue}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate stock_code to remove market suffixes")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without making changes")
    parser.add_argument("--force", action="store_true", help="Skip backup confirmation")
    args = parser.parse_args()
    
    # Check database exists
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return 1
    
    # Create backup
    if not args.dry_run:
        if not args.force:
            response = input(f"\nThis script will modify the database.\nBackup will be created at: {BACKUP_PATH}\n\nPress 'y' to continue: ")
            if response.lower() != 'y':
                print("Aborted.")
                return 0
        
        print(f"\nCreating backup: {BACKUP_PATH}")
        shutil.copy2(DB_PATH, BACKUP_PATH)
        print("Backup created.")
    
    # Connect to database
    print(f"\nConnecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get tables
    tables = get_tables(cursor)
    print(f"Found tables: {', '.join(tables)}")
    
    # Run migrations
    results = []
    
    print("\nProcessing analysis_records...")
    result = migrate_analysis_records(cursor, dry_run=args.dry_run)
    results.append(result)
    print(f"  {result['updates']} updates, {len(result['errors'])} errors")
    
    print("\nProcessing stock_profiles...")
    result = migrate_stock_profiles(cursor, dry_run=args.dry_run)
    results.append(result)
    print(f"  {result['updates']} updates, {result['deletes']} deletes, {len(result['errors'])} errors")
    
    print("\nProcessing portfolios...")
    result = migrate_portfolios(cursor, dry_run=args.dry_run)
    results.append(result)
    print(f"  {result['updates']} updates, {len(result['errors'])} errors")
    
    print("\nProcessing watchlists...")
    result = migrate_watchlists(cursor, dry_run=args.dry_run)
    results.append(result)
    print(f"  {result['updates']} updates, {len(result['errors'])} errors")
    
    # Commit if not dry run
    if not args.dry_run:
        conn.commit()
        print("\nChanges committed to database.")
    else:
        print("\n[DRY RUN] No changes were made.")
    
    # Verify
    print("\nVerifying migration...")
    verify_result = verify_migration(cursor)
    
    # Print report
    print_report(results, verify_result, args.dry_run)
    
    # Close connection
    conn.close()
    
    if not args.dry_run and verify_result["is_clean"]:
        print("\n✓ Migration completed successfully!")
        return 0
    elif not args.dry_run and not verify_result["is_clean"]:
        print("\n✗ Migration completed but verification failed!")
        return 1
    else:
        print("\n[DRY RUN] No changes were made.")
        return 0


if __name__ == "__main__":
    exit(main())
