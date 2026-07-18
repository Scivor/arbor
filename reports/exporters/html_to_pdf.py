"""
reports/exporters/html_to_pdf.py
Generate HTML report with Kami warm-parchment editorial design system.

Design tokens (from kami.tw93.fun):
  Canvas    #f5f4ed   warm parchment
  Accent    #1B365D   deep navy
  Text      #141413   near-black
  Olive     #3d3d3a   warm dark
  Stone     #6b6a64   muted
  Border    #e8e6dc   warm border
  Serif     Charter, Georgia, "Source Han Serif SC", "Noto Serif CJK SC", serif
"""

from __future__ import annotations
import base64
import html as _html
import io
import os
import subprocess
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

from reports.formatters import (
    format_distance as _fmt_distance,
    format_number as _fmt_number,
    format_percent as _fmt_percent,
    format_price as _fmt_price,
    format_range as _fmt_range,
    format_signed_number as _fmt_signed_number,
)

# ── i18n translations ────────────────────────────────────────────────────────

_TRANSLATIONS = {
    # Report meta
    "report_title": {"zh": "Arbor 咖啡期货下周预测", "en": "Arbor Coffee Futures Weekly Prediction"},
    "page_title": {"zh": "Arbor 咖啡期货下周预测 · {date}", "en": "Arbor Coffee Futures Weekly Prediction · {date}"},
    "hero_eyebrow": {"zh": "Weekly Futures Outlook", "en": "Weekly Futures Outlook"},
    "forecast_range": {"zh": "预测区间", "en": "Forecast"},
    "contract": {"zh": "合约", "en": "Contract"},
    "figure_price_caption": {"zh": "图 1. KC=F 近 30 日价格走势，供内部研究参考。", "en": "Fig. 1. KC=F 30-day price action, for internal research reference."},

    # Sections
    "market_snapshot": {"zh": "市场行情", "en": "Market Snapshot"},
    "ml_prediction": {"zh": "ML 模型预测", "en": "ML Prediction"},
    "scenario_analysis": {"zh": "情景分析", "en": "Scenario Analysis"},
    "key_levels": {"zh": "关键价位", "en": "Key Levels"},
    "market_drivers": {"zh": "多空驱动", "en": "Market Drivers"},
    "market_outlook": {"zh": "市场展望", "en": "Market Outlook"},

    # Metrics
    "rsi": {"zh": "RSI (14)", "en": "RSI (14)"},
    "ma20": {"zh": "MA20", "en": "MA20"},
    "ma60": {"zh": "MA60", "en": "MA60"},
    "high_30d": {"zh": "30日高", "en": "30D High"},
    "low_30d": {"zh": "30日低", "en": "30D Low"},
    "volume_ratio": {"zh": "量比", "en": "Vol Ratio"},
    "distance": {"zh": "距当前", "en": "from current"},

    # Metric states
    "overbought": {"zh": "超买", "en": "Overbought"},
    "oversold": {"zh": "超卖", "en": "Oversold"},
    "neutral": {"zh": "中性", "en": "Neutral"},
    "below_price": {"zh": "价格下方", "en": "Below Price"},
    "above_price": {"zh": "价格上方", "en": "Above Price"},
    "high_volume": {"zh": "放量", "en": "High Vol"},
    "low_volume": {"zh": "缩量", "en": "Low Vol"},
    "normal_volume": {"zh": "正常", "en": "Normal"},

    # Scenarios
    "direction": {"zh": "方向", "en": "Direction"},
    "up": {"zh": "上涨", "en": "Up"},
    "down": {"zh": "下跌", "en": "Down"},
    "sideways": {"zh": "横盘", "en": "Sideways"},
    "range_bound": {"zh": "区间震荡", "en": "Range-Bound"},
    "breakout_up": {"zh": "方向突破(涨)", "en": "Breakout (Up)"},
    "breakout_down": {"zh": "方向突破(跌)", "en": "Breakout (Down)"},
    "scenario_a": {"zh": "情景A", "en": "Scenario A"},
    "scenario_b": {"zh": "情景B", "en": "Scenario B"},
    "scenario_c": {"zh": "情景C", "en": "Scenario C"},

    # ML
    "ml_model_type": {"zh": "ML 模型预测", "en": "ML Model Prediction"},
    "ml_target_30d": {"zh": "30日价格目标", "en": "30-Day Price Target"},
    "ml_accuracy": {"zh": "方向准确率", "en": "Direction Accuracy"},
    "ml_mae": {"zh": "收益MAE", "en": "Return MAE"},
    "ml_key_features": {"zh": "关键特征", "en": "Key Features"},
    "ml_hedge_bias": {"zh": "套保比率调整", "en": "Hedge Ratio Adj"},
    "ml_confidence": {"zh": "置信度", "en": "Confidence"},

    # Review
    "review_title": {"zh": "上周预测回顾", "en": "Last Week Review"},
    "review_date": {"zh": "预测日期", "en": "Forecast Date"},
    "review_direction": {"zh": "主导方向", "en": "Direction"},
    "review_hedge": {"zh": "套保建议", "en": "Hedge Advice"},
    "review_price_change": {"zh": "价格变动", "en": "Price Change"},
    "review_actual": {"zh": "实际方向", "en": "Actual"},
    "review_hit": {"zh": "价格区间命中", "en": "Price Range Hit"},
    "review_dir_correct": {"zh": "方向判断正确", "en": "Direction Correct"},
    "review_dir_miss": {"zh": "方向判断偏差", "en": "Direction Miss"},
    "review_hedge_ok": {"zh": "套保有效", "en": "Hedge Effective"},
    "review_hedge_conservative": {"zh": "套保偏保守", "en": "Hedge Conservative"},
    "review_hit_badge": {"zh": "命中", "en": "Hit"},
    "review_partial": {"zh": "部分命中", "en": "Partial"},
    "review_miss": {"zh": "偏离", "en": "Miss"},

    # Driver Attribution
    "attr_title": {"zh": "驱动因子归因", "en": "Driver Attribution"},
    "attr_empty": {"zh": "上期未记录驱动因子", "en": "No drivers recorded last week"},
    "attr_summary": {"zh": "应验 {hits} / 失效 {misses} / 中性 {neutrals}", "en": "Confirmed {hits} / Missed {misses} / Neutral {neutrals}"},

    # Related / Climate
    "related_markets": {"zh": "关联市场", "en": "Related Markets"},
    "climate_bg": {"zh": "气候背景", "en": "Climate"},

    # Hedge
    "hedge_advice": {"zh": "套保建议", "en": "Hedge Advice"},

    # China Import
    "china_import": {"zh": "进口成本与政策", "en": "Import Cost & Policy"},
    "landed_total": {"zh": "到库成本", "en": "Landed Cost"},
    "cyp_share": {"zh": "CYP 占比", "en": "CYP Share"},
    "current_hedge": {"zh": "当前套保比率", "en": "Current Hedge"},
    "policy_events": {"zh": "政策事件", "en": "Policy Events"},
    "no_policy_events": {"zh": "近 7 日无显著政策事件", "en": "No significant policy events in the past 7 days"},

    # Levels
    "support": {"zh": "支撑 Support", "en": "Support"},
    "resistance": {"zh": "阻力 Resistance", "en": "Resistance"},

    # Drivers
    "bullish_factors": {"zh": "▲ 利多因素 Bullish", "en": "▲ Bullish Factors"},
    "bearish_factors": {"zh": "▼ 利空因素 Bearish", "en": "▼ Bearish Factors"},
    "no_bullish": {"zh": "暂无明确利多因素", "en": "No clear bullish factors"},
    "no_bearish": {"zh": "暂无明确利空因素", "en": "No clear bearish factors"},

    # Outlook
    "no_outlook": {"zh": "暂无展望", "en": "No outlook available"},
    "risk_warnings": {"zh": "⚠ 风险提示 Risk Warnings", "en": "⚠ Risk Warnings"},

    # Footer
    "data_sources": {"zh": "数据来源", "en": "Data Sources"},
    "disclaimer": {"zh": "本报告仅供内部决策参考，不构成投资建议。市场有风险，套保需谨慎。", "en": "For internal reference only. Not investment advice. Markets carry risks."},
    "generated_by": {"zh": "Generated by Arbor.", "en": "Generated by Arbor."},
}


def _t(key: str, lang: str = "zh", **kwargs) -> str:
    """Get translated text."""
    text = _TRANSLATIONS.get(key, {}).get(lang, key)
    if kwargs:
        text = text.format(**kwargs)
    return text


def html_to_pdf(html_path: str, pdf_path: str) -> None:
    """Convert HTML file to PDF using Playwright (headless Chromium).

    Falls back to macOS textutil if Playwright is unavailable.
    Preserves CSS colors, fonts, and layout via print-background.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        _html_to_pdf_textutil(html_path, pdf_path)
        return

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{os.path.abspath(html_path)}")
        page.wait_for_load_state("networkidle")
        page.pdf(
            path=pdf_path,
            format="A4",
            margin={"top": "14mm", "right": "16mm", "bottom": "14mm", "left": "16mm"},
            print_background=True,
        )
        browser.close()

    if not os.path.exists(pdf_path):
        raise RuntimeError(f"PDF not created: {pdf_path}")


def _html_to_pdf_textutil(html_path: str, pdf_path: str) -> None:
    """Fallback PDF conversion using macOS textutil (CSS support is poor)."""
    result = subprocess.run(
        ["textutil", "-convert", "pdf", "-output", pdf_path, html_path],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"textutil failed: {result.stderr}")
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"PDF not created: {result.stderr}")


def export_pdf(report, dest: str | None = None, lang: str = "zh") -> str:
    """Export report directly to PDF (via temporary HTML).

    Args:
        report: PredictionReport from pipeline.
        dest:   Output PDF path. Defaults to coffee_outlook_YYYY-MM-DD.pdf.
        lang:   Report language: 'zh' or 'en' (default: 'zh').

    Returns:
        Path to the generated PDF file.
    """
    html = build_report_html(report, lang=lang)
    today = datetime.now().strftime("%Y-%m-%d")
    dest = dest or f"coffee_outlook_{today}.pdf"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp_html = f.name

    try:
        html_to_pdf(tmp_html, dest)
    finally:
        os.unlink(tmp_html)

    return dest


def _build_price_chart(report, lang: str = "zh") -> str:
    """Generate a candlestick chart as base64 PNG, styled after Kami/Tesla editorial.

    Uses mplfinance for professional candlestick rendering with Kami color tokens.
    Brand-aligned: parchment bg, navy up / olive down, gold MA20, warm grid.
    """
    m = report.market
    if not m or not m.close_30d:
        return ""

    # -- Fetch OHLC data from Yahoo Finance --
    import pandas as pd
    import mplfinance as mpf

    ticker = report.ticker or "KC=F"
    try:
        import requests
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        data = r.json()["chart"]["result"][0]
        timestamps = data["timestamp"]
        quote = data["indicators"]["quote"][0]
        df = pd.DataFrame({
            "Open": quote["open"],
            "High": quote["high"],
            "Low": quote["low"],
            "Close": quote["close"],
        }, index=pd.to_datetime(timestamps, unit="s"))
        df = df.dropna()
        if len(df) < 5:
            raise ValueError("Insufficient OHLC data")
    except Exception:
        # Fallback: synthesize OHLC from close prices with small synthetic ranges
        import numpy as np
        closes = list(m.close_30d)
        n = len(closes)
        np.random.seed(42)
        opens = [closes[0]] + closes[:-1]
        highs = [max(c, o) * (1 + np.random.uniform(0.003, 0.015)) for c, o in zip(closes, opens)]
        lows = [min(c, o) * (1 - np.random.uniform(0.003, 0.015)) for c, o in zip(closes, opens)]
        dates = [datetime.now() - timedelta(days=(n - 1 - i)) for i in range(n)]
        df = pd.DataFrame({
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
        }, index=pd.to_datetime(dates))

    # -- Font setup --
    plt.rcParams["font.family"] = ["Songti SC", "DejaVu Serif", "Hiragino Sans GB", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    # -- Brand-aligned Kami style --
    PARCHMENT = "#f5f4ed"
    BORDER    = "#e8e6dc"
    BRAND     = "#1B365D"
    OLIVE     = "#504e49"
    STONE     = "#6b6a64"
    GOLD      = "#C5A572"
    NEAR_BLK  = "#141413"

    kami_style = mpf.make_mpf_style(
        base_mpf_style="default",
        figcolor=PARCHMENT,
        facecolor=PARCHMENT,
        edgecolor=BORDER,
        rc={
            "font.family": ["Songti SC", "DejaVu Serif", "Hiragino Sans GB", "DejaVu Sans"],
            "axes.unicode_minus": False,
        },
        marketcolors=mpf.make_marketcolors(
            up=BRAND,
            down=OLIVE,
            edge={"up": BRAND, "down": OLIVE},
            wick={"up": BRAND, "down": OLIVE},
        ),
        gridstyle="-",
        gridcolor=BORDER,
        gridaxis="horizontal",
    )

    # -- Addplots: MA + levels --
    addplots = []

    # MA20 -- gold solid, primary reference
    if m and m.ma20:
        ma20_series = pd.Series([m.ma20] * len(df), index=df.index)
        addplots.append(mpf.make_addplot(
            ma20_series, color=GOLD, width=1.0, linestyle="-", alpha=0.75,
        ))

    # MA60 -- stone dashed, secondary reference
    if m and m.ma60:
        ma60_series = pd.Series([m.ma60] * len(df), index=df.index)
        addplots.append(mpf.make_addplot(
            ma60_series, color=STONE, width=0.8, linestyle="--", alpha=0.5,
        ))

    # Current price -- subtle gold dotted reference
    if m and m.current:
        curr_series = pd.Series([m.current] * len(df), index=df.index)
        addplots.append(mpf.make_addplot(
            curr_series, color=GOLD, width=0.6, linestyle=":", alpha=0.45,
        ))

    # Support levels -- brand blue, thin dash-dot
    for lvl in (report.support_levels or []):
        s = pd.Series([lvl.price] * len(df), index=df.index)
        addplots.append(mpf.make_addplot(
            s, color=BRAND, width=0.5, linestyle="-.", alpha=0.35,
        ))

    # Resistance levels -- olive, thin dash-dot
    for lvl in (report.resistance_levels or []):
        s = pd.Series([lvl.price] * len(df), index=df.index)
        addplots.append(mpf.make_addplot(
            s, color=OLIVE, width=0.5, linestyle="-.", alpha=0.35,
        ))

    # -- Title with current price inline --
    title_text = (
        f"KC=F 近30日走势  |  {_fmt_price(m.current, suffix=' USc/lb')}  |  30-Day Price Action"
        if lang != "en" and m and m.current
        else "KC=F 30-Day Price Action"
    )

    # -- Plot --
    fig, axes = mpf.plot(
        df,
        type="candle",
        style=kami_style,
        figsize=(10.5, 4.5),
        title=title_text,
        ylabel="USc/lb",
        xrotation=0,
        returnfig=True,
        addplot=addplots if addplots else None,
    )

    # Fine-tune spines, ticks, and margins
    for ax in axes:
        ax.set_facecolor(PARCHMENT)
        for spine in ax.spines.values():
            spine.set_color(BORDER)
            spine.set_linewidth(0.4)
        ax.tick_params(colors=STONE, labelsize=7)
        ax.yaxis.label.set_color(STONE)
        ax.yaxis.label.set_fontsize(8)
        ax.margins(x=0.02, y=0.08)

    fig.patch.set_facecolor(PARCHMENT)
    fig.subplots_adjust(left=0.08, right=0.92, top=0.88, bottom=0.12)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor=PARCHMENT, pad_inches=0.08)
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f'<img class="figure-chart" src="data:image/png;base64,{b64}" style="width:100%;max-width:100%;display:block;margin:0;" alt="Price Chart">'


def _scenario_accent(direction: str) -> str:
    """Return scenario accent color by direction."""
    if direction == "up":
        return "#1B365D"
    if direction == "down":
        return "#504e49"
    return "#6b6a64"


def _build_scenario_rows(report, lang: str) -> str:
    """Render scenario cards."""
    rows = ""
    for scenario in (report.scenarios or []):
        accent = _scenario_accent(scenario.direction)
        rationale_html = "".join(f"<p>• {reason}</p>" for reason in (scenario.rationale or []))
        rows += f"""
        <div class="sc-card">
          <div class="sc-hdr">
            <span class="sc-label" style="color:{accent};">{scenario.label}</span>
            <span class="sc-prob">{_fmt_percent(scenario.probability, decimals=0, scale=100)}</span>
          </div>
          <div class="sc-range">{_fmt_range(scenario.price_min, scenario.price_max, separator=" – ")} <span class="sc-unit">¢/lb</span></div>
          <div class="sc-dir" style="color:{accent};">{_t("direction", lang)}: {scenario.direction}</div>
          <div class="sc-rationale">{rationale_html}</div>
        </div>"""
    return rows


def _build_level_rows(levels, *, color: str) -> str:
    """Render support/resistance rows."""
    rows = ""
    for level in (levels or []):
        rows += f"""
        <tr><td class="lv-price" style="color:{color};">{_fmt_price(level.price)}</td><td class="lv-label">{level.label}</td></tr>"""
    return rows


def _build_driver_rows(params) -> str:
    """Render driver list items."""
    return "".join(f"<li><strong>{param.param_name}</strong> — {param.narrative}</li>" for param in (params or []))


def _build_risk_items(risk_warnings) -> str:
    """Render risk warning list items."""
    return "".join(f"<li>{warning}</li>" for warning in (risk_warnings or []))


def _signal_color(signal: str) -> str:
    """Return ML signal color."""
    if signal == "BULLISH":
        return "#1B365D"
    if signal == "BEARISH":
        return "#504e49"
    return "#6b6a64"


def _build_ml_perf_html(ml, lang: str) -> str:
    """Render ML performance summary."""
    perf_items = []
    if ml.model_accuracy is not None:
        perf_items.append(f'{_t("ml_accuracy", lang)} <strong>{_fmt_percent(ml.model_accuracy, decimals=1, scale=100)}</strong>')
    if ml.model_mae is not None:
        perf_items.append(f'{_t("ml_mae", lang)} <strong>{_fmt_percent(ml.model_mae, decimals=2, scale=100)}</strong>')
    if not perf_items:
        return ""
    return f"<div class=\"ml-perf\">{'  ·  '.join(perf_items)}</div>"


def _build_ml_features_html(ml, lang: str) -> str:
    """Render ML feature importance table."""
    if not ml.top_features:
        return ""

    rows = ""
    for name, importance in ml.top_features:
        bar_width = min(int(abs(importance) * 200), 100)
        rows += (
            f"<tr><td class='fi-name'>{name}</td>"
            f"<td class='fi-bar-cell'><div class='fi-bar'><div class='fi-fill' style='width:{bar_width}%'></div></div></td>"
            f"<td class='fi-val'>{_fmt_number(importance, decimals=4)}</td></tr>"
        )

    return f"""
            <div class="ml-features">
              <div class="ml-features-title">{_t("ml_key_features", lang)}</div>
              <table class="fi-table">{rows}</table>
            </div>"""


def _build_ml_html(ml, lang: str) -> str:
    """Render ML summary card."""
    if not ml:
        return ""

    target_html = (
        f'<div class="ml-target">{_t("ml_target_30d", lang)} <strong>{_fmt_price(ml.price_target_30d, suffix="¢/lb")}</strong></div>'
        if ml.price_target_30d
        else ""
    )
    rationale_html = "".join(f"<li>{reason}</li>" for reason in ml.rationale)

    return f"""
        <div class="card ml-card">
          <div class="card-hdr">
            <span>{_t("ml_model_type", lang)}</span>
            <span class="card-tag">{ml.model_type}</span>
          </div>
          <div class="ml-body">
            <div class="ml-signal" style="color:{_signal_color(ml.signal)}">
              <span class="ml-sig-label">{ml.signal}</span>
              <span class="ml-confidence">{_t("ml_confidence", lang)} {_fmt_percent(ml.confidence, decimals=0, scale=100)}</span>
            </div>
            {target_html}
            <div class="ml-bias">{_t("ml_hedge_bias", lang)} <strong>{_fmt_percent(ml.bias, decimals=0, signed=True, scale=100)}</strong></div>
            {_build_ml_perf_html(ml, lang)}
            {_build_ml_features_html(ml, lang)}
            <ul class="ml-rationale">{rationale_html}</ul>
          </div>
        </div>"""


def _review_badge_color(review_badge: str, lang: str) -> str:
    """Return review badge color."""
    return {
        _t("review_hit_badge", lang): "#1B365D",
        _t("review_partial", lang): "#504e49",
        _t("review_miss", lang): "#504e49",
    }.get(review_badge, "#6b6a64")


def _actual_direction_text(direction: str, lang: str) -> str:
    """Translate review actual direction."""
    if direction == "up":
        return _t("up", lang)
    if direction == "down":
        return _t("down", lang)
    return _t("sideways", lang)


def _build_attribution_html(last, current_price: float, lang: str) -> str:
    """Render driver attribution block — 上期驱动因子逐个判 应验/失效/中性。"""
    if not last.drivers:
        return f"""
                <div class="attr-block">
                  <div class="attr-title">{_t("attr_title", lang)}</div>
                  <div class="attr-empty">{_t("attr_empty", lang)}</div>
                </div>"""

    try:
        from reports.history import compute_attribution
        attr = compute_attribution(last, current_price)
    except Exception:
        return ""

    icons = {"应验": ("✓", "#1B365D"), "失效": ("✗", "#504e49"), "中性": ("–", "#6b6a64")}
    rows = ""
    for v in attr["verdicts"]:
        icon, color = icons.get(v["verdict"], icons["中性"])
        weight = f" <span class='attr-weight'>{v['weight']}</span>" if v.get("weight") else ""
        rows += (f"<li><span class='attr-icon' style='color:{color};'>{icon}</span>"
                 f"{v['param_name']}{weight}</li>")

    summary = _t("attr_summary", lang, hits=attr["hits"], misses=attr["misses"], neutrals=attr["neutrals"])
    return f"""
                <div class="attr-block">
                  <div class="attr-title">{_t("attr_title", lang)}</div>
                  <ul class="attr-list">{rows}</ul>
                  <div class="attr-summary">{summary}</div>
                </div>"""


def _build_review_html(report, current_price: float | None, lang: str) -> str:
    """Render prediction review card when history is available."""
    if current_price is None:
        return ""

    try:
        from reports.history import load_last_week_summary, compute_prediction_review

        last = load_last_week_summary(report.report_date)
        if not last:
            return ""
        review = compute_prediction_review(last, current_price)
    except Exception:
        return ""

    direction_result = _t("review_dir_correct", lang) if review.direction_correct else _t("review_dir_miss", lang)
    hedge_result = _t("review_hedge_ok", lang) if review.hedge_advice_correct else _t("review_hedge_conservative", lang)
    attribution_html = _build_attribution_html(last, review.current_price, lang)

    return f"""
            <div class="card review-card">
              <div class="card-hdr">
                <span>{_t("review_title", lang)}</span>
                <span class="card-tag" style="background:var(--parchment);color:{_review_badge_color(review.review_badge, lang)};border:1px solid var(--border);">{review.review_badge}</span>
              </div>
              <div class="review-body">
                <p><strong>{_t("review_date", lang)}</strong> {review.last_report_date} &nbsp;·&nbsp; <strong>{_t("review_direction", lang)}</strong> {review.last_dominant_direction} &nbsp;·&nbsp; <strong>{_t("review_hedge", lang)}</strong> {review.last_hedge_signal}({_fmt_percent(review.last_hedge_ratio, decimals=0, scale=100)})</p>
                <p><strong>{_t("review_price_change", lang)}</strong> {_fmt_price(review.current_price, decimals=1)} vs {_fmt_price(last.current_price, decimals=1)} ({_fmt_percent(review.price_change_pct, decimals=1, signed=True)}) &nbsp;·&nbsp; <strong>{_t("review_actual", lang)}</strong> {_actual_direction_text(review.direction_actual, lang)}</p>
                <ul>
                  <li>{"✓" if review.prediction_hit else "✗"} {_t("review_hit", lang)}</li>
                  <li>{"✓" if review.direction_correct else "✗"} {direction_result}</li>
                  <li>{"✓" if review.hedge_advice_correct else "✗"} {_t("review_hedge", lang)}{hedge_result}</li>
                </ul>
                {attribution_html}
                <p class="review-note">{review.review_text}</p>
              </div>
            </div>"""


def _build_related_html(related_markets, lang: str) -> str:
    """Render related markets strip."""
    if not related_markets:
        return ""

    items = ""
    for name, change in related_markets.items():
        color = "#1B365D" if change > 0 else "#504e49" if change < 0 else "#6b6a64"
        items += f"<span class='rel-tag' style='color:{color};'><b>{name}</b> {_fmt_percent(change, decimals=1, signed=True, scale=100)}</span>"

    return f"""
        <div class="rel-strip">
          <span class="rel-label">{_t("related_markets", lang)}</span>
          {items}
        </div>"""


def _build_climate_html(climate, lang: str) -> str:
    """Render climate strip."""
    if not climate:
        return ""

    return f"""
        <div class="rel-strip" style="margin-top:0;">
          <span class="rel-label">{_t("climate_bg", lang)}</span>
          <span class="rel-tag"><b>ONI {climate.oni_period}</b> {_fmt_signed_number(climate.oni_value, decimals=2)} ({climate.oni_phase})</span>
          <span style="color:#6b6a64;font-size:8pt;margin-left:8px;">{climate.narrative}</span>
        </div>"""


def _build_hedge_html(hedge, lang: str) -> str:
    """Render hedge advice card."""
    if not hedge:
        return ""

    return f"""
        <div class="card hedge-card">
          <div class="hedge-hdr">{_t("review_hedge", lang)}</div>
          <div class="hedge-body">
            <div class="hedge-ratio">{int(hedge.ratio * 100)}%</div>
            <div class="hedge-signal">{hedge.signal}</div>
            <div class="hedge-narrative">{hedge.narrative}</div>
          </div>
        </div>"""


def _build_china_import_html(report, lang: str) -> str:
    """Render China import cost & policy section（china_import 为 None 时整段不渲染）."""
    ci = getattr(report, "china_import", None)
    if ci is None:
        return ""

    b = ci.landed

    # ── 到库成本 ──
    cost_html = ""
    if b is not None:
        cost_html = f"""
          <div class="ci-cost">
            <div class="ci-cost-main">{_fmt_number(b.total_cost_cny_jin, decimals=2)}<span class="ci-cost-unit"> CNY/斤</span></div>
            <div class="ci-cost-sub">{_t("landed_total", lang)} · {_fmt_number(b.total_cost_usd_mt, decimals=0, suffix=" USD/MT")} · {_t("cyp_share", lang)} {_fmt_percent(b.cyp_fraction_pct, decimals=0, scale=100)} · {_t("current_hedge", lang)} {_fmt_percent(b.hedge_ratio_pct, decimals=0, scale=100)}</div>
          </div>"""

    # ── USD/CNY 汇率 ──
    fx_html = ""
    if ci.fx_rate is not None:
        fx_src = f" · {_html.escape(str(ci.fx_source))}" if ci.fx_source else ""
        fx_html = f"""
          <div class="ci-fx">USD/CNY <strong>{ci.fx_rate:.4f}</strong><span class="ci-fx-src">{fx_src}</span></div>"""

    # ── 政策事件 ──
    if ci.policy_events:
        items = ""
        for ev in ci.policy_events[:5]:
            sev = int(ev.get("severity", 1) or 1)
            color = "#1B365D" if sev >= 4 else "#504e49"
            narrative = _html.escape(str(ev.get("narrative", "")))
            items += (f"<li><span class='ci-sev' style='color:{color};border-color:{color};'>S{sev}</span>"
                      f"{narrative}</li>")
        events_html = f"""
          <div class="ci-events-title">{_t("policy_events", lang)}</div>
          <ul class="ci-events">{items}</ul>"""
    else:
        events_html = f"""
          <div class="ci-events-title">{_t("policy_events", lang)}</div>
          <div class="ci-empty">{_t("no_policy_events", lang)}</div>"""

    return f"""
<div class="section">
  <div class="section-title">{_t("china_import", lang)} <span>Import Cost &amp; Policy</span></div>
  <div class="card ci-card">
    <div class="ci-body">
      {cost_html}
      {fx_html}
      {events_html}
    </div>
  </div>
</div>"""


def _build_market_context(market, lang: str) -> dict[str, str]:
    """Compute hero and metric-strip display values."""
    if not market:
        return {
            "price_val": "N/A",
            "chg_val": "N/A",
            "chg_color": "#1B365D",
            "rsi_val": "N/A",
            "rsi_sub": "N/A",
            "ma20_val": "N/A",
            "ma20_sub": "N/A",
            "ma60_val": "N/A",
            "ma60_sub": "N/A",
            "high30_val": "N/A",
            "high30_sub": "N/A",
            "low30_val": "N/A",
            "low30_sub": "N/A",
            "volume_val": "N/A",
            "volume_sub": "N/A",
        }

    return {
        "price_val": _fmt_price(market.current),
        "chg_val": _fmt_percent(market.change_1d_pct, decimals=2, signed=True, scale=100),
        "chg_color": "#1B365D" if (market.change_1d_pct or 0) >= 0 else "#504e49",
        "rsi_val": _fmt_price(market.rsi_14, decimals=1),
        "rsi_sub": _t("overbought", lang) if (market.rsi_14 or 0) > 65 else _t("oversold", lang) if (market.rsi_14 or 0) < 40 else _t("neutral", lang),
        "ma20_val": _fmt_price(market.ma20),
        "ma20_sub": _t("below_price", lang) if market.current < (market.ma20 or market.current) else _t("above_price", lang),
        "ma60_val": _fmt_price(market.ma60),
        "ma60_sub": _t("below_price", lang) if market.current < (market.ma60 or market.current) else _t("above_price", lang),
        "high30_val": _fmt_price(market.high_30d),
        "high30_sub": f'{_t("distance", lang)} {_fmt_distance(market.high_30d - market.current)}' if market.high_30d and market.current else "N/A",
        "low30_val": _fmt_price(market.low_30d),
        "low30_sub": f'{_t("distance", lang)} {_fmt_distance(market.current - market.low_30d)}' if market.low_30d and market.current else "N/A",
        "volume_val": _fmt_number(market.volume_ratio, decimals=1, suffix="x"),
        "volume_sub": _t("high_volume", lang) if market.volume_ratio > 1.2 else _t("low_volume", lang) if market.volume_ratio < 0.8 else _t("normal_volume", lang),
    }


def _build_metrics_html(metric_ctx: dict[str, str], lang: str) -> str:
    """Render market metric strip."""
    metrics = [
        ("RSI (14)", metric_ctx["rsi_val"], metric_ctx["rsi_sub"]),
        ("MA20", metric_ctx["ma20_val"], metric_ctx["ma20_sub"]),
        ("MA60", metric_ctx["ma60_val"], metric_ctx["ma60_sub"]),
        (_t("high_30d", lang), metric_ctx["high30_val"], metric_ctx["high30_sub"]),
        (_t("low_30d", lang), metric_ctx["low30_val"], metric_ctx["low30_sub"]),
        (_t("volume_ratio", lang), metric_ctx["volume_val"], metric_ctx["volume_sub"]),
    ]
    rows = ""
    for label, value, sub in metrics:
        rows += f"""
      <div class="metric">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-sub">{sub}</div>
      </div>"""
    return rows


def build_report_html(report, lang: str = "zh") -> str:
    """Build HTML report in Kami editorial style (zh/en)."""

    m = report.market
    h = report.hedge_advice
    climate = report.climate
    market_ctx = _build_market_context(m, lang)
    metrics_html = _build_metrics_html(market_ctx, lang)

    # ── Scenarios ──
    scenario_rows = _build_scenario_rows(report, lang)

    # ── Levels ──
    support_rows = _build_level_rows(report.support_levels, color="#1B365D")
    resistance_rows = _build_level_rows(report.resistance_levels, color="#504e49")

    # ── Drivers ──
    bull_rows = _build_driver_rows(report.bullish_params)
    bear_rows = _build_driver_rows(report.bearish_params)

    # ── Risk warnings ──
    risk_items = _build_risk_items(report.risk_warnings)

    # ── ML ──
    ml_html = _build_ml_html(report.ml_snapshot, lang)

    # ── Prediction Review ──
    review_html = _build_review_html(report, m.current if m else None, lang)

    # ── Related markets ──
    related_html = _build_related_html(report.related_markets, lang)

    # ── Climate ──
    climate_html = _build_climate_html(climate, lang)

    # ── Hedge ──
    hedge_html = _build_hedge_html(h, lang)

    # ── China Import ──
    china_import_html = _build_china_import_html(report, lang)

    html_lang = "en" if lang == "en" else "zh-CN"
    body_font = "var(--serif)" if lang == "en" else "var(--sans)"

    html = f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_t("page_title", lang, date=report.report_date)}</title>
<style>
  @page {{
    size: A4;
    margin: 14mm 16mm;
    background: #f5f4ed;
  }}
  @media print {{
    body {{ background: #f5f4ed; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}

  :root {{
    --parchment: #f5f4ed;
    --ivory:     #faf9f5;
    --warm-sand: #e8e6dc;
    --brand:     #1B365D;
    --brand-light: #2D5A8A;
    --near-black:  #141413;
    --dark-warm:   #3d3d3a;
    --olive:       #504e49;
    --stone:       #6b6a64;
    --border:      #e8e6dc;
    --border-soft: #e5e3d8;
    --serif: Charter, Georgia, "TsangerJinKai02", "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", Palatino, serif;
    --sans:  ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
    --mono:  "SF Mono", Monaco, Consolas, monospace;
  }}

  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    background: var(--parchment);
    color: var(--near-black);
    font-family: {body_font};
    font-size: 9.5pt;
    line-height: 1.62;
    letter-spacing: 0.12px;
    -webkit-font-smoothing: antialiased;
  }}

  .page {{
    max-width: 188mm;
    margin: 0 auto;
    padding: 9mm 10mm 11mm;
  }}

  /* ── Header ── */
  .hero {{
    border-bottom: 1px solid var(--border-soft);
    padding-bottom: 4.5mm;
    margin-bottom: 3.5mm;
  }}
  .hero-eyebrow {{
    font-family: var(--sans);
    font-size: 6.4pt;
    font-weight: 500;
    letter-spacing: 0.9px;
    text-transform: uppercase;
    color: var(--stone);
    margin-bottom: 1.6mm;
  }}
  .hero-main {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 10mm;
  }}
  .hero-title {{
    font-family: var(--serif);
    font-size: 21pt;
    font-weight: 600;
    line-height: 1.08;
    color: var(--near-black);
    margin: 0;
    letter-spacing: 0;
  }}
  .hero-sub {{
    font-family: var(--sans);
    font-size: 8pt;
    color: var(--olive);
    margin-top: 2mm;
    letter-spacing: 0.08px;
    max-width: 96mm;
  }}
  .hero-price {{
    text-align: right;
    flex-shrink: 0;
    min-width: 33mm;
  }}
  .hero-price-ticker {{
    font-family: var(--sans);
    font-size: 6.8pt;
    color: var(--stone);
    letter-spacing: 0.7px;
  }}
  .hero-price-val {{
    font-family: var(--serif);
    font-size: 22pt;
    font-weight: 600;
    color: var(--near-black);
    line-height: 1;
    margin: 0.8mm 0 0.6mm;
  }}
  .hero-price-unit {{
    font-family: var(--sans);
    font-size: 6.8pt;
    color: var(--stone);
  }}
  .hero-price-chg {{
    font-family: var(--sans);
    font-size: 7.8pt;
    margin-top: 0.8mm;
  }}

  /* ── Section ── */
  .section {{
    margin-bottom: 4.2mm;
    page-break-inside: auto;
  }}
  .section-title {{
    font-family: var(--serif);
    font-size: 13pt;
    font-weight: 600;
    color: var(--near-black);
    border-bottom: 1px solid var(--border-soft);
    padding-bottom: 1.4mm;
    margin-bottom: 2.2mm;
    letter-spacing: 0.08px;
  }}
  .section-title span {{
    font-family: var(--sans);
    font-size: 6.7pt;
    font-weight: 500;
    color: var(--stone);
    margin-left: 2.2mm;
    letter-spacing: 0.35px;
    text-transform: uppercase;
  }}

  /* ── Card ── */
  .card {{
    background: transparent;
    border: 0;
    border-radius: 0;
    margin-bottom: 2.2mm;
    page-break-inside: avoid;
  }}
  .card-hdr {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 0 1.2mm;
    border-bottom: 1px solid var(--border-soft);
    font-family: var(--sans);
    font-size: 7pt;
    font-weight: 500;
    color: var(--dark-warm);
    letter-spacing: 0.2px;
  }}
  .card-tag {{
    font-size: 6.6pt;
    font-weight: 500;
    padding: 0;
    border-radius: 0;
    background: transparent;
    color: var(--stone);
  }}

  /* ── Metrics Grid ── */
  .metrics-strip {{
    border-top: 1px solid var(--border-soft);
    border-bottom: 1px solid var(--border-soft);
    margin-bottom: 2.6mm;
  }}
  .metrics {{
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 0;
    padding: 2.2mm 0;
  }}
  .metric {{
    text-align: left;
    padding: 0.4mm 2.4mm;
    border-right: 1px solid var(--border);
  }}
  .metric:last-child {{
    border-right: 0;
  }}
  .metric-label {{
    font-family: var(--sans);
    font-size: 6.3pt;
    color: var(--stone);
    letter-spacing: 0.4px;
    text-transform: uppercase;
    margin-bottom: 0.8mm;
  }}
  .metric-value {{
    font-family: var(--serif);
    font-size: 12.2pt;
    font-weight: 600;
    color: var(--brand);
    line-height: 1.05;
  }}
  .metric-sub {{
    font-family: var(--sans);
    font-size: 6.2pt;
    color: var(--stone);
    margin-top: 0.55mm;
  }}

  /* ── Figure ── */
  .figure-chart {{
    border-top: 1px solid var(--border-soft);
    border-bottom: 1px solid var(--border-soft);
    padding: 2mm 0 1mm;
  }}
  .figure-caption {{
    font-family: var(--sans);
    font-size: 6.5pt;
    line-height: 1.45;
    color: var(--stone);
    margin-top: 1.2mm;
    text-align: center;
  }}

  /* ── Scenarios ── */
  .scenarios {{
    display: flex;
    gap: 2mm;
    margin-bottom: 2mm;
  }}
  .sc-card {{
    flex: 1;
    background: #f7f6f1;
    border: 1px solid var(--border-soft);
    border-radius: 3px;
    padding: 2.4mm;
    page-break-inside: avoid;
  }}
  .sc-hdr {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5mm;
  }}
  .sc-label {{
    font-family: var(--sans);
    font-size: 7pt;
    font-weight: 500;
    letter-spacing: 0.18px;
  }}
  .sc-prob {{
    font-family: var(--serif);
    font-size: 11pt;
    font-weight: 600;
    color: var(--near-black);
  }}
  .sc-range {{
    font-family: var(--serif);
    font-size: 10pt;
    font-weight: 600;
    color: var(--near-black);
    margin: 1mm 0;
  }}
  .sc-unit {{
    font-family: var(--sans);
    font-size: 7pt;
    color: var(--stone);
    font-weight: 400;
  }}
  .sc-dir {{
    font-family: var(--sans);
    font-size: 7.5pt;
    margin-bottom: 1.5mm;
  }}
  .sc-rationale p {{
    margin: 0 0 1mm 0;
    font-size: 6.9pt;
    color: var(--stone);
    line-height: 1.45;
  }}

  /* ── Hedge ── */
  .hedge-card {{
    background: #f7f6f1;
    border: 1px solid var(--border-soft);
    border-radius: 3px;
  }}
  .hedge-hdr {{
    padding: 1.8mm 2.4mm;
    font-family: var(--sans);
    font-size: 7pt;
    font-weight: 500;
    color: var(--dark-warm);
    letter-spacing: 0.2px;
    border-bottom: 1px solid var(--border-soft);
  }}
  .hedge-body {{
    padding: 2.4mm;
    display: flex;
    align-items: center;
    gap: 4mm;
  }}
  .hedge-ratio {{
    font-family: var(--serif);
    font-size: 19pt;
    font-weight: 600;
    color: var(--near-black);
    line-height: 1;
  }}
  .hedge-signal {{
    font-family: var(--sans);
    font-size: 8pt;
    font-weight: 500;
    color: var(--dark-warm);
  }}
  .hedge-narrative {{
    flex: 1;
    font-size: 7pt;
    color: var(--olive);
    line-height: 1.55;
  }}

  /* ── Levels ── */
  .levels {{
    width: 100%;
    border-collapse: collapse;
    font-size: 8pt;
  }}
  .levels th {{
    font-family: var(--sans);
    font-size: 6.4pt;
    font-weight: 500;
    letter-spacing: 0.3px;
    color: var(--stone);
    text-align: left;
    padding: 1.4mm 1.8mm;
    border-bottom: 1px solid var(--border-soft);
  }}
  .levels td {{
    padding: 1.25mm 1.8mm;
    border-bottom: 1px solid var(--border);
  }}
  .lv-price {{
    font-family: var(--serif);
    font-weight: 600;
    font-size: 9pt;
    width: 22mm;
    color: var(--near-black);
  }}
  .lv-label {{
    color: var(--stone);
    font-size: 7.2pt;
  }}

  /* ── Drivers ── */
  .drivers {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2mm;
  }}
  .drv-card {{
    background: #f7f6f1;
    border: 1px solid var(--border-soft);
    border-radius: 3px;
    page-break-inside: avoid;
  }}
  .drv-hdr {{
    padding: 1.8mm 2.4mm;
    font-family: var(--sans);
    font-size: 7pt;
    font-weight: 500;
    letter-spacing: 0.2px;
    color: var(--near-black);
    border-bottom: 1px solid var(--border-soft);
  }}
  .drv-hdr.bull {{ color: #1B365D; }}
  .drv-hdr.bear {{ color: #504e49; }}
  .drv-body {{
    padding: 2.2mm 2.4mm;
  }}
  .drv-body ul {{
    margin: 0;
    padding-left: 4mm;
    list-style: none;
  }}
  .drv-body li {{
    margin-bottom: 1.2mm;
    font-size: 7pt;
    line-height: 1.5;
    color: var(--dark-warm);
    position: relative;
    padding-left: 2.5mm;
  }}
  .drv-body li::before {{
    content: "·";
    position: absolute;
    left: -2mm;
    color: var(--stone);
  }}
  .drv-body li strong {{
    color: var(--near-black);
    font-weight: 500;
  }}

  /* ── ML ── */
  .ml-body {{ padding: 2.2mm 0 0; }}
  .ml-signal {{
    display: flex;
    align-items: baseline;
    gap: 2mm;
    margin-bottom: 1.5mm;
  }}
  .ml-sig-label {{
    font-family: var(--serif);
    font-size: 12pt;
    font-weight: 600;
  }}
  .ml-confidence {{
    font-family: var(--sans);
    font-size: 7pt;
    color: var(--stone);
  }}
  .ml-target, .ml-bias {{
    font-size: 7.1pt;
    color: var(--olive);
    margin: 1mm 0;
  }}
  .ml-perf {{
    font-size: 7pt;
    color: var(--stone);
    margin: 1.5mm 0;
    padding: 1.2mm 1.4mm;
    background: #f7f6f1;
    border: 1px solid var(--border-soft);
    border-radius: 3px;
  }}
  .ml-rationale {{
    margin: 1.5mm 0 0 0;
    padding-left: 4mm;
    font-size: 6.9pt;
    color: var(--stone);
  }}
  .ml-rationale li {{ margin-bottom: 0.5mm; }}
  .ml-features {{ margin-top: 2mm; }}
  .ml-features-title {{
    font-family: var(--sans);
    font-size: 6.8pt;
    font-weight: 500;
    color: var(--dark-warm);
    margin-bottom: 1mm;
  }}
  .fi-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 6.8pt;
  }}
  .fi-table td {{
    padding: 0.75mm 1.2mm;
    border-bottom: 1px solid var(--border);
  }}
  .fi-name {{ width: 40%; color: var(--dark-warm); }}
  .fi-bar-cell {{ width: 45%; }}
  .fi-val {{ width: 15%; text-align: right; color: var(--stone); }}
  .fi-bar {{
    background: var(--border);
    border-radius: 4px;
    height: 3mm;
    overflow: hidden;
  }}
  .fi-fill {{
    background: var(--brand);
    height: 100%;
    border-radius: 4px;
  }}

  /* ── Review ── */
  .review-body {{
    padding: 2.2mm 0 0;
    font-size: 7pt;
    color: var(--dark-warm);
    line-height: 1.55;
  }}
  .review-body p {{
    margin: 0 0 1mm 0;
  }}
  .review-body ul {{
    margin: 1mm 0;
    padding-left: 4mm;
  }}
  .review-body li {{
    margin-bottom: 0.5mm;
  }}
  .review-note {{
    font-style: italic;
    color: var(--stone);
    margin-top: 1.5mm !important;
    padding-top: 1.5mm;
    border-top: 1px solid var(--border);
  }}

  /* ── Driver Attribution ── */
  .attr-block {{
    margin-top: 1.8mm;
    padding-top: 1.5mm;
    border-top: 1px solid var(--border);
  }}
  .attr-title {{
    font-family: var(--sans);
    font-size: 6.9pt;
    font-weight: 500;
    color: var(--dark-warm);
    letter-spacing: 0.2px;
    margin-bottom: 1mm;
  }}
  .attr-list {{
    margin: 0;
    padding-left: 0;
    list-style: none;
    font-size: 6.9pt;
    color: var(--dark-warm);
  }}
  .attr-list li {{
    margin-bottom: 0.6mm;
    line-height: 1.5;
  }}
  .attr-icon {{
    display: inline-block;
    width: 3.5mm;
    font-weight: 600;
  }}
  .attr-weight {{
    font-size: 6.2pt;
    color: var(--stone);
    margin-left: 1mm;
  }}
  .attr-summary {{
    font-size: 6.8pt;
    color: var(--stone);
    margin-top: 1mm;
  }}
  .attr-empty {{
    font-size: 6.9pt;
    color: var(--stone);
  }}

  /* ── Related / Climate strip ── */
  .rel-strip {{
    display: flex;
    align-items: center;
    gap: 1.6mm;
    flex-wrap: wrap;
    padding: 1.3mm 0;
    border-bottom: 1px solid var(--border-soft);
    margin-bottom: 2.2mm;
  }}
  .rel-label {{
    font-family: var(--sans);
    font-size: 6.3pt;
    font-weight: 500;
    letter-spacing: 0.35px;
    text-transform: uppercase;
    color: var(--stone);
    margin-right: 1.6mm;
  }}
  .rel-tag {{
    font-size: 6.8pt;
    font-family: var(--sans);
  }}

  /* ── Outlook ── */
  .outlook-box {{
    background: #f7f6f1;
    border: 1px solid var(--border-soft);
    border-radius: 3px;
    padding: 2.8mm 3mm;
    font-size: 7.3pt;
    line-height: 1.6;
    color: var(--dark-warm);
    page-break-inside: avoid;
  }}
  .risk-box {{
    margin-top: 1.8mm;
    padding: 2.2mm 2.4mm;
    background: #f7f6f1;
    border: 1px solid var(--border-soft);
    border-radius: 3px;
  }}
  .risk-title {{
    font-family: var(--sans);
    font-size: 6.9pt;
    font-weight: 500;
    color: var(--dark-warm);
    margin-bottom: 0.8mm;
    letter-spacing: 0.2px;
    padding-bottom: 0.8mm;
    border-bottom: 1px solid var(--border-soft);
  }}
  .risk-box ul {{
    margin: 0;
    padding-left: 4mm;
    font-size: 6.9pt;
    color: var(--olive);
  }}
  .risk-box li {{ margin-bottom: 1mm; }}

  /* ── China Import ── */
  .ci-card {{
    background: #f7f6f1;
    border: 1px solid var(--border-soft);
    border-radius: 3px;
    page-break-inside: avoid;
  }}
  .ci-body {{
    padding: 2.4mm;
  }}
  .ci-cost-main {{
    font-family: var(--serif);
    font-size: 19pt;
    font-weight: 600;
    color: var(--near-black);
    line-height: 1;
  }}
  .ci-cost-unit {{
    font-family: var(--sans);
    font-size: 7.5pt;
    font-weight: 400;
    color: var(--stone);
  }}
  .ci-cost-sub {{
    font-family: var(--sans);
    font-size: 7pt;
    color: var(--olive);
    margin-top: 1mm;
  }}
  .ci-fx {{
    font-family: var(--sans);
    font-size: 7.5pt;
    color: var(--dark-warm);
    margin-top: 1.6mm;
  }}
  .ci-fx-src {{
    color: var(--stone);
    font-size: 6.5pt;
  }}
  .ci-events-title {{
    font-family: var(--sans);
    font-size: 6.9pt;
    font-weight: 500;
    color: var(--dark-warm);
    letter-spacing: 0.2px;
    margin-top: 2mm;
    padding-bottom: 0.8mm;
    border-bottom: 1px solid var(--border-soft);
  }}
  .ci-events {{
    margin: 0;
    padding-left: 0;
    list-style: none;
    font-size: 7pt;
    color: var(--dark-warm);
  }}
  .ci-events li {{
    margin-top: 1mm;
    line-height: 1.5;
  }}
  .ci-sev {{
    display: inline-block;
    font-family: var(--sans);
    font-size: 6.2pt;
    font-weight: 600;
    border: 1px solid var(--stone);
    border-radius: 2px;
    padding: 0 1mm;
    margin-right: 1.6mm;
    color: var(--stone);
  }}
  .ci-empty {{
    font-size: 7pt;
    color: var(--stone);
    margin-top: 1mm;
  }}

  /* ── Footer ── */
  .footer {{
    border-top: 1px solid var(--border-soft);
    padding-top: 2.4mm;
    margin-top: 4.5mm;
    text-align: center;
  }}
  .footer-source {{
    font-family: var(--sans);
    font-size: 6.1pt;
    color: var(--stone);
    margin-bottom: 0.8mm;
  }}
  .footer-legal {{
    font-size: 6.1pt;
    color: var(--stone);
    opacity: 0.8;
  }}
</style>
</head>
<body>
<div class="page">

<!-- ══ Header ══ -->
<div class="hero">
  <div class="hero-eyebrow">Weekly Futures Outlook &nbsp;·&nbsp; {report.report_date} &nbsp;·&nbsp; {report.ticker}</div>
  <div class="hero-main">
    <div>
      <div class="hero-title">{_t("report_title", lang)}</div>
      <div class="hero-sub">{_t("forecast_range", lang)} {report.forecast_week_start} – {report.forecast_week_end} &nbsp;|&nbsp; {_t("contract", lang)} KC=F (Coffee Sep 26)</div>
    </div>
    <div class="hero-price">
      <div class="hero-price-ticker">KC=F</div>
      <div class="hero-price-val">{market_ctx['price_val']}</div>
      <div class="hero-price-unit">US¢/lb</div>
      <div class="hero-price-chg" style="color:{market_ctx['chg_color']}">{market_ctx['chg_val']}</div>
    </div>
  </div>
</div>

{related_html}
{climate_html}

<!-- ══ Market Snapshot ══ -->
<div class="section">
  <div class="section-title">{_t("market_snapshot", lang)} <span>Market Snapshot</span></div>
  <div class="metrics-strip">
    <div class="metrics">
{metrics_html}
    </div>
  </div>
  {_build_price_chart(report, lang=lang)}
  <div class="figure-caption">{_t("figure_price_caption", lang)}</div>
</div>

<!-- ══ Prediction Review ══ -->
{review_html}

<!-- ══ ML Prediction ══ -->
<div class="section">
  <div class="section-title">{_t("ml_prediction", lang)} <span>ML Prediction</span></div>
  {ml_html}
</div>

<!-- ══ Scenarios ══ -->
<div class="section">
  <div class="section-title">{_t("scenario_analysis", lang)} <span>Scenario Analysis</span></div>
  <div class="scenarios">
    {scenario_rows}
  </div>
  {hedge_html}
</div>

<!-- ══ Key Levels ══ -->
<div class="section">
  <div class="section-title">{_t("key_levels", lang)} <span>Key Levels</span></div>
  <div class="card">
    <table class="levels">
      <thead>
        <tr>
          <th style="width:22mm;">{_t("support", lang)}</th>
          <th></th>
          <th style="width:22mm;">{_t("resistance", lang)}</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td class="lv-price">{(report.support_levels or [None])[0].price if (report.support_levels or []) else 'N/A'}</td>
          <td class="lv-label">{(report.support_levels or [None])[0].label if (report.support_levels or []) else ''}</td>
          <td class="lv-price">{(report.resistance_levels or [None])[0].price if (report.resistance_levels or []) else 'N/A'}</td>
          <td class="lv-label">{(report.resistance_levels or [None])[0].label if (report.resistance_levels or []) else ''}</td>
        </tr>
        <tr>
          <td class="lv-price">{(report.support_levels or [None])[1].price if len(report.support_levels or [])>1 else ''}</td>
          <td class="lv-label">{(report.support_levels or [None])[1].label if len(report.support_levels or [])>1 else ''}</td>
          <td class="lv-price">{(report.resistance_levels or [None])[1].price if len(report.resistance_levels or [])>1 else ''}</td>
          <td class="lv-label">{(report.resistance_levels or [None])[1].label if len(report.resistance_levels or [])>1 else ''}</td>
        </tr>
        <tr>
          <td class="lv-price">{(report.support_levels or [None])[2].price if len(report.support_levels or [])>2 else ''}</td>
          <td class="lv-label">{(report.support_levels or [None])[2].label if len(report.support_levels or [])>2 else ''}</td>
          <td class="lv-price">{(report.resistance_levels or [None])[2].price if len(report.resistance_levels or [])>2 else ''}</td>
          <td class="lv-label">{(report.resistance_levels or [None])[2].label if len(report.resistance_levels or [])>2 else ''}</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ══ Drivers ══ -->
<div class="section">
  <div class="section-title">{_t("market_drivers", lang)} <span>Market Drivers</span></div>
  <div class="drivers">
    <div class="drv-card bull">
      <div class="drv-hdr bull">{_t("bullish_factors", lang)}</div>
      <div class="drv-body"><ul>{bull_rows or f'<li>{_t("no_bullish", lang)}</li>'}</ul></div>
    </div>
    <div class="drv-card bear">
      <div class="drv-hdr bear">{_t("bearish_factors", lang)}</div>
      <div class="drv-body"><ul>{bear_rows or f'<li>{_t("no_bearish", lang)}</li>'}</ul></div>
    </div>
  </div>
</div>

<!-- ══ Import Cost & Policy ══ -->
{china_import_html}

<!-- ══ Outlook ══ -->
<div class="section">
  <div class="section-title">{_t("market_outlook", lang)} <span>Market Outlook</span></div>
  <div class="outlook-box">{report.outlook or _t("no_outlook", lang)}</div>
  {f'''
  <div class="risk-box">
    <div class="risk-title">{_t("risk_warnings", lang)}</div>
    <ul>{risk_items}</ul>
  </div>''' if report.risk_warnings else ''}
</div>

<!-- ══ Footer ══ -->
<div class="footer">
  <div class="footer-source">{_t("data_sources", lang)}: Yahoo Finance (~15min delayed) · NOAA CPC · CFTC · ML(Internal Ensemble)</div>
  <div class="footer-legal">{_t("disclaimer", lang)} {_t("generated_by", lang)}</div>
</div>

</div>
</body>
</html>"""

    return html
