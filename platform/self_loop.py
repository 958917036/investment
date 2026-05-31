#!/usr/bin/env python3
"""
神农平台自闭环执行器 v4
核心原则：1次执行 = 处理完所有pending blocker后退出，不是只处理1个
"""
import json
import os
import sys
import subprocess
import time
import fcntl
from datetime import datetime

LOCK_FILE = "/tmp/hermes_platform.lock"
STATE_FILE = os.path.expanduser("~/.hermes/investment/platform/platform_state.json")
LOG_DIR = os.path.expanduser("~/.hermes/cron/output/self_loop_logs")
os.makedirs(LOG_DIR, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def write_log(msg):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"{ts}.log")
    with open(log_file, "w") as f:
        f.write(msg + "\n")
    return log_file

def acquire_lock():
    """获取锁，防止并发执行"""
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid = os.getpid()
        data = {
            "pid": pid,
            "status": "running",
            "start_time": datetime.now().isoformat(),
            "current_blocker_id": None,
            "completed_ids": []
        }
        lock.write(json.dumps(data))
        lock.flush()
        log(f"Lock acquired, PID={pid}")
        return True
    except BlockingIOError:
        log("SKIP: 锁被占用，上次任务仍在运行")
        return False

def release_lock():
    """释放锁"""
    try:
        os.unlink(LOCK_FILE)
    except:
        pass

def update_blocker_state(blocker_id, new_state, error_msg=None):
    """
    更新blocker状态到platform_state.json
    new_state: 'running' | 'resolved' | 'failed'
    """
    with open(STATE_FILE) as f:
        state = json.load(f)

    for b in state.get("system_blockers", []):
        if b["id"] == blocker_id:
            b["state"] = new_state
            b["updated_at"] = datetime.now().isoformat()
            if error_msg:
                b["error_message"] = error_msg
                b["retry_count"] = b.get("retry_count", 0) + 1
            break

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    log(f"Blocker {blocker_id} state -> {new_state}")

def get_claude_env():
    """从 /Users/guchuang/.claude/settings.json 读取凭证，供cron session使用"""
    settings_path = "/Users/guchuang/.claude/settings.json"
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        env = os.environ.copy()
        env["HOME"] = "/Users/guchuang"  # cron session需要
        env.update(settings.get("env", {}))
        return env
    except Exception as e:
        log(f"读取claude凭证失败: {e}，使用当前环境")
        return os.environ.copy()

def delegate_fix(blocker_id, description, estimated_fix):
    """
    通过 claude -p (print mode) 执行修复
    返回 (success, detail)
    """
    task = f"""你是一个自动化代码修复工具。

blocker_id: {blocker_id}
问题描述: {description}
建议修复方案: {estimated_fix}

项目路径: ~/.hermes/investment/platform/
前端目录: ~/.hermes/investment/platform/frontend/

请严格按照以下步骤执行：
1. 读取相关源文件，定位问题
2. 使用 patch 工具修复代码
3. 在 ~/.hermes/investment/platform/frontend 目录执行 npm run build
4. 如果build失败，继续修复直到通过
5. 验证修复有效后，执行 exit 退出

重要：
- 只修复指定的blocker，不要改动其他文件
- 必须确保 npm run build 通过
- 使用 patch 工具进行代码修改，不要用其他方式"""

    try:
        env = get_claude_env()
        # stdin=/dev/null 防止 claude -p 等待 tty 输入
        # timeout=600 给测试类 blocker 足够时间
        result = subprocess.run(
            ["claude", "-p", task,
             "--dangerously-skip-permissions",
             "--allowedTools", "Read,Edit,Bash,Terminal",
             "--max-turns", "60",
             "--no-session-persistence"],
            capture_output=True, text=True, timeout=600,
            cwd=os.path.expanduser("~/.hermes/investment/platform"),
            env=env,
            stdin=subprocess.DEVNULL
        )
        if result.returncode == 0:
            log(f"delegate成功: {blocker_id}")
            return True, "ok"
        else:
            err = result.stderr[-300:] if result.stderr else "unknown"
            log(f"delegate失败: {blocker_id} - {err}")
            return False, err
    except Exception as e:
        log(f"delegate异常: {blocker_id} - {e}")
        return False, str(e)

def run_build():
    """执行 npm run build，返回 (success, detail)"""
    try:
        r = subprocess.run(
            ["npm", "run", "build"],
            cwd=os.path.expanduser("~/.hermes/investment/platform/frontend"),
            capture_output=True, text=True, timeout=180
        )
        if r.returncode == 0:
            return True, "build_ok"
        err = r.stderr[-500:] if r.stderr else r.stdout[-500:]
        return False, err
    except Exception as e:
        return False, str(e)

def run_api_check():
    """检查后端API是否正常"""
    try:
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:8000/api/health"],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() == "200", r.stdout.strip()
    except:
        return False, "error"

def remove_blocker(blocker_id):
    """将blocker从队列中移除（视为已解决）"""
    with open(STATE_FILE) as f:
        state = json.load(f)
    state["system_blockers"] = [b for b in state["system_blockers"] if b["id"] != blocker_id]
    if not state["system_blockers"]:
        state["system_complete"] = True
        state["completion_percentage"] = 100
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def process_blocker(b):
    """处理单个blocker，返回是否成功"""
    bid = b["id"]
    desc = b.get("description", "")
    fix = b.get("estimated_fix", "")
    sev = b.get("severity", "medium")

    log(f"处理 blocker: {bid} - {desc[:60]}")

    # 1. 更新状态为 running
    update_blocker_state(bid, "running")

    # 2. 委托修复
    fix_ok, fix_detail = delegate_fix(bid, desc, fix)

    if not fix_ok:
        update_blocker_state(bid, "failed", f"delegate_failed: {fix_detail[:200]}")
        log_msg = f"FAIL {bid}: delegate失败 - {fix_detail[:200]}"
        write_log(log_msg)
        log(log_msg)
        return False

    # 3. 验证build
    build_ok, build_detail = run_build()
    if not build_ok:
        update_blocker_state(bid, "failed", f"build_failed: {build_detail[-200:]}")
        log_msg = f"FAIL {bid}: build失败 - {build_detail[-200:]}"
        write_log(log_msg)
        log(log_msg)
        return False

    # 4. 验证API（可选，快速检查）
    api_ok, api_detail = run_api_check()
    if not api_ok:
        log(f"WARNING: API不健康但build通过 - {api_detail}")

    # 5. 成功：移除blocker
    remove_blocker(bid)

    log_msg = f"OK {bid} (severity={sev}, build=ok, api={'ok' if api_ok else 'warn'})"
    write_log(log_msg)
    log(log_msg)
    return True

def main():
    log("=== 神农平台自闭环开始 (v4: 处理所有pending) ===")

    # 1. 获取锁
    if not acquire_lock():
        log("自闭环退出：锁被占用")
        return

    try:
        # 2. 读取state
        with open(STATE_FILE) as f:
            state = json.load(f)

        blockers = state.get("system_blockers", [])

        # 3. 收集所有 pending 状态的blocker
        pending = []
        for b in blockers:
            s = b.get("state") or b.get("status")
            if s == "pending":
                pending.append(b)

        if not pending:
            log("无待处理blocker，执行健康检查后退出")
            ok, detail = run_api_check()
            log(f"API健康检查: {'OK' if ok else 'FAIL'} - {detail}")
            log("=== 自闭环结束 ===")
            return

        log(f"共 {len(pending)} 个待处理blocker，依次处理")

        # 4. 循环处理所有pending blocker
        for b in pending:
            # 重新读取state（因为上一个blocker处理后可能改变了列表）
            with open(STATE_FILE) as f:
                state = json.load(f)
            # 检查当前blocker是否还在pending列表
            still_pending = any(
                (blk.get("state") or blk.get("status")) == "pending" and blk["id"] == b["id"]
                for blk in state.get("system_blockers", [])
            )
            if not still_pending:
                log(f"跳过 {b['id']}（已被处理或不在pending列表）")
                continue

            success = process_blocker(b)

            # 失败后继续处理下一个，不停止
            if not success:
                log(f"WARNING: {b['id']} 处理失败，继续下一个")

        # 5. 全部处理完毕，更新system_complete状态
        with open(STATE_FILE) as f:
            state = json.load(f)
        remaining = [blk for blk in state.get("system_blockers", [])
                     if (blk.get("state") or blk.get("status")) == "pending"]
        if not remaining:
            state["system_complete"] = True
            state["completion_percentage"] = 100
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            log("所有blocker已处理完毕，system_complete=true")

        # 6. 微信推送（汇总）
        try:
            subprocess.run(
                ["python3", os.path.expanduser("~/.hermes/scripts/weixin_push.py"),
                 "自闭环", "自闭环一轮执行完毕"],
                capture_output=True, timeout=15
            )
        except:
            pass

        log("=== 自闭环结束 ===")

    finally:
        release_lock()

if __name__ == "__main__":
    main()
