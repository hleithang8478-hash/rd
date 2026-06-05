# -*- coding: utf-8 -*-
# AUTO-SPLIT from legacy app.py lines 1-404.
# Section: imports, logging, env helpers, AI helpers.
# Loaded by root app.py; keep project-root paths based on root app.py.

import logging
import re
from collections import Counter, defaultdict, deque
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    send_file,
    jsonify,
    flash,
    g,
    has_request_context,
)
import sqlite3
import os
import time
import io
from openpyxl import Workbook
import requests
from datetime import datetime, timedelta, date
import tempfile
import hashlib
import secrets
import html
from functools import wraps
import calendar as cal_lib
import pandas as pd
import json
import threading
from urllib.parse import urlencode
import shutil
import subprocess
import uuid
from html.parser import HTMLParser
from werkzeug.utils import secure_filename
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
    from werkzeug.security import check_password_hash, generate_password_hash
except ImportError:
    ProxyFix = None
    check_password_hash = None
    generate_password_hash = None
from jinja2 import TemplateNotFound
from juyuan_bridge import (
    BRIDGE_PATH_PREFIX,
    configure_juyuan_bridge_database,
    ensure_juyuan_bridge_tables_with_cursor,
    register_juyuan_bridge_routes,
)
try:
    import winreg
except ImportError:
    winreg = None


# 配置日志记录 - 优化为简洁且完整的日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 创建专用日志器，用于不同场景
app_logger = logging.getLogger('app')
query_logger = logging.getLogger('query')  # 查询相关日志（简化输出）
error_logger = logging.getLogger('error')  # 错误日志（详细输出）

# 设置查询日志器为WARNING级别，减少正常查询的日志输出
query_logger.setLevel(logging.WARNING)


def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default, min_value=None, max_value=None):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value

# AI / OpenAI-compatible API 配置（优先环境变量；管理页可在运行时更新）
DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_JSON_MODEL = (os.environ.get("DEEPSEEK_JSON_MODEL") or "deepseek-v4-pro").strip() or "deepseek-v4-pro"
AI_CONNECT_TIMEOUT_SECONDS = 15
AI_CHAT_TIMEOUT_SECONDS = 120
AI_JSON_TIMEOUT_SECONDS = 180
AI_JSON_MAX_ATTEMPTS = 3
AI_JSON_MAX_CONTEXT_TOKENS = 24000
AI_JSON_INPUT_TOKEN_BUDGET = 18000
AI_MAX_OUTPUT_TOKENS = 6000
AI_RETRY_BASE_SECONDS = 2

# 选择 AI 提供者：deepseek / gpt5.5 / openai-compatible。
AI_PROVIDER = (os.environ.get("AI_PROVIDER") or "deepseek").strip().lower()

AI_PROVIDER_OPTIONS = [
    {
        "value": "deepseek",
        "label": "DeepSeek",
        "default_base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-reasoner",
        "default_json_model": DEEPSEEK_JSON_MODEL,
    },
    {
        "value": "gpt5.5",
        "label": "GPT5.5 / OpenAI 兼容网关",
        "default_base_url": "https://ai.zh-zh.top/v1",
        "default_model": "gpt-5.5",
        "default_json_model": "gpt-5.5",
    },
    {
        "value": "openai-compatible",
        "label": "OpenAI 兼容接口",
        "default_base_url": "",
        "default_model": "",
        "default_json_model": "",
    },
]
_AI_PROVIDER_BY_VALUE = {item["value"]: item for item in AI_PROVIDER_OPTIONS}
_AI_PROVIDER_ALIASES = {
    "deepseek-chat": "deepseek",
    "deepseek-reasoner": "deepseek",
    "gpt": "gpt5.5",
    "gpt55": "gpt5.5",
    "gpt-5.5": "gpt5.5",
    "gpt5.5": "gpt5.5",
    "openai": "openai-compatible",
    "openai_compatible": "openai-compatible",
    "openai-compatible": "openai-compatible",
    "custom": "openai-compatible",
}
_DEEPSEEK_MODEL_NAMES = {"deepseek-chat", "deepseek-reasoner", "deepseek-v4-pro"}


class AIProviderHTTPError(Exception):
    def __init__(self, status_code, body, provider_label):
        self.status_code = status_code
        self.body = body or ""
        self.provider_label = provider_label or "AI"
        super().__init__(f"{self.provider_label} HTTP {status_code}: {self.body[:500]}")


def normalize_ai_provider(provider=None):
    raw = (provider or os.environ.get("AI_PROVIDER") or AI_PROVIDER or "deepseek").strip().lower()
    return _AI_PROVIDER_ALIASES.get(raw, raw if raw in _AI_PROVIDER_BY_VALUE else "deepseek")


def _env_clean(name, default=""):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip()


def _first_env(*names):
    for name in names:
        value = _env_clean(name)
        if value:
            return value
    return ""


def _ai_provider_defaults(provider):
    provider = normalize_ai_provider(provider)
    return dict(_AI_PROVIDER_BY_VALUE.get(provider) or _AI_PROVIDER_BY_VALUE["deepseek"])


def _provider_api_key_env_names(provider):
    provider = normalize_ai_provider(provider)
    if provider == "deepseek":
        return ("DEEPSEEK_API_KEY",)
    if provider == "gpt5.5":
        return ("GPT55_API_KEY", "GPT_API_KEY", "OPENAI_API_KEY")
    return ("OPENAI_API_KEY",)


def _provider_base_url_env_names(provider):
    provider = normalize_ai_provider(provider)
    if provider == "deepseek":
        return ("DEEPSEEK_BASE_URL",)
    if provider == "gpt5.5":
        return ("GPT55_BASE_URL", "GPT_BASE_URL", "OPENAI_BASE_URL")
    return ("OPENAI_BASE_URL",)


def _provider_model_env_names(provider, json_mode=False):
    provider = normalize_ai_provider(provider)
    if json_mode:
        if provider == "deepseek":
            return ("DEEPSEEK_JSON_MODEL",)
        if provider == "gpt5.5":
            return ("GPT55_JSON_MODEL", "GPT_JSON_MODEL", "OPENAI_JSON_MODEL")
        return ("OPENAI_JSON_MODEL",)
    if provider == "deepseek":
        return ("DEEPSEEK_MODEL",)
    if provider == "gpt5.5":
        return ("GPT55_MODEL", "GPT_MODEL", "OPENAI_MODEL")
    return ("OPENAI_MODEL",)


def _chat_completions_url(base_url):
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/chat/completions"


def _mask_secret(value):
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 10:
        return value[:2] + "..." + value[-2:]
    return value[:5] + "..." + value[-4:]


def _proxy_file_exists():
    try:
        root = _project_root()
    except Exception:
        root = Path.cwd()
    env_path = os.environ.get("GPT_PROXY_PATH")
    if env_path:
        proxy_path = Path(env_path)
        if not proxy_path.is_absolute():
            proxy_path = root / proxy_path
    else:
        proxy_path = root / "from openai import OpenAI.py"
    return proxy_path.exists()


def get_ai_provider_config(mask_secret=True):
    """Return the active provider config. Runtime os.environ values win."""
    provider = normalize_ai_provider()
    defaults = _ai_provider_defaults(provider)
    api_key = _first_env("AI_API_KEY", "AI_PROVIDER_API_KEY", *_provider_api_key_env_names(provider))
    base_url = _first_env("AI_BASE_URL", "AI_PROVIDER_BASE_URL", *_provider_base_url_env_names(provider))
    if not base_url:
        if provider == "deepseek" and _env_clean("DEEPSEEK_API_URL"):
            base_url = _env_clean("DEEPSEEK_API_URL")
        else:
            base_url = defaults.get("default_base_url", "")
    model = _first_env("AI_MODEL", "AI_PROVIDER_MODEL", *_provider_model_env_names(provider, json_mode=False))
    json_model = _first_env("AI_JSON_MODEL", "AI_PROVIDER_JSON_MODEL", *_provider_model_env_names(provider, json_mode=True))
    model = model or defaults.get("default_model", "")
    json_model = json_model or model or defaults.get("default_json_model", "")
    chat_url = _chat_completions_url(base_url)
    proxy_available = bool(provider == "gpt5.5" and not api_key and _proxy_file_exists())
    cfg = {
        "provider": provider,
        "label": defaults.get("label") or provider,
        "api_key": api_key if not mask_secret else "",
        "api_key_masked": _mask_secret(api_key),
        "api_key_present": bool(api_key),
        "base_url": base_url,
        "chat_url": chat_url,
        "model": model,
        "json_model": json_model,
        "proxy_available": proxy_available,
        "uses_proxy": proxy_available,
    }
    return cfg


def has_ai_api_key():
    cfg = get_ai_provider_config(mask_secret=False)
    return bool(cfg.get("api_key") or cfg.get("proxy_available"))


def _select_ai_model(cfg, explicit_model=None, json_mode=False):
    explicit = (explicit_model or "").strip()
    provider = cfg.get("provider") or "deepseek"
    if explicit and not (provider != "deepseek" and explicit in _DEEPSEEK_MODEL_NAMES):
        return explicit
    return (cfg.get("json_model") if json_mode else cfg.get("model")) or explicit


def _ai_runtime_limits(max_tokens=None, timeout=None, max_attempts=None, max_input_tokens=None):
    """Read AI runtime limits from current os.environ so admin changes apply live."""
    output_tokens = _env_int(
        "AI_MAX_OUTPUT_TOKENS",
        int(max_tokens or AI_MAX_OUTPUT_TOKENS),
        min_value=256,
        max_value=64000,
    )
    context_tokens = _env_int(
        "AI_JSON_MAX_CONTEXT_TOKENS",
        AI_JSON_MAX_CONTEXT_TOKENS,
        min_value=4000,
        max_value=200000,
    )
    default_input_budget = max(1000, context_tokens - output_tokens - 1200)
    input_budget = _env_int(
        "AI_JSON_INPUT_TOKEN_BUDGET",
        int(max_input_tokens or min(AI_JSON_INPUT_TOKEN_BUDGET, default_input_budget)),
        min_value=800,
        max_value=max(1200, context_tokens - 256),
    )
    input_budget = min(input_budget, max(800, context_tokens - min(output_tokens, context_tokens // 2) - 512))
    return {
        "connect_timeout": _env_int("AI_CONNECT_TIMEOUT_SECONDS", AI_CONNECT_TIMEOUT_SECONDS, 1, 120),
        "chat_timeout": _env_int("AI_CHAT_TIMEOUT_SECONDS", int(timeout or AI_CHAT_TIMEOUT_SECONDS), 15, 1200),
        "json_timeout": _env_int("AI_JSON_TIMEOUT_SECONDS", int(timeout or AI_JSON_TIMEOUT_SECONDS), 15, 1200),
        "max_attempts": _env_int("AI_JSON_MAX_ATTEMPTS", int(max_attempts or AI_JSON_MAX_ATTEMPTS), 1, 6),
        "max_context_tokens": context_tokens,
        "input_token_budget": input_budget,
        "max_output_tokens": output_tokens,
        "retry_base_seconds": _env_int("AI_RETRY_BASE_SECONDS", AI_RETRY_BASE_SECONDS, 1, 30),
    }


def _estimate_ai_text_tokens(text):
    """Cheap mixed Chinese/English token estimate for budgeting prompts."""
    s = str(text or "")
    if not s:
        return 0
    cjk = len(re.findall(r"[\u3400-\u9fff]", s))
    ascii_like = len(re.sub(r"[\u3400-\u9fff\s]", "", s))
    spaces = max(1, len(re.findall(r"\s+", s)))
    return max(1, cjk + (ascii_like + spaces) // 4)


def _estimate_ai_messages_tokens(messages):
    total = 0
    for message in messages or []:
        if not isinstance(message, dict):
            total += _estimate_ai_text_tokens(message)
            continue
        total += 4
        total += _estimate_ai_text_tokens(message.get("role") or "")
        content = message.get("content")
        if isinstance(content, str):
            total += _estimate_ai_text_tokens(content)
        else:
            total += _estimate_ai_text_tokens(json.dumps(content, ensure_ascii=False, default=str))
    return total


def _clip_text_middle(text, max_chars):
    s = str(text or "")
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    if max_chars < 80:
        return s[:max_chars]
    head = max(40, int(max_chars * 0.72))
    tail = max(20, max_chars - head - 40)
    return s[:head].rstrip() + "\n...[中间内容因上下文预算被截断]...\n" + s[-tail:].lstrip()


def _compact_ai_messages_for_budget(messages, max_input_tokens):
    copied = [dict(message) if isinstance(message, dict) else {"role": "user", "content": str(message)} for message in (messages or [])]
    before = _estimate_ai_messages_tokens(copied)
    meta = {
        "estimated_input_tokens_before": before,
        "estimated_input_tokens_after": before,
        "input_token_budget": int(max_input_tokens or 0),
        "truncated": False,
    }
    if not max_input_tokens or before <= max_input_tokens:
        return copied, meta

    text_indexes = [
        idx
        for idx, message in enumerate(copied)
        if isinstance(message.get("content"), str) and str(message.get("role") or "").lower() != "system"
    ]
    if not text_indexes:
        text_indexes = [
            idx
            for idx, message in enumerate(copied)
            if isinstance(message.get("content"), str)
        ]
    if not text_indexes:
        return copied, meta

    current = before
    for _round in range(4):
        if current <= max_input_tokens:
            break
        ratio = max(0.12, min(0.92, float(max_input_tokens) / float(max(current, 1)) * 0.92))
        for idx in text_indexes:
            content = str(copied[idx].get("content") or "")
            if len(content) < 800:
                continue
            copied[idx]["content"] = _clip_text_middle(content, max(600, int(len(content) * ratio)))
        current = _estimate_ai_messages_tokens(copied)

    meta["estimated_input_tokens_after"] = current
    meta["truncated"] = current < before
    return copied, meta


def _ai_sleep_for_attempt(attempt, response_status=None):
    base = _env_int("AI_RETRY_BASE_SECONDS", AI_RETRY_BASE_SECONDS, 1, 30)
    if response_status == 429:
        base = max(base, 5)
    time.sleep(min(30, base * (2 ** max(0, attempt))))

import importlib.util
from pathlib import Path

def _project_root() -> Path:
    """Application root; works when this file is exec'd via app.py (__file__ -> app.py)."""
    here = Path(__file__).resolve()
    if here.name == "app.py":
        return here.parent
    return here.parents[2]

def _load_local_proxy_module():
    """Dynamically load the local proxy module file.

    Priority:
    1. If `GPT_PROXY_PATH` env var is set, resolve it (absolute or relative to project root).
    2. Otherwise fall back to project-root file name: "from openai import OpenAI.py".
    """
    root = _project_root()
    env_path = os.environ.get("GPT_PROXY_PATH")
    if env_path:
        proxy_path = Path(env_path)
        if not proxy_path.is_absolute():
            proxy_path = root / proxy_path
    else:
        proxy_path = root / "from openai import OpenAI.py"

    if not proxy_path.exists():
        raise FileNotFoundError(f"Proxy file not found: {proxy_path}")
    spec = importlib.util.spec_from_file_location("local_openai_proxy", str(proxy_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def generate_prompt_for_day(row):
    """
    为某一天的数据生成提示词
    """
    date_str = row["date"].strftime("%Y-%m-%d")

    prompt = f"""
    以下是 {date_str} 的市场分析和工作总结：
    - 整体行情：{row['overall_market']}
    - 事件&政策&热点&异常：{row['events']}
    - 情绪周期：{row['emotion_cycle']}
    - 市场风格：{row['market_style']}
    - 基本面&资金面：{row['fundamentals']}
    - 国际热点：{row['international_hotspots']}
    - 前瞻点&思考总结：{row['insights']}
    - 每日金股：{row['golden_stocks']}

    请根据以上内容：
    1. 发表你的看法，如果提到了行业、个股，尽量按照产业链和事件驱动机会来进行联想。
    2. 分析我的思考总结，指出其中的亮点和不足，重点是你对我思考总结的看法，如果我的观点和看法有逻辑错误，请指出并给出答案。
    3. 提供你的拓展思考（请特别标注“【AI 拓展】”），多联想一些，给我更多的方向，有一些关于财经、股票、政策的知识点，每次生成都给我三个。
    4. 如果我分析了多天的数据，请将多天的数据上下文联系起来，分析多天的变化趋势，或者有无热点延续。
    5. 对于每日金股，指出其中个股的行业，主要合作伙伴，主营业务。
    6. 今天发生的一些你觉得重要的事情，要你自己去搜索思考，而不是从我的原文中去摘录。
    7. 要求所有回答都联网。、
    8. 不需要复述我的原文，直接开始你的回答就可以了，避免我忘记说什么去翻阅原文，你可以稍加提醒。
    """
    # 正常操作不记录详细内容
    # logging.debug(f"Generated prompt for {date_str}")
    return prompt

def call_deepseek_api(prompt):
    """
    调用当前 AI 提供者获取总结和拓展。

    函数名保留为 call_deepseek_api，兼容旧路由。
    """
    cfg = get_ai_provider_config(mask_secret=False)
    provider = cfg["provider"]
    limits = _ai_runtime_limits(max_tokens=5000, timeout=AI_CHAT_TIMEOUT_SECONDS, max_attempts=3)
    messages, budget_meta = _compact_ai_messages_for_budget(
        [{"role": "user", "content": prompt}],
        limits["input_token_budget"],
    )

    # 兼容历史 GPT5.5 本地代理；管理页填写 key/base_url 后会优先走通用 HTTP 调用。
    if cfg.get("uses_proxy"):
        try:
            proxy = _load_local_proxy_module()
            model = _select_ai_model(cfg, getattr(proxy, "MODEL_NAME", None), json_mode=False)
            response = proxy.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=min(5000, limits["max_output_tokens"]),
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"GPT proxy call failed: {e}")
            raise

    if not cfg.get("api_key"):
        raise ValueError(f"未配置 {cfg.get('label') or provider} API Key，请到 AI 提供者设置中填写")
    if not cfg.get("chat_url"):
        raise ValueError(f"未配置 {cfg.get('label') or provider} Base URL")

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": _select_ai_model(cfg, None, json_mode=False) or "deepseek-reasoner",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": min(5000, limits["max_output_tokens"]),
    }
    if provider == "deepseek":
        payload["web_search"] = True
    max_retries = max(1, int(limits["max_attempts"]))
    retries = 0
    
    while retries < max_retries:
        started = time.time()
        try:
            logging.info(
                "[ai_chat] attempt_start attempt=%s model=%s timeout=%s input_tokens~%s%s",
                retries + 1,
                payload["model"],
                limits["chat_timeout"],
                budget_meta.get("estimated_input_tokens_after"),
                " truncated" if budget_meta.get("truncated") else "",
            )
            response = requests.post(
                cfg["chat_url"],
                headers=headers,
                json=payload,
                timeout=(limits["connect_timeout"], limits["chat_timeout"]),
            )
            logging.info(
                "[ai_chat] attempt_response attempt=%s status=%s cost=%.2fs",
                retries + 1,
                response.status_code,
                time.time() - started,
            )
            # 只在错误时记录状态码
            # logging.debug(f"API response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "No response returned.")
                if content and content != "No response returned.":
                    return content
                else:
                    # 重试是正常情况，不记录每次重试
                    # logging.debug("API 返回空内容，重试...")
                    retries += 1
                    _ai_sleep_for_attempt(retries - 1)
                    continue
            else:
                logging.error(f"API 返回错误状态码: {response.status_code}, 响应: {response.text}")
                if response.status_code == 401:
                    raise Exception(f"{cfg.get('label') or provider} API 密钥无效，请检查配置")
                elif response.status_code == 429:
                    logging.warning("API 请求频率过高，等待后重试")
                    retries += 1
                    _ai_sleep_for_attempt(retries - 1, response_status=429)
                    continue
                else:
                    retries += 1
                    _ai_sleep_for_attempt(retries - 1, response_status=response.status_code)
                    continue
                    
        except requests.exceptions.Timeout:
            # 只在最后一次重试失败时记录
            if retries == max_retries - 1:
                logging.warning(f"API 请求超时，已重试 {max_retries} 次")
            # logging.debug(f"API 请求超时，重试第 {retries + 1} 次...")
            retries += 1
            if retries < max_retries:
                _ai_sleep_for_attempt(retries - 1)
                continue
            else:
                raise Exception("API 请求超时，请稍后重试")
                
        except requests.exceptions.RequestException as req_err:
            logging.error(f"请求异常: {req_err}")
            retries += 1
            if retries < max_retries:
                _ai_sleep_for_attempt(retries - 1)
                continue
            else:
                raise Exception(f"API 请求失败: {str(req_err)}")
                
        except ValueError as value_err:
            if "Expecting value" in str(value_err):
                # 只在最后一次重试失败时记录
                if retries == max_retries - 1:
                    logging.warning(f"JSON 解析错误，已重试 {max_retries} 次")
                # logging.debug(f"JSON 解析错误，重试第 {retries + 1} 次...")
                retries += 1
                if retries < max_retries:
                    _ai_sleep_for_attempt(retries - 1)
                    continue
                else:
                    raise Exception("API 响应格式错误，无法解析")
            else:
                raise Exception(f"数据解析错误: {str(value_err)}")
                
        except Exception as e:
            logging.error(f"API 请求失败: {e}")
            if retries < max_retries - 1:
                retries += 1
                _ai_sleep_for_attempt(retries - 1)
                continue
            else:
                raise Exception(f"API 请求失败: {str(e)}")
    
    raise Exception("API 请求失败，已达到最大重试次数")


def _extract_json_object_string(text):
    """从模型输出中取出 JSON 字符串（兼容 ```json 包裹）。"""
    if not text or not str(text).strip():
        raise ValueError("模型返回为空")
    s = str(text).strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    s = s.strip()
    balanced = _extract_balanced_json_blob(s)
    return balanced or s


def _extract_balanced_json_blob(text):
    s = str(text or "").strip()
    if not s:
        return ""
    starts = [idx for idx in (s.find("{"), s.find("[")) if idx >= 0]
    if not starts:
        return ""
    start = min(starts)
    stack = []
    in_string = False
    escape = False
    for idx in range(start, len(s)):
        ch = s[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
            continue
        if ch in "}]":
            if not stack or ch != stack[-1]:
                continue
            stack.pop()
            if not stack:
                return s[start : idx + 1].strip()
    return s[start:].strip()


def _loads_ai_json_blob(content):
    blob = _extract_json_object_string(content)
    candidates = [blob]
    repaired = re.sub(r",\s*([}\]])", r"\1", blob)
    if repaired != blob:
        candidates.append(repaired)
    last_error = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError(f"AI JSON 顶层必须是对象，实际为 {type(parsed).__name__}")
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
    raise last_error or ValueError("AI JSON 解析失败")


def call_deepseek_json_chat(
    messages,
    temperature=0.2,
    max_tokens=2500,
    timeout=90,
    log_prefix=None,
    trace_id=None,
    max_attempts=3,
    retry_on_length=True,
    model=None,
    max_input_tokens=None,
):
    """
    调用当前 AI 提供者，要求返回 JSON 对象（response_format=json_object）。
    返回已解析的 dict。
    """
    cfg = get_ai_provider_config(mask_secret=False)
    provider = cfg["provider"]
    limits = _ai_runtime_limits(
        max_tokens=max_tokens,
        timeout=timeout,
        max_attempts=max_attempts,
        max_input_tokens=max_input_tokens,
    )
    max_tokens = min(int(max_tokens or 2500), limits["max_output_tokens"])
    messages, budget_meta = _compact_ai_messages_for_budget(messages, limits["input_token_budget"])

    # 兼容历史 GPT5.5 本地代理；管理页填写 key/base_url 后会优先走通用 HTTP 调用。
    if cfg.get("uses_proxy"):
        try:
            proxy = _load_local_proxy_module()
            model_name = _select_ai_model(cfg, model or getattr(proxy, "MODEL_NAME", None), json_mode=True)
            response = proxy.client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            parsed = _loads_ai_json_blob(content)
            return parsed
        except Exception as e:
            logging.error(f"GPT proxy JSON chat failed: {e}")
            raise

    if not cfg.get("api_key"):
        raise ValueError(f"未配置 {cfg.get('label') or provider} API Key，请到 AI 提供者设置中填写")
    if not cfg.get("chat_url"):
        raise ValueError(f"未配置 {cfg.get('label') or provider} Base URL")

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _select_ai_model(cfg, model, json_mode=True) or DEEPSEEK_JSON_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    last_err = None
    max_attempts = max(1, int(limits["max_attempts"]))
    last_finish_reason = ''
    for attempt in range(max_attempts):
        attempt_started = time.time()
        if log_prefix:
            logging.info(
                '[%s] api_attempt_start trace=%s attempt=%s model=%s timeout=%s input_tokens~%s output_tokens=%s%s',
                log_prefix,
                trace_id or '-',
                attempt + 1,
                payload["model"],
                limits["json_timeout"],
                budget_meta.get("estimated_input_tokens_after"),
                payload.get("max_tokens"),
                " truncated" if budget_meta.get("truncated") else "",
            )
        try:
            response = requests.post(
                cfg["chat_url"],
                headers=headers,
                json=payload,
                timeout=(limits["connect_timeout"], limits["json_timeout"]),
            )
            if log_prefix:
                logging.info(
                    '[%s] api_attempt_response trace=%s attempt=%s status=%s cost=%.2fs',
                    log_prefix,
                    trace_id or '-',
                    attempt + 1,
                    response.status_code,
                    time.time() - attempt_started,
                )
            if response.status_code == 200:
                result = response.json()
                choice = (result.get("choices") or [{}])[0]
                finish_reason = choice.get("finish_reason") or ""
                last_finish_reason = finish_reason
                message = choice.get("message") or {}
                content = message.get("content", "")
                reasoning_content = message.get("reasoning_content", "")
                if log_prefix:
                    logging.info(
                        '[%s] api_attempt_body trace=%s attempt=%s finish=%s content_chars=%s reasoning_chars=%s',
                        log_prefix,
                        trace_id or '-',
                        attempt + 1,
                        finish_reason,
                        len(content or ''),
                        len(reasoning_content or ''),
                    )
                if not content or not str(content).strip():
                    last_err = (
                        f"模型返回为空 finish_reason={finish_reason or '-'} "
                        f"reasoning_chars={len(reasoning_content or '')}"
                    )
                    if log_prefix:
                        logging.warning(
                            '[%s] api_attempt_empty trace=%s attempt=%s finish=%s reasoning_chars=%s response_chars=%s',
                            log_prefix,
                            trace_id or '-',
                            attempt + 1,
                            finish_reason,
                            len(reasoning_content or ''),
                            len(response.text or ''),
                        )
                    if attempt < max_attempts - 1:
                        time.sleep(2 ** attempt)
                        continue
                    raise ValueError(last_err)
                parsed = _loads_ai_json_blob(content)
                if log_prefix:
                    logging.info(
                        '[%s] api_attempt_ok trace=%s attempt=%s content_chars=%s input_tokens~%s',
                        log_prefix,
                        trace_id or '-',
                        attempt + 1,
                        len(content or ''),
                        budget_meta.get("estimated_input_tokens_after"),
                    )
                return parsed
            if response.status_code == 401:
                last_err = f"{cfg.get('label') or provider} API 密钥无效，请检查 AI 提供者设置"
                break
            if response.status_code in (400, 413) and not budget_meta.get("truncated") and attempt < max_attempts - 1:
                tighter_budget = max(800, int(limits["input_token_budget"] * 0.7))
                messages, budget_meta = _compact_ai_messages_for_budget(messages, tighter_budget)
                payload["messages"] = messages
                last_err = f"HTTP {response.status_code}: 已收紧上下文预算后重试"
                continue
            last_err = f"HTTP {response.status_code}: {response.text[:500]}"
        except (json.JSONDecodeError, ValueError) as e:
            last_err = f"JSON 解析失败: {e}"
            if last_finish_reason == 'length':
                last_err = f"模型输出被截断，JSON 未闭合: {e}"
                if not retry_on_length:
                    break
                if payload["max_tokens"] < limits["max_output_tokens"]:
                    payload["max_tokens"] = min(limits["max_output_tokens"], max(payload["max_tokens"] + 800, int(payload["max_tokens"] * 1.25)))
                elif not budget_meta.get("truncated"):
                    tighter_budget = max(800, int(limits["input_token_budget"] * 0.75))
                    messages, budget_meta = _compact_ai_messages_for_budget(messages, tighter_budget)
                    payload["messages"] = messages
        except requests.exceptions.Timeout:
            last_err = f"请求超时（connect={limits['connect_timeout']}s, read={limits['json_timeout']}s）"
        except requests.exceptions.RequestException as e:
            last_err = str(e)
        if log_prefix:
            logging.warning(
                '[%s] api_attempt_fail trace=%s attempt=%s cost=%.2fs error=%s',
                log_prefix,
                trace_id or '-',
                attempt + 1,
                time.time() - attempt_started,
                last_err,
            )
        if attempt < max_attempts - 1:
            _ai_sleep_for_attempt(attempt)
    raise ValueError(last_err or f"{cfg.get('label') or provider} 调用失败")


_INVESTMENT_PLAN_AI_SYSTEM = """你是投研笔记结构化助手。用户会给出一段自然语言投研笔记。
你必须只输出一个 JSON 对象（不要 markdown、不要解释）。用户消息里会包含「今天是 YYYY-MM-DD（公历）」，用于换算相对日期。

你的目标不是把笔记分类成事件型/基本面型，而是把一次真实投资计划拆成：
为什么投、依据是什么、关键锚在哪里、胜率如何、仓位如何、依据失效怎么办。

【必须先识别的三项】
1) instruments (string): 投资标的（股票/ETF/指数/可转债/期货主力等）。中文简称、全名、代码（如 宁德时代、300750）。多项英文逗号分隔。也可用 investment_targets 字段名（与 instruments 二选一，内容相同）。无则 ""。
2) tracking_items (array): 跟踪事项。每条为 {"title":"简短标题","date":"YYYY-MM-DD 或 null","detail":"需关注的变化、催化剂、风险、验证点、仓位动作等"}。凡原文提到的关键事件、数据发布、政策窗口、财报、估值观察、反证条件、加减仓触发条件，尽量拆成多条；有明确日期则填 date，否则 null。至少一条时 title 不可为空。无任何可拆事项则 []。
3) target_date (string 或 null): 本计划层面的目标/复盘/观察截止日 YYYY-MM-DD（与单条 tracking_items 可并存）。相对日期结合「今天是…」换算；2026Q1末等季度末按：Q1→03-31，Q2→06-30，Q3→09-30，Q4→12-31；H1末→06-30；H2末→12-31。

【计划描述 description 必须采用下面结构，缺信息也要保留标题并写“待补充”】
一、投资锚
- 我为什么要投：
- 核心锚：
- 锚的验证指标：

二、依据链条
- 主要依据：
- 关键数据/事实：
- 需要继续确认：

三、情景、概率与仓位
- 乐观情景：概率__%，计划仓位__%，触发条件：
- 基准情景：概率__%，计划仓位__%，触发条件：
- 悲观/证伪情景：概率__%，计划仓位__%，触发条件：
- 底仓：
- 博弈仓/加仓：

四、失效与退出
- 依据不生效的信号：
- 减仓/止损条件：
- 复盘日期：

【其余字段】
- title (string, 必填): 计划标题，点出核心标的或主题。
- description (string): 按上面的四段结构输出；不要写空泛口号。
- status (string): todo、in_progress、done、cancelled；未提及则 todo
- priority (string): low、medium、high；默认 medium
- category (string): 如 股票投资；无则 "投资计划"
- tags (string): 英文逗号分隔；应包含投资锚/行业/催化词；无则 ""
- keywords (string): 资讯爬虫用补充词（题材、行业关键词等）；系统会把 instruments 与 keywords 合并去重，缺省可 ""。
- progress (number): 0-100；未提及则 0
- color (string 或 null): #RRGGBB；无法判断则 null
- is_profitable (number 或 null): 仅已了结且明确盈/亏时为 1 或 0

除 target_date、color、is_profitable、tracking_items 内外层 date 外，字符串缺省用 ""；tracking_items 无事项时用 []。"""


_THOR_GATEWAY_AI_SYSTEM = """你是投研工作台「雷神之锤」路由助手。用户输入一句随手笔记，你只输出一个 JSON 对象（不要 markdown、不要解释）。

【分类 data_type（必填，小写字符串）】互斥三选一：
- plan：可执行的投资/交易动作或结构化研究计划（建仓、减仓、止损止盈、观察标的、调研待办、策略步骤等）。
- essay：主观感受、盘感流水、情绪与心态、碎片观察、无明确执行项的随笔（偏日记/盘面感觉）。
- event：落在具体日期的客观事项（财报、会议、宏观数据发布、提醒、DDL、电话会等）。

【锚点日期】用户消息中会给出「锚点日期 YYYY-MM-DD」，用于解析「明天」「下周五」及默认落档日期；未写明日期时 essay/event 优先用锚点日期。

【各类型字段】只填与本类型相关的键，其它类型可省略：
- plan：title (string 必填), description (string), target_date (YYYY-MM-DD 或 null), instruments (string), keywords (string), tracking_items (array，元素 {"title","date","detail"}，date 为 YYYY-MM-DD 或 null；无则 []), priority (low|medium|high), status (todo|in_progress|done|cancelled), category (string), tags (string), color (#RRGGBB 或 null), progress (0-100 或省略)。
  description 要尽量写成真实投资计划，不要只复述原文；至少覆盖：投资锚、依据链条、情景概率与仓位、依据失效/退出条件。tracking_items 优先拆出验证指标、关键催化、减仓/止损触发、复盘日期。
- essay：content (string 必填，尽量保留用户原话，可轻微整理标点), date (YYYY-MM-DD 或 null)。
- event：title (string 必填), date (YYYY-MM-DD 必填), content (string 备注，可 ""), event_category (macro|earnings|meeting|personal_trade|other，无法判断用 other)。

【歧义】若极度模糊，优先 essay，将用户原文写入 content。

除日期、枚举、数字外，字符串缺省用 ""。\n"""
