"""
分层 Cron 触发脚本 — L2 层
读取 L1_candidates.json，执行 L2 数据采集，输出 L2_result.json
供下游 L3 cron 接力
"""
import sys, os, json, time

WD = "/Users/guchuang/.hermes/investment"
sys.path.insert(0, WD)
os.chdir(WD)

from datetime import date
from main.shennong import run_L2, save_result, make_serializable, logger

TODAY = date.today().strftime("%Y-%m-%d")
RECORDS_DIR = f"{WD}/main/records/{TODAY}"
os.makedirs(RECORDS_DIR, exist_ok=True)

# ── 检查上游 L1 是否完成 ──────────────────────────────────────────────────────
L1_FILE = f"{RECORDS_DIR}/L1_candidates.json"
if not os.path.exists(L1_FILE):
    print(f"⛔ L1结果文件不存在: {L1_FILE}")
    print("⛔ 请先执行 cron_L1 任务")
    sys.exit(1)

with open(L1_FILE) as f:
    l1_data = json.load(f)

candidates = l1_data.get("candidates", [])
print(f"✓ L1读取完成: {len(candidates)}只候选")

# ── 执行 L2 ──────────────────────────────────────────────────────────────────
print(f"⏳ L2 数据采集中 ({len(candidates)}只候选)...")
t0 = time.time()
l2_result = run_L2(candidates)
elapsed = time.time() - t0

print(f"✓ L2完成: {l2_result.get('stock_count', 0)}只, 耗时{elapsed:.1f}s")

# ── 保存 ──────────────────────────────────────────────────────────────────────
l2_serializable = make_serializable(l2_result)
l2_serializable["_layer"] = "L2"
l2_serializable["_completed_at"] = time.time()

# 关键：写入标准文件名供下游读取
L2_OUT = f"{RECORDS_DIR}/L2_result.json"
with open(L2_OUT, "w") as f:
    json.dump(l2_serializable, f, ensure_ascii=False, indent=2)
print(f"✓ L2结果已保存: {L2_OUT}")

# ── 检查关键失败 ──────────────────────────────────────────────────────────────
if l2_result.get("_DATA_CRITICAL_FAILURE"):
    pct = l2_result.get("_moneyflow_valid_pct", 0)
    print(f"⛔ L2资金流数据严重缺失({pct:.0f}%)，建议中止全链路")
    sys.exit(2)

print(f"✓ L2层完成，等待L3接力")
