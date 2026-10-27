"""
web/app.py
Arbor 预测周报站（FastAPI）

Routes:
  /                     → 最新一期周报；没有周报时显示等待页
  /reports/             → 周报档案
  /reports/{date}/      → 单期周报
  /reports/{date}.pdf   → PDF
  /api/health           → 健康检查

Design:
  报告页直接返回生成 HTML，保留 Kami token；页顶细导航 + 往期索引。
  档案页用 Jinja2。

  uvicorn web.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import re
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from reports.fonts import css_display_stack, css_serif_stack

WEB_DIR = Path(__file__).resolve().parent
REPORTS_DIR = WEB_DIR / "static" / "reports"
TEMPLATES_DIR = WEB_DIR / "templates"

app = FastAPI(title="Arbor", version="4.0")
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


def _template_context(request: Request) -> dict:
    return {"weekly": _latest_report_date()}


templates = Jinja2Templates(directory=TEMPLATES_DIR, context_processors=[_template_context])


def _list_report_dates() -> List[str]:
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
    serif = css_serif_stack()
    display = css_display_stack()
    items_html = ""
    for r in recent_meta:
        current_cls = "past-item-current" if r["date"] == report_date else ""
        pdf_link = (
            f'<a class="past-item-pdf" href="/reports/{r["date"]}.pdf" download>PDF</a>'
            if r["has_pdf"] else ""
        )
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
  font-weight: 500;
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
  border: 0;
  border-radius: 6px;
  padding: 12px 14px;
  text-decoration: none;
  color: inherit;
  transition: background 0.15s;
  display: block;
}}
.past-item:hover {{
  background: #e8e6dc;
}}
.past-item-current {{
  outline: 1.5px solid #1B365D;
  outline-offset: -1.5px;
}}
.past-item-date {{
  font-family: {serif};
  font-size: 13px;
  font-weight: 500;
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


def _report_nav(report_date: str, lang: str) -> str:
    if lang == "en":
        home, archive, switch, switch_href, label = (
            "/?lang=en", "/reports/?lang=en", "中文", f"/reports/{report_date}/", "Archive",
        )
    else:
        home, archive, switch, switch_href, label = (
            "/", "/reports/", "EN", f"/reports/{report_date}/?lang=en", "档案",
        )
    return f"""<nav style="background:#faf9f5;border-bottom:1px solid #e5e3d8;position:sticky;top:0;z-index:100;">
  <div style="max-width:1120px;margin:0 auto;padding:0 28px;height:56px;display:flex;align-items:center;justify-content:space-between;">
    <a href="{home}" aria-label="Arbor"><img src="/static/img/arbor-wordmark-nav.png" alt="Arbor" width="120" height="34" /></a>
    <div style="display:flex;gap:18px;font-size:13px;">
      <a href="{archive}" style="color:#504e49;text-decoration:none;">{label}</a>
      <a href="{switch_href}" style="color:#504e49;text-decoration:none;">{switch}</a>
    </div>
  </div>
</nav>"""


def _serve_report_page(report_date: str, is_latest: bool = False, lang: str = "zh") -> HTMLResponse:
    html_path = REPORTS_DIR / report_date / f"report_{lang}.html"
    if not html_path.exists():
        html_path = REPORTS_DIR / report_date / "report.html"
    html_content = html_path.read_text(encoding="utf-8")

    if is_latest:
        badge_text = "Latest" if lang == "en" else "最新"
        html_content = html_content.replace(
            '<div class="hero-eyebrow">',
            f'<div style="float:right;font-size:11px;font-weight:500;color:#1B365D;background:#E4ECF5;padding:2px 8px;border-radius:4px;letter-spacing:0.3px;">{badge_text}</div><div class="hero-eyebrow">'
        )

    opened = re.search(r"<body[^>]*>", html_content, re.I)
    nav = _report_nav(report_date, lang)
    if opened:
        html_content = html_content[:opened.end()] + nav + html_content[opened.end():]
    else:
        html_content = nav + html_content

    recent = _list_report_dates()[:10]
    recent_meta = [_read_report_meta(d) for d in recent]
    past_index_html = _build_past_index_html(report_date, recent_meta, lang=lang)
    body_end = html_content.rfind("</body>")
    if body_end != -1:
        html_content = html_content[:body_end] + past_index_html + "\n" + html_content[body_end:]
    else:
        html_content += past_index_html

    return HTMLResponse(content=html_content)


ERROR_MESSAGES = {
    400: ("请求有误", "请检查 URL 或参数是否正确。"),
    403: ("无权访问", "您没有权限访问此页面。"),
    404: ("页面未找到", "该报告或页面不存在，可能已被删除或尚未生成。"),
    422: ("参数校验失败", "提交的数据格式不正确，请检查后重试。"),
    500: ("服务器内部错误", "抱歉，服务器遇到了问题。请稍后再试。"),
    502: ("网关错误", "上游服务暂时不可用，请稍后再试。"),
    503: ("服务不可用", "系统正在维护中，请稍后再试。"),
}

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


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """有周报就打开最新一期；还没有时只留等待页。"""
    lang = request.query_params.get("lang", "zh")
    latest = _latest_report_date()
    if latest and _report_exists(latest):
        return _serve_report_page(latest, is_latest=True, lang=lang)
    return templates.TemplateResponse(request, "empty.html", {"lang": lang})


@app.get("/reports/", response_class=HTMLResponse)
async def archive(request: Request):
    all_dates = _list_report_dates()
    all_meta = [_read_report_meta(d) for d in all_dates]
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
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", report_date):
        raise HTTPException(status_code=400, detail="Invalid date format")
    if not _report_exists(report_date):
        raise HTTPException(status_code=404, detail="Report not found")
    lang = request.query_params.get("lang", "zh")
    return _serve_report_page(
        report_date,
        is_latest=(report_date == _latest_report_date()),
        lang=lang,
    )


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
