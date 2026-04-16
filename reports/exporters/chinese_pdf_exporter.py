"""
reports/exporters/chinese_pdf_exporter.py
Professional Chinese-language coffee market report PDF using ReportLab + STHeiti.
"""

from __future__ import annotations

import os
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import mm

# ── Font registration (one-time, module-level) ──────────────────────────────

FONT_NAME = "STHeiti"

_registered = False

def _ensure_fonts():
    global _registered
    if _registered:
        return
    # Double-check: re-check after acquiring (guards against racing import)
    if _registered:
        return
    stht = "/System/Library/Fonts/STHeiti Medium.ttc"
    if os.path.exists(stht) and FONT_NAME not in pdfmetrics._fonts:
        pdfmetrics.registerFont(TTFont(FONT_NAME, stht, subfontIndex=0))
    _registered = True


# ── Color palette ─────────────────────────────────────────────────────────────

DARK_GREEN   = HexColor("#1a3a1a")
MED_GREEN    = HexColor("#2d6a2d")
LIGHT_GREEN  = HexColor("#d4edda")
DARK_RED     = HexColor("#8b1a1a")
MED_RED      = HexColor("#c0392b")
AMBER        = HexColor("#d4a017")
LIGHT_AMBER  = HexColor("#fef9e7")
GRAY         = HexColor("#555555")
LIGHT_GRAY   = HexColor("#f5f5f5")
MID_GRAY     = HexColor("#cccccc")
DARK_GRAY    = HexColor("#222222")
WHITE        = white
BLACK        = black


# ── Drawing helpers ──────────────────────────────────────────────────────────

class ChinesePDF:
    PAGE_W = 210 * mm
    PAGE_H = 297 * mm
    MARGIN = 15 * mm
    CONTENT_W = PAGE_W - 2 * MARGIN

    def __init__(self, path: str):
        _ensure_fonts()
        self._c = rl_canvas.Canvas(path, pagesize=(self.PAGE_W, self.PAGE_H))
        self._c.setTitle("咖啡期货周度市场报告")
        self._y = 0.0

    # ── Low-level primitives ─────────────────────────────────────────────────

    def _text(self, x, y, text, font=FONT_NAME, size=10, color=BLACK):
        self._c.setFont(font, size)
        self._c.setFillColor(color)
        self._c.drawString(x, y, text)

    def _rect(self, x, y, w, h, fill_color=None, stroke_color=None, radius=0):
        if fill_color:   self._c.setFillColor(fill_color)
        if stroke_color: self._c.setStrokeColor(stroke_color)
        self._c.roundRect(x, y, w, h, radius,
                          fill=bool(fill_color), stroke=bool(stroke_color))

    def _hline(self, y, color=MID_GRAY, width=0.5):
        self._c.setStrokeColor(color)
        self._c.setLineWidth(width)
        self._c.line(self.MARGIN, y, self.PAGE_W - self.MARGIN, y)

    def _move_down(self, h):
        self._y -= h

    def _reset_y(self):
        self._y = self.PAGE_H - self.MARGIN

    def _newpage(self):
        self._c.showPage()
        self._reset_y()

    def _ensure_space(self, needed):
        if self._y - needed < self.MARGIN + 15 * mm:
            self._newpage()

    def _section_title(self, title, color=DARK_GREEN):
        h = 7 * mm
        self._ensure_space(h + 3 * mm)
        self._rect(self.MARGIN, self._y - h, self.CONTENT_W, h,
                   fill_color=color)
        self._text(self.MARGIN + 3 * mm, self._y - 5 * mm, title,
                   FONT_NAME, 10, WHITE)
        self._move_down(h + 3 * mm)

    # ── Header banner ───────────────────────────────────────────────────────

    def _draw_header(self, ticker, report_date, week_start, week_end):
        y = self.PAGE_H - self.MARGIN
        banner_h = 18 * mm
        self._rect(self.MARGIN, y - banner_h, self.CONTENT_W, banner_h,
                   fill_color=DARK_GREEN)
        self._move_down(banner_h)

        self._text(self.MARGIN + 5 * mm, y - 9 * mm,
                   "咖啡期货市场周度报告", FONT_NAME, 16, WHITE)
        self._text(self.MARGIN + 5 * mm, y - 16 * mm,
                   f"报告日期: {report_date}  |  预测区间: {week_start} 至 {week_end}",
                   FONT_NAME, 8.5, HexColor("#aaddaa"))

        badge_x = self.PAGE_W - self.MARGIN - 32 * mm
        badge_y = y - banner_h + 3 * mm
        self._rect(badge_x, badge_y, 30 * mm, 12 * mm, fill_color=MED_GREEN)
        self._text(badge_x + 3 * mm, badge_y + 4 * mm,
                   f"KC=F {ticker}", FONT_NAME, 9, WHITE)

        self._move_down(6 * mm)

    # ── Market snapshot ─────────────────────────────────────────────────────

    def _draw_market(self, m):
        if not m:
            return
        self._ensure_space(45 * mm)
        box_h = 38 * mm
        y = self._y
        gap = 2 * mm
        price_w = 48 * mm

        self._rect(self.MARGIN, y - box_h, self.CONTENT_W, box_h,
                   fill_color=LIGHT_GRAY, stroke_color=MID_GRAY, radius=2)

        # Price block
        self._rect(self.MARGIN, y - box_h, price_w, box_h, fill_color=DARK_GREEN)
        self._text(self.MARGIN + 4 * mm, y - 9 * mm,
                   "当前价格", FONT_NAME, 8, HexColor("#aaddaa"))
        self._text(self.MARGIN + 4 * mm, y - 22 * mm,
                   f"{m.current:.2f}", FONT_NAME, 20, WHITE)
        self._text(self.MARGIN + 4 * mm, y - 30 * mm,
                   "美分/磅", FONT_NAME, 8, HexColor("#aaddaa"))
        chg = m.change_1d_pct or 0
        chg_clr = HexColor("#aaffaa") if chg >= 0 else HexColor("#ffaaaa")
        self._text(self.MARGIN + 4 * mm, y - 37 * mm,
                   f"{'+' if chg >= 0 else ''}{chg * 100:.2f}% (日间)",
                   FONT_NAME, 8, chg_clr)

        # Metric cards
        card_x = self.MARGIN + price_w + gap
        card_w = (self.CONTENT_W - price_w - gap) / 2 - gap / 2
        card_h = (box_h - 4 * mm) / 3
        card_top = y - 3 * mm

        metrics = [
            ("RSI (14)",    f"{m.rsi_14:.1f}" if m.rsi_14 else "N/A",
             HexColor("#8b1a1a") if (m.rsi_14 or 50) > 65 else HexColor("#1a7a1a") if (m.rsi_14 or 50) < 40 else GRAY),
            ("MA20",        f"{m.ma20:.2f}" if m.ma20 else "N/A", GRAY),
            ("MA60",        f"{m.ma60:.2f}" if m.ma60 else "N/A", GRAY),
            ("30日高",      f"{m.high_30d:.2f}" if m.high_30d else "N/A", MED_RED),
            ("30日低",      f"{m.low_30d:.2f}" if m.low_30d else "N/A", MED_GREEN),
            ("价格",        f"{m.current:.2f}", GRAY),
        ]

        for i, (label, val, val_clr) in enumerate(metrics):
            row = i // 2
            col = i % 2
            cx = card_x + col * (card_w + gap)
            cy = card_top - card_h * (row + 1)
            self._rect(cx, cy, card_w, card_h - 1 * mm,
                       fill_color=WHITE, stroke_color=MID_GRAY, radius=1)
            self._text(cx + 2 * mm, cy + card_h - 5 * mm,
                       label, FONT_NAME, 7, GRAY)
            self._text(cx + 2 * mm, cy + 2.5 * mm,
                       val, FONT_NAME, 10, val_clr)

        self._move_down(box_h + 4 * mm)

    # ── Scenarios + Hedge ───────────────────────────────────────────────────

    def _draw_scenarios(self, scenarios, h):
        self._ensure_space(60 * mm)
        self._section_title("情景分析 | SCENARIO ANALYSIS", DARK_GREEN)

        box_h = 22 * mm
        gap = 2 * mm
        n = len(scenarios) or 3
        box_w = (self.CONTENT_W - gap * (n - 1)) / n

        for i, s in enumerate(scenarios or []):
            bx = self.MARGIN + i * (box_w + gap)
            by = self._y - box_h

            if s.direction == "上涨":
                border = MED_GREEN; hdr = DARK_GREEN; txt_clr = MED_GREEN
            elif s.direction == "下跌":
                border = MED_RED;   hdr = DARK_RED;   txt_clr = MED_RED
            else:
                border = GRAY;     hdr = HexColor("#555"); txt_clr = GRAY

            self._rect(bx, by, box_w, box_h,
                       fill_color=WHITE, stroke_color=border, radius=2)
            self._rect(bx, by + box_h - 7 * mm, box_w, 7 * mm, fill_color=hdr)

            self._text(bx + 2 * mm, by + box_h - 5 * mm,
                       s.label, FONT_NAME, 7.5, WHITE)
            self._text(bx + box_w - 14 * mm, by + box_h - 5 * mm,
                       f"{s.probability:.0f}%", FONT_NAME, 9, WHITE)

            self._text(bx + 2 * mm, by + box_h - 14 * mm,
                       "价格区间", FONT_NAME, 6.5, GRAY)
            self._text(bx + 2 * mm, by + box_h - 22 * mm,
                       f"{s.price_min:.0f} – {s.price_max:.0f}",
                       FONT_NAME, 11, txt_clr)
            self._text(bx + 2 * mm, by + 3 * mm,
                       f"方向: {s.direction}", FONT_NAME, 7.5, txt_clr)

        self._move_down(box_h + 4 * mm)

        # Hedge advice
        if h:
            self._ensure_space(24 * mm)
            hedge_h = 20 * mm
            self._rect(self.MARGIN, self._y - hedge_h, self.CONTENT_W, hedge_h,
                       fill_color=LIGHT_GREEN, stroke_color=DARK_GREEN, radius=2)
            self._text(self.MARGIN + 4 * mm, self._y - 6 * mm,
                       "套保建议 | HEDGE ADVICE", FONT_NAME, 9.5, DARK_GREEN)
            self._text(self.MARGIN + 4 * mm, self._y - 13 * mm,
                       f"建议套保比率: {int(h.ratio * 100)}%  — {h.signal}",
                       FONT_NAME, 9, DARK_GREEN)
            # Wrap narrative
            self._text(self.MARGIN + 4 * mm, self._y - 19 * mm,
                       h.narrative[:65], FONT_NAME, 8, GRAY)
            self._move_down(hedge_h + 4 * mm)

    # ── Levels ──────────────────────────────────────────────────────────────

    def _draw_levels(self, supports, resistances):
        self._ensure_space(40 * mm)
        self._section_title("关键价位 | KEY LEVELS", DARK_GRAY)

        hdr_h = 7 * mm
        row_h = 7 * mm
        col1 = 30 * mm
        col2 = self.CONTENT_W - col1

        # Header
        y = self._y
        self._rect(self.MARGIN, y - hdr_h, self.CONTENT_W, hdr_h, fill_color=DARK_GREEN)
        self._text(self.MARGIN + 3 * mm, y - 5 * mm,
                   "支撑 SUPPORT", FONT_NAME, 8.5, WHITE)
        self._text(self.MARGIN + col1 + 4 * mm, y - 5 * mm,
                   "阻力 RESISTANCE", FONT_NAME, 8.5, WHITE)
        self._move_down(hdr_h)

        max_rows = max(len(supports or []), len(resistances or []))
        for i in range(max_rows):
            self._ensure_space(row_h)
            ry = self._y

            s_lbl = supports[i].label if i < len(supports or []) else ""
            s_val = supports[i].price if i < len(supports or []) else 0
            r_lbl = resistances[i].label if i < len(resistances or []) else ""
            r_val = resistances[i].price if i < len(resistances or []) else 0

            self._rect(self.MARGIN, ry - row_h + 1 * mm, col1, row_h - 1 * mm,
                       fill_color=LIGHT_GREEN, stroke_color=MID_GRAY, radius=1)
            self._text(self.MARGIN + 2 * mm, ry - 5 * mm,
                       f"{s_val:.2f}", FONT_NAME, 9, DARK_GREEN)
            self._text(self.MARGIN + 22 * mm, ry - 5 * mm,
                       s_lbl, FONT_NAME, 7.5, GRAY)

            self._rect(self.MARGIN + col1 + 3 * mm, ry - row_h + 1 * mm,
                       col2 - 3 * mm, row_h - 1 * mm,
                       fill_color=HexColor("#fff0f0"), stroke_color=MID_GRAY, radius=1)
            self._text(self.MARGIN + col1 + 5 * mm, ry - 5 * mm,
                       f"{r_val:.2f}", FONT_NAME, 9, DARK_RED)
            self._text(self.MARGIN + col1 + 25 * mm, ry - 5 * mm,
                       r_lbl, FONT_NAME, 7.5, GRAY)

            self._move_down(row_h)

        self._move_down(4 * mm)

    # ── Drivers ─────────────────────────────────────────────────────────────

    def _draw_drivers(self, bullish, bearish, climate_narrative):
        self._ensure_space(50 * mm)
        self._section_title("多空驱动 | DRIVERS", DARK_GRAY)

        if climate_narrative:
            self._ensure_space(9 * mm)
            cl = 8 * mm
            self._rect(self.MARGIN, self._y - cl, self.CONTENT_W, cl,
                       fill_color=LIGHT_AMBER, stroke_color=AMBER, radius=1)
            self._text(self.MARGIN + 3 * mm, self._y - 5.5 * mm,
                       f"气候背景: {climate_narrative}", FONT_NAME, 8.5,
                       HexColor("#7a6000"))
            self._move_down(cl + 3 * mm)

        col_w = self.CONTENT_W / 2 - 2 * mm
        for side, params, hdr_bg, label in [
            (True,  bullish, DARK_GREEN, "▲ 利多因素 BULLISH"),
            (False, bearish, DARK_RED,   "▼ 利空因素 BEARISH"),
        ]:
            bx = self.MARGIN if side else self.MARGIN + col_w + 4 * mm
            items = params or []
            box_h = max(10 * mm, len(items) * 6 * mm + 10 * mm)

            self._ensure_space(box_h + 2 * mm)
            by = self._y

            self._rect(bx, by - box_h, col_w, box_h,
                       fill_color=WHITE, stroke_color=hdr_bg, radius=2)
            self._rect(bx, by - 8 * mm, col_w, 8 * mm, fill_color=hdr_bg)
            self._text(bx + 3 * mm, by - 5.5 * mm, label, FONT_NAME, 8.5, WHITE)

            iy = by - 11 * mm
            for p in items:
                if iy - 6 * mm < by - box_h + 2 * mm:
                    break
                self._text(bx + 3 * mm, iy,
                           f"• {p.param_name}", FONT_NAME, 7.5, hdr_bg)
                self._text(bx + 5 * mm, iy - 4 * mm,
                           p.narrative[:48], FONT_NAME, 6.5, GRAY)
                iy -= 7 * mm

            self._move_down(box_h + 3 * mm)

    # ── Outlook & Risks ────────────────────────────────────────────────────

    def _draw_outlook(self, outlook, risks):
        self._ensure_space(45 * mm)
        self._section_title("市场展望 | MARKET OUTLOOK", DARK_GRAY)

        if outlook:
            self._ensure_space(20 * mm)
            oh = 18 * mm
            self._rect(self.MARGIN, self._y - oh, self.CONTENT_W, oh,
                       fill_color=LIGHT_GREEN, stroke_color=MED_GREEN, radius=2)
            # Two lines
            self._text(self.MARGIN + 4 * mm, self._y - 7 * mm,
                       outlook[:60], FONT_NAME, 9.5, DARK_GREEN)
            if len(outlook) > 60:
                self._text(self.MARGIN + 4 * mm, self._y - 14 * mm,
                           outlook[60:120], FONT_NAME, 9.5, DARK_GREEN)
            self._move_down(oh + 3 * mm)

        if risks:
            self._ensure_space(8 * mm + len(risks) * 5.5 * mm + 3 * mm)
            rh = 7 * mm + len(risks) * 5.5 * mm
            self._rect(self.MARGIN, self._y - rh, self.CONTENT_W, rh,
                       fill_color=LIGHT_AMBER, stroke_color=AMBER, radius=1)
            self._text(self.MARGIN + 3 * mm, self._y - 5.5 * mm,
                       "⚠ 风险提示 | RISK WARNINGS", FONT_NAME, 8.5,
                       HexColor("#7a6000"))
            ry = self._y - 11 * mm
            for r in risks:
                self._text(self.MARGIN + 3 * mm, ry,
                           f"⚠ {r}", FONT_NAME, 7.5, HexColor("#8b6000"))
                ry -= 5.5 * mm
            self._move_down(rh + 4 * mm)

    # ── Footer ─────────────────────────────────────────────────────────────

    def _draw_footer(self):
        y = self.MARGIN
        self._hline(y, color=MID_GRAY)
        self._text(self.MARGIN, y - 4 * mm,
                   "本报告仅供决策参考，不构成投资建议。",
                   FONT_NAME, 7, GRAY)
        self._text(self.PAGE_W - self.MARGIN - 55 * mm, y - 4 * mm,
                   "Generated by Coffee V3 System",
                   FONT_NAME, 7, GRAY)

    # ── Main build ─────────────────────────────────────────────────────────

    def build(self, report):
        _ensure_fonts()
        self._reset_y()

        self._draw_header(
            report.ticker,
            str(report.report_date),
            str(report.forecast_week_start),
            str(report.forecast_week_end),
        )

        self._draw_market(report.market)

        self._draw_scenarios(report.scenarios, report.hedge_advice)

        self._draw_levels(report.support_levels or [],
                          report.resistance_levels or [])

        self._draw_drivers(
            report.bullish_params or [],
            report.bearish_params or [],
            report.climate.narrative if report.climate else "",
        )

        self._draw_outlook(report.outlook, report.risk_warnings or [])

        self._draw_footer()

        self._c.save()
        return self._c.getpdfdata()
