#!/usr/bin/env python3
"""
scripts/subscribers.py
邮件订阅者最小表 CLI — ~/.arbor/subscribers.json（用户数据，不进 git）

数据格式:
  {"subscribers": [{"email": "...", "since": "YYYY-MM-DD", "active": true}]}

用法:
  python scripts/subscribers.py add user@example.com
  python scripts/subscribers.py remove user@example.com
  python scripts/subscribers.py list
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".arbor" / "subscribers.json"


def _data_path(path=None) -> Path:
    """数据文件路径（path=None 时用 _DEFAULT_PATH，便于测试 monkeypatch）。"""
    return Path(path) if path else _DEFAULT_PATH


def _load(path: Path) -> dict:
    """读取订阅文件；不存在/损坏 → 空表。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("subscribers"), list):
            return data
        logger.warning("subscribers: %s 结构异常，按空表处理", path)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("subscribers: 读取 %s 失败: %s", path, e)
    return {"subscribers": []}


def _save(path: Path, data: dict) -> None:
    """原子写（tmp + replace，沿用 learning.py 模式）；失败仅告警不抛出。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning("subscribers: 写入 %s 失败: %s", path, e)


def load_active_emails(path=None) -> list[str]:
    """active 订阅者邮箱列表（供 daemon 复用；文件不存在/损坏 → []）。"""
    return [s["email"] for s in _load(_data_path(path))["subscribers"]
            if s.get("active") and s.get("email")]


def add(email: str, path=None) -> str:
    """订阅（幂等: 已存在则恢复 active 并保留原订阅日期）。"""
    p = _data_path(path)
    data = _load(p)
    for s in data["subscribers"]:
        if s.get("email") == email:
            if s.get("active"):
                return f"已在订阅中: {email}"
            s["active"] = True
            _save(p, data)
            return f"已恢复订阅: {email}"
    data["subscribers"].append({
        "email": email,
        "since": date.today().isoformat(),
        "active": True,
    })
    _save(p, data)
    return f"已订阅: {email}"


def remove(email: str, path=None) -> str:
    """退订（置 active=false，不删记录）。"""
    p = _data_path(path)
    data = _load(p)
    for s in data["subscribers"]:
        if s.get("email") == email:
            if not s.get("active"):
                return f"未在订阅中: {email}"
            s["active"] = False
            _save(p, data)
            return f"已退订: {email}"
    return f"未在订阅中: {email}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Arbor 邮件订阅者管理")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="订阅（幂等）")
    p_add.add_argument("email")
    p_rm = sub.add_parser("remove", help="退订（保留记录）")
    p_rm.add_argument("email")
    sub.add_parser("list", help="列出 active 订阅者")
    args = parser.parse_args(argv)

    if args.cmd == "add":
        print(add(args.email))
    elif args.cmd == "remove":
        print(remove(args.email))
    else:
        emails = load_active_emails()
        if not emails:
            print("暂无订阅者")
        else:
            print(f"active 订阅者 ({len(emails)}):")
            for e in emails:
                print(f"  {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
