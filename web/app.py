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

from web.chat import build_chat_page
from web.track_record import build_track_record_html

# ── Paths ────────────────────────────────────────────────────────────────────
WEB_DIR = Path(__file__).resolve().parent
REPORTS_DIR = WEB_DIR / "static" / "reports"
TEMPLATES_DIR = WEB_DIR / "templates"

app = FastAPI(title="Arbor", version="3.0")

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
  font-family: Charter, Georgia, "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", serif;
  font-size: 15px;
  font-weight: 600;
  color: #141413;
  letter-spacing: 0.3px;
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
  font-family: Charter, Georgia, "Source Han Serif SC", serif;
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

    # 首页入口: 指向预测战绩页 / AI 分析师聊天页
    if is_latest:
        chat_text = "AI Analyst →" if lang == "en" else "AI 分析师 →"
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


def _error_response(status_code: int, detail: str | None = None, lang: str = "zh") -> HTMLResponse:
    title, desc = ERROR_MESSAGES.get(status_code, ("出错了", "发生未知错误。"))
    if detail and detail not in (str(status_code), ""):
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

@app.get("/", response_class=HTMLResponse)
async def latest_report(request: Request):
    """Root path shows the latest report directly — no nav bar."""
    lang = request.query_params.get("lang", "zh")
    latest = _latest_report_date()
    if not latest:
        return templates.TemplateResponse(request, "empty.html", {"lang": lang})
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


# ── AI 分析师聊天 ─────────────────────────────────────────────────────────────

_analyst = None  # 进程级 CoffeeAnalyst 单例（lazy 首次构造）


def _get_analyst():
    """lazy 构造 CoffeeAnalyst 单例；无 API key 时 RuntimeError 向上抛。"""
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


@app.get("/chat/", response_class=HTMLResponse)
async def chat_page():
    """AI 分析师聊天页。"""
    return HTMLResponse(content=build_chat_page())


@app.post("/api/chat")
async def chat_api(request: Request):
    """聊天 API: {message} → {output}。agent 是同步长任务，走 to_thread 不阻塞事件循环。"""
    ip = request.client.host if request.client else "unknown"
    if not _chat_rate_ok(ip):
        return JSONResponse({"error": "请求过于频繁，请稍后再试"}, status_code=429)

    try:
        body = await request.json()
    except Exception:
        body = {}
    message = (body.get("message") or "").strip() if isinstance(body, dict) else ""
    if not message:
        return JSONResponse({"error": "消息不能为空"}, status_code=400)

    try:
        analyst = _get_analyst()
    except RuntimeError:
        return JSONResponse(
            {"error": "LLM 未配置，请设置 DEEPSEEK_API_KEY 或 ~/.arbor/.env"},
            status_code=503,
        )

    try:
        output = await asyncio.to_thread(analyst.chat, message)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)
    return {"output": output}


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
