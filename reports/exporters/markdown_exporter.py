"""
reports/exporters/markdown_exporter.py
Markdown 导出 — 公众号/文档友好的纯文本报告（全双语 zh/en）

结构与 PredictionReport.to_text() 一致：None 字段对应小节整块跳过。
所有用户可见字符串走 _T 词典；英文翻译与 html_to_pdf.py 的 _t 术语保持一致。
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
    "ai_commentary": {"zh": "AI 分析师点评", "en": "AI Analyst Commentary"},
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
    # ── 字段标签（全双语化的硬编码迁移）──
    "md_metric": {"zh": "指标", "en": "Metric"},
    "md_value": {"zh": "数值", "en": "Value"},
    "md_price": {"zh": "现价", "en": "Price"},
    "md_chg_1d": {"zh": "日涨跌", "en": "1D Chg"},
    "md_chg_30d": {"zh": "30日涨跌", "en": "30D Chg"},
    "md_range_30d": {"zh": "30日区间", "en": "30D Range"},
    "md_vol_ratio": {"zh": "量比", "en": "Vol Ratio"},
    "md_market_col": {"zh": "市场", "en": "Market"},
    "md_chg_col": {"zh": "涨跌", "en": "Chg"},
    "md_price_col": {"zh": "价位", "en": "Price"},
    "md_label_col": {"zh": "标签", "en": "Label"},
    "md_scenario_col": {"zh": "情景", "en": "Scenario"},
    "direction": {"zh": "方向", "en": "Direction"},
    "md_range_col": {"zh": "区间", "en": "Range"},
    "md_prob_col": {"zh": "概率", "en": "Prob"},
    "md_rationale_col": {"zh": "主要依据", "en": "Key Rationale"},
    "ref_class_line": {
        "zh": "参考类: 近 {years} 年相似行情 {n} 周，涨 {up} / 横 {flat} / 跌 {down}",
        "en": "Reference class: {n} similar weeks in {years}y — up {up} / flat {flat} / down {down}",
    },
    "ref_class_thin": {"zh": "（样本稀薄，仅供参考）", "en": " (thin sample, for reference only)"},
    "ml_signal": {"zh": "信号", "en": "Signal"},
    "ml_conf": {"zh": "置信度", "en": "Confidence"},
    "ml_model": {"zh": "模型", "en": "Model"},
    "ml_target": {"zh": "30日价格目标", "en": "30-Day Price Target"},
    "ml_bias": {"zh": "套保比率调整", "en": "Hedge Ratio Adj"},
    "ml_perf": {"zh": "模型表现", "en": "Model Performance"},
    "ml_accuracy": {"zh": "方向准确率", "en": "Direction Accuracy"},
    "ml_mae": {"zh": "收益MAE", "en": "Return MAE"},
    "trigger_below": {
        "zh": "↓ 跌破 {x} → 提高套保至 75-80%",
        "en": "↓ Break {x} → increase hedge to 75-80%",
    },
    "trigger_above": {
        "zh": "↑ 突破 {x} → 降低套保至 50%",
        "en": "↑ Break {x} → reduce hedge to 50%",
    },
    "kelly_active": {
        "zh": "凯利视角: 建议 {s}（edge {e}）vs 当前建议 {c}",
        "en": "Kelly view: suggests {s} (edge {e}) vs current {c}",
    },
    "kelly_inactive": {"zh": "凯利视角: {reason}", "en": "Kelly view: {reason}"},
    "landed_total": {"zh": "到库成本", "en": "Landed Cost"},
    "cyp_share": {"zh": "CYP 占比", "en": "CYP Share"},
    "current_hedge": {"zh": "当前套保比率", "en": "Current Hedge"},
    "ico_line": {
        "zh": "ICO 综合现货 {icip} ¢/lb（月均 {avg}，日变动 {dod}）",
        "en": "ICO composite spot {icip} ¢/lb (month avg {avg}, DoD {dod})",
    },
    "gfex_line": {
        "zh": "广期所咖啡 {close} 元/吨，内外盘价差 {spread} 元/吨（{pct}）",
        "en": "GFEX coffee {close} CNY/MT, spread vs KC {spread} CNY/MT ({pct})",
    },
    "generated_at": {"zh": "生成时间", "en": "Generated"},
    "zh_tag": {"zh": "", "en": "（中文）"},  # en 模式下中文内容的标注
}


def _t(key: str, lang: str, **kwargs) -> str:
    text = _T.get(key, {}).get(lang, key)
    if kwargs:
        text = text.format(**kwargs)
    return text


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
        f"| {_t('md_metric', lang)} | {_t('md_value', lang)} | {_t('md_metric', lang)} | {_t('md_value', lang)} |",
        "|---|---|---|---|",
        f"| {_t('md_price', lang)} | {m.current:.2f} ¢/lb | RSI (14) | {m.rsi_14:.1f} |",
        f"| {_t('md_chg_1d', lang)} | {change_1d} | MA20 | {m.ma20:.2f} |",
        f"| {_t('md_chg_30d', lang)} | {change_30d} | MA60 | {m.ma60:.2f} |",
        f"| {_t('md_range_30d', lang)} | {m.low_30d:.2f} – {m.high_30d:.2f} | {_t('md_vol_ratio', lang)} | {m.volume_ratio:.1f}x |",
        "",
    ]


def _md_related(report: "Report", lang: str) -> list[str]:
    if not report.related_markets:
        return []
    lines = [f"## {_t('related_markets', lang)}", "",
             f"| {_t('md_market_col', lang)} | {_t('md_chg_col', lang)} |", "|---|---|"]
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
    header = f"| {_t('md_price_col', lang)} | {_t('md_label_col', lang)} |"
    if report.support_levels:
        lines += [f"**{_t('support', lang)}**", "", header, "|---|---|"]
        for lvl in report.support_levels:
            lines.append(f"| {lvl.price:.2f} | {lvl.label} |")
        lines.append("")
    if report.resistance_levels:
        lines += [f"**{_t('resistance', lang)}**", "", header, "|---|---|"]
        for lvl in report.resistance_levels:
            lines.append(f"| {lvl.price:.2f} | {lvl.label} |")
        lines.append("")
    return lines


def _md_scenarios(report: "Report", lang: str) -> list[str]:
    if not report.scenarios:
        return []
    lines = [
        f"## {_t('scenario_analysis', lang)}",
        "",
        f"| {_t('md_scenario_col', lang)} | {_t('direction', lang)} | {_t('md_range_col', lang)} "
        f"| {_t('md_prob_col', lang)} | {_t('md_rationale_col', lang)} |",
        "|---|---|---|---|---|",
    ]
    for s in report.scenarios:
        rationale = s.rationale[0] if s.rationale else ""
        # direction 枚举值保留原始标签（与 html 版一致，不翻译）
        lines.append(f"| {s.label} | {s.direction} | {s.price_min:.0f} – {s.price_max:.0f} | {s.probability:.0%} | {rationale} |")
    lines.append("")

    # 参考类基础概率（reference_class 非 None 时一行标注）
    rc = getattr(report, "reference_class", None)
    if rc:
        thin = _t("ref_class_thin", lang) if rc.get("n_analogs", 0) < 20 else ""
        lines.append(_t("ref_class_line", lang,
                        years=f"{rc.get('years', 5):.0f}", n=rc.get("n_analogs", 0),
                        up=f"{rc.get('up', 0):.0%}", flat=f"{rc.get('flat', 0):.0%}",
                        down=f"{rc.get('down', 0):.0%}") + thin)
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
    if lang == "en":
        lines = [
            f"## {_t('ml_prediction', lang)}",
            "",
            f"- {_t('ml_signal', lang)}: **{ml.signal}** ({_t('ml_conf', lang)} {ml.confidence:.0%}, model {ml.model_type})",
        ]
    else:
        lines = [
            f"## {_t('ml_prediction', lang)}",
            "",
            f"- {_t('ml_signal', lang)}: **{ml.signal}**（{_t('ml_conf', lang)} {ml.confidence:.0%}，{_t('ml_model', lang)} {ml.model_type}）",
        ]
    if ml.price_target_30d:
        lines.append(f"- {_t('ml_target', lang)}: {ml.price_target_30d:.2f} ¢/lb")
    lines.append(f"- {_t('ml_bias', lang)}: {ml.bias:+.0%}")
    perf = []
    if ml.model_accuracy is not None:
        perf.append(f"{_t('ml_accuracy', lang)} {ml.model_accuracy:.1%}")
    if ml.model_mae is not None:
        perf.append(f"{_t('ml_mae', lang)} {ml.model_mae:.2%}")
    if perf:
        lines.append(f"- {_t('ml_perf', lang)}: {' | '.join(perf)}")
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
        lines.append(f"- {_t('trigger_below', lang, x=f'{h.trigger_below:.0f}')}")
    if h.trigger_above:
        lines.append(f"- {_t('trigger_above', lang, x=f'{h.trigger_above:.0f}')}")
    if h.trigger_below or h.trigger_above:
        lines.append("")

    # 凯利仓位影子（kelly_shadow 非 None 时一行，只读展示）
    k = getattr(report, "kelly_shadow", None)
    if k:
        if k.get("active"):
            edge = k.get("edge") or 0.0
            lines.append(_t("kelly_active", lang,
                            s=f"{k['suggested_ratio']:.0%}", e=f"{edge:+.0%}",
                            c=f"{h.ratio:.0%}"))
        else:
            lines.append(_t("kelly_inactive", lang, reason=k.get("reason", "")))
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
        lines.append(f"- **{_t('landed_total', lang)}: {b.total_cost_cny_jin:.2f} CNY/斤**（{b.total_cost_usd_mt:.0f} USD/MT）")
        lines.append(f"- {_t('cyp_share', lang)}: {b.cyp_fraction_pct:.0%} | {_t('current_hedge', lang)}: {b.hedge_ratio_pct:.0%}")
    if ci.ico_spot:
        s = ci.ico_spot
        dod = f"{s['dod_change_pct']:+.1f}%" if s.get("dod_change_pct") is not None else "N/A"
        avg = f"{s['month_avg']:.2f}" if s.get("month_avg") is not None else "N/A"
        lines.append("- " + _t("ico_line", lang, icip=f"{s['icip']:.2f}", avg=avg, dod=dod))
    if ci.gfex:
        g = ci.gfex
        lines.append("- " + _t("gfex_line", lang, close=f"{g['close']:.0f}",
                               spread=f"{g['spread_cny_mt']:+.0f}", pct=f"{g['spread_pct']:+.1%}"))
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


def _md_ai_commentary(report: "Report", lang: str) -> list[str]:
    """AI 分析师点评小节（en 模式优先 llm_commentary_en，缺省回退中文并标注）"""
    text = getattr(report, "llm_commentary", None)
    suffix = ""
    if lang == "en":
        en_text = getattr(report, "llm_commentary_en", None)
        if en_text:
            text = en_text
        elif text:
            suffix = _t("zh_tag", lang)
    if not text:
        return []
    return [f"## {_t('ai_commentary', lang)}{suffix}", "", text.strip(), ""]


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
    导出 Markdown 格式报告（公众号友好，全双语）。

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
    lines += _md_ai_commentary(report, lang)
    lines += _md_outlook(report, lang)

    # ── 页脚 ──
    lines += [
        "---",
        "",
        f"*{_t('generated_at', lang)}: {report.generated_at.strftime('%Y-%m-%d %H:%M')} · {_t('disclaimer', lang)}*",
        "",
    ]
    return "\n".join(lines)
