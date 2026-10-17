"""
web/track_record.py
预测战绩页 HTML 渲染 — 纯字符串拼装，无 fastapi/jinja2 依赖（便于测试）。

风格对齐 web/app.py 的 _build_past_index_html：手写 HTML + 内联 <style>，
复用 Kami 设计 token（parchment/brand/olive/stone/border）。
"""

from __future__ import annotations

from html import escape as _esc

from reports.fonts import css_sans_stack, css_serif_stack


def _fmt_step(value) -> str:
    """系数调整至少两位小数；0.005 这类半步不被收成 0.01。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".00"
    elif len(text.split(".", 1)[1]) < 2:
        text += "0"
    return text


def _build_learning_html(learning: dict | None) -> str:
    """自校准区块：当前系数 + 近期指标 + 最近 5 条调整记录。"""
    if not learning:
        return ""
    cur = learning.get("current") or {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}
    n = learning.get("n_samples", 0)
    min_samples = learning.get("min_samples", 8)
    acc = learning.get("ml_accuracy")
    hit = learning.get("band_hit_rate")
    changelog = learning.get("changelog") or []

    def _coef(name: str) -> str:
        v = cur.get(name, 1.0)
        base = ' <span class="tr-learn-base">未校准</span>' if abs(v - 1.0) < 1e-9 else ""
        return f"{name} <b>{v:.2f}</b>{base}"

    memory = learning.get("memory") or {}
    conviction = memory.get("hedge_conviction", cur.get("hedge_conviction", 1.0))
    try:
        conviction = float(conviction)
    except (TypeError, ValueError):
        conviction = 1.0
    conviction_base = ' <span class="tr-learn-base">未校准</span>' if abs(conviction - 1.0) < 1e-9 else ""
    hedge_acc = memory.get("hedge_accuracy")
    hedge_acc_text = f" · 有方向的套保有效率 {hedge_acc:.0%}" if isinstance(hedge_acc, (int, float)) else ""
    direction = memory.get("direction_trust") or {}
    direction_html = ""
    if isinstance(direction, dict) and direction:
        labels = {"up": "上涨", "down": "下跌"}
        parts = []
        for side, value in list(direction.items())[:4]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            parts.append(f"{_esc(labels.get(str(side), str(side)))} {number:.2f}")
        if parts:
            direction_html = f"""
    <div class="tr-learn-metrics">方向信任 {" · ".join(parts)}</div>"""
    shift_html = ""
    try:
        shift = float(memory.get("band_center_shift") or 0.0)
    except (TypeError, ValueError):
        shift = 0.0
    if abs(shift) >= 0.0025:
        side = "下移" if shift < 0 else "上移"
        shift_html = f"""
    <div class="tr-learn-metrics">区间中心 {side} {abs(shift) * 100:.2f}%</div>"""
    flat_html = ""
    try:
        flat_trust = float(memory.get("flat_trust", 1.0))
    except (TypeError, ValueError):
        flat_trust = 1.0
    if flat_trust < 0.999:
        flat_html = f"""
    <div class="tr-learn-metrics">横盘信任 <b>{flat_trust:.2f}</b></div>"""
    trust = memory.get("driver_trust") or {}
    if trust:
        discounted = " · ".join(
            f"{_esc(str(name))} {float(value):.2f}"
            for name, value in list(trust.items())[:8]
        )
        trust_html = f"""
    <div class="tr-learn-metrics">压低的驱动 {discounted}</div>"""
    elif learning.get("memory") is not None:
        trust_html = """
    <div class="tr-learn-metrics tr-learn-dim">驱动因子维持原权重</div>"""
    else:
        trust_html = ""
    if learning.get("memory") is not None:
        trust_html += """
    <div class="tr-learn-metrics tr-learn-dim">仍在出现的不可靠因子会修正下一期：套保往反方向挪，该方向的情景概率让给横盘。合计都不超过 6 个百分点。机器学习和 RSI 走各自的系数。上涨或下跌连续说错时，该方向的概率按方向信任让给横盘。情景区间中心连续偏高或偏低时，下一期整段价格区间同向挪动，每步 0.5 个百分点，最多 3 个。横盘连续说错时，横盘概率按横盘信任分给上涨和下跌。停在中性的周不给套保持信加分。</div>"""

    rows = f"""
    <div class="tr-learn-coefs">{_coef("ml_bias_scale")} &nbsp;·&nbsp; {_coef("scenario_band_scale")}</div>
    <div class="tr-learn-metrics">套保持信 hedge_conviction <b>{conviction:.2f}</b>{conviction_base}{hedge_acc_text}</div>{direction_html}{shift_html}{flat_html}{trust_html}"""

    if acc is not None and hit is not None:
        rows += f"""
    <div class="tr-learn-metrics">ML 方向准确率 {acc:.0%} · 区间命中率 {hit:.0%}（n={n}）</div>"""
    else:
        rows += f"""
    <div class="tr-learn-metrics tr-learn-dim">样本不足 {n}/{min_samples}</div>"""

    if changelog:
        log_rows = ""
        for e in reversed(changelog):  # 最新一条在前
            ts = str(e.get("ts", ""))[:16].replace("T", " ")
            log_rows += f"""
        <tr>
          <td class="tr-num">{_esc(ts)}</td>
          <td>{_esc(str(e.get("param", "")))}</td>
          <td class="tr-num">{_fmt_step(e.get("old", 0))} → {_fmt_step(e.get("new", 0))}</td>
          <td>{_esc(str(e.get("reason", "")))}</td>
        </tr>"""
        rows += f"""
    <table class="tr-table tr-learn-log">
      <thead>
        <tr><th>时间</th><th>参数</th><th>调整</th><th>原因</th></tr>
      </thead>
      <tbody>{log_rows}
      </tbody>
    </table>"""
    else:
        rows += """
    <div class="tr-empty" style="padding:14px;">暂无校准记录</div>"""

    return f"""
  <div class="tr-drivers-title">系数自校准</div>
  <div class="tr-learn">{rows}
  </div>"""


def build_track_record_html(record: dict, driver_stats: list[dict] | None = None, learning: dict | None = None) -> str:
    """渲染预测战绩页。

    Args:
        record: reports.history.compute_track_record() 的返回 dict。
        driver_stats: reports.history.compute_driver_stats() 的返回 list（可选）。
        learning: reports.learning.learning_status() 的返回 dict（可选）。
    """
    total = record.get("total", 0)
    weeks = record.get("weeks", [])
    pending = record.get("pending")

    if not weeks:
        body = '<div class="tr-empty">暂无历史复盘数据</div>'
    else:
        # ── Brier 记分卡（None 时显示 —）──
        mean_brier = record.get("mean_brier")
        bss = record.get("bss")
        brier_val = f"{mean_brier:.3f}" if mean_brier is not None else "—"
        bss_html = f'<div class="tr-metric-sub">BSS {bss:+.2f}</div>' if bss is not None else ""

        rows = ""
        for w in reversed(weeks):  # 最新一期在前
            badge_cls = {"命中": "tr-badge-hit", "部分命中": "tr-badge-partial"}.get(w["badge"], "tr-badge-miss")
            chg = w["price_change_pct"]
            chg_color = "#1B365D" if chg >= 0 else "#504e49"
            brier_cell = f'{w["brier"]:.3f}' if w.get("brier") is not None else "—"
            kelly_cell = f'{w["kelly"]:.0%}' if w.get("kelly") is not None else "—"
            rows += f"""
        <tr>
          <td class="tr-date">{w["report_date"]}</td>
          <td><span class="tr-badge {badge_cls}">{w["badge"]}</span></td>
          <td>{w["direction"]}</td>
          <td class="tr-num">{w["predicted_min"]:.0f} – {w["predicted_max"]:.0f}</td>
          <td class="tr-num">{w["actual_price"]:.1f}</td>
          <td class="tr-num" style="color:{chg_color};">{chg:+.1f}%</td>
          <td class="tr-num">{brier_cell}</td>
          <td class="tr-num">{kelly_cell}</td>
        </tr>"""
        pending_html = f'<div class="tr-pending">{pending} 期预测待复盘（下期周报发布后更新）</div>' if pending else ""

        # ── 校准度分桶 + 区分度 ──
        cal_rows = ""
        for b in (record.get("calibration") or []):
            mp = f'{b["mean_predicted"]:.0%}' if b.get("mean_predicted") is not None else "—"
            of = f'{b["observed_freq"]:.0%}' if b.get("observed_freq") is not None else "—"
            cal_rows += f"""
        <tr>
          <td class="tr-date">{_esc(str(b["bucket"]))}</td>
          <td class="tr-num">{mp}</td>
          <td class="tr-num">{of}</td>
          <td class="tr-num">{b["count"]}</td>
        </tr>"""
        resolution = record.get("resolution")
        res_text = f"区分度: {resolution:.3f}（越大越敢报极端概率）" if resolution is not None else "区分度: —"
        calibration_html = f"""
  <div class="tr-drivers-title">概率校准（Brier）</div>
  <table class="tr-table tr-calib">
    <thead>
      <tr><th>桶区间</th><th>平均预测</th><th>实际频率</th><th>样本数</th></tr>
    </thead>
    <tbody>{cal_rows}
    </tbody>
  </table>
  <div class="tr-calib-note">{res_text}</div>"""

        # ── 驱动因子应验率（仅显示样本 ≥2 的因子，按样本数降序）──
        qualified = [s for s in (driver_stats or []) if s.get("samples", 0) >= 2]
        trust_map = ((learning or {}).get("memory") or {}).get("driver_trust") or {}
        if qualified:
            drv_rows = ""
            for s in qualified:
                rate_color = "#1B365D" if s["rate"] >= 0.5 else "#504e49"
                name = str(s["param_name"])
                if name in trust_map:
                    trust_cell = f'<td class="tr-num">{float(trust_map[name]):.2f}</td>'
                elif trust_map:
                    trust_cell = '<td class="tr-num">1.00</td>'
                else:
                    trust_cell = ""
                drv_rows += f"""
        <tr>
          <td class="tr-date">{_esc(name)}</td>
          <td class="tr-num" style="color:{rate_color};">{s["rate"]:.0%}</td>
          <td class="tr-num">{s["samples"]}</td>
          {trust_cell}
        </tr>"""
            trust_head = "<th>信任</th>" if trust_map else ""
            drivers_html = f"""
  <div class="tr-drivers-title">驱动因子应验率</div>
  <table class="tr-table tr-drivers">
    <thead>
      <tr><th>因子</th><th>应验率</th><th>样本数</th>{trust_head}</tr>
    </thead>
    <tbody>{drv_rows}
    </tbody>
  </table>"""
        else:
            drivers_html = """
  <div class="tr-drivers-title">驱动因子应验率</div>
  <div class="tr-empty" style="padding:20px;">驱动因子样本不足（需 ≥2 期复盘）</div>"""

        body = f"""
  <div class="tr-metrics">
    <div class="tr-metric"><div class="tr-metric-val">{record["hit_rate"]:.0%}</div><div class="tr-metric-label">区间命中率</div></div>
    <div class="tr-metric"><div class="tr-metric-val">{record["direction_rate"]:.0%}</div><div class="tr-metric-label">方向正确率</div></div>
    <div class="tr-metric"><div class="tr-metric-val">{record["hedge_rate"]:.0%}</div><div class="tr-metric-label">套保有效率</div></div>
    <div class="tr-metric"><div class="tr-metric-val">{total}</div><div class="tr-metric-label">已复盘期数</div></div>
    <div class="tr-metric"><div class="tr-metric-val">{brier_val}</div><div class="tr-metric-label">平均 Brier · 基准 0.667</div>{bss_html}</div>
  </div>
  <table class="tr-table">
    <thead>
      <tr><th>日期</th><th>结果</th><th>预测方向</th><th>预测区间</th><th>实际价</th><th>涨跌</th><th>Brier</th><th>凯利</th></tr>
    </thead>
    <tbody>{rows}
    </tbody>
  </table>
  {pending_html}
  {calibration_html}
  {drivers_html}
  {_build_learning_html(learning)}"""

    sans = css_sans_stack()
    serif = css_serif_stack()
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>预测战绩 · Arbor</title>
<style>
  body {{
    background: #f5f4ed;
    color: #141413;
    font-family: {sans};
    font-size: 14px;
    margin: 0;
  }}
  .tr-wrap {{
    max-width: 210mm;
    margin: 0 auto;
    padding: 40px 14mm 48px;
  }}
  .tr-hdr {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 24px;
  }}
  .tr-title {{
    font-family: {serif};
    font-size: 22px;
    font-weight: 600;
    color: #141413;
    letter-spacing: 0.3px;
  }}
  .tr-back {{
    font-size: 12px;
    color: #504e49;
    text-decoration: none;
  }}
  .tr-back:hover {{ color: #1B365D; }}
  .tr-metrics {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
    margin-bottom: 24px;
  }}
  .tr-metric {{
    background: #faf9f5;
    border: 1px solid #e8e6dc;
    border-radius: 6px;
    padding: 16px 14px;
  }}
  .tr-metric-val {{
    font-family: {serif};
    font-size: 30px;
    font-weight: 600;
    color: #1B365D;
    line-height: 1.1;
  }}
  .tr-metric-label {{
    font-size: 11px;
    color: #6b6a64;
    margin-top: 6px;
    letter-spacing: 0.3px;
  }}
  .tr-metric-sub {{
    font-size: 11px;
    color: #6b6a64;
    margin-top: 4px;
  }}
  .tr-table {{
    width: 100%;
    border-collapse: collapse;
    background: #faf9f5;
    border: 1px solid #e8e6dc;
    border-radius: 6px;
    overflow: hidden;
    font-size: 13px;
  }}
  .tr-table th {{
    font-size: 11px;
    font-weight: 500;
    color: #6b6a64;
    letter-spacing: 0.3px;
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid #e8e6dc;
  }}
  .tr-table td {{
    padding: 10px 12px;
    border-bottom: 1px solid #e8e6dc;
  }}
  .tr-date {{
    font-family: {serif};
    font-weight: 600;
  }}
  .tr-num {{ font-variant-numeric: tabular-nums; }}
  .tr-badge {{
    display: inline-block;
    font-size: 11px;
    font-weight: 500;
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid #e8e6dc;
  }}
  .tr-badge-hit {{ color: #1B365D; border-color: #1B365D; }}
  .tr-badge-partial {{ color: #504e49; border-color: #504e49; }}
  .tr-badge-miss {{ color: #6b6a64; }}
  .tr-pending {{
    font-size: 12px;
    color: #6b6a64;
    margin-top: 14px;
  }}
  .tr-drivers-title {{
    font-family: {serif};
    font-size: 15px;
    font-weight: 600;
    color: #141413;
    letter-spacing: 0.3px;
    margin: 28px 0 12px;
  }}
  .tr-drivers {{ margin-bottom: 4px; }}
  .tr-calib {{ margin-bottom: 4px; }}
  .tr-calib-note {{
    font-size: 11px;
    color: #6b6a64;
    margin-top: 8px;
  }}
  .tr-learn {{
    background: #faf9f5;
    border: 1px solid #e8e6dc;
    border-radius: 6px;
    padding: 16px 14px;
  }}
  .tr-learn-coefs {{
    font-size: 13px;
    color: #141413;
  }}
  .tr-learn-coefs b {{
    font-family: {serif};
    font-size: 18px;
    color: #1B365D;
  }}
  .tr-learn-base {{
    font-size: 10px;
    color: #6b6a64;
    border: 1px solid #e8e6dc;
    border-radius: 4px;
    padding: 1px 5px;
    margin-left: 2px;
  }}
  .tr-learn-metrics {{
    font-size: 12px;
    color: #504e49;
    margin-top: 8px;
  }}
  .tr-learn-dim {{ color: #6b6a64; }}
  .tr-learn-log {{ margin-top: 12px; }}
  .tr-empty {{
    background: #faf9f5;
    border: 1px solid #e8e6dc;
    border-radius: 6px;
    padding: 40px 20px;
    text-align: center;
    color: #6b6a64;
    font-size: 13px;
  }}
  .tr-foot {{
    font-size: 11px;
    color: #6b6a64;
    margin-top: 28px;
    padding-top: 14px;
    border-top: 1px solid #e8e6dc;
  }}
  @media (max-width: 768px) {{
    .tr-wrap {{ padding: 24px 16px 32px; }}
    .tr-metrics {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
<div class="tr-wrap">
  <div class="tr-hdr">
    <span class="tr-title">预测战绩</span>
    <a class="tr-back" href="/">← 返回最新周报</a>
  </div>
  {body}
  <div class="tr-foot">数据来源: 本地历史周报复盘（相邻期配对） · 仅供内部研究，不构成投资建议</div>
</div>
</body>
</html>"""
