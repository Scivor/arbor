"""采购顾问和周报点评共用的 DeepSeek 接入点。

有 DEEPSEEK_API_KEY 时走 https://api.deepseek.com 的 deepseek-chat。
只有 OPENAI_API_KEY 时才改走 OpenAI。钥匙本身不离开这个模块的返回值给网页。
"""

from __future__ import annotations

import os
from typing import Optional

from arbor.infrastructure import secrets

_DEEPSEEK_BASE = "https://api.deepseek.com"
_DEEPSEEK_MODEL = "deepseek-chat"
_OPENAI_MODEL = "gpt-4o-mini"


def resolve_llm(model: Optional[str] = None, env_file=None) -> dict:
    """返回 api_key、provider、model、base_url。没有钥匙时 api_key 为 None。"""
    if env_file is None:
        api_key, provider = secrets.load_llm_api_key()
    else:
        api_key, provider = secrets.load_llm_api_key(env_file=env_file)
    chosen = (model or os.getenv("AGENT_MODEL") or "").strip()
    if not chosen:
        chosen = _OPENAI_MODEL if provider == "openai" else _DEEPSEEK_MODEL
    override = (os.getenv("AGENT_BASE_URL") or "").strip()
    if override:
        base_url = override
    elif provider == "deepseek":
        base_url = _DEEPSEEK_BASE
    else:
        base_url = None
    return {
        "api_key": api_key,
        "provider": provider,
        "model": chosen if api_key else None,
        "base_url": base_url if api_key else None,
    }


def agent_status(env_file=None) -> dict:
    """给网页和 /api/agent 的公开状态。不含钥匙。"""
    endpoint = resolve_llm(env_file=env_file)
    return {
        "configured": bool(endpoint["api_key"]),
        "provider": endpoint["provider"],
        "model": endpoint["model"],
    }
