"""
core/notify/ops_alert.py
运维告警 — 周报生成失败/降级时通过 Telegram 通知运营者

配置（任选一）:
  1. 环境变量 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
  2. ~/.arbor/.env 文件中的同名变量（launchd 常驻进程无 shell 环境，推荐）

未配置时静默跳过（返回 False），不影响主流程。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_FILE = Path.home() / ".arbor" / ".env"


def _load_credentials() -> tuple[str, str]:
    """读取 Telegram 凭据：环境变量优先，~/.arbor/.env 兜底。"""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if (not token or not chat_id) and _ENV_FILE.exists():
        try:
            from dotenv import dotenv_values
            vals = dotenv_values(_ENV_FILE)
            token = token or vals.get("TELEGRAM_BOT_TOKEN", "")
            chat_id = chat_id or vals.get("TELEGRAM_CHAT_ID", "")
        except Exception as e:
            logger.warning(f"ops_alert: 读取 {_ENV_FILE} 失败: {e}")
    return token, chat_id


def send_ops_alert(text: str) -> bool:
    """
    发送运维告警。未配置或网络失败时返回 False，绝不抛异常。

    Args:
        text: 消息正文（支持 Telegram HTML parse_mode）
    """
    token, chat_id = _load_credentials()
    if not token or not chat_id:
        logger.debug("ops_alert: 未配置 TELEGRAM_BOT_TOKEN/CHAT_ID，跳过")
        return False

    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if r.status_code != 200:
            logger.warning(f"ops_alert: Telegram 返回 {r.status_code}: {r.text[:200]}")
            return False
        logger.info("ops_alert: 告警已发送")
        return True
    except Exception as e:
        logger.warning(f"ops_alert: 发送失败: {e}")
        return False
