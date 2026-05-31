#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 全层测试套件执行器

用法:
    python3 testsv2/run_all_tests.py          # 执行全部测试
    python3 testsv2/run_all_tests.py --layer L1  # 只跑指定层
    python3 testsv2/run_all_tests.py --fast       # 跳过慢速网络测试
"""
import sys
import os
import json
import time
import subprocess
import argparse
from datetime import datetime

BASE = os.path.expanduser("~/.hermes/investment")
RESULTS_FILE = os.path.join(BASE, "testsv2", "_last_run_results.json")

# 测试目录配置
LAYER_CONFIG = {
    "L1": {
        "dir": os.path.join(BASE, "testsv2", "l1"),
        "files": ["test_l1_runner.py"],
    },
    "L2": {
        "dir": os.path.join(BASE, "testsv2", "l2"),
        "files": ["test_l2_runner.py"],
    },
    "L3": {
        "dir": os.path.join(BASE, "testsv2", "l3"),
        "files": ["test_l3_quant_runner.py", "test_l3_score_calculation.py", "test_l3_veto_logic.py", "test_portfolio_optimizer.py"],
    },
    "L3_persona": {
        "dir": os.path.join(BASE, "testsv2", "l3_persona"),
        "files": ["test_l3_persona_runner.py"],
    },
    "L4": {
        "dir": os.path.join(BASE, "testsv2", "l4"),
        "files": ["test_l4_runner.py"],
    },
    "L5": {
        "dir": os.path.join(BASE, "testsv2", "l5"),
        "files": ["test_l5_freeze_manager.py", "test_l5_review_engine.py"],
    },
}


def run_test_file(filepath: str, timeout: int = 300) -> dict:
    """执行单个测试文件，返回结果摘要"""
    t0 = time.time()
    try:
        result = subprocess.run(
            ["python3", filepath],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=BASE,
        )
        elapsed = time.time() - t0
        output = result.stdout + result.stderr

        # 优先从 TEST suite_end 行解析（格式稳定）
        import re
        result_line = ""
        for line in output.split("\n"):
            m = re.search(r"\[TEST\]\s+(\S+)\s+▶\s+END\s+passed=(\d+)\s+failed=(\d+)\s+elapsed=([\d.]+)s", line)
            if m:
                passed = int(m.group(2))
                failed = int(m.group(3))
                elapsed = float(m.group(4))
                result_line = f"{passed} 通过, {failed} 失败"
                break

        # 如果还是没有，尝试解析 "结果: X/Y 通过, Z 失败"
        if not result_line or (passed == 0 and failed == 0):
            for line in output.split("\n"):
                if "结果:" in line:
                    result_line = line.strip()
                    parts = line.split("结果:")[1].strip()
                    m = re.match(r"(\d+)/(\d+)\s*通过.*?(\d+)\s*失败", parts)
                    if m:
                        passed = int(m.group(1))
                        failed = int(m.group(3))
                    elif "通过" in parts and "失败" not in parts:
                        m2 = re.match(r"(\d+)/(\d+)\s*通过", parts)
                        if m2:
                            passed = int(m2.group(1))
                    break

        # 最后 fallback：统计 [PASS] / [FAIL] 计数
        if passed == 0 and failed == 0:
            passed = output.count("[PASS]")
            failed = output.count("[FAIL]")
            if passed > 0 or failed > 0:
                result_line = f"{passed} 通过, {failed} 失败"

        return {
            "file": os.path.basename(filepath),
            "passed": passed,
            "failed": failed,
            "elapsed": elapsed,
            "result_line": result_line,
            "success": result.returncode == 0,
            "output": output[-2000:] if len(output) > 2000 else output,
        }
    except subprocess.TimeoutExpired:
        return {
            "file": os.path.basename(filepath),
            "passed": 0,
            "failed": 0,
            "elapsed": timeout,
            "result_line": "TIMEOUT",
            "success": False,
            "output": f"Timed out after {timeout}s",
        }
    except Exception as e:
        return {
            "file": os.path.basename(filepath),
            "passed": 0,
            "failed": 0,
            "elapsed": time.time() - t0,
            "result_line": f"ERROR: {e}",
            "success": False,
            "output": str(e),
        }


def run_layer(layer_name: str, config: dict, timeout: int = 300) -> dict:
    """执行指定层的所有测试文件"""
    layer_dir = config["dir"]
    files = config["files"]

    results = []
    total_passed = 0
    total_failed = 0
    total_elapsed = 0.0

    for fname in files:
        fpath = os.path.join(layer_dir, fname)
        if not os.path.exists(fpath):
            results.append({
                "file": fname,
                "passed": 0,
                "failed": 0,
                "elapsed": 0,
                "result_line": "FILE NOT FOUND",
                "success": False,
                "output": f"Path not found: {fpath}",
            })
            continue

        r = run_test_file(fpath, timeout=timeout)
        results.append(r)
        total_passed += r["passed"]
        total_failed += r["failed"]
        total_elapsed += r["elapsed"]

    return {
        "layer": layer_name,
        "files": len(files),
        "results": results,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_elapsed": total_elapsed,
    }


def print_summary(all_results: list):
    """打印汇总表格"""
    print("\n" + "=" * 70)
    print("Hermes 全层测试汇总")
    print("=" * 70)

    total_all_passed = sum(r['total_passed'] for r in all_results)
    total_all_failed = sum(r['total_failed'] for r in all_results)
    total_all_elapsed = sum(r['total_elapsed'] for r in all_results)

    for res in all_results:
        layer = res["layer"]
        files = res["files"]
        passed = res["total_passed"]
        failed = res["total_failed"]
        elapsed = res["total_elapsed"]

        file_results = []
        for fr in res["results"]:
            if fr["result_line"] == "FILE NOT FOUND":
                file_results.append("❌ not found")
            elif fr["result_line"] == "TIMEOUT":
                file_results.append("⏱ timeout")
            elif fr["success"]:
                file_results.append(f"✅ {fr['file']}")
            else:
                file_results.append(f"❌ {fr['file']}")

        print(f"\n{layer} ({files} 文件, {passed+failed} 用例)")
        for fr in file_results:
            print(f"  {fr}")
        for fr in res["results"]:
            if fr["result_line"] and fr["result_line"] not in ("FILE NOT FOUND", "TIMEOUT"):
                print(f"    → {fr['result_line']} ({fr['elapsed']:.1f}s)")
        print(f"  小计: {passed} 通过, {failed} 失败 ({elapsed:.1f}s)")

    print("\n" + "=" * 70)
    print(f"总计: {total_all_passed} 通过, {total_all_failed} 失败 ({total_all_elapsed:.1f}s)")
    print("=" * 70)

    # 全部通过标识
    if total_all_failed == 0 and total_all_passed > 0:
        print("✅ 全部通过")
    elif total_all_failed > 0:
        print("❌ 存在失败")

    # 保存结果
    with open(RESULTS_FILE, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "layers": all_results,
            "summary": {
                "total_passed": total_all_passed,
                "total_failed": total_all_failed,
                "total_elapsed": total_all_elapsed,
            }
        }, f, ensure_ascii=False, indent=2)

    return total_all_passed, total_all_failed


def main():
    parser = argparse.ArgumentParser(description="Hermes 全层测试执行器")
    parser.add_argument("--layer", choices=list(LAYER_CONFIG.keys()), help="只跑指定层")
    parser.add_argument("--timeout", type=int, default=300, help="单个文件超时(秒)")
    parser.add_argument("--fast", action="store_true", help="跳过慢速测试")
    args = parser.parse_args()

    layers_to_run = {args.layer: LAYER_CONFIG[args.layer]} if args.layer else LAYER_CONFIG

    print(f"开始执行测试... ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")

    all_results = []
    for layer_name, config in layers_to_run.items():
        print(f"\n>>> {layer_name}...", end="", flush=True)
        res = run_layer(layer_name, config, timeout=args.timeout)
        all_results.append(res)
        print(f" {res['total_passed']} 通过, {res['total_failed']} 失败 ({res['total_elapsed']:.1f}s)")

    print_summary(all_results)


if __name__ == "__main__":
    main()