"""
reports/exporters/pdf_exporter.py
Apple-style PDF export using fpdf2.

Requires: pip install fpdf2
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

try:
    from fpdf import FPDF
    _HAS_FPDF = True
except ImportError:
    _HAS_FPDF = False

from reports.models import PredictionReport


# ─────────────────────────────────────────────────────────────────────────────
# Apple Colours
# ─────────────────────────────────────────────────────────────────────────────

class AppleColors:
    """Apple HIG-inspired palette for PDF reports."""
    BACKGROUND = (255, 255, 255)
    SURFACE    = (248, 248, 248)
    LABEL      = (120, 120, 128)
    PRIMARY    = (0, 112, 209)
    GREEN      = (52, 199, 89)
    RED        = (255, 59, 48)
    YELLOW     = (255, 204, 0)
    TEXT       = (29, 29, 31)
    BORDER     = (220, 220, 227)


# ─────────────────────────────────────────────────────────────────────────────
# PDF Document
# ─────────────────────────────────────────────────────────────────────────────

class CoffeePDF(FPDF):
    """Apple-style Coffee Futures PDF report."""

    MARGIN = 18
    PAGE_W = 210
    PAGE_H = 297

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(left=self.MARGIN, top=15, right=self.MARGIN)
        self.add_font("hiragino", fname="/System/Library/Fonts/Hiragino Sans GB.ttc")
        self._cn_font = "hiragino"
        self._title_font = "helvetica"
        self._body_font = "helvetica"
        self._section_count = 0
        self._page_count = 0

    # ── Page header / footer ─────────────────────────────────────

    def header(self) -> None:
        self._page_count += 1
        if self._page_count > 1:
            self.set_font(self._body_font, size=8)
            self.set_text_color(*AppleColors.LABEL)
            self.cell(0, 6, f"KC=F Weekly Outlook  |  {self._page_count - 1}", align="R")
            self.ln(4)
            self._line(AppleColors.BORDER)
            self.ln(5)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font(self._body_font, size=8)
        self.set_text_color(*AppleColors.LABEL)
        self.cell(0, 8, f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Coffee V3.0", align="C")

    # ── Drawing helpers ───────────────────────────────────────────

    def _line(self, color: tuple, width: float = 0.3) -> None:
        self.set_draw_color(*color)
        self.set_line_width(width)
        self.line(self.MARGIN, self.get_y(), self.PAGE_W - self.MARGIN, self.get_y())

    def _fill(self, color: tuple) -> None:
        self.set_fill_color(*color)
        self.set_draw_color(*color)

    def _cn(self, text) -> bool:
        """Detect non-ASCII (Chinese / CJK) text."""
        if not isinstance(text, str):
            return False
        return bool(text and not all(ord(c) < 128 for c in text))

    def _strip_cn(self, text: str) -> str:
        """Remove non-ASCII characters (for PDF cells that can't render CJK)."""
        if not isinstance(text, str):
            return text
        return "".join(c if ord(c) < 128 else "" for c in text)

    def _set_font(self, text, style: str = "", size: float = None) -> None:
        self.set_font(self._body_font, style, size)

    def _clean_args(self, args, kwargs):
        """Strip Chinese from all string args, return (cleaned_args, cleaned_kwargs)."""
        clean_args = []
        for a in args:
            if isinstance(a, str) and self._cn(a):
                clean_args.append(self._strip_cn(a))
            else:
                clean_args.append(a)
        clean_kwargs = {}
        for k, v in kwargs.items():
            if isinstance(v, str) and self._cn(v):
                clean_kwargs[k] = self._strip_cn(v)
            else:
                clean_kwargs[k] = v
        return tuple(clean_args), clean_kwargs

    def cell(self, *args, **kwargs) -> None:
        a, kw = self._clean_args(args, kwargs)
        super().cell(*a, **kw)

    def multi_cell(self, *args, **kwargs) -> None:
        a, kw = self._clean_args(args, kwargs)
        super().multi_cell(*a, **kw)

    # ── Legacy helpers ─────────────────────────────────────────────

    def _cell(self, *args, **kwargs) -> None:
        self.cell(*args, **kwargs)

    def _mc(self, *args, **kwargs) -> None:
        self.multi_cell(*args, **kwargs)

    # ── Section builder helpers ────────────────────────────────────

    def section_title(self, title: str, icon: str = "") -> None:
        """Apple-style section header."""
        self._section_count += 1
        self.ln(6)
        self.set_font(self._title_font, "B", 13)
        self.set_text_color(*AppleColors.TEXT)
        text = f"{icon}  {title}" if icon else title
        self.cell(0, 8, text, ln=True)
        self._line(AppleColors.BORDER, 0.5)
        self.ln(3)

    # ── Content blocks ─────────────────────────────────────────────

    def price_card(self, m) -> None:
        """Price overview card."""
        x0 = self.MARGIN
        w = self.PAGE_W - 2 * self.MARGIN
        self._fill(AppleColors.SURFACE)
        self.rect(x0, self.get_y(), w, 46, "F")

        self.set_xy(x0 + 4, self.get_y() + 4)
        self.set_font(self._title_font, "B", 36)
        color = AppleColors.GREEN if m.change_1d_pct >= 0 else AppleColors.RED
        self.set_text_color(*color)
        sign = "+" if m.change_1d_pct >= 0 else ""
        self.cell(55, 14, f"{sign}{m.current:.2f}", align="L")
        self.set_font(self._body_font, size=10)
        self.set_text_color(*AppleColors.LABEL)
        self.cell(0, 14, "cents/lb", align="L", ln=True)

        self.set_x(x0 + 4)
        self.set_font(self._body_font, size=9)
        self.set_text_color(*AppleColors.LABEL)
        self.cell(28, 5, "Today: ", align="L")
        self.set_text_color(*color)
        self.cell(20, 5, f"{sign}{m.change_1d_pct:.2f}%", align="L")
        self.set_text_color(*AppleColors.LABEL)
        self.cell(20, 5, "30d: ", align="L")
        color30 = AppleColors.GREEN if m.change_30d_pct >= 0 else AppleColors.RED
        self.set_text_color(*color30)
        self.cell(20, 5, f"{sign}{m.change_30d_pct:.1f}%", align="L")
        self.set_text_color(*AppleColors.LABEL)
        self.cell(25, 5, "RSI(14): ", align="L")
        rsi_c = AppleColors.RED if m.rsi_14 < 35 else AppleColors.GREEN if m.rsi_14 > 65 else AppleColors.LABEL
        self.set_text_color(*rsi_c)
        self.cell(15, 5, f"{m.rsi_14:.1f}", align="L")
        self.ln(6)

        self.set_x(x0 + 4)
        self.set_font(self._body_font, size=9)
        self.set_text_color(*AppleColors.LABEL)
        ma_trend = "^" if m.current > m.ma20 else "v"
        self.cell(40, 5, f"MA20: {m.ma20:.2f} {ma_trend}", align="L")
        ma60_trend = "^" if m.current > m.ma60 else "v"
        self.cell(45, 5, f"MA60: {m.ma60:.2f} {ma60_trend}", align="L")
        self.set_text_color(*AppleColors.LABEL)
        self.cell(35, 5, f"30d Range: {m.low_30d:.1f}-{m.high_30d:.1f}", align="L")
        self.ln(7)

        self.set_x(x0 + 4)
        self._draw_sparkline(m.close_5d, x0 + 4, self.get_y(), w - 8, 14)
        self.ln(16)

    def _draw_sparkline(self, data, x, y, width, height) -> None:
        if not data:
            return
        self.set_draw_color(*AppleColors.PRIMARY)
        self.set_line_width(0.5)
        min_d, max_d = min(data), max(data)
        span = max_d - min_d or 1
        step_x = width / max(len(data) - 1, 1)
        pts = []
        for i, v in enumerate(data):
            px = x + i * step_x
            py = y + height - ((v - min_d) / span * (height - 2))
            pts.append((px, py))
        for i in range(len(pts) - 1):
            self.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        last = pts[-1]
        self.set_fill_color(*AppleColors.PRIMARY)
        self.ellipse(last[0] - 1.5, last[1] - 1.5, 3, 3, "F")

    def scenario_table(self, scenarios) -> None:
        self.ln(2)
        h = 8
        cols = [28, 30, 22, 58]
        headers = ["Scenario", "Range", "Prob", "Rationale"]
        x_positions = [self.MARGIN]
        for c in cols[:-1]:
            x_positions.append(x_positions[-1] + c)

        self._fill(AppleColors.SURFACE)
        self.rect(self.MARGIN, self.get_y(), sum(cols), h, "F")
        self.set_font(self._body_font, "B", 9)
        self.set_text_color(*AppleColors.LABEL)
        for header, xp, cw in zip(headers, x_positions, cols):
            self.set_xy(xp + 2, self.get_y() + 2)
            self.cell(cw - 2, 5, header, align="L")
        self.ln(h)
        self._line(AppleColors.BORDER, 0.3)
        self.ln(1)

        for s in scenarios:
            row_h = 9
            if s.direction == "BEARISH":
                bg = (255, 245, 245)
            elif s.direction == "BULLISH":
                bg = (245, 255, 245)
            else:
                bg = AppleColors.SURFACE if s.probability < 0.15 else AppleColors.BACKGROUND
            self.set_fill_color(*bg)
            self.rect(self.MARGIN, self.get_y(), sum(cols), row_h, "F")

            icon = {"BEARISH": "*", "NEUTRAL": "o", "BULLISH": "*"}.get(s.direction, "o")
            dir_color = AppleColors.RED if s.direction == "BEARISH" else AppleColors.GREEN if s.direction == "BULLISH" else AppleColors.LABEL
            prob_bar = "|" * int(s.probability * 16) + "|" * (16 - int(s.probability * 16))

            self.set_font(self._body_font, "B", 9)
            self.set_text_color(*dir_color)
            self.set_xy(self.MARGIN + 2, self.get_y() + 2)
            self._cell(cols[0] - 2, 5, f"{icon} {s.label}", align="L")
            self.set_text_color(*AppleColors.TEXT)
            self.set_font(self._body_font, size=9)
            self.cell(cols[1] - 2, 5, f"{s.price_min:.0f}-{s.price_max:.0f}", align="L")
            self.set_text_color(*AppleColors.TEXT)
            self.cell(cols[2] - 2, 5, f"{s.probability:.0%}", align="L")
            self.set_text_color(*AppleColors.LABEL)
            self.cell(cols[3] - 2, 5, prob_bar, align="L")
            self.ln(row_h)

        self._line(AppleColors.BORDER, 0.3)
        self.ln(4)

    def drivers_section(self, bearish, bullish) -> None:
        self.ln(2)
        col_w = (self.PAGE_W - 2 * self.MARGIN - 6) / 2
        self.set_font(self._title_font, "B", 10)
        self.set_text_color(*AppleColors.RED)
        self.cell(col_w, 6, "BEARISH", align="L")
        self.set_text_color(*AppleColors.GREEN)
        self.cell(col_w + 6, 6, "BULLISH", align="R", ln=True)
        self._line(AppleColors.BORDER, 0.3)
        self.ln(2)

        max_rows = max(len(bearish), len(bullish))
        for i in range(max_rows):
            row_y = self.get_y()
            left_h = 0
            right_h = 0
            if i < len(bearish):
                p = bearish[i]
                self.set_font(self._body_font, size=8.5)
                self.set_text_color(*AppleColors.TEXT)
                self.set_x(self.MARGIN)
                self._mc(col_w, 4.5, f"- {p.param_name}", align="L")
                self.set_font(self._body_font, size=7.5)
                self.set_text_color(*AppleColors.LABEL)
                self.set_x(self.MARGIN)
                self._mc(col_w, 4, f"  {p.current_value} -- {p.narrative}", align="L")
                left_h = self.get_y() - row_y
            if i < len(bullish):
                p = bullish[i]
                self.set_font(self._body_font, size=8.5)
                self.set_text_color(*AppleColors.TEXT)
                self.set_xy(self.MARGIN + col_w + 6, row_y)
                self._mc(col_w, 4.5, f"- {p.param_name}", align="L")
                self.set_font(self._body_font, size=7.5)
                self.set_text_color(*AppleColors.LABEL)
                self.set_xy(self.MARGIN + col_w + 6, row_y + 4.5)
                self._mc(col_w, 4, f"  {p.current_value} -- {p.narrative}", align="L")
                right_h = self.get_y() - row_y
            row_h = max(left_h or 0, right_h or 0, 9)
            self.set_y(row_y + row_h)
        self.ln(4)

    def key_levels(self, support, resistance, climate_info=None) -> None:
        self.ln(2)
        col_w = (self.PAGE_W - 2 * self.MARGIN - 4) / 2
        self.set_font(self._title_font, "B", 10)
        self.set_text_color(*AppleColors.TEXT)
        self.set_x(self.MARGIN)
        self.cell(col_w, 6, "Support", align="L")
        self.set_x(self.MARGIN + col_w + 4)
        self.cell(col_w, 6, "Resistance", align="L", ln=True)
        self._line(AppleColors.BORDER, 0.3)
        self.ln(2)

        max_rows = max(len(support), len(resistance))
        for i in range(max_rows):
            row_y = self.get_y()
            if i < len(support):
                l = support[i]
                self.set_font(self._title_font, "B", 13)
                self.set_text_color(*AppleColors.GREEN)
                self.set_x(self.MARGIN)
                self.cell(col_w * 0.35, 7, f"{l.price:.2f}", align="L")
                self.set_font(self._body_font, size=8)
                self.set_text_color(*AppleColors.LABEL)
                self._cell(col_w * 0.65, 7, f" {l.label}", align="L")
            if i < len(resistance):
                l = resistance[i]
                self.set_font(self._title_font, "B", 13)
                self.set_text_color(*AppleColors.RED)
                self.set_xy(self.MARGIN + col_w + 4, row_y)
                self.cell(col_w * 0.35, 7, f"{l.price:.2f}", align="L")
                self.set_font(self._body_font, size=8)
                self.set_text_color(*AppleColors.LABEL)
                self._cell(col_w * 0.65, 7, f" {l.label}", align="L")
            self.ln(9)

        if climate_info:
            self.ln(2)
            c = climate_info
            phase_color = AppleColors.LABEL
            if c.get("oni_value", 0) < -0.5:
                phase_color = AppleColors.LABEL
            elif c.get("oni_value", 0) > 0.5:
                phase_color = AppleColors.RED
            self.set_font(self._body_font, size=8.5)
            self.set_text_color(*AppleColors.LABEL)
            self.cell(25, 5, "Climate / ONI:", align="L")
            self.set_text_color(*phase_color)
            self.set_font(self._body_font, "B", 8.5)
            self._cell(0, 5,
                f"{c.get('oni_value', 0):+.2f} ({c.get('oni_phase', '')})  {c.get('narrative', '')}",
                align="L", ln=True)
        self.ln(4)

    def hedge_panel(self, advice) -> None:
        self.ln(2)
        x0 = self.MARGIN
        w = self.PAGE_W - 2 * self.MARGIN
        self._fill(AppleColors.SURFACE)
        self.rect(x0, self.get_y(), w, 28, "F")
        self._fill(AppleColors.PRIMARY)
        self.rect(x0, self.get_y(), w, 2.5, "F")
        self.ln(2.5)

        self.set_font(self._title_font, "B", 12)
        self.set_text_color(*AppleColors.TEXT)
        self.set_x(x0 + 4)
        self.cell(40, 7, "Hedge Ratio", align="L")
        self.set_font(self._title_font, "B", 20)
        ratio_pct = int(advice.ratio * 100)
        self.set_text_color(AppleColors.PRIMARY)
        self.cell(25, 7, f"{ratio_pct}%", align="L")
        self.set_font(self._title_font, "B", 9)
        self.set_text_color(*AppleColors.LABEL)
        self.cell(0, 7, f"Signal: {advice.signal}", align="L", ln=True)

        self.set_x(x0 + 4)
        self.set_font(self._body_font, size=9)
        self.set_text_color(*AppleColors.TEXT)
        self._mc(w - 8, 5, advice.narrative, align="L")
        self.ln(1)

        triggers = []
        if advice.trigger_below:
            triggers.append(f"  ↓ Break {advice.trigger_below:.0f} → increase hedge to 75-80%")
        if advice.trigger_above:
            triggers.append(f"  ↑ Break {advice.trigger_above:.0f} → reduce hedge to 50%")
        if triggers:
            self.set_x(x0 + 4)
            self.set_font(self._body_font, size=8.5)
            self.set_text_color(*AppleColors.LABEL)
            self._mc(w - 8, 5, "  ".join(triggers), align="L")
        self.ln(6)

    # ── Full report builder ────────────────────────────────────────

    def build_from_report(self, report: PredictionReport) -> None:
        """Populate PDF from a PredictionReport."""
        self.add_page()
        r = report
        m = r.market

        # Title
        self.set_font(self._title_font, "B", 22)
        self.set_text_color(*AppleColors.TEXT)
        week_str = f"{r.forecast_week_start.strftime('%b %d')} - {r.forecast_week_end.strftime('%b %d')}"
        self.cell(0, 12, f"KC Futures Weekly Outlook", ln=True)
        self.set_font(self._body_font, size=10)
        self.set_text_color(*AppleColors.LABEL)
        self.cell(0, 6, f"{r.report_date}  |  Forecast: {week_str}", ln=True)
        self._line(AppleColors.BORDER)
        self.ln(4)

        if m:
            self.price_card(m)
        if r.related_markets:
            self.section_title("Related Markets", "[Rel]")
            self.related_markets_table(r.related_markets)
        if r.resistance_levels or r.support_levels:
            climate_d = {"oni_value": r.climate.oni_value, "oni_phase": r.climate.oni_phase,
                          "narrative": r.climate.narrative} if r.climate else None
            self.section_title("Key Levels", "[Levels]")
            self.key_levels(r.support_levels, r.resistance_levels, climate_d)
        if r.scenarios:
            self.section_title("Scenario Analysis", "[Scenarios]")
            self.scenario_table(r.scenarios)
        if r.bullish_params or r.bearish_params:
            self.section_title("Drivers", "[Drvr]")
            self.drivers_section(r.bearish_params, r.bullish_params)
        if r.hedge_advice:
            self.section_title("Hedge Advice", "[Hedge]️")
            self.hedge_panel(r.hedge_advice)
        if r.outlook or r.risk_warnings:
            self.section_title("Outlook", "[Outlook]")
            if r.outlook:
                self.set_font(self._body_font, size=10)
                self.set_text_color(*AppleColors.TEXT)
                self._mc(self.PAGE_W - 2 * self.MARGIN, 5, r.outlook, align="L")
                self.ln(2)
            if r.risk_warnings:
                self.set_font(self._body_font, "B", 9)
                self.set_text_color(*AppleColors.RED)
                self.cell(0, 6, "Risk Warnings:", ln=True)
                self.set_font(self._body_font, size=8.5)
                self.set_text_color(*AppleColors.LABEL)
                for rw in r.risk_warnings:
                    self.set_x(self.MARGIN + 2)
                    self._mc(self.PAGE_W - 2 * self.MARGIN - 4, 5, f"[!]  {rw}", align="L")

    def related_markets_table(self, markets) -> None:
        h = 7
        cols = [(self.PAGE_W - 2 * self.MARGIN) * f for f in [0.45, 0.35, 0.20]]
        headers = ["Market", "30d Change", ""]
        x_pos = [self.MARGIN]
        for c in cols[:-1]:
            x_pos.append(x_pos[-1] + c)
        self._fill(AppleColors.SURFACE)
        self.rect(self.MARGIN, self.get_y(), sum(cols), h, "F")
        self.set_font(self._body_font, "B", 8.5)
        self.set_text_color(*AppleColors.LABEL)
        for header, xp, cw in zip(headers, x_pos, cols):
            self.set_xy(xp + 2, self.get_y() + 2)
            self.cell(cw - 2, 4, header, align="L")
        self.ln(h)
        self._line(AppleColors.BORDER, 0.3)
        self.ln(1)
        for name, chg in markets.items():
            row_h = 6.5
            color = AppleColors.GREEN if chg > 0 else AppleColors.RED
            sign = "+" if chg > 0 else ""
            bar_w = min(abs(chg) / 10 * (cols[2] - 6), cols[2] - 6)
            bar_x = x_pos[2] + 3
            self.set_font(self._body_font, size=9)
            self.set_text_color(*AppleColors.TEXT)
            self.set_xy(x_pos[0] + 2, self.get_y() + 1)
            self.cell(cols[0] - 2, 4, name, align="L")
            self.set_text_color(*color)
            self.set_font(self._body_font, "B", 9)
            self.cell(cols[1] - 2, 4, f"{sign}{chg:.1f}%", align="L")
            self._fill(color)
            self.rect(bar_x, self.get_y() + 0.5, bar_w, 3.5, "F")
            self._fill(AppleColors.BORDER)
            self.set_line_width(0.3)
            self.rect(bar_x, self.get_y() + 0.5, cols[2] - 6, 3.5, "D")
            self.ln(row_h)
        self._line(AppleColors.BORDER, 0.3)
        self.ln(4)


# ─────────────────────────────────────────────────────────────────────────────
# Exporter function
# ─────────────────────────────────────────────────────────────────────────────

def export_pdf(report: PredictionReport, path: str = "coffee_outlook.pdf") -> str:
    """
    Export a PredictionReport to a PDF file.

    Args:
        report: PredictionReport instance.
        path: Output file path (default: coffee_outlook.pdf).

    Returns:
        The path to the written file.

    Raises:
        RuntimeError: if fpdf2 is not installed.
    """
    if not _HAS_FPDF:
        raise RuntimeError("fpdf2 is not installed — run: pip install fpdf2")

    pdf = CoffeePDF()
    pdf.build_from_report(report)
    pdf.output(path)
    return path
