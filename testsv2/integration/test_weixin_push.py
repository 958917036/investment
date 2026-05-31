#!/usr/bin/env python3
"""
===================================================================
神农系统 — WeChat 推送诊断 + 修复测试
===================================================================
目标：彻底诊断 WeChat 推送失败根因，并找到可用的推送方式

Step 1: 检查环境配置
Step 2: 测试 send_message_tool 直接调用
Step 3: 测试 _send_weixin 独立调用
Step 4: 测试 cron scheduler deliver 路径
Step 5: 验证可行方案
===================================================================
"""
import sys, os, asyncio, json, time

# ── Step 1: 检查环境配置 ──────────────────────────────────────
print("="*60)
print("STEP 1: 环境配置检查")
print("="*60)

required_env = [
    "WEIXIN_TOKEN",
    "WEIXIN_ACCOUNT_ID",
    "WEIXIN_BASE_URL",
]
for var in required_env:
    val = os.getenv(var, "")
    masked = val[:6] + "***" if val else "❌ 未设置"
    print(f"  {var}: {masked}")

home_channel = os.getenv("WEIXIN_HOME_CHANNEL", "")
print(f"  WEIXIN_HOME_CHANNEL: {home_channel if home_channel else '❌ 未设置'}")

# 检查 config.yaml
config_path = os.path.expanduser("~/.hermes/config.yaml")
if os.path.exists(config_path):
    with open(config_path) as f:
        content = f.read()
        has_weixin = "weixin" in content.lower()
        print(f"  config.yaml 有 weixin 配置: {'✅' if has_weixin else '❌'}")
else:
    print(f"  config.yaml: ❌ 不存在")

# ── Step 2: 测试 send_message_tool 直接调用 ──────────────────
print("\n" + "="*60)
print("STEP 2: send_message_tool 直接调用（主会话上下文）")
print("="*60)

try:
    from tools.send_message_tool import send_message_tool
    test_args = {
        "action": "send",
        "target": "weixin:o9cq800p94khwtbadUjqZNYJvy0Y@im.wechat",
        "message": f"🔬 WeChat推送诊断测试 {time.strftime('%H:%M:%S')}\n\n这是来自神农系统的诊断消息，验证WeChat推送功能。"
    }
    result = send_message_tool(test_args)
    parsed = json.loads(result)
    print(f"  结果: {json.dumps(parsed, ensure_ascii=False, indent=2)}")
except Exception as e:
    print(f"  ❌ send_message_tool 调用失败: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# ── Step 3: 测试 _send_weixin 独立调用 ──────────────────────
print("\n" + "="*60)
print("STEP 3: _send_weixin 独立调用（绕过 send_message_tool）")
print("="*60)

try:
    from gateway.platforms.weixin import _send_weixin_one_shot
    from gateway.config import PlatformConfig
    import os

    token = os.getenv("WEIXIN_TOKEN", "")
    account_id = os.getenv("WEIXIN_ACCOUNT_ID", "")
    base_url = os.getenv("WEIXIN_BASE_URL", "")

    if token and account_id:
        pconfig = PlatformConfig(
            enabled=True,
            token=token,
            extra={
                "account_id": account_id,
                "base_url": base_url,
                "cdn_base_url": os.getenv("WEIXIN_CDN_BASE_URL", ""),
            }
        )
        coro = _send_weixin_one_shot(
            token=token,
            chat_id="o9cq800p94khwtbadUjqZNYJvy0Y@im.wechat",
            message=f"🔬 _send_weixin_one_shot 诊断测试 {time.strftime('%H:%M:%S')}",
            extra=pconfig.extra,
        )
        result = asyncio.run(coro)
        print(f"  结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
    else:
        print(f"  ❌ 缺少 WEIXIN_TOKEN 或 WEIXIN_ACCOUNT_ID")
except ImportError as e:
    print(f"  ❌ 导入失败: {e}")
except Exception as e:
    print(f"  ❌ _send_weixin_one_shot 调用失败: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# ── Step 4: 测试 cron scheduler deliver 路径 ──────────────────
print("\n" + "="*60)
print("STEP 4: cron scheduler deliver 路径测试")
print("="*60)

try:
    from cron.scheduler import _resolve_single_delivery_target, _deliver_result
    from gateway.config import load_gateway_config

    job = {
        "id": "test_weixin_job",
        "deliver": "weixin",
        "name": "测试任务",
    }
    target = _resolve_single_delivery_target(job, "weixin")
    print(f"  解析目标: {target}")

    config = load_gateway_config()
    pconfig = config.platforms.get("weixin") if hasattr(config.platforms, "get") else config.platforms.get("weixin")

    test_content = f"🔬 Cron scheduler deliver 测试 {time.strftime('%H:%M:%S')}"
    result = _deliver_result(job, test_content)
    print(f"  deliver 结果: {result}")
except Exception as e:
    print(f"  ❌ cron deliver 测试失败: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# ── Step 5: 列出所有可用平台配置 ────────────────────────────
print("\n" + "="*60)
print("STEP 5: 可用平台配置")
print("="*60)
try:
    from gateway.config import load_gateway_config, Platform
    config = load_gateway_config()
    print(f"  已配置平台数: {len(config.platforms)}")
    for name, pconfig in config.platforms.items():
        enabled = getattr(pconfig, 'enabled', '?')
        token_short = str(getattr(pconfig, 'token', ''))[:6] + "***" if getattr(pconfig, 'token', '') else "无"
        print(f"    {name}: enabled={enabled}, token={token_short}")
except Exception as e:
    print(f"  ❌ 无法加载平台配置: {e}")

print("\n" + "="*60)
print("诊断完成")
print("="*60)
