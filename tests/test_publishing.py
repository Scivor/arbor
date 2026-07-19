"""
tests/test_publishing.py
周报发布半自动化 — 无网络（tmp_path 隔离订阅表与 env）
"""

import json

import pytest

import scripts.subscribers as subs
from scripts.scheduler import _build_publish_notice
from scripts.weekly_report_daemon import _resolve_recipients
from reports.demo_data import demo_report


@pytest.fixture
def subs_path(tmp_path, monkeypatch):
    """隔离的订阅者数据文件"""
    path = tmp_path / "subscribers.json"
    monkeypatch.setattr(subs, "_DEFAULT_PATH", path)
    return path


# ── subscribers CLI ───────────────────────────────────────────────────────────

def test_add_list_remove_roundtrip(subs_path):
    assert "已订阅" in subs.add("a@x.com")
    assert "已订阅" in subs.add("b@x.com")
    assert subs.load_active_emails() == ["a@x.com", "b@x.com"]

    assert "已退订" in subs.remove("a@x.com")
    assert subs.load_active_emails() == ["b@x.com"]

    # 记录保留（active=false 不删除）
    data = json.loads(subs_path.read_text(encoding="utf-8"))
    assert len(data["subscribers"]) == 2


def test_add_idempotent_restores(subs_path):
    subs.add("a@x.com")
    subs.remove("a@x.com")
    assert "已恢复订阅" in subs.add("a@x.com")   # 幂等恢复
    assert subs.load_active_emails() == ["a@x.com"]
    # 重复 add active 记录 → 提示已在订阅中，不重复写
    assert "已在订阅中" in subs.add("a@x.com")
    data = json.loads(subs_path.read_text(encoding="utf-8"))
    assert len(data["subscribers"]) == 1


def test_remove_unknown_and_corrupted_file(subs_path):
    assert "未在订阅中" in subs.remove("ghost@x.com")
    # 坏文件 → 空表
    subs_path.write_text("not-json{{{", encoding="utf-8")
    assert subs.load_active_emails() == []
    # 结构异常（非 subscribers 列表）→ 空表
    subs_path.write_text(json.dumps({"other": 1}), encoding="utf-8")
    assert subs.load_active_emails() == []


def test_cli_main(subs_path, capsys):
    subs.main(["add", "cli@x.com"])
    subs.main(["list"])
    out = capsys.readouterr().out
    assert "已订阅: cli@x.com" in out
    assert "cli@x.com" in out


# ── daemon 收件人解析 ─────────────────────────────────────────────────────────

def test_resolve_recipients_from_subscribers(subs_path, monkeypatch):
    subs.add("a@x.com")
    subs.add("b@x.com")
    monkeypatch.setenv("COFFEE_SMTP_TO", "env@x.com")
    # 订阅表非空 → 优先订阅表
    assert _resolve_recipients() == ["a@x.com", "b@x.com"]


def test_resolve_recipients_env_fallback(subs_path, monkeypatch):
    # 订阅表不存在 → 回退 env（逗号分隔，去空白）
    monkeypatch.setenv("COFFEE_SMTP_TO", " e1@x.com , e2@x.com ")
    assert _resolve_recipients() == ["e1@x.com", "e2@x.com"]


def test_resolve_recipients_none(subs_path, monkeypatch):
    monkeypatch.delenv("COFFEE_SMTP_TO", raising=False)
    assert _resolve_recipients() == []


# ── 发布提醒文本 ──────────────────────────────────────────────────────────────

def test_publish_notice_content():
    report = demo_report()
    report.llm_commentary = "【核心判断】横盘，概率 55%\n第二行不应出现"
    text = _build_publish_notice(report, "/tmp/reports/2026-07-17", "2026-07-17")
    assert "Arbor 周报已生成 2026-07-17" in text
    assert "65%" in text                       # 套保比率
    assert "/tmp/reports/2026-07-17/report.md" in text
    assert "【核心判断】横盘，概率 55%" in text  # 首句
    assert "第二行不应出现" not in text          # 只取首行
    assert "🔴" not in text and "🟡" not in text  # 常态通知无告警图标


def test_publish_notice_no_commentary():
    report = demo_report()
    assert report.llm_commentary is None
    text = _build_publish_notice(report, "/tmp/r", "2026-07-17")
    assert "AI 点评: 无" in text
