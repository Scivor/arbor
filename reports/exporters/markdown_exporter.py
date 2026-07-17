"""
reports/exporters/markdown_exporter.py
Markdown 导出 — 公众号/文档友好的纯文本报告

结构与 PredictionReport.to_text() 一致：None 字段对应小节整块跳过。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reports.pipeline import Report


# ── i18n ─────────────────────────────────────────────────────────────────────

_T = {
    "title": {"zh": "Arbor 咖啡期货周报", "en": "Arbor Coffee Futures Weekly"},
    "forecast_range": {"zh": "预测区间", "en": "Forecast"},
    "contract": {"zh": "合约", "en": "Contract"},
    "market_snapshot": {"zh": "市场快照", "en": "Market Snapshot"},
    "related_markets": {"zh": "关联市场", "en": "Related Markets"},
    "climate_bg": {"zh": "气候背景", "en": "Climate"},
    "key_levels": {"zh": "关键价位", "en": "Key Levels"},
    "scenario_analysis": {"zh": "情景分析", "en": "Scenario Analysis"},
    "market_drivers": {"zh": "多空驱动", "en": "Market Drivers"},
    "ml_prediction": {"zh": "ML 模型预测", "en": "ML Prediction"},
    "hedge_advice": {"zh": "套保建议", "en": "Hedge Advice"},
    "china_import": {"zh": "进口成本与政策", "en": "Import Cost & Policy"},
    "outlook": {"zh": "核心观点", "en": "Outlook"},
    "risk_warnings": {"zh": "风险提示", "en": "Risk Warnings"},
    "policy_events": {"zh": "政策事件", "en": "Policy Events"},
    "no_policy_events": {"zh": "近 7 日无显著政策事件", "en": "No significant policy events in the past 7 days"},
    "support": {"zh": "支撑", "en": "Support"},
    "resistance": {"zh": "阻力", "en": "Resistance"},
    "bullish": {"zh": "看涨", "en": "Bullish"},
    "bearish": {"zh": "看跌", "en": "Bearish"},
    "disclaimer": {
        "zh": "本报告仅为研究信息，不构成投资建议",
        "en": "For research information only. Not investment advice.",
    },
}


def _t(key: str, lang: str) -> str:
    return _T.get(key, {}).get(lang, key)


# ── 小节 builders ─────────────────────────────────────────────────────────────

def _md_market(report: "Report", lang: str) -> list[str]:
    m = report.market
    if not m:
        return []
    change_1d = f"{m.change_1d_pct:+.1f}%" if m.change_1d_pct is not None else "N/A"
    change_30d = f"{m.change_30d_pct:+.1f}%" if m.change_30d_pct is not None else "N/A"
    return [
        f"## {_t('market_snapshot', lang)}",
        "",
        "| 指标 | 数值 | 指标 | 数值 |",
        "|---|---|---|---|",
        f"| 现价 | {m.current:.2f} ¢/lb | RSI (14) | {m.rsi_14:.1f} |",
        f"| 日涨跌 | {change_1d} | MA20 | {m.ma20:.2f} |",
        f"| 30日涨跌 | {change_30d} | MA60 | {m.ma60:.2f} |",
        f"| 30日区间 | {m.low_30d:.2f} – {m.high_30d:.2f} | 量比 | {m.volume_ratio:.1f}x |",
        "",
    ]


def _md_related(report: "Report", lang: str) -> list[str]:
    if not report.related_markets:
        return []
    lines = [f"## {_t('related_markets', lang)}", "", "| 市场 | 涨跌 |", "|---|---|"]
    for name, chg in report.related_markets.items():
        lines.append(f"| {name} | {chg:+.1f}% |")
    lines.append("")
    return lines


def _md_climate(report: "Report", lang: str) -> list[str]:
    c = report.climate
    if not c:
        return []
    return [
        f"## {_t('climate_bg', lang)}",
        "",
        f"ONI ({c.oni_period}): **{c.oni_value:+.2f}** ({c.oni_phase})",
        "",
        c.narrative,
        "",
    ]


def _md_levels(report: "Report", lang: str) -> list[str]:
    if not report.resistance_levels and not report.support_levels:
        return []
    lines = [f"## {_t('key_levels', lang)}", ""]
    if report.support_levels:
        lines += [f"**{_t('support', lang)}**", "", "| 价位 | 标签 |", "|---|---|"]
        for l in report.support_levels:
            lines.append(f"| {l.price:.2f} | {l.label} |")
        lines.append("")
    if report.resistance_levels:
        lines += [f"**{_t('resistance', lang)}**", "", "| 价位 | 标签 |", "|---|---|"]
        for l in report.resistance_levels:
            lines.append(f"| {l.price:.2f} | {l.label} |")
        lines.append("")
    return lines


def _md_scenarios(report: "Report", lang: str) -> list[str]:
    if not report.scenarios:
        return []
    lines = [
        f"## {_t('scenario_analysis', lang)}",
        "",
        "| 情景 | 方向 | 区间 | 概率 | 主要依据 |",
        "|---|---|---|---|---|",
    ]
    for s in report.scenarios:
        rationale = s.rationale[0] if s.rationale else ""
        lines.append(f"| {s.label} | {s.direction} | {s.price_min:.0f} – {s.price_max:.0f} | {s.probability:.0%} | {rationale} |")
    lines.append("")
    return lines


def _md_drivers(report: "Report", lang: str) -> list[str]:
    if not report.bullish_params and not report.bearish_params:
        return []
    lines = [f"## {_t('market_drivers', lang)}", ""]
    if report.bullish_params:
        lines.append(f"**▲ {_t('bullish', lang)}**")
        lines.append("")
        for p in report.bullish_params:
            lines.append(f"- **{p.param_name}**（{p.current_value}）— {p.narrative}")
        lines.append("")
    if report.bearish_params:
        lines.append(f"**▼ {_t('bearish', lang)}**")
        lines.append("")
        for p in report.bearish_params:
            lines.append(f"- **{p.param_name}**（{p.current_value}）— {p.narrative}")
        lines.append("")
    return lines


def _md_ml(report: "Report", lang: str) -> list[str]:
    ml = report.ml_snapshot
    if not ml:
        return []
    lines = [
        f"## {_t('ml_prediction', lang)}",
        "",
        f"- 信号: **{ml.signal}**（置信度 {ml.confidence:.0%}，模型 {ml.model_type}）",
    ]
    if ml.price_target_30d:
        lines.append(f"- 30日价格目标: {ml.price_target_30d:.2f} ¢/lb")
    lines.append(f"- 套保比率调整: {ml.bias:+.0%}")
    perf = []
    if ml.model_accuracy is not None:
        perf.append(f"方向准确率 {ml.model_accuracy:.1%}")
    if ml.model_mae is not None:
        perf.append(f"收益MAE {ml.model_mae:.2%}")
    if perf:
        lines.append(f"- 模型表现: {' | '.join(perf)}")
    for r in ml.rationale:
        lines.append(f"- {r}")
    lines.append("")
    return lines


def _md_hedge(report: "Report", lang: str) -> list[str]:
    h = report.hedge_advice
    if not h:
        return []
    lines = [
        f"## {_t('hedge_advice', lang)}",
        "",
        f"**{h.ratio:.0%}** · {h.signal}",
        "",
        h.narrative,
        "",
    ]
    if h.trigger_below:
        lines.append(f"- ↓ 跌破 {h.trigger_below:.0f} → 提高套保至 75-80%")
    if h.trigger_above:
        lines.append(f"- ↑ 突破 {h.trigger_above:.0f} → 降低套保至 50%")
    if h.trigger_below or h.trigger_above:
        lines.append("")
    return lines


def _md_china_import(report: "Report", lang: str) -> list[str]:
    ci = getattr(report, "china_import", None)
    if ci is None:
        return []
    lines = [f"## {_t('china_import', lang)}", ""]
    if ci.fx_rate is not None:
        fx_src = f"（{ci.fx_source}）" if ci.fx_source else ""
        lines.append(f"- USD/CNY: {ci.fx_rate:.4f}{fx_src}")
    if ci.landed:
        b = ci.landed
        lines.append(f"- **到库成本: {b.total_cost_cny_jin:.2f} CNY/斤**（{b.total_cost_usd_mt:.0f} USD/MT）")
        lines.append(f"- CYP 占比: {b.cyp_fraction_pct:.0%} | 当前套保比率: {b.hedge_ratio_pct:.0%}")
    lines.append("")
    if ci.policy_events:
        lines.append(f"**{_t('policy_events', lang)}**")
        lines.append("")
        for ev in ci.policy_events[:5]:
            lines.append(f"- [S{int(ev.get('severity', 0))}] {ev.get('narrative', '')}")
    else:
        lines.append(_t("no_policy_events", lang))
    lines.append("")
    return lines


def _md_outlook(report: "Report", lang: str) -> list[str]:
    lines = [f"## {_t('outlook', lang)}", ""]
    if report.outlook:
        lines += [report.outlook, ""]
    if report.risk_warnings:
        lines += [f"**⚠ {_t('risk_warnings', lang)}**", ""]
        for rw in report.risk_warnings:
            lines.append(f"- {rw}")
        lines.append("")
    return lines


# ── 主入口 ────────────────────────────────────────────────────────────────────

def export_markdown(report: "Report", lang: str = "zh") -> str:
    """
    导出 Markdown 格式报告（公众号友好）。

    Args:
        report: PredictionReport from reports.pipeline.
        lang:   'zh' | 'en'

    Returns:
        Markdown 字符串。
    """
    lines = [
        f"# {_t('title', lang)} · {report.report_date.strftime('%Y-%m-%d')}",
        "",
        f"**{_t('forecast_range', lang)}**: {report.forecast_week_start} – {report.forecast_week_end}  |  "
        f"**{_t('contract', lang)}**: {report.ticker}",
        "",
    ]

    lines += _md_market(report, lang)
    lines += _md_related(report, lang)
    lines += _md_climate(report, lang)
    lines += _md_levels(report, lang)
    lines += _md_scenarios(report, lang)
    lines += _md_drivers(report, lang)
    lines += _md_ml(report, lang)
    lines += _md_hedge(report, lang)
    lines += _md_china_import(report, lang)
    lines += _md_outlook(report, lang)

    # ── 页脚 ──
    lines += [
        "---",
        "",
        f"*生成时间: {report.generated_at.strftime('%Y-%m-%d %H:%M')} · {_t('disclaimer', lang)}*",
        "",
    ]
    return "\n".join(lines)
