"""
web/app.py
Arbor Report, Minimal Static Site (FastAPI)

Routes:
  /                → Latest report (full HTML, no nav bar, past index at bottom)
  /reports/        → Archive list (with nav bar)
  /reports/{date}/ → Single report (full HTML, no nav bar, past index at bottom)
  /reports/{date}.pdf → PDF download
  /api/health      → Health check

Design principle:
  Report pages serve the original generated HTML directly, preserving
  all Kami CSS tokens. A past-index strip is injected before </body>.
  Only the archive page uses a Jinja2 template with navigation.

Deployment:
  uvicorn web.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from reports.fonts import css_display_stack, css_serif_stack
from web.chat import build_chat_page
from web.quiet_market import quiet_quotes
from web.track_record import build_track_record_html

# ── Paths ────────────────────────────────────────────────────────────────────
WEB_DIR = Path(__file__).resolve().parent
REPORTS_DIR = WEB_DIR / "static" / "reports"
TEMPLATES_DIR = WEB_DIR / "templates"

app = FastAPI(title="Scivor Arbor", version="3.0")

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _list_report_dates() -> List[str]:
    """Return all report dates (YYYY-MM-DD) sorted desc."""
    if not REPORTS_DIR.exists():
        return []
    dates = []
    for entry in REPORTS_DIR.iterdir():
        if entry.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", entry.name):
            dates.append(entry.name)
    return sorted(dates, reverse=True)


def _latest_report_date() -> Optional[str]:
    dates = _list_report_dates()
    return dates[0] if dates else None


def _report_exists(report_date: str) -> bool:
    return (REPORTS_DIR / report_date / "report.html").exists()


def _report_pdf_exists(report_date: str) -> bool:
    return (REPORTS_DIR / report_date / "report.pdf").exists()


def _read_report_meta(report_date: str) -> dict:
    """Extract key metadata from report HTML for preview cards."""
    meta = {
        "date": report_date,
        "price": "—",
        "change": "—",
        "signal": "—",
        "hedge": "—",
        "has_pdf": _report_pdf_exists(report_date),
    }
    html_path = REPORTS_DIR / report_date / "report.html"
    if not html_path.exists():
        return meta

    try:
        text = html_path.read_text(encoding="utf-8")
        m = re.search(r'class="hero-price-val">([\d.]+)</div>', text)
        if m:
            meta["price"] = m.group(1)
        m = re.search(r'class="hero-price-chg"[^>]*>([\+\-]?[\d.]+%)</div>', text)
        if m:
            meta["change"] = m.group(1)
        m = re.search(r'ML\s+(?:模型预测|Model Prediction).*?(BULLISH|BEARISH|NEUTRAL)', text, re.S)
        if m:
            meta["signal"] = m.group(1)
        m = re.search(r'class="hedge-signal">([^<]+)</div>', text)
        if m:
            meta["hedge"] = m.group(1).strip()
    except Exception:
        pass
    return meta


def _build_past_index_html(report_date: str, recent_meta: List[dict], lang: str = "zh") -> str:
    """Build the past-index HTML snippet to inject into report pages."""
    serif = css_serif_stack()
    display = css_display_stack()
    items_html = ""
    for r in recent_meta:
        current_cls = "past-item-current" if r["date"] == report_date else ""
        pdf_link = f'<a class="past-item-pdf" href="/reports/{r["date"]}.pdf" download>PDF</a>' if r["has_pdf"] else ""
        prefix = "/en" if lang == "en" else ""
        items_html += f"""
      <a href="{prefix}/reports/{r["date"]}/" class="past-item {current_cls}">
        <div class="past-item-date">{r["date"]}</div>
        <div class="past-item-sig">{r["signal"]}</div>
        <div class="past-item-price">{r["price"]} ¢/lb</div>
        {pdf_link}
      </a>"""

    title = "Past Issues" if lang == "en" else "往期索引"
    all_link = "View All →" if lang == "en" else "查看全部 →"
    archive_url = "/en/reports/" if lang == "en" else "/reports/"

    return f"""<div class="past-index-wrap">
  <div class="past-index-hdr">
    <span class="past-index-title">{title}</span>
    <a class="past-index-all" href="{archive_url}">{all_link}</a>
  </div>
  <div class="past-index-strip">{items_html}
  </div>
</div>
<style>
.past-index-wrap {{
  max-width: 210mm;
  margin: 0 auto;
  padding: 28px 14mm 40px;
  border-top: 1px solid #e5e3d8;
  background: #f5f4ed;
}}
.past-index-hdr {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 16px;
}}
.past-index-title {{
  font-family: {display};
  font-size: 15px;
  font-weight: 600;
  color: #141413;
  letter-spacing: 0.02em;
}}
.past-index-all {{
  font-size: 12px;
  color: #504e49;
  text-decoration: none;
  transition: color 0.15s;
}}
.past-index-all:hover {{ color: #1B365D; }}
.past-index-strip {{
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
}}
.past-item {{
  flex: 0 0 auto;
  min-width: 130px;
  background: #faf9f5;
  border: 1px solid #e8e6dc;
  border-radius: 6px;
  padding: 12px 14px;
  text-decoration: none;
  color: inherit;
  transition: box-shadow 0.15s, border-color 0.15s;
  display: block;
}}
.past-item:hover {{
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
  border-color: #e5e3d8;
}}
.past-item-current {{
  outline: 1.5px solid #1B365D;
  outline-offset: -1.5px;
}}
.past-item-date {{
  font-family: {serif};
  font-size: 13px;
  font-weight: 600;
  color: #141413;
  margin-bottom: 4px;
}}
.past-item-sig {{
  font-size: 11px;
  font-weight: 500;
  color: #1B365D;
  margin-bottom: 2px;
}}
.past-item-price {{
  font-size: 11px;
  color: #504e49;
  margin-bottom: 4px;
}}
.past-item-pdf {{
  font-size: 10px;
  color: #6b6a64;
  text-decoration: none;
  border-top: 1px solid #e8e6dc;
  display: block;
  padding-top: 4px;
  margin-top: 4px;
}}
.past-item-pdf:hover {{ color: #1B365D; }}
@media (max-width: 768px) {{
  .past-index-wrap {{ padding: 20px 16px 32px; }}
}}
</style>"""


def _serve_report_page(report_date: str, is_latest: bool = False, lang: str = "zh") -> HTMLResponse:
    """Serve a report page: original HTML + injected past-index. No nav bar."""
    html_path = REPORTS_DIR / report_date / f"report_{lang}.html"
    # Fallback to zh if en not available
    if not html_path.exists():
        html_path = REPORTS_DIR / report_date / "report.html"
    html_content = html_path.read_text(encoding="utf-8")

    # Inject "latest" badge
    if is_latest:
        badge_text = "Latest" if lang == "en" else "最新"
        html_content = html_content.replace(
            '<div class="hero-eyebrow">',
            f'<div style="float:right;font-size:11px;font-weight:500;color:#1B365D;background:#E4ECF5;padding:2px 8px;border-radius:4px;letter-spacing:0.3px;">{badge_text}</div><div class="hero-eyebrow">'
        )

    # Build and inject past-index before </body>
    recent = _list_report_dates()[:10]
    recent_meta = [_read_report_meta(d) for d in recent]
    past_index_html = _build_past_index_html(report_date, recent_meta, lang=lang)

    # 首页入口: 指向预测战绩页 / 采购顾问追问页
    if is_latest:
        chat_text = "Next procurement steps →" if lang == "en" else "采购下一步建议 →"
        past_index_html = past_index_html.replace(
            '<a class="past-index-all"',
            f'<a class="past-index-all" style="margin-right:14px;" href="/chat/">{chat_text}</a><a class="past-index-all"',
            1,
        )
        tr_text = "Track Record →" if lang == "en" else "预测战绩 →"
        past_index_html = past_index_html.replace(
            '<a class="past-index-all"',
            f'<a class="past-index-all" style="margin-right:14px;" href="/track-record/">{tr_text}</a><a class="past-index-all"',
            1,
        )

    # Find </body> and insert before it
    body_end = html_content.rfind("</body>")
    if body_end != -1:
        html_content = html_content[:body_end] + past_index_html + "\n" + html_content[body_end:]
    else:
        html_content += past_index_html

    return HTMLResponse(content=html_content)


# ── Error pages ──────────────────────────────────────────────────────────────

ERROR_MESSAGES = {
    400: ("请求有误", "请检查 URL 或参数是否正确。"),
    403: ("无权访问", "您没有权限访问此页面。"),
    404: ("页面未找到", "该报告或页面不存在，可能已被删除或尚未生成。"),
    422: ("参数校验失败", "提交的数据格式不正确，请检查后重试。"),
    500: ("服务器内部错误", "抱歉，服务器遇到了问题。请稍后再试。"),
    502: ("网关错误", "上游服务暂时不可用，请稍后再试。"),
    503: ("服务不可用", "系统正在维护中，请稍后再试。"),
}


# Starlette 对未匹配路由给出的英文原因，不要盖掉中文说明。
_STOCK_HTTP_DETAILS = {
    "Bad Request",
    "Forbidden",
    "Not Found",
    "Unprocessable Entity",
    "Internal Server Error",
    "Bad Gateway",
    "Service Unavailable",
}


def _error_response(status_code: int, detail: str | None = None, lang: str = "zh") -> HTMLResponse:
    title, desc = ERROR_MESSAGES.get(status_code, ("出错了", "发生未知错误。"))
    if detail and detail not in (str(status_code), "") and detail not in _STOCK_HTTP_DETAILS:
        desc = detail
    # Build minimal request-like object for template context
    class _DummyReq:
        url = type("URL", (), {"path": "/", "query_params": {}})()
        query_params = {}
    html = templates.TemplateResponse(_DummyReq(), "error.html", {
        "status_code": status_code,
        "title": title,
        "description": desc,
        "lang": lang,
    }).body.decode("utf-8")
    return HTMLResponse(content=html, status_code=status_code)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return _error_response(exc.status_code, exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _error_response(422, "请求参数校验失败，请检查输入格式。")


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/workbench/", response_class=HTMLResponse)
async def procurement_workbench(request: Request):
    """Explicit synthetic demo; never reads or mutates a trading account."""
    return templates.TemplateResponse(request, "workbench.html", {})


@app.get("/", response_class=HTMLResponse)
async def latest_report(request: Request):
    """Root path shows the latest report directly — no nav bar."""
    lang = request.query_params.get("lang", "zh")
    latest = _latest_report_date()
    if not latest:
        try:
            quotes = await asyncio.to_thread(quiet_quotes)
        except Exception:
            quotes = {"coffee": None, "fx": None}
        return templates.TemplateResponse(request, "empty.html", {
            "lang": lang,
            "coffee": (quotes or {}).get("coffee"),
            "fx": (quotes or {}).get("fx"),
            "yuan": (quotes or {}).get("yuan"),
            "landed": (quotes or {}).get("landed"),
        })
    return _serve_report_page(latest, is_latest=True, lang=lang)


@app.get("/track-record/", response_class=HTMLResponse)
async def track_record():
    """预测战绩页 — 历史周报相邻期配对复盘聚合 + 驱动因子应验率 + 自校准状态，纯本地数据。"""
    from reports.history import compute_track_record, compute_driver_stats
    # 主数据与可选数据各自独立兜底：可选数据失败不拖垮整页
    try:
        record = compute_track_record()
    except Exception:
        record = {"total": 0, "hit_rate": 0.0, "direction_rate": 0.0,
                  "hedge_rate": 0.0, "weeks": [], "pending": None}
    try:
        driver_stats = compute_driver_stats()
    except Exception:
        driver_stats = []
    try:
        from reports.learning import learning_status
        learning = learning_status()
    except Exception:
        learning = None
    return HTMLResponse(content=build_track_record_html(record, driver_stats, learning))


# ── 采购顾问追问 ─────────────────────────────────────────────────────────────

_analyst = None  # 进程级 CoffeeAnalyst 单例（lazy 首次构造）


def _get_analyst():
    """lazy 构造采购顾问单例；无 API key 时 RuntimeError 向上抛。"""
    global _analyst
    if _analyst is None:
        from agent.agents.analyst import CoffeeAnalyst
        _analyst = CoffeeAnalyst()
    return _analyst


_CHAT_RATE: dict[str, list[float]] = {}
_CHAT_RATE_LIMIT = 10  # 每 IP 每分钟最多 10 次（防公开部署被刷 token）


def _chat_rate_ok(ip: str) -> bool:
    """内存简易限流: 滑动窗口 60s 内不超过 _CHAT_RATE_LIMIT 次。"""
    now = time.time()
    hits = [t for t in _CHAT_RATE.get(ip, []) if now - t < 60]
    if len(hits) >= _CHAT_RATE_LIMIT:
        _CHAT_RATE[ip] = hits
        return False
    hits.append(now)
    _CHAT_RATE[ip] = hits
    return True


def _extract_procurement_briefing(report_date: str) -> Optional[str]:
    """读本期采购简报：优先 briefing.json，回退 HTML 抽取。"""
    from reports.procurement_briefing import load_briefing_from_dir

    return load_briefing_from_dir(REPORTS_DIR / report_date)


# 进程内多轮会话（session_id → [("human"|"ai", text), ...]）；最多保留 10 轮；1h 过期
_CHAT_SESSIONS: dict[str, list] = {}
_CHAT_SESSION_TS: dict[str, float] = {}
_CHAT_SESSION_MAX_TURNS = 10
_CHAT_SESSION_MAX_LEN = _CHAT_SESSION_MAX_TURNS * 2
_CHAT_SESSION_TTL_SEC = 3600


def _normalize_session_id(session_id: Optional[str]) -> Optional[str]:
    if not session_id:
        return None
    sid = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:64]
    return sid or None


def _purge_stale_sessions(now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    cutoff = now - _CHAT_SESSION_TTL_SEC
    dead = [sid for sid, ts in _CHAT_SESSION_TS.items() if ts < cutoff]
    for sid in dead:
        _CHAT_SESSIONS.pop(sid, None)
        _CHAT_SESSION_TS.pop(sid, None)


def _session_history(session_id: Optional[str]) -> list:
    _purge_stale_sessions()
    sid = _normalize_session_id(session_id)
    if not sid:
        return []
    return list(_CHAT_SESSIONS.get(sid, []))


def _append_session(session_id: Optional[str], user_msg: str, assistant_msg: str) -> None:
    _purge_stale_sessions()
    sid = _normalize_session_id(session_id)
    if not sid:
        return
    hist = _CHAT_SESSIONS.setdefault(sid, [])
    hist.append(("human", user_msg))
    hist.append(("ai", assistant_msg))
    if len(hist) > _CHAT_SESSION_MAX_LEN:
        _CHAT_SESSIONS[sid] = hist[-_CHAT_SESSION_MAX_LEN:]
    _CHAT_SESSION_TS[sid] = time.time()


def _offline_clarify(
    message: str,
    briefing: Optional[str],
    history: Optional[list] = None,
) -> str:
    """无 LLM 时的简短澄清：从本期简报里点题回答，不编造数字。"""
    msg = message.strip()
    if not briefing:
        return "当前没有可用的本期采购简报。请先生成周报后再追问。"

    def _section(title: str) -> Optional[str]:
        for line in briefing.splitlines():
            if title in line:
                return line.strip()
        return None

    # 短指代追问（「那呢」「为什么」）结合上一轮用户问题扩写意图
    prior_user = ""
    if history:
        for role, text in reversed(history):
            if role == "human":
                prior_user = text
                break
    lookup = msg
    if len(msg) <= 8 and prior_user and any(k in msg for k in ("那", "呢", "呢？", "呢?", "还有", "呢啊")):
        lookup = f"{prior_user} {msg}"

    if any(k in lookup for k in ("该不该买", "买不买", "采购", "补库", "怎么买")):
        return _section("现在怎么做") or _section("时机好不好") or briefing
    if any(k in lookup for k in ("套保", "对冲", "要紧", "偏松", "偏紧")):
        return _section("现在怎么做") or briefing
    if any(k in lookup for k in ("到库", "成本", "CIF", "落地")):
        line = _section("时机好不好") or _section("为什么")
        return line or "本期简报未单独拆出到库数字，请打开周报「进口成本与政策」板块。"
    if any(k in lookup for k in ("为什么", "依据", "理由", "原因")):
        return _section("为什么") or briefing
    if any(k in lookup for k in ("盯什么", "下周", "触发", "看什么")):
        return _section("下周盯什么") or briefing
    if any(k in lookup for k in ("跌破", "支撑", "怎么办", "风险", "坑")):
        return "\n".join(
            x for x in (_section("别踩的坑"), _section("下周盯什么")) if x
        ) or briefing
    return briefing


@app.get("/api/briefing")
async def api_briefing():
    """最新采购简报 JSON：{report_date, direction, zh, en?}。无简报 → 404。"""
    from reports.procurement_briefing import load_latest_published_briefing

    loaded = load_latest_published_briefing(REPORTS_DIR)
    if not loaded:
        return JSONResponse({"error": "暂无采购简报"}, status_code=404)
    report_date, zh = loaded
    payload = {
        "report_date": report_date,
        "zh": zh,
        "direction": None,
        "en": None,
    }
    side = REPORTS_DIR / report_date / "briefing.json"
    if side.exists():
        try:
            import json
            data = json.loads(side.read_text(encoding="utf-8"))
            payload["direction"] = data.get("direction")
            payload["en"] = data.get("en")
            if data.get("zh"):
                payload["zh"] = data["zh"]
        except Exception:
            pass
    return payload


@app.get("/chat/", response_class=HTMLResponse)
async def chat_page():
    """采购顾问追问页：默认展示最新周报的采购简报 + 追问芯片。"""
    latest = _latest_report_date()
    briefing = _extract_procurement_briefing(latest) if latest else None
    return HTMLResponse(
        content=build_chat_page(briefing=briefing, report_date=latest)
    )


@app.post("/api/chat")
async def chat_api(request: Request):
    """
    聊天 API: {message, session_id?} → {output, session_id}。
    session_id 用于多轮记忆（进程内，最多 10 轮）；agent 同步长任务走 to_thread。
    """
    ip = request.client.host if request.client else "unknown"
    if not _chat_rate_ok(ip):
        return JSONResponse({"error": "请求过于频繁，请稍后再试"}, status_code=429)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    message = (body.get("message") or "").strip()
    session_id = (body.get("session_id") or "").strip() or None
    if not message:
        return JSONResponse({"error": "消息不能为空"}, status_code=400)

    latest = _latest_report_date()
    briefing = _extract_procurement_briefing(latest) if latest else None
    history = _session_history(session_id)

    try:
        analyst = _get_analyst()
    except RuntimeError:
        output = _offline_clarify(message, briefing, history=history)
        _append_session(session_id, message, output)
        return {"output": output, "session_id": session_id}

    # 首轮注入本期简报；后续轮次靠 chat_history，避免重复灌简报
    agent_input = message
    if briefing and not history:
        from reports.procurement_briefing import format_followup_context
        agent_input = format_followup_context(briefing, message, report_date=latest or "")

    try:
        output = await asyncio.to_thread(analyst.chat, agent_input, history)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)

    _append_session(session_id, message, output)
    return {"output": output, "session_id": session_id}


@app.get("/reports/", response_class=HTMLResponse)
async def archive(request: Request):
    """Archive page uses the Jinja2 template with navigation."""
    all_dates = _list_report_dates()
    all_meta = [_read_report_meta(d) for d in all_dates]
    from itertools import groupby
    year_groups = []
    for year, entries in groupby(all_meta, key=lambda x: x["date"][:4]):
        year_groups.append({"year": year, "entries": list(entries)})
    lang = request.query_params.get("lang", "zh")
    return templates.TemplateResponse(request, "archive.html", {
        "year_groups": year_groups,
        "count": len(all_meta),
        "lang": lang,
    })


@app.get("/reports/{report_date}/", response_class=HTMLResponse)
async def report_viewer(report_date: str, request: Request):
    """Single report viewer — no nav bar, original HTML preserved."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", report_date):
        raise HTTPException(status_code=400, detail="Invalid date format")
    if not _report_exists(report_date):
        raise HTTPException(status_code=404, detail="Report not found")
    lang = request.query_params.get("lang", "zh")
    return _serve_report_page(report_date, is_latest=False, lang=lang)


@app.get("/reports/{report_date}.pdf")
async def report_pdf(report_date: str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", report_date):
        raise HTTPException(status_code=400, detail="Invalid date format")
    pdf_path = REPORTS_DIR / report_date / "report.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"coffee_report_{report_date}.pdf",
    )


@app.get("/api/health")
async def health():
    latest = _latest_report_date()
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "latest_report": latest,
        "report_count": len(_list_report_dates()),
    }
