"""
reports/provenance.py
Data provenance tracking — every number in the report must be traceable
to its source, collection time, and reliability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DataSource:
    """A single data field with full provenance."""
    field_name: str           # e.g. "current_price"
    value: str                # string representation
    source_name: str          # e.g. "Yahoo Finance"
    source_url: str = ""      # e.g. "https://finance.yahoo.com/quote/KC=F"
    collected_at: str = ""    # ISO timestamp
    latency: str = ""         # e.g. "~15 min delayed"
    reliability: str = "A"    # A=real-time/exchange, B=delayed, C=estimated/model
    notes: str = ""           # any caveats


@dataclass
class ReportProvenance:
    """Complete provenance ledger for a PredictionReport."""
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    sources: list[DataSource] = field(default_factory=list)

    def add(self, field_name: str, value, source_name: str,
            source_url: str = "", latency: str = "", reliability: str = "A",
            notes: str = "") -> None:
        """Convenience method to add a source entry."""
        self.sources.append(DataSource(
            field_name=field_name,
            value=str(value) if value is not None else "N/A",
            source_name=source_name,
            source_url=source_url,
            collected_at=datetime.now().isoformat(timespec="minutes"),
            latency=latency,
            reliability=reliability,
            notes=notes,
        ))

    def to_html_table(self) -> str:
        """Render as an HTML table for embedding in reports."""
        if not self.sources:
            return ""

        rows = ""
        for s in self.sources:
            rel_color = {"A": "#1a7a1a", "B": "#d4a017", "C": "#8b1a1a"}.get(s.reliability, "#555")
            rel_label = {"A": "A 实时/交易所", "B": "B 延迟", "C": "C 模型/估算"}.get(s.reliability, s.reliability)
            rows += f"""
            <tr>
              <td style="padding:1.5mm 2mm;border-bottom:1px solid #eee;font-size:8pt;font-weight:bold;color:#333;">{s.field_name}</td>
              <td style="padding:1.5mm 2mm;border-bottom:1px solid #eee;font-size:8pt;color:#555;font-family:monospace;">{s.value}</td>
              <td style="padding:1.5mm 2mm;border-bottom:1px solid #eee;font-size:8pt;color:#333;">{s.source_name}</td>
              <td style="padding:1.5mm 2mm;border-bottom:1px solid #eee;font-size:7.5pt;color:#888;">{s.latency}</td>
              <td style="padding:1.5mm 2mm;border-bottom:1px solid #eee;font-size:7.5pt;color:{rel_color};font-weight:bold;">{rel_label}</td>
            </tr>"""

        return f"""
        <div class="section">
          <div class="section-title">数据来源与可靠性 | DATA PROVENANCE</div>
          <div style="font-size:7.5pt;color:#888;margin-bottom:2mm;">采集时间: {self.generated_at} &nbsp;|&nbsp; 可靠性分级: A=交易所/官方, B=第三方延迟, C=模型推算</div>
          <table style="width:100%;border-collapse:collapse;font-size:8pt;">
            <thead>
              <tr style="background:#1a3a1a;color:#fff;">
                <th style="padding:2mm;text-align:left;font-size:8pt;">字段</th>
                <th style="padding:2mm;text-align:left;font-size:8pt;">当前值</th>
                <th style="padding:2mm;text-align:left;font-size:8pt;">数据来源</th>
                <th style="padding:2mm;text-align:left;font-size:8pt;">延迟说明</th>
                <th style="padding:2mm;text-align:left;font-size:8pt;">可靠性</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        """
