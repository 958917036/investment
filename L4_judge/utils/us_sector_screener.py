#!/usr/bin/env python3
"""
神农系统 — 美股 AI/新能源/芯片 选股批量分析
Target: ~100只 AI芯片/云计算基础设施/清洁能源 相关美股
"""
import sys, os, json, time, subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.expanduser('~/.hermes/investment')
os.chdir(BASE)
sys.path.insert(0, BASE)

# 导入共享日志工具
sys.path.insert(0, os.path.join(BASE, "main", "utils"))
from logger import log_start, log_end, log_fail, info

TODAY = datetime.now().strftime('%Y-%m-%d')

# ── 精选股池：AI芯片/云计算/清洁能源 ──────────────────────────────
AI_CHIP = [
    'NVDA', 'AMD', 'INTC', 'QCOM', 'AVGO', 'MRVL', 'TXN', 'NXPI',
    'ON', 'MCHP', 'ADI', 'MPWR', 'GFS', 'ON',
]
CLOUD_AI = [
    'MSFT', 'GOOGL', 'META', 'AMZN', 'CRM', 'NOW', 'SNOW', 'PLTR', 'DBR', 'PANW',
    'CRWD', 'NET', 'ZS', 'VEEV', 'HUBS', 'TEAM', 'DDOG', 'APP', 'FVRR',
]
SEMI_EQUIP = [
    'AMAT', 'KLAC', 'LRCX', 'AMAT', 'TER', 'CAMT', 'ACLS',
    'SMCI', 'DELL', 'HPQ', 'ANET', 'CDNS', 'SNPS',
]
MEMORY = ['MU', 'WDC', 'STX']
CLEAN_ENERGY = [
    'TSLA', 'ENPH', 'SEDG', 'FSLR', 'NEE', 'BEP', 'CWEN',
    'RIVN', 'LCID', 'CHPT', 'BE', 'NOVA',
]
AI_SW = ['AI', 'SPLK', 'U', 'DT', 'PATH', 'ESTC', 'CFLT', 'GLOB']
ROBOTICS = ['TSLA', 'HON', 'CAT', 'DE', 'ABM', 'IRBT', 'OM']
OTHER_TECH = [
    'AAPL', 'CSCO', 'AMAT', 'ADI', 'MRVL', 'GFS', 'TEL',
    'MSI', 'JKHY', 'BR', 'NAVI', 'AFRM', 'SOFI', 'UPST',
]
HARDWARE = ['NVDA', 'AMD', 'INTC', 'QCOM', 'AVGO', 'MRVL', 'TXN', 'NXPI']

# 合并去重
all_tickers = list(set(AI_CHIP + CLOUD_AI + SEMI_EQUIP + MEMORY + CLEAN_ENERGY + AI_SW + ROBOTICS + OTHER_TECH + HARDWARE))
all_tickers.sort()
print(f"总股票数: {len(all_tickers)}")
print(f"列表: {all_tickers}")

# ── 分析函数 ──────────────────────────────────────────────────
def analyze_ticker(ticker):
    """运行单只股票分析，返回 (ticker, decision, score, reason)"""
    try:
        result = subprocess.run(
            [sys.executable, 'us_analysis.py', ticker, '--skip-persona'],
            capture_output=True, text=True, timeout=180,
            cwd=BASE
        )
        output = result.stdout + result.stderr
        
        # 提取关键信息
        decision = None
        score = None
        verdict = None
        stop_loss = None
        take_profit = None
        
        for line in output.split('\n'):
            if '最终裁决:' in line and '**' in line:
                # 格式: **最终裁决: WATCH** 或 **最终裁决: REJECT**
                if 'WATCH' in line:
                    decision = 'WATCH'
                elif 'BUY' in line:
                    decision = 'BUY'
                elif 'REJECT' in line:
                    decision = 'REJECT'
            if '综合评分:' in line and '/100' in line:
                # 格式:  🟡 综合评分: 51.1/100 (等级C)
                import re
                m = re.search(r'([\d.]+)/100', line)
                if m:
                    score = float(m.group(1))
            if '最终裁决: 谨慎' in line and '(' in line:
                # 格式: **最终裁决: 谨慎看空** | 置信度: 51%
                import re
                m = re.search(r'谨慎([看多看空]+)\**\s*\|\s*置信度:\s*([\d.]+)', line)
                if m:
                    verdict = m.group(1)
        
        return (ticker, decision, score, verdict, stop_loss, take_profit, output[-500:] if output else '')
    
    except subprocess.TimeoutExpired:
        return (ticker, 'TIMEOUT', None, None, None, None, 'Timeout after 180s')
    except Exception as e:
        return (ticker, 'ERROR', None, None, None, None, str(e))

# ── 批量并行分析 ──────────────────────────────────────────────
print(f"\n开始批量分析 {len(all_tickers)} 只股票...")
print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

MAX_WORKERS = 8  # 并行数
results = []

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {executor.submit(analyze_ticker, t): t for t in all_tickers}
    done = 0
    for future in as_completed(futures):
        ticker = futures[future]
        done += 1
        try:
            r = future.result()
            results.append(r)
            status_icon = '✅' if r[1] in ('BUY', 'WATCH') else '❌' if r[1] == 'REJECT' else '⚠️'
            print(f"  [{done}/{len(all_tickers)}] {status_icon} {ticker}: {r[1]} | 评分={r[2]} | {r[3]}")
        except Exception as e:
            print(f"  [{done}/{len(all_tickers)}] ❌ {ticker}: ERROR {e}")
            results.append((ticker, 'ERROR', None, None, None, None, str(e)))

# ── 汇总报告 ─────────────────────────────────────────────────
print(f"\n{'='*72}")
print(f"  神农系统 — 美股 AI/新能源/芯片 选股报告")
print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  覆盖股票: {len(all_tickers)} 只")
print(f"{'='*72}")

# 按决策分组
buy_list = [(t, s, v) for t, d, s, v, sl, tp, _ in results if d == 'BUY']
watch_list = [(t, s, v) for t, d, s, v, sl, tp, _ in results if d == 'WATCH']
reject_list = [(t, s, v) for t, d, s, v, sl, tp, _ in results if d == 'REJECT']
error_list = [(t, r[-100:]) for t, d, s, v, sl, tp, r in results if d not in ('BUY', 'WATCH', 'REJECT')]

print(f"\n📈 买入(WATCH) — {len(watch_list)} 只:")
watch_sorted = sorted(watch_list, key=lambda x: x[1] or 0, reverse=True)
for i, (t, s, v) in enumerate(watch_sorted[:20], 1):
    emoji = '🟢' if (s or 0) >= 60 else '🟡' if (s or 0) >= 30 else '🔴'
    print(f"  {i:2d}. {emoji} {t:6s} 评分={s or '?'} | {v or ''}")

print(f"\n⚠️  不建议 — {len(reject_list)} 只:")
print(f"  (Top 10 by score)")
reject_sorted = sorted(reject_list, key=lambda x: x[1] or 0, reverse=True)
for i, (t, s, v) in enumerate(reject_sorted[:10], 1):
    print(f"  {i:2d}. 🔴 {t:6s} 评分={s or '?'} | {v or ''}")

if error_list:
    print(f"\n⚠️  分析异常 — {len(error_list)} 只:")
    for t, err in error_list:
        print(f"  • {t}: {err}")

# 统计
total_with_score = len([r for r in results if r[2] is not None])
avg_score = sum(r[2] for r in results if r[2] is not None) / total_with_score if total_with_score else 0
print(f"\n📊 统计:")
print(f"  总计: {len(results)} 只")
print(f"  有效分析: {total_with_score} 只")
print(f"  平均评分: {avg_score:.1f}")
print(f"  WATCH: {len(watch_list)} ({100*len(watch_list)/len(results):.0f}%)")
print(f"  REJECT: {len(reject_list)} ({100*len(reject_list)/len(results):.0f}%)")

# 保存详细结果
output_dir = os.path.join(BASE, 'main', 'records', TODAY)
os.makedirs(output_dir, exist_ok=True)

# 保存汇总
summary = {
    'run_date': TODAY,
    'total': len(results),
    'valid': total_with_score,
    'avg_score': round(avg_score, 1),
    'watch_count': len(watch_list),
    'reject_count': len(reject_list),
    'watch_list': [{'ticker': t, 'score': s, 'verdict': v} for t, s, v in watch_sorted],
    'reject_list': [{'ticker': t, 'score': s, 'verdict': v} for t, s, v in reject_sorted],
    'error_list': [{'ticker': t, 'error': e} for t, e in error_list],
}
summary_path = os.path.join(output_dir, f'US_AI_chip_screening_{TODAY}.json')
log_start("us_sector_screener", "save_summary", summary_path)
try:
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    log_end("us_sector_screener", "save_summary", f"写入 {len(results)} 条结果")
except Exception as e:
    log_fail("us_sector_screener", "save_summary", str(e))
    raise

print(f"\n📄 详情已保存: {summary_path}")
print(f"  总耗时: {time.time()}")