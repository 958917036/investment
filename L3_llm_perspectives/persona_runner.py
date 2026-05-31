"""
人格轨引擎 v3 — 双模式设计

默认模式（merged）：
  - 12大师合并调用，一次LLM请求完成全部12位大师的分析
  - 加强prompt隔离指令，每位大师各自独立段落，禁止互相引用
  - 每大师输出结构统一（score/grade/verdict/rationale）
  - 速度快（1次API≈1.5s vs 12次≈22s）

独立模式（independent）：
  - 12次独立LLM调用，每位大师加载完整system_prompt.md
  - 完全隔离，无角色污染
  - 通过环境变量 TEST_PERSONAS 限制测试人数
  - 通过参数 run_mode="independent" 激活

API：使用MiniMax API（需MINIMAX_CN_API_KEY环境变量）
"""

import json
import os
import logging
import time
import re
from typing import Dict, Any, Optional, List

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger("persona_runner")

# 大师列表（完整12位）
PERSONAS = [
    "buffett", "graham", "burry", "druckenmiller",
    "taleb", "ackman", "pabrai", "lynch",
    "cathie_wood", "munger", "phil_fisher", "jhunjhunwala",
]

# ── 生产默认：精简至3位（价值/成长/宏观）────────────────────────
# 价值投资：巴菲特（护城河+合理价格买伟大公司）
# 成长投资：彼得·林奇（成长股挖掘）
# 宏观交易：德鲁肯米勒（宏观催化+择时）
# 理由：3位覆盖最主流风格，avg_score区分度最高；保留PERSONAS完整列表供TEST_PERSONAS调试
DEFAULT_PERSONAS = ["buffett", "lynch", "druckenmiller"]

PERSONA_NAMES = {
    "buffett": "沃伦·巴菲特(Warren Buffett)",
    "graham": "本杰明·格雷厄姆(Benjamin Graham)",
    "burry": "迈克尔·巴里(Michael Burry)",
    "druckenmiller": "斯坦利·德鲁肯米勒(Stanley Druckenmiller)",
    "taleb": "纳西姆·塔勒布(Nassim Taleb)",
    "ackman": "比尔·阿克曼(Bill Ackman)",
    "pabrai": "莫尼斯·帕伯莱(Mohnish Pabrai)",
    "lynch": "彼得·林奇(Peter Lynch)",
    "cathie_wood": "凯西·伍德(Cathie Wood)",
    "munger": "查理·芒格(Charlie Munger)",
    "phil_fisher": "菲利普·费雪(Philip Fisher)",
    "jhunjhunwala": "拉克什·君胡瓦拉(Rakesh Jhunjhunwala)",
}

CONSERVATIVE = ["buffett", "graham", "burry", "taleb", "munger"]
MODERATE = ["druckenmiller", "lynch", "phil_fisher", "jhunjhunwala"]
AGGRESSIVE = ["ackman", "pabrai", "cathie_wood"]

PERSONA_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 模型配置（统一入口）─────────────────────────────────────
_MODEL_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "main", "config", "model_config.json"
)

def _load_model_config() -> dict:
    """从 model_config.json 加载模型配置"""
    try:
        with open(_MODEL_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_model_config_cache = None
def _get_model_config() -> dict:
    global _model_config_cache
    if _model_config_cache is None:
        _model_config_cache = _load_model_config()
    return _model_config_cache

def _get_api_key() -> str:
    """获取 API Key：优先从 model_config.json 读取（支持 ${ENV_VAR} 语法），回退到环境变量"""
    cfg = _get_model_config()
    minimax_cfg = cfg.get("minimax", {})
    key = minimax_cfg.get("api_key", "")
    # 支持 ${ENV_VAR} 环境变量引用格式
    if key.startswith("${") and key.endswith("}"):
        env_var = key[2:-1]
        key = os.environ.get(env_var, "")
    if not key:
        key = os.environ.get("MINIMAX_CN_API_KEY", "")
    return key

# ── Persona 配置加载 ────────────────────────────────────────
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "main", "config", "l3_persona_config.json"
)

def _load_persona_config() -> dict:
    """从配置文件加载Persona参数"""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_persona_config_cache = None
def _get_persona_config() -> dict:
    global _persona_config_cache
    if _persona_config_cache is None:
        _persona_config_cache = _load_persona_config()
    return _persona_config_cache

def _get_active_personas() -> list:
    """获取活跃人格列表（支持TEST_PERSONAS环境变量覆盖）"""
    test = os.environ.get("TEST_PERSONAS", "")
    if test:
        names = [n.strip() for n in test.split(",") if n.strip()]
        valid = [n for n in names if n in PERSONAS]
        if valid:
            return valid
    cfg = _get_persona_config()
    return cfg.get("default_personas", DEFAULT_PERSONAS)


def _load_persona_prompt(name: str) -> str:
    """加载单个人格的完整system prompt"""
    path = os.path.join(PERSONA_DIR, name, "system_prompt.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        alt_path = os.path.join(PERSONA_DIR, "prompts", name, "system_prompt.md")
        try:
            with open(alt_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.warning(f"人格prompt未找到: {path} 或 {alt_path}")
            return f"# {name} Perspective\n\n角色：{name}\n核心理念：无\n"


def _build_data_summary(code: str, name: str, price: float, data: dict) -> dict:
    """构建数据摘要"""
    tech = data.get("technical_data", data)
    funda = data.get("fundamental_data", data)
    mf = data.get("moneyflow_data", {})
    sector = data.get("sector_data", {})

    return {
        "code": code, "name": name, "price": price,
        "pe": funda.get("pe", tech.get("pe", "N/A")),
        "pb": funda.get("pb", tech.get("pb", "N/A")),
        "market_cap": funda.get("market_cap", tech.get("market_cap", "N/A")),
        "turnover_rate": tech.get("turnover", "N/A"),
        "52w_high": tech.get("week52_high", "N/A"),
        "52w_low": tech.get("week52_low", "N/A"),
        "change_pct": tech.get("change_pct", "N/A"),
        "volume": tech.get("volume", "N/A"),
        "amount": tech.get("amount", "N/A"),
        "ma60_position_pct": tech.get("ma60_position_pct", "N/A"),
        "macd_signal": tech.get("macd_status", tech.get("macd_signal", "N/A")),
        "rsi": tech.get("rsi", "N/A"),
        "main_net_flow_5d": mf.get("main_net_flow_5d", "N/A"),
        "small_order_net_flow_5d": mf.get("small_order_net_flow_5d", "N/A"),
        "roe": funda.get("roe", "N/A"),
        "gross_margin": funda.get("gross_margin", "N/A"),
        "revenue_growth": funda.get("revenue_growth", "N/A"),
        "debt_ratio": funda.get("debt_ratio", "N/A"),
    }


def _call_llm(system_prompt: str, user_prompt: str,
              caller_name: str, max_tokens: int = None,
              temperature: float = None) -> Optional[Dict[str, Any]]:
    model_cfg = _get_model_config()
    minimax_cfg = model_cfg.get("minimax", {})
    # API 参数：从 model_config.json 读取，支持环境变量 ${VAR} 语法
    api_key = _get_api_key()
    if not api_key:
        logger.error(f"[{caller_name}] API Key 未设置（model_config.json 或 MINIMAX_CN_API_KEY），人格轨跳过")
        return None

    if requests is None:
        logger.error(f"[{caller_name}] requests 库未安装")
        return None

    # 模型参数
    if max_tokens is None:
        max_tokens = minimax_cfg.get("max_tokens", 4096)
    if temperature is None:
        temperature = minimax_cfg.get("temperature", 0.3)
    timeout = minimax_cfg.get("timeout", 120)
    url = minimax_cfg.get("endpoint", "https://api.minimaxi.com/anthropic/v1/messages")
    model = minimax_cfg.get("model", "MiniMax-M2.7")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }
    payload = {
        "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        result = resp.json()
        # 防御：检查是否是错误响应
        if "error" in result:
            raise ValueError(f"API返回错误: {result['error']}")
        # 兼容 OpenAI (choices) 和 Anthropic (content blocks) 两种响应格式
        content = None
        if "choices" in result and result["choices"]:
            # OpenAI 兼容格式
            content = result["choices"][0]["message"]["content"]
        elif "content" in result and isinstance(result["content"], list):
            # Anthropic 兼容格式 (MiniMax)
            for block in result["content"]:
                if block.get("type") == "text":
                    content = block.get("text", "")
                    break
        if not content:
            raise ValueError(f"无法从响应中提取content: {str(result)[:200]}")
        # 去除Markdown代码 fence（常见于LLM返回格式）
        content = content.strip()
        if content.startswith('```'):
            # 去掉 ```json ... ``` 或 ``` ... ```
            lines = content.split('\n')
            # 去掉第一行的 ```json 或 ```
            first_line = lines[0].strip().lstrip('`').strip()
            if first_line:
                lines = lines[1:]
            # 去掉最后一行的 ```
            if lines and lines[-1].strip().lstrip('`').strip() == '':
                lines = lines[:-1]
            content = '\n'.join(lines).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as je:
            # 记录原始content前500字符用于调试
            logger.warning(f"[{caller_name}] JSON解析失败(char={je.pos}, line~{content[:500]}): {je}")
            raise  # 让下面的except捕获
    except json.JSONDecodeError as e:
        logger.warning(f"[{caller_name}] JSON解析失败: {e}")
        # MiniMax有时返回纯文本或Markdown包裹的JSON，尝试多种方式提取
        if 'content' in locals() and content:
            # 方法1: 直接尝试已去除fence的content（新增的fence去除逻辑已处理）
            # 方法2: 找到第一个{到最后一个}的范围，渐进扩大尝试解析
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1 and end > start:
                # 逐步扩大搜索范围，最多扩10次
                for delta in range(0, 10):
                    s = max(0, start - delta)
                    e = min(len(content), end + delta + 1)
                    candidate = content[s:e]
                    try:
                        parsed = json.loads(candidate)
                        logger.warning(f"[{caller_name}] 渐进式JSON提取成功(offset={delta})")
                        return parsed
                    except json.JSONDecodeError:
                        continue
            # 方法3: 尝试提取 JSON 数组
            for match in re.finditer(r'\[[\s\S]+\]', content):
                try:
                    parsed = json.loads(match.group())
                    if isinstance(parsed, list) and len(parsed) > 0:
                        logger.warning(f"[{caller_name}] JSON数组提取成功")
                        return parsed
                except json.JSONDecodeError:
                    continue
            # 方法4: 逐人格块正则提取（LLM输出中某个人格的rationale含特殊字符
            # 导致整体JSON缺逗号，但每个子块本身是完整JSON）
            extracted = {}
            for pname in _get_active_personas():
                # 匹配 "persona_name": { ... }
                pattern = rf'"{re.escape(pname)}"\s*:\s*\{{'
                m = re.search(pattern, content)
                if not m:
                    continue
                brace_start = m.end() - 1  # 定位到{
                depth = 0
                i = brace_start
                while i < len(content):
                    if content[i] == '{':
                        depth += 1
                    elif content[i] == '}':
                        depth -= 1
                        if depth == 0:
                            block = content[brace_start:i+1]
                            try:
                                parsed_block = json.loads(block)
                                extracted[pname] = parsed_block
                            except json.JSONDecodeError:
                                # 尝试修复：缺逗号（相邻字符串值之间）是最常见问题
                                # 如 "rationale": "foo" "grade" → 应在 "foo" 后加 ,
                                fixed = re.sub(
                                    r'(")\s*("[\w_]+"\s*:)',
                                    r'\1,\2',
                                    block
                                )
                                try:
                                    parsed_block = json.loads(fixed)
                                    extracted[pname] = parsed_block
                                    logger.warning(f"[{caller_name}] 逐人格块修复成功: {pname}")
                                except json.JSONDecodeError:
                                    pass  # 无法修复，放弃该人格
                            break
                    i += 1
            if extracted:
                logger.warning(f"[{caller_name}] 逐人格块提取成功: {list(extracted.keys())}")
                return extracted
            logger.warning(f"[{caller_name}] 无法从文本中提取JSON: {content[:100]}...")
        return None
    except Exception as e:
        logger.error(f"[{caller_name}] LLM调用失败: {e}")
        return None


def _normalize_persona_result(result: dict, persona_name: str) -> dict:
    """将各大师输出的自定义字段映射为标准字段"""
    required = ["score", "grade", "verdict", "rationale"]
    local_name = persona_name.replace("-", "_").lower()

    # 字段映射
    field_map = {
        "score": [f"{local_name}_score", f"{persona_name}_score",
                  "score", "rating", "buffett_score", "graham_score",
                  "burry_score", "lynch_score", "munger_score",
                  "fisher_score", "taleb_score", "druckenmiller_score",
                  "ackman_score", "pabrai_score", "wood_score",
                  "cathie_score", "jhunjhunwala_score"],
        "grade": [f"{local_name}_grade", f"{persona_name}_grade",
                  "grade", "level", "buffett_grade", "graham_grade",
                  "burry_grade", "lynch_grade", "munger_grade",
                  "fisher_grade", "taleb_grade", "druckenmiller_grade",
                  "ackman_grade", "pabrai_grade", "wood_grade",
                  "cathie_grade", "jhunjhunwala_grade"],
        "verdict": ["verdict", "decision", "action", "recommendation"],
        "rationale": ["rationale", "reasoning", "explanation", "analysis",
                      "summary", "reason"],
    }

    normalized = {}
    for std_name, aliases in field_map.items():
        found = None
        for alias in aliases:
            if alias in result:
                found = result[alias]
                break
        if found is not None:
            normalized[std_name] = found
        else:
            normalized[std_name] = 0 if std_name == "score" else "D" if std_name == "grade" else "REJECT" if std_name == "verdict" else "数据不足"

    return normalized


def _normalize_verdict(verdict: str) -> str:
    """规范化判断结果"""
    v = verdict.upper().strip()
    if v in ("BUY", "WATCH", "REJECT", "HOLD"):
        return v
    return "REJECT"


# ============================================================
#  合并模式 — 1次LLM调用分析所有12位大师
# ============================================================

def _build_merged_system_prompt() -> str:
    """构建合并调用的系统prompt — 强隔离指令"""
    personas_info = "\n".join([
        f"- {key}: {PERSONA_NAMES[key]}"
        for key in _get_active_personas()
    ])

    return f"""你是一位多视角投资分析系统，负责模拟{len(_get_active_personas())}位不同投资大师的视角，对同一只股票做出独立判断。

## ⚠️ 核心隔离规则（必须严格遵守）
每位大师的判断必须是**完全独立**的，基于各自独特的投资理念和框架。禁止任何大师引用其他大师的意见。禁止出现"与其他大师看法一致/相似"之类的表述。每位大师的段落必须自我完备。

## 大师列表
{personas_info}

## 输出格式
输出一个JSON对象，key为大师ID（如 "buffett", "graham" 等），每个value为包含以下字段的对象：
- "score": 0.0-1.0 评分（越高越看好）
- "grade": "A/B/C/D" 等级（A=强烈看好, B=看好, C=中性, D=不看好）
- "verdict": "BUY"/"WATCH"/"REJECT"/"HOLD" 决断
- "rationale": 1-2句判断理由（不超过100字）

示例：
{{
    "buffett": {{"score": 0.3, "grade": "D", "verdict": "REJECT", "rationale": "护城河不足..."}},
    "graham": {{"score": 0.7, "grade": "B", "verdict": "BUY", "rationale": "安全边际充足..."}}
}}

## 约束
1. 所有评分必须在0-1之间
2. verdict只能是BUY/WATCH/REJECT/HOLD之一
3. 每位大师的输出互不影响
4. 必须包含所有大师，不得遗漏"""


def _build_merged_user_prompt(code: str, name: str, price: float,
                               data_summary: dict) -> str:
    """构建合并调用的用户prompt"""
    return f"""请模拟下面{len(_get_active_personas())}位投资大师，分别对以下股票做出独立判断。

## 股票信息
- 名称：{name}（{code}）
- 当前价格：{price}元
- 分析日期：{time.strftime('%Y-%m-%d')}

## 输入数据
```json
{json.dumps(data_summary, ensure_ascii=False, indent=2)}
```

## 要求
每位大师**独立**分析上面的数据，基于各自的投资理念做出判断。
禁止任何大师引用、参考、或对比其他大师的观点。
每位大师的思考过程必须完全独立。

输出严格JSON格式。"""


def _run_merged_mode(code: str, name: str, price: float,
                     data_summary: dict, data: dict) -> dict:
    """合并模式：1次LLM调用分析全部大师"""
    logger.info(f"人格轨合并模式: {name}({code}) — 1次调用{len(_get_active_personas())}位大师")

    system_prompt = _build_merged_system_prompt()
    user_prompt = _build_merged_user_prompt(code, name, price, data_summary)

    result = _call_llm(system_prompt, user_prompt, "merged_persona",
                       max_tokens=None, temperature=None)

    perspectives = {}
    total_score = 0.0
    buy_count = watch_count = reject_count = hold_count = 0
    success_count = 0

    if result is None:
        logger.error("合并模式LLM调用失败")
        for persona_name in _get_active_personas():
            perspectives[persona_name] = {
                "score": 0, "grade": "D", "verdict": "REJECT",
                "rationale": "LLM调用失败",
            }
            reject_count += 1
        return {
            "_status": "error", "_mode": "merged",
            "perspectives": perspectives,
            "summary": {
                "avg_score": 0, "buy_count": 0, "watch_count": 0,
                "reject_count": len(_get_active_personas()),
                "hold_count": 0, "agents_ok": 0,
                "agents_total": len(_get_active_personas()),
            },
        }

    for persona_name in _get_active_personas():
        raw = result.get(persona_name, {})
        if not raw:
            logger.warning(f"  [{persona_name}] 合并结果中缺失")
            perspectives[persona_name] = {
                "score": 0, "grade": "D", "verdict": "REJECT",
                "rationale": "数据缺失",
            }
            reject_count += 1
            continue

        norm = _normalize_persona_result(raw, persona_name)
        try:
            score = max(0, min(1, float(norm.get("score", 0))))
        except (ValueError, TypeError):
            score = 0

        grade = norm.get("grade", "D")[:1]
        grade = grade if grade in "ABCD" else "D"
        verdict = _normalize_verdict(norm.get("verdict", "REJECT"))
        rationale = str(norm.get("rationale", ""))[:120]

        perspectives[persona_name] = {
            "score": score, "grade": grade,
            "verdict": verdict, "rationale": rationale,
        }

        total_score += score
        success_count += 1

        if verdict == "BUY":
            buy_count += 1
        elif verdict == "WATCH":
            watch_count += 1
        elif verdict == "REJECT":
            reject_count += 1
        elif verdict == "HOLD":
            hold_count += 1

        logger.info(f"  [{persona_name}] {verdict} score={score:.2f}")

    # 补充缺失的大师
    for persona_name in _get_active_personas():
        if persona_name not in perspectives:
            perspectives[persona_name] = {
                "score": 0, "grade": "D", "verdict": "REJECT",
                "rationale": "LLM输出缺失",
            }
            reject_count += 1

    avg_score = round(total_score / max(success_count, 1), 4)

    return {
        "_status": "ok", "_mode": "merged",
        "perspectives": perspectives,
        "summary": {
            "avg_score": avg_score,
            "buy_count": buy_count,
            "watch_count": watch_count,
            "reject_count": reject_count,
            "hold_count": hold_count,
            "agents_ok": success_count,
            "agents_total": len(_get_active_personas()),
        },
    }


# ============================================================
#  独立模式 — 12次独立LLM调用（原v2保留）
# ============================================================

def _call_single_persona(persona_name: str, code: str, name: str,
                          price: float, data_summary: dict,
                          semaphore=None) -> tuple:
    """单大师并行调用（供ThreadPoolExecutor使用）"""
    p_start = time.time()

    # MiniMax并发限制：信号量控制同时请求数
    if semaphore is not None:
        semaphore.acquire()

    try:
        system_prompt = _load_persona_prompt(persona_name)
        user_prompt = f"""请以 **{persona_name}** 的视角，对股票 **{name}({code})** 做出独立判断。

当前价格：{price}元
分析日期：{time.strftime('%Y-%m-%d')}

## 输入数据
```json
{json.dumps(data_summary, ensure_ascii=False, indent=2)}
```

## 输出格式
基于你自己的投资理念和框架，必须输出严格JSON，包含：
- "score": 0.0-1.0 评分（越高越看好）
- "grade": "A/B/C/D" 等级
- "verdict": "BUY"/"WATCH"/"REJECT"/"HOLD"
- "rationale": 1-2句判断理由

只输出JSON，不要其他文字。"""

        result = _call_llm(system_prompt, user_prompt, persona_name,
                           max_tokens=None, temperature=None)

        p_duration = round(time.time() - p_start, 2)

        if result:
            norm = _normalize_persona_result(result, persona_name)
            try:
                score = max(0, min(1, float(norm.get("score", 0))))
            except (ValueError, TypeError):
                score = 0

            grade = norm.get("grade", "D")[:1]
            grade = grade if grade in "ABCD" else "D"
            verdict = _normalize_verdict(norm.get("verdict", "REJECT"))
            rationale = str(norm.get("rationale", ""))[:120]

            logger.info(f"  [{persona_name}] {verdict} score={score:.2f} ({p_duration:.1f}s)")
            return (persona_name, {
                "score": score, "grade": grade,
                "verdict": verdict, "rationale": rationale,
            }, verdict, score, p_duration, None)
        else:
            logger.warning(f"  [{persona_name}] ❌ 返回空 ({p_duration:.1f}s)")
            return (persona_name, {
                "score": 0, "grade": "D", "verdict": "REJECT",
                "rationale": "LLM调用失败",
            }, "REJECT", 0, p_duration, "LLM调用失败")
    finally:
        if semaphore is not None:
            semaphore.release()


def _run_independent_mode(code: str, name: str, price: float,
                           data_summary: dict) -> dict:
    """独立模式：12次顺序LLM调用，完全隔离（顺序执行稳定可靠）"""
    logger.info(f"人格轨独立模式: {name}({code}) — {len(_get_active_personas())}次顺序调用")

    perspectives = {}
    total_score = 0.0
    buy_count = watch_count = reject_count = hold_count = 0
    success_count = 0

    for persona_name in _get_active_personas():
        p_start = time.time()

        system_prompt = _load_persona_prompt(persona_name)
        user_prompt = f"""请以 **{persona_name}** 的视角，对股票 **{name}({code})** 做出独立判断。

当前价格：{price}元
分析日期：{time.strftime('%Y-%m-%d')}

## 输入数据
```json
{json.dumps(data_summary, ensure_ascii=False, indent=2)}
```

## 输出格式
基于你自己的投资理念和框架，必须输出严格JSON，包含：
- "score": 0.0-1.0 评分（越高越看好）
- "grade": "A/B/C/D" 等级
- "verdict": "BUY"/"WATCH"/"REJECT"/"HOLD"
- "rationale": 1-2句判断理由

只输出JSON，不要其他文字。"""

        result = _call_llm(system_prompt, user_prompt, persona_name,
                           max_tokens=None, temperature=None)

        if result:
            norm = _normalize_persona_result(result, persona_name)
            try:
                score = max(0, min(1, float(norm.get("score", 0))))
            except (ValueError, TypeError):
                score = 0

            grade = norm.get("grade", "D")[:1]
            grade = grade if grade in "ABCD" else "D"
            verdict = _normalize_verdict(norm.get("verdict", "REJECT"))
            rationale = str(norm.get("rationale", ""))[:120]

            perspectives[persona_name] = {
                "score": score, "grade": grade,
                "verdict": verdict, "rationale": rationale,
            }
            total_score += score
            success_count += 1

            if verdict == "BUY":
                buy_count += 1
            elif verdict == "WATCH":
                watch_count += 1
            elif verdict == "REJECT":
                reject_count += 1
            elif verdict == "HOLD":
                hold_count += 1

            p_duration = round(time.time() - p_start, 2)
            logger.info(f"  [{persona_name}] {verdict} score={score:.2f} ({p_duration:.1f}s)")
        else:
            perspectives[persona_name] = {
                "score": 0, "grade": "D", "verdict": "REJECT",
                "rationale": "LLM调用失败",
            }
            reject_count += 1
            p_duration = round(time.time() - p_start, 2)
            logger.warning(f"  [{persona_name}] ❌ 返回空 ({p_duration:.1f}s)")

    avg_score = round(total_score / max(success_count, 1), 4)

    return {
        "_status": "ok", "_mode": "independent",
        "perspectives": perspectives,
        "summary": {
            "avg_score": avg_score,
            "buy_count": buy_count,
            "watch_count": watch_count,
            "reject_count": reject_count,
            "hold_count": hold_count,
            "agents_ok": success_count,
            "agents_total": len(_get_active_personas()),
        },
    }


# ============================================================
#  公共入口
# ============================================================

def run_persona_analysis(code: str, name: str, price: float,
                         data: dict, run_mode: str = "merged") -> dict:
    """
    人格轨分析入口（保留，向后兼容）

    Args:
        code: 股票代码
        name: 股票名称
        price: 当前价格
        data: L2完整数据包
        run_mode: "merged"（默认，一次调用全部大师）或 "independent"（12次独立调用）

    Returns:
        dict with 'perspectives', 'summary', '_status', '_mode'
    """
    start = time.time()

    # 从统一配置读取 API Key
    api_key = _get_api_key()
    if not api_key:
        logger.warning("API Key 未设置（model_config.json 或 MINIMAX_CN_API_KEY），跳过人格轨分析")
        return {
            "_status": "skipped",
            "_reason": "API key not set",
            "perspectives": {}, "summary": {},
        }

    if run_mode not in ("merged", "independent"):
        logger.warning(f"未知模式 {run_mode}，使用默认merged")
        run_mode = "merged"

    data_summary = _build_data_summary(code, name, price, data)

    if run_mode == "independent":
        result = _run_independent_mode(code, name, price, data_summary)
    else:
        result = _run_merged_mode(code, name, price, data_summary, data)

    # 便利字段：顶层avg_score（兼容旧代码习惯）
    result["avg_score"] = result.get("summary", {}).get("avg_score", None)
    result["_version"] = "v3"
    result["_duration_s"] = round(time.time() - start, 2)
    result["_mode"] = run_mode

    s = result.get("summary", {})
    logger.info(f"人格轨{run_mode}完成: {name}({code}) {result['_duration_s']:.1f}s, "
                f"BUY={s.get('buy_count',0)} WATCH={s.get('watch_count',0)} "
                f"REJECT={s.get('reject_count',0)} HOLD={s.get('hold_count',0)} "
                f"均分={s.get('avg_score',0):.2f}")

    return result


def run_persona(L2_data: dict, l3_persona_config: dict, model_config: dict) -> dict:
    """
    L3 人格分析层统一入口（v4接口）

    入参:
        L2_data: L2 输出（整个 dict）
        l3_persona_config: 必须，从 PipelineContext.l3_persona_config 传入
        model_config: 必须，从 PipelineContext.model_config 传入

    出参: {perspectives, summary, quality_overall}

    L2数据结构参考:
    {
        "layer": "L2",
        "code": "600519",
        "market": "CN",
        "run_date": "2026-05-30",
        "moneyflow_data": {"quality": "ok", ...},
        "technical_data": {"quality": "ok", ...},
        "fundamental_data": {"quality": "fail", ...},
        ...
    }
    """
    import datetime

    start = time.time()

    # config 注入：必须从 PipelineContext 传入，不接受 fallback
    global _model_config_cache, _persona_config_cache
    if l3_persona_config is None:
        raise ValueError("run_persona() 必须传入 l3_persona_config 参数（从 PipelineContext.l3_persona_config 获取）")
    if model_config is None:
        raise ValueError("run_persona() 必须传入 model_config 参数（从 PipelineContext.model_config 获取）")
    _model_config_cache = model_config
    _persona_config_cache = l3_persona_config

    # ── 提取L2层关键字段 ──────────────────────────────────────────
    code = L2_data.get("code", "UNKNOWN")
    run_date = L2_data.get("run_date", datetime.date.today().isoformat())

    # 尝试从各子数据中提取name/price
    name = L2_data.get("name", code)
    price = L2_data.get("price", 0.0)
    if price == 0.0:
        price = L2_data.get("technical_data", {}).get("price",
                  L2_data.get("fundamental_data", {}).get("price", 0.0))

    # 内部data字典（供run_persona_analysis使用）
    data = {
        "moneyflow_data": L2_data.get("moneyflow_data", {}),
        "technical_data": L2_data.get("technical_data", L2_data),
        "fundamental_data": L2_data.get("fundamental_data", L2_data),
        "sector_data": L2_data.get("sector_data", {}),
        "event_data": L2_data.get("event_data", {}),
    }

    # ── 计算 quality_overall ──────────────────────────────────────
    quality_overall = _calc_quality_overall(L2_data)

    # ── 执行人格分析 ─────────────────────────────────────────────
    inner_result = run_persona_analysis(code, name, price, data)

    # ── 组装 v4 接口输出 ─────────────────────────────────────────
    duration_ms = round((time.time() - start) * 1000)

    result = {
        "layer": "L3_persona",
        "code": code,
        "run_date": run_date,
        "perspectives": inner_result.get("perspectives", {}),
        "summary": inner_result.get("summary", {}),
        "quality_overall": quality_overall,
        "duration_ms": duration_ms,
    }
    # Pass through inner _status (e.g., "skipped" when no API key)
    if "_status" in inner_result:
        result["_status"] = inner_result["_status"]
    return result


def _calc_quality_overall(L2_data: dict) -> str:
    """
    根据L2各子数据的quality字段计算整体质量等级

    规则:
    - 任一子数据quality为"fail" → "fail"
    - 任一子数据quality为"degraded" → "degraded"
    - 全部为"ok" → "ok"
    - 默认 → "degraded"
    """
    sub_keys = ["moneyflow_data", "technical_data", "fundamental_data",
                "sector_data", "event_data"]
    qualities = []
    for key in sub_keys:
        sub = L2_data.get(key, {})
        if isinstance(sub, dict):
            q = sub.get("quality", "")
            if q:
                qualities.append(q)

    if "fail" in qualities:
        return "fail"
    if "degraded" in qualities:
        return "degraded"
    if all(q == "ok" for q in qualities):
        return "ok"
    return "degraded"
