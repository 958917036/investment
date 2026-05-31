#!/Users/guchuang/.hermes/hermes-agent/venv/bin/python3
"""Final verification script for shennong platform."""
import subprocess, json, urllib.request, urllib.parse, time

BASE = "http://localhost:8000"

def api(path, body=None, method=None, timeout=15):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if body else "GET"))
    req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        raw = r.read().decode()
        return json.loads(raw) if raw else {}, r.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode()), e.code
        except:
            return {"error": str(e.code)}, e.code
    except Exception as e:
        return {"error": str(e)}, -1

results = {}
passed = failed = 0

def check(name, cond, detail=""):
    global passed, failed
    ok = bool(cond)
    if ok:
        passed += 1
    else:
        failed += 1
    icon = "✓" if ok else "✗"
    print(f"  {icon} {name}" + (f" ({detail})" if detail else ""))
    results[name] = ok
    return ok

print("="*55)
print("FINAL COMPREHENSIVE VERIFICATION")
print("="*55)

# 1. Input validation
print("\n[1] Input Validation")
r, s = api("/api/analyze", {"stock_codes": []})
check("Empty list → 422", s == 422, f"got {s}")

# 2. Dashboard
print("\n[2] Dashboard")
r, s = api("/api/dashboard/stats")
if isinstance(r, dict):
    check("stocks_analyzed", r.get("stocks_analyzed") is not None and r.get("stocks_analyzed") > 0, f"={r.get('stocks_analyzed')}")
    check("watch_count", r.get("watch_count") is not None, f"={r.get('watch_count')}")
    check("total_analyses", r.get("total_analyses") is not None and r.get("total_analyses") > 0, f"={r.get('total_analyses')}")
    check("recent_analyses[]", isinstance(r.get("recent_analyses"), list) and len(r.get("recent_analyses",[])) > 0)
    check("buy_count", r.get("buy_count") is not None)
else:
    check("Dashboard response", False)

# 3. Batch list
print("\n[3] Batch")
r, s = api("/api/batches")
check("batches[]", isinstance(r, list) and len(r) > 0, f"len={len(r)}")
if isinstance(r, list) and r:
    check("batch.task_id exists", bool(r[0].get("task_id")))
    check("batch.total_count > 0", r[0].get("total_count", 0) > 0)

# 4. History + Data integrity
print("\n[4] History & Data Integrity")
for code in ["AAPL", "MSFT", "TSLA"]:
    rh, _ = api(f"/api/history/{code}")
    if isinstance(rh, list) and rh:
        h = rh[0]
        check(f"{code}: decision", bool(h.get("final_decision")), h.get("final_decision"))
        check(f"{code}: L1 data", bool(h.get("l1_data")))
        check(f"{code}: L4 data", bool(h.get("l4_data")))
    else:
        check(f"{code} history", False)

# 5. Stock search
print("\n[5] Stock Search")
for q, expected_min in [("腾讯", 1), ("nvidia", 1), ("apple", 1), ("msft", 1)]:
    encoded = urllib.parse.quote(q)
    r, _ = api(f"/api/stocks/search?q={encoded}")
    n = len(r) if isinstance(r, list) else -1
    check(f"search('{q}')", n >= expected_min, f"{n} results")

# 6. Stocks library
print("\n[6] Stocks Library")
r, s = api("/api/stocks")
check("stocks[]", isinstance(r, list) and len(r) > 0, f"len={len(r)}")
if isinstance(r, list) and r:
    for s_item in r[:3]:
        check(f"  {s_item.get('stock_code')} has name", bool(s_item.get("stock_name")))

# 7. Reflections
print("\n[7] Reflections")
for code in ["NVDA", "AAPL"]:
    r, s = api(f"/api/reflections/{code}")
    check(f"reflections/{code}", isinstance(r, list))

# 8. Result detail
print("\n[8] Result Detail")
rh, _ = api("/api/history/MSFT")
if isinstance(rh, list) and rh:
    rid = rh[0].get("id")
    r2, _ = api(f"/api/result/{rid}")
    if isinstance(r2, dict):
        l4 = r2.get("l4_data", {})
        decisions = l4.get("decisions", []) if isinstance(l4, dict) else []
        check("MSFT decision", bool(r2.get("final_decision")), r2.get("final_decision"))
        check("MSFT L4 decisions", len(decisions) > 0, f"count={len(decisions)}")
        check("MSFT L1 present", bool(r2.get("l1_data")))

# 9. Compare
print("\n[9] Compare")
rh, _ = api("/api/history/00700")
if isinstance(rh, list) and len(rh) >= 2:
    ids = f"{rh[0]['id']},{rh[1]['id']}"
    rc, _ = api(f"/api/compare/00700?ids={ids}")
    check("compare/00700", isinstance(rc, dict))
    if isinstance(rc, dict):
        check("compare.has_decision_a", "decision_a" in rc.get("comparison", {}))
        check("compare.has_score_a", "score_a" in rc.get("comparison", {}))

# 10. Batch detail
print("\n[10] Batch Detail")
rb, _ = api("/api/batches")
if isinstance(rb, list) and rb:
    bid = rb[0]["task_id"]
    rbd, _ = api(f"/api/batch/{bid}")
    check("batch/detail", isinstance(rbd, dict))
    if isinstance(rbd, dict):
        check("batch/records[]", isinstance(rbd.get("records"), list))
        check("batch/has_progress", "completed_count" in rbd and "total_count" in rbd)

# 11. E2E new analysis
print("\n[11] E2E: New Analysis (GOOGL)")
r, s = api("/api/analyze", {"stock_codes": ["GOOGL"]}, timeout=10)
batch_id = r.get("batch_id") if isinstance(r, dict) else None
check("analyze(GOOGL) returns immediately", batch_id is not None)
if batch_id:
    for i in range(20):
        time.sleep(4)
        rb, _ = api(f"/api/batch/{batch_id}")
        status = rb.get("status","unknown") if isinstance(rb, dict) else "unknown"
        if status in ("completed", "failed"):
            check(f"GOOGL {status}", status == "completed", status)
            break
        if i == 0:
            print(f"  polling... {status}")

print("\n" + "="*55)
print(f"RESULT: {passed} passed, {failed} failed out of {passed+failed} tests")
print("="*55)
for k, v in sorted(results.items()):
    if not v:
        print(f"  FAILED: {k}")
