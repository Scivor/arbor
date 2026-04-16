"""
reports/exporters/html_to_pdf.py
Generate HTML report with CJK fonts, convert to PDF via macOS textutil.
"""

from __future__ import annotations
import subprocess
import tempfile
import os

def html_to_pdf(html_path: str, pdf_path: str) -> None:
    """Convert HTML file to PDF using macOS textutil."""
    result = subprocess.run(
        ["textutil", "-convert", "pdf", "-output", pdf_path, html_path],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"textutil failed: {result.stderr}")
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"PDF not created: {result.stderr}")


def build_chinese_html(report) -> str:
    """Build full Chinese-language HTML report from a PredictionReport."""

    m = report.market
    h = report.hedge_advice
    climate = report.climate

    # Market snapshot values
    price_val = f"{m.current:.2f}" if m else "N/A"
    chg_val = f"{(m.change_1d_pct or 0)*100:+.2f}%" if m else "N/A"
    rsi_val = f"{m.rsi_14:.1f}" if m and m.rsi_14 else "N/A"
    ma20_val = f"{m.ma20:.2f}" if m and m.ma20 else "N/A"
    ma60_val = f"{m.ma60:.2f}" if m and m.ma60 else "N/A"
    high30_val = f"{m.high_30d:.2f}" if m and m.high_30d else "N/A"
    low30_val = f"{m.low_30d:.2f}" if m and m.low_30d else "N/A"

    # Scenarios
    scenario_rows = ""
    for s in (report.scenarios or []):
        if s.direction == "上涨":
            dir_color = "#1a7a1a"; hdr_bg = "#d4edda"; border = "#1a7a1a"
        elif s.direction == "下跌":
            dir_color = "#8b1a1a"; hdr_bg = "#f8d7da"; border = "#8b1a1a"
        else:
            dir_color = "#555"; hdr_bg = "#e2e3e5"; border = "#555"
        scenario_rows += f"""
        <div class="scenario-box" style="border-color:{border};">
          <div class="scenario-hdr" style="background:{border};color:#fff;">
            <span class="scenario-label">{s.label}</span>
            <span class="scenario-prob">{s.probability:.0f}%</span>
          </div>
          <div class="scenario-body">
            <div class="scenario-range">{s.price_min:.0f} – {s.price_max:.0f}</div>
            <div class="scenario-dir" style="color:{dir_color}">方向：{s.direction}</div>
            <div class="scenario-rationale">{'；'.join(s.rationale or [])}</div>
          </div>
        </div>"""

    # Levels
    support_rows = ""
    for l in (report.support_levels or []):
        support_rows += f"""
        <tr>
          <td class="level-price sup">{l.price:.2f}</td>
          <td class="level-label">{l.label}</td>
        </tr>"""
    resistance_rows = ""
    for l in (report.resistance_levels or []):
        resistance_rows += f"""
        <tr>
          <td class="level-price res">{l.price:.2f}</td>
          <td class="level-label">{l.label}</td>
        </tr>"""

    # Drivers
    bull_rows = ""
    for p in (report.bullish_params or []):
        bull_rows += f"<li><strong>{p.param_name}</strong>：{p.narrative}</li>"
    bear_rows = ""
    for p in (report.bearish_params or []):
        bear_rows += f"<li><strong>{p.param_name}</strong>：{p.narrative}</li>"

    # Risk warnings
    risk_items = ""
    for r in (report.risk_warnings or []):
        risk_items += f"<li>⚠ {r}</li>"

    # Hedge
    hedge_ratio_str = f"{int(h.ratio*100)}%" if h else "N/A"
    hedge_signal_str = h.signal if h else "N/A"
    hedge_narrative_str = h.narrative if h else ""

    # Climate
    climate_str = climate.narrative if climate else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>咖啡期货市场周度报告</title>
<style>
  @page {{
    size: A4;
    margin: 15mm 15mm 20mm 15mm;
    @bottom-center {{
      content: "本报告仅供决策参考，不构成投资建议。";
      font-size: 8pt;
      color: #888;
    }}
  }}
  body {{
    font-family: "Hiragino Sans", "Hiragino Kaku Gothic Pro", "Hei", "Kai", "Yu Gothic", "Microsoft YaHei", sans-serif;
    font-size: 10pt;
    color: #222;
    margin: 0;
    padding: 0;
  }}
  /* ── Header ── */
  .header {{
    background: #1a3a1a;
    color: #fff;
    padding: 12mm 15mm;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6mm;
  }}
  .header-title {{
    font-size: 16pt;
    font-weight: bold;
    letter-spacing: 0.5mm;
  }}
  .header-sub {{
    font-size: 9pt;
    color: #aaddaa;
    margin-top: 2mm;
  }}
  .header-badge {{
    background: #2d6a2d;
    padding: 4mm 6mm;
    font-size: 11pt;
    font-weight: bold;
    text-align: right;
  }}
  /* ── Market Snapshot ── */
  .snapshot {{
    display: flex;
    border: 1px solid #ccc;
    margin-bottom: 5mm;
    border-radius: 3px;
    overflow: hidden;
  }}
  .snap-price {{
    background: #1a3a1a;
    color: #fff;
    width: 50mm;
    padding: 5mm 4mm;
    text-align: center;
    flex-shrink: 0;
  }}
  .snap-price-label {{ font-size: 8pt; color: #aaddaa; }}
  .snap-price-val {{ font-size: 22pt; font-weight: bold; margin: 2mm 0; }}
  .snap-price-unit {{ font-size: 8pt; color: #aaddaa; }}
  .snap-price-chg {{ font-size: 9pt; }}
  .snap-metrics {{
    flex: 1;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1mm;
    padding: 3mm;
    background: #f5f5f5;
  }}
  .metric-card {{
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 2px;
    padding: 2mm 3mm;
    text-align: center;
  }}
  .metric-label {{ font-size: 7pt; color: #888; }}
  .metric-value {{ font-size: 11pt; font-weight: bold; margin-top: 1mm; }}
  /* ── Scenarios ── */
  .section {{ margin-bottom: 5mm; }}
  .section-title {{
    background: #1a3a1a;
    color: #fff;
    font-size: 10pt;
    font-weight: bold;
    padding: 2.5mm 4mm;
    margin-bottom: 2mm;
  }}
  .scenarios {{
    display: flex;
    gap: 3mm;
  }}
  .scenario-box {{
    flex: 1;
    border: 1.5px solid;
    border-radius: 3px;
    overflow: hidden;
  }}
  .scenario-hdr {{
    padding: 2mm 3mm;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .scenario-label {{ font-size: 8pt; font-weight: bold; }}
  .scenario-prob {{ font-size: 9pt; }}
  .scenario-body {{ padding: 3mm; }}
  .scenario-range {{ font-size: 13pt; font-weight: bold; margin: 2mm 0; }}
  .scenario-dir {{ font-size: 9pt; margin-bottom: 1mm; }}
  .scenario-rationale {{ font-size: 7.5pt; color: #666; line-height: 1.4; }}
  /* ── Hedge ── */
  .hedge-box {{
    background: #d4edda;
    border: 1.5px solid #1a7a1a;
    border-radius: 3px;
    padding: 4mm;
    margin-top: 3mm;
  }}
  .hedge-title {{ font-size: 10pt; font-weight: bold; color: #1a3a1a; margin-bottom: 2mm; }}
  .hedge-ratio {{ font-size: 14pt; font-weight: bold; color: #1a7a1a; }}
  .hedge-signal {{ font-size: 9pt; color: #2d6a2d; }}
  .hedge-narrative {{ font-size: 8pt; color: #555; margin-top: 2mm; }}
  /* ── Levels ── */
  .levels-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9pt;
  }}
  .levels-table th {{
    background: #1a3a1a;
    color: #fff;
    padding: 2mm 3mm;
    text-align: left;
  }}
  .levels-table td {{
    padding: 1.5mm 3mm;
    border-bottom: 1px solid #eee;
  }}
  .level-price {{ font-weight: bold; width: 25mm; }}
  .level-price.sup {{ color: #1a7a1a; }}
  .level-price.res {{ color: #8b1a1a; }}
  .level-label {{ color: #555; }}
  /* ── Drivers ── */
  .drivers {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 3mm;
  }}
  .driver-box {{
    border: 1px solid #ddd;
    border-radius: 3px;
    overflow: hidden;
  }}
  .driver-hdr {{
    padding: 2mm 3mm;
    font-weight: bold;
    font-size: 9pt;
    color: #fff;
  }}
  .driver-hdr.bull {{ background: #1a7a1a; }}
  .driver-hdr.bear {{ background: #8b1a1a; }}
  .driver-body {{ padding: 3mm; }}
  .driver-body ul {{ margin: 0; padding-left: 5mm; }}
  .driver-body li {{ margin-bottom: 2mm; font-size: 8.5pt; line-height: 1.4; }}
  /* ── Climate ── */
  .climate-strip {{
    background: #fef9e7;
    border: 1px solid #d4a017;
    border-radius: 3px;
    padding: 2.5mm 4mm;
    font-size: 9pt;
    color: #7a6000;
    margin-bottom: 3mm;
  }}
  /* ── Outlook ── */
  .outlook-box {{
    background: #d4edda;
    border: 1.5px solid #2d6a2d;
    border-radius: 3px;
    padding: 4mm;
    font-size: 9.5pt;
    line-height: 1.6;
    color: #1a3a1a;
    margin-bottom: 3mm;
  }}
  /* ── Risks ── */
  .risk-box {{
    background: #fff8e1;
    border: 1px solid #d4a017;
    border-radius: 3px;
    padding: 3mm;
    margin-bottom: 3mm;
  }}
  .risk-title {{
    font-size: 9pt;
    font-weight: bold;
    color: #7a6000;
    margin-bottom: 2mm;
  }}
  .risk-box ul {{ margin: 0; padding-left: 5mm; }}
  .risk-box li {{ font-size: 8.5pt; color: #8b6000; margin-bottom: 1.5mm; }}
  /* ── Footer ── */
  .footer {{
    border-top: 1px solid #ccc;
    padding-top: 2mm;
    margin-top: 5mm;
    font-size: 8pt;
    color: #888;
    text-align: center;
  }}
</style>
</head>
<body>

<!-- ══ Header ══ -->
<div class="header">
  <div>
    <div class="header-title">咖啡期货市场周度报告</div>
    <div class="header-sub">报告日期：{report.report_date} &nbsp;|&nbsp; 预测区间：{report.forecast_week_start} 至 {report.forecast_week_end}</div>
  </div>
  <div class="header-badge">KC=F<br>{price_val}<br>美分/磅</div>
</div>

<!-- ══ Market Snapshot ══ -->
<div class="section">
  <div class="section-title">市场行情 | MARKET SNAPSHOT</div>
  <div class="snapshot">
    <div class="snap-price">
      <div class="snap-price-label">当前价格</div>
      <div class="snap-price-val">{price_val}</div>
      <div class="snap-price-unit">美分/磅 (US¢/lb)</div>
      <div class="snap-price-chg" style="color:{'#aaffaa' if (m.change_1d_pct or 0)>=0 else '#ffaaaa'}">{chg_val}</div>
    </div>
    <div class="snap-metrics">
      <div class="metric-card">
        <div class="metric-label">RSI (14)</div>
        <div class="metric-value" style="color:{'#8b1a1a' if float(rsi_val or 0)>65 else '#1a7a1a' if float(rsi_val or 0)<40 else '#555'}">{rsi_val}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">MA20</div>
        <div class="metric-value">{ma20_val}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">MA60</div>
        <div class="metric-value">{ma60_val}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">30日高</div>
        <div class="metric-value" style="color:#8b1a1a">{high30_val}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">30日低</div>
        <div class="metric-value" style="color:#1a7a1a">{low30_val}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">当前价格</div>
        <div class="metric-value">{price_val}</div>
      </div>
    </div>
  </div>
</div>

<!-- ══ Scenarios ══ -->
<div class="section">
  <div class="section-title">情景分析 | SCENARIO ANALYSIS</div>
  <div class="scenarios">
    {scenario_rows}
  </div>
  <div class="hedge-box">
    <div class="hedge-title">套保建议 | HEDGE ADVICE</div>
    <div class="hedge-ratio">建议套保比率：{hedge_ratio_str}</div>
    <div class="hedge-signal">{hedge_signal_str}</div>
    <div class="hedge-narrative">{hedge_narrative_str}</div>
  </div>
</div>

<!-- ══ Key Levels ══ -->
<div class="section">
  <div class="section-title">关键价位 | KEY LEVELS</div>
  <table class="levels-table">
    <thead>
      <tr>
        <th style="width:25mm;">支撑 SUPPORTS</th>
        <th></th>
        <th style="width:25mm;">阻力 RESISTANCE</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td class="level-price sup">{(report.support_levels or [None])[0].price if (report.support_levels or []) else 0:.2f}</td>
        <td class="level-label">{(report.support_levels or [None])[0].label if (report.support_levels or []) else ''}</td>
        <td class="level-price res">{(report.resistance_levels or [None])[0].price if (report.resistance_levels or []) else 0:.2f}</td>
        <td class="level-label">{(report.resistance_levels or [None])[0].label if (report.resistance_levels or []) else ''}</td>
      </tr>
      <tr>
        <td class="level-price sup">{(report.support_levels or [None])[1].price if len(report.support_levels or [])>1 else 0:.2f}</td>
        <td class="level-label">{(report.support_levels or [None])[1].label if len(report.support_levels or [])>1 else ''}</td>
        <td class="level-price res">{(report.resistance_levels or [None])[1].price if len(report.resistance_levels or [])>1 else 0:.2f}</td>
        <td class="level-label">{(report.resistance_levels or [None])[1].label if len(report.resistance_levels or [])>1 else ''}</td>
      </tr>
      <tr>
        <td class="level-price sup">{(report.support_levels or [None])[2].price if len(report.support_levels or [])>2 else 0:.2f}</td>
        <td class="level-label">{(report.support_levels or [None])[2].label if len(report.support_levels or [])>2 else ''}</td>
        <td class="level-price res">{(report.resistance_levels or [None])[2].price if len(report.resistance_levels or [])>2 else 0:.2f}</td>
        <td class="level-label">{(report.resistance_levels or [None])[2].label if len(report.resistance_levels or [])>2 else ''}</td>
      </tr>
    </tbody>
  </table>
</div>

<!-- ══ Drivers ══ -->
<div class="section">
  <div class="section-title">多空驱动 | DRIVERS</div>
  {f'<div class="climate-strip">🌡 气候背景：{climate_str}</div>' if climate_str else ''}
  <div class="drivers">
    <div class="driver-box">
      <div class="driver-hdr bull">▲ 利多因素 BULLISH</div>
      <div class="driver-body"><ul>{bull_rows or '<li>暂无明确利多</li>'}</ul></div>
    </div>
    <div class="driver-box">
      <div class="driver-hdr bear">▼ 利空因素 BEARISH</div>
      <div class="driver-body"><ul>{bear_rows or '<li>暂无明确利空</li>'}</ul></div>
    </div>
  </div>
</div>

<!-- ══ Outlook ══ -->
<div class="section">
  <div class="section-title">市场展望 | MARKET OUTLOOK</div>
  <div class="outlook-box">{report.outlook or '暂无展望'}</div>
  {f'''
  <div class="risk-box">
    <div class="risk-title">⚠ 风险提示 RISK WARNINGS</div>
    <ul>{risk_items}</ul>
  </div>''' if report.risk_warnings else ''}
</div>

<div class="footer">
  本报告仅供决策参考，不构成投资建议。Generated by Coffee V3 System.
</div>

</body>
</html>"""
    return html
