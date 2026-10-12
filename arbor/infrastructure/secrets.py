"""
Shared credential loading — infrastructure concern.

Used by agent adapters and report LLM commentary alike,
so reports does not import agent (keeps adapter layers peer-independent).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ENV_FILE = Path.home() / ".arbor" / ".env"


def load_llm_api_key(env_file: Optional[Path] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Read LLM API key: process env first, ~/.arbor/.env as fallback.

    Returns:
        (api_key, provider) where provider ∈ {"deepseek", "openai"};
        (None, None) if neither key is available.
    """
    path = env_file if env_file is not None else ENV_FILE
    deepseek = os.getenv("DEEPSEEK_API_KEY", "")
    openai = os.getenv("OPENAI_API_KEY", "")
    if (not deepseek and not openai) and path.exists():
        try:
            from dotenv import dotenv_values

            vals = dotenv_values(path)
            deepseek = deepseek or vals.get("DEEPSEEK_API_KEY", "") or ""
            openai = openai or vals.get("OPENAI_API_KEY", "") or ""
        except Exception as e:
            logger.warning("读取 %s 失败: %s", path, e)
    if deepseek:
        return deepseek, "deepseek"
    if openai:
        return openai, "openai"
    return None, None
