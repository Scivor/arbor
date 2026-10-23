"""
web/app.py
Arbor Report, Minimal Static Site (FastAPI)

Routes:
  /                → Today's morning note, then the live tape
  /daily/          → Morning note (latest)
  /daily/{date}/   → One morning note
  /reports/        → Weekly archive
  /reports/{date}/ → One weekly report
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from reports.fonts import css_display_stack, css_serif_stack
from arbor.infrastructure.llm import agent_status
from web.chat import build_followup_note, build_followup_panel, build_followup_waiting
from web.daily_brief import (
    bias_label, get_issue, issue_brief, issue_card, latest_issue, published_issues, today_text,
)
from web.quiet_market import kilo_gap_split, quiet_quotes, versus_settlement
from web.track_record import build_track_record_html

# ── Paths ────────────────────────────────────────────────────────────────────
WEB_DIR = Path(__file__).resolve().parent
REPORTS_DIR = WEB_DIR / "static" / "reports"
TEMPLATES_DIR = WEB_DIR / "templates"

app = FastAPI(title="Arbor", version="3.0")

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
def _template_context(request: Request) -> dict:
    """导航里的周报指向最新一期。没有周报时落到档案。"""
    return {"weekly": _latest_report_date()}


templates = Jinja2Templates(directory=TEMPLATES_DIR, context_processors=[_template_context])


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


def _report_nav(report_date: str, lang: str) -> str:
    """周报页顶的细导航：品牌回首页，旁边只留档案。"""
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
    """周报正文，页顶一条细导航。最新一期页尾才有追问。"""
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

    opened = re.search(r"<body[^>]*>", html_content, re.I)
    nav = _report_nav(report_date, lang)
    if opened:
        html_content = html_content[:opened.end()] + nav + html_content[opened.end():]
    else:
        html_content = nav + html_content

    recent = _list_report_dates()[:10]
    recent_meta = [_read_report_meta(d) for d in recent]
    past_index_html = _build_past_index_html(report_date, recent_meta, lang=lang)
    if is_latest:
        tr_text = "Track Record →" if lang == "en" else "预测战绩 →"
        past_index_html = past_index_html.replace(
            '<a class="past-index-all"',
            f'<a class="past-index-all" style="margin-right:14px;" href="/track-record/">{tr_text}</a><a class="past-index-all"',
            1,
        )
        tail = build_followup_panel(report_date, lang=lang, agent=agent_status())
    else:
        latest = _latest_report_date()
        tail = build_followup_note(latest, lang) if latest else ""

    extra = past_index_html + "\n" + tail
    body_end = html_content.rfind("</body>")
    if body_end != -1:
        html_content = html_content[:body_end] + extra + "\n" + html_content[body_end:]
    else:
        html_content += extra

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

def _mark_names(issue: dict, key: str, zh: str, en: str, leg_en: str) -> tuple[str, str, str]:
    noun = ((issue or {}).get("marks") or {}).get(key) or {}
    return noun.get("zh") or zh, noun.get("en") or en, noun.get("leg_en") or leg_en


def _morning_mark(
    price: Optional[str],
    reference: Optional[str],
    decimals: int,
    issue: Optional[dict],
    noun_zh: str,
    noun_en: str,
) -> Optional[dict]:
    """现价相对当天早报里的一个价。早报不是今天的，或两边缺一，就不写。"""
    if not price or not reference or not issue or not issue.get("date"):
        return None
    if issue["date"] != today_text():
        return None
    gap = versus_settlement(price, reference, decimals)
    if not gap:
        return None
    gap["date"] = issue["date"]
    gap["noun_zh"] = noun_zh
    gap["noun_en"] = noun_en
    return gap


def _morning_gap(coffee: Optional[dict], issue: Optional[dict]) -> Optional[dict]:
    """空页现价相对当天早报里的阿拉比卡价。"""
    contracts = (issue or {}).get("contracts") or []
    settlement = contracts[0].get("price") if contracts else None
    noun_zh, noun_en, _leg = _mark_names(issue or {}, "coffee", "结算", "settlement", "Settlement")
    return _morning_mark((coffee or {}).get("price"), settlement, 2, issue, noun_zh, noun_en)


def _morning_fix(fx: Optional[dict], issue: Optional[dict]) -> Optional[dict]:
    """空页汇率相对当天早报里的汇率。"""
    fixing = ((issue or {}).get("fix") or {}).get("price")
    noun_zh, noun_en, _leg = _mark_names(issue or {}, "fx", "中间价", "fixing", "fixing")
    return _morning_mark((fx or {}).get("price"), fixing, 4, issue, noun_zh, noun_en)


def _landing_kilo(yuan: Optional[dict], landed: Optional[dict]) -> Optional[dict]:
    """到库元/公斤相对上面那一公斤期货。两边都用页面上的两位小数。"""
    if not landed or not landed.get("per_kg") or not yuan or not yuan.get("per_kg"):
        return None
    return versus_settlement(landed["per_kg"], yuan["per_kg"], 2)


def _morning_yuan(yuan: Optional[dict], issue: Optional[dict]) -> Optional[dict]:
    """空页元/公斤相对当天早报的折算，并拆成两腿各走了多少。"""
    contracts = (issue or {}).get("contracts") or []
    estimate = contracts[0].get("per_kg") if contracts else None
    noun_zh, noun_en, _leg = _mark_names(issue or {}, "yuan", "推算", "estimate", "Conversion")
    gap = _morning_mark((yuan or {}).get("per_kg"), estimate, 2, issue, noun_zh, noun_en)
    if not gap or not yuan or not contracts:
        return gap
    coffee_zh, _coffee_en, coffee_leg = _mark_names(issue or {}, "coffee", "结算", "settlement", "Settlement")
    fx_zh, _fx_en, fx_leg = _mark_names(issue or {}, "fx", "中间价", "fixing", "fixing")
    split = kilo_gap_split(
        yuan.get("cents"),
        yuan.get("rate"),
        contracts[0].get("price"),
        (issue.get("fix") or {}).get("price"),
        estimate,
        yuan.get("per_kg"),
    )
    if split:
        gap.update(split)
        gap["coffee_noun_zh"] = coffee_zh
        gap["fx_noun_zh"] = fx_zh
        gap["coffee_leg_en"] = coffee_leg
        gap["fx_leg_en"] = fx_leg
    return gap


def _redirect_report(report_date: str, lang: str) -> RedirectResponse:
    url = f"/reports/{report_date}/"
    if lang == "en":
        url += "?lang=en"
    return RedirectResponse(url, status_code=302)


@app.get("/", response_class=HTMLResponse)
async def latest_report(request: Request):
    """上海当天有周报就看周报。没有的日子只留现价，早报不放在这一页。"""
    lang = request.query_params.get("lang", "zh")
    if _report_exists(today_text()):
        today = today_text()
        return _serve_report_page(today, is_latest=(today == _latest_report_date()), lang=lang)
    try:
        quotes = await asyncio.to_thread(quiet_quotes)
    except Exception:
        quotes = {"coffee": None, "fx": None}
    coffee = (quotes or {}).get("coffee")
    fx = (quotes or {}).get("fx")
    yuan = (quotes or {}).get("yuan")
    landed = (quotes or {}).get("landed")
    sheet = get_issue(today_text(), quotes) or latest_issue()
    return templates.TemplateResponse(request, "empty.html", {
        "lang": lang,
        "issue": sheet,
        "bias": bias_label,
        "coffee": coffee,
        "fx": fx,
        "yuan": yuan,
        "landed": landed,
        "source": (quotes or {}).get("source"),
        "note": _morning_gap(coffee, sheet),
        "fix": _morning_fix(fx, sheet),
        "yuan_note": _morning_yuan(yuan, sheet),
        "landing": _landing_kilo(yuan, landed),
    })


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
    morning: str = "",
    lang: str = "zh",
) -> str:
    """无 LLM 时只点已出版的那一截。对不上就说没写，不倒回整份简报。"""
    msg = message.strip()
    morning = (morning or "").strip()
    missing = "This issue does not say that." if lang == "en" else "这期简报没写这一点。"
    if not briefing and not morning:
        return "当前没有已出版的早报或周报。我只接问题，不编数字。"

    def _section(title: str) -> Optional[str]:
        if not briefing:
            return None
        for line in briefing.splitlines():
            if title in line:
                return line.strip()
        return None

    def _or_miss(*parts: Optional[str]) -> str:
        kept = [part for part in parts if part]
        return "\n".join(kept) if kept else missing

    prior_user = ""
    if history:
        for role, text in reversed(history):
            if role == "human":
                prior_user = text
                break
    lookup = msg
    if len(msg) <= 8 and prior_user and any(k in msg for k in ("那", "呢", "呢？", "呢?", "还有", "呢啊")):
        lookup = f"{prior_user} {msg}"
    low = lookup.lower()

    if morning and any(k in lookup for k in ("早报", "现价", "最近成交", "在岸", "公斤")):
        return morning
    if any(k in lookup for k in ("该不该买", "买不买", "采购", "补库", "怎么买")) or "should we buy" in low:
        return _or_miss(_section("现在怎么做"), _section("时机好不好"))
    if any(k in lookup for k in ("套保", "对冲", "要紧", "偏松", "偏紧")) or "hedge" in low or "tighten" in low or "loosen" in low:
        return _or_miss(_section("现在怎么做"))
    if any(k in lookup for k in ("到库", "成本", "CIF", "落地")) or "landed" in low:
        line = _section("时机好不好") or _section("为什么")
        if line:
            return line
        return "本期简报未单独拆出到库数字，请打开周报「进口成本与政策」板块。"
    if any(k in lookup for k in ("为什么", "依据", "理由", "原因")) or low.strip() in ("why", "why?"):
        return _or_miss(_section("为什么"))
    if any(k in lookup for k in ("盯什么", "下周", "触发", "看什么")):
        return _or_miss(_section("下周盯什么"))
    if any(k in lookup for k in ("跌破", "支撑", "怎么办", "风险", "坑")) or "support" in low:
        return _or_miss(_section("别踩的坑"), _section("下周盯什么"))
    return missing


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


def _today_morning_text() -> str:
    """顾问只读当天已经冻结的早报，不在追问时新写一期。"""
    issue = get_issue(today_text())
    return issue_brief(issue) if issue else ""


@app.get("/chat/", response_class=HTMLResponse)
async def chat_page(request: Request):
    """追问不单独占一页。有周报就转到最新一期的页尾。"""
    latest = _latest_report_date()
    lang = request.query_params.get("lang", "zh")
    if latest:
        url = f"/reports/{latest}/#followup"
        if lang == "en":
            url = f"/reports/{latest}/?lang=en#followup"
        return RedirectResponse(url, status_code=302)
    return HTMLResponse(content=build_followup_waiting(agent_status(), lang))


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
    report_date = (body.get("report_date") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        report_date = latest or ""
    lang = body.get("lang") if body.get("lang") in ("zh", "en") else "zh"
    briefing = _extract_procurement_briefing(report_date) if report_date else None
    morning = _today_morning_text() if report_date and report_date == today_text() else ""
    history = _session_history(session_id)

    try:
        analyst = _get_analyst()
    except RuntimeError:
        output = _offline_clarify(message, briefing, history=history, morning=morning, lang=lang)
        _append_session(session_id, message, output)
        return {"output": output, "session_id": session_id, "provider": "offline"}

    # 首轮才带这期简报。早报只在周报日期就是今天、且已经冻结时附上。
    agent_input = message
    if not history and (briefing or morning):
        from reports.procurement_briefing import format_followup_context
        agent_input = format_followup_context(
            briefing or "", message, report_date=report_date, morning=morning, lang=lang,
        )

    try:
        output = await asyncio.to_thread(analyst.chat, agent_input, history)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)

    _append_session(session_id, message, output)
    status = agent_status()
    return {
        "output": output,
        "session_id": session_id,
        "provider": status["provider"] or "deepseek",
    }


@app.get("/api/agent")
async def api_agent():
    """采购顾问是否已接通。响应里没有钥匙。"""
    return agent_status()


def _daily_response(request: Request, issue: dict) -> HTMLResponse:
    lang = request.query_params.get("lang", "zh")
    return templates.TemplateResponse(request, "daily.html", {
        "lang": lang,
        "issue": issue,
        "bias": bias_label,
    })


def _quotes_for_today() -> Optional[dict]:
    """当天还没有早报时才读行情。读失败就留空，调用方回到已有的一期。"""
    if get_issue(today_text()) is not None:
        return None
    try:
        return quiet_quotes()
    except Exception:
        return None


@app.get("/daily/", response_class=HTMLResponse)
async def daily_latest(request: Request):
    """最新一期早报。当天已有周报时，这一页让给周报。"""
    lang = request.query_params.get("lang", "zh")
    if _report_exists(today_text()):
        return _redirect_report(today_text(), lang)
    quotes = await asyncio.to_thread(_quotes_for_today)
    return _daily_response(request, latest_issue(quotes))


@app.get("/daily/{issue_date}/", response_class=HTMLResponse)
async def daily_issue(issue_date: str, request: Request):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", issue_date):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD。")
    if _report_exists(issue_date):
        return _redirect_report(issue_date, request.query_params.get("lang", "zh"))
    quotes = None
    if issue_date == today_text() and get_issue(issue_date) is None:
        quotes = await asyncio.to_thread(_quotes_for_today)
    issue = get_issue(issue_date, quotes)
    if issue is None:
        raise HTTPException(status_code=404, detail="没有这一期早报。")
    return _daily_response(request, issue)


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
        "mornings": [issue_card(issue) for issue in published_issues()],
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
