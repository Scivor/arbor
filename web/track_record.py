"""
web/track_record.py
预测战绩页 HTML 渲染 — 纯字符串拼装，无 fastapi/jinja2 依赖（便于测试）。

风格对齐 web/app.py 的 _build_past_index_html：手写 HTML + 内联 <style>，
复用 Kami 设计 token（parchment/brand/olive/stone/border）。
"""

from __future__ import annotations


def build_track_record_html(record: dict) -> str:
    """渲染预测战绩页。

    Args:
        record: reports.history.compute_track_record() 的返回 dict。
    """
    total = record.get("total", 0)
    weeks = record.get("weeks", [])
    pending = record.get("pending")

    if not weeks:
        body = '<div class="tr-empty">暂无历史复盘数据</div>'
    else:
        rows = ""
        for w in reversed(weeks):  # 最新一期在前
            badge_cls = {"命中": "tr-badge-hit", "部分命中": "tr-badge-partial"}.get(w["badge"], "tr-badge-miss")
            chg = w["price_change_pct"]
            chg_color = "#1B365D" if chg >= 0 else "#504e49"
            rows += f"""
        <tr>
          <td class="tr-date">{w["report_date"]}</td>
          <td><span class="tr-badge {badge_cls}">{w["badge"]}</span></td>
          <td>{w["direction"]}</td>
          <td class="tr-num">{w["predicted_min"]:.0f} – {w["predicted_max"]:.0f}</td>
          <td class="tr-num">{w["actual_price"]:.1f}</td>
          <td class="tr-num" style="color:{chg_color};">{chg:+.1f}%</td>
        </tr>"""
        pending_html = f'<div class="tr-pending">{pending} 期预测待复盘（下期周报发布后更新）</div>' if pending else ""
        body = f"""
  <div class="tr-metrics">
    <div class="tr-metric"><div class="tr-metric-val">{record["hit_rate"]:.0%}</div><div class="tr-metric-label">区间命中率</div></div>
    <div class="tr-metric"><div class="tr-metric-val">{record["direction_rate"]:.0%}</div><div class="tr-metric-label">方向正确率</div></div>
    <div class="tr-metric"><div class="tr-metric-val">{record["hedge_rate"]:.0%}</div><div class="tr-metric-label">套保有效率</div></div>
    <div class="tr-metric"><div class="tr-metric-val">{total}</div><div class="tr-metric-label">已复盘期数</div></div>
  </div>
  <table class="tr-table">
    <thead>
      <tr><th>日期</th><th>结果</th><th>预测方向</th><th>预测区间</th><th>实际价</th><th>涨跌</th></tr>
    </thead>
    <tbody>{rows}
    </tbody>
  </table>
  {pending_html}"""

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
    font-family: ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", sans-serif;
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
    font-family: Charter, Georgia, "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", serif;
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
    grid-template-columns: repeat(4, 1fr);
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
    font-family: Charter, Georgia, "Source Han Serif SC", serif;
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
    font-family: Charter, Georgia, "Source Han Serif SC", serif;
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
