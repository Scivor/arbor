"""
reports/pdf_export.py
Coffee Futures Weekly Outlook — Apple-style PDF Export

依赖: fpdf2
    pip install fpdf2
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict
from datetime import date, datetime
from typing import Optional

from fpdf import FPDF
from fpdf.enums import TableCellFillMode


# ─── Apple 风格配色 ────────────────────────────────────────────

class AppleColors:
    """Apple Human Interface Guidelines 配色"""
    BACKGROUND = (255, 255, 255)       # 纯白
    SURFACE    = (248, 248, 248)      # 浅灰白（卡片背景）
    LABEL      = (120, 120, 128)      # 次要标签
    PRIMARY    = (0, 112, 209)        # Apple Blue
    GREEN      = (52, 199, 89)        # Bullish / 正
    RED        = (255, 59, 48)         # Bearish / 负
    YELLOW     = (255, 204, 0)         # Warning
    TEXT       = (29, 29, 31)          # 主文本
    BORDER     = (220, 220, 227)       # 分割线
    COFFEE     = (139, 90, 43)        # 咖啡棕


# ─── PDF 文档 ─────────────────────────────────────────────────

class CoffeePDF(FPDF):
    """
    Apple 风格 Coffee Futures 报告 PDF
    - Helvetica Neue / SF Pro 风格字体
    - 绿涨红跌配色
    - 清晰的信息层级
    """

    MARGIN = 18       # 左右边距 (mm)
    PAGE_W = 210     # A4
    PAGE_H = 297     # A4

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(left=self.MARGIN, top=15, right=self.MARGIN)

        # 字体策略：Hiragino 支持中英文混排，helvetica 提供 B/BI 样式
        # 注册顺序重要：先注册 Hiragino，再用 helvetica
        self.add_font("hiragino", fname="/System/Library/Fonts/Hiragino Sans GB.ttc")
        self._cn_font = "hiragino"     # 中文
        self._title_font = "helvetica"  # 英文标题（支持 bold）
        self._body_font = "helvetica"   # 英文正文（支持 bold）

        # 状态
        self._section_count = 0
        self._page_count = 0

    # ─── 页面控制 ─────────────────────────────────────────────

    def header(self) -> None:
        """每页页眉"""
        self._page_count += 1
        if self._page_count > 1:
            # 后续页面：简洁顶栏
            self.set_font(self._body_font, size=8)
            self.set_text_color(*AppleColors.LABEL)
            self.cell(0, 6, f"KC=F Weekly Outlook  |  {self._page_count - 1}", align="R")
            self.ln(4)
            self._draw_line(AppleColors.BORDER)
            self.ln(5)

    def footer(self) -> None:
        """每页页脚"""
        self.set_y(-15)
        self.set_font(self._body_font, size=8)
        self.set_text_color(*AppleColors.LABEL)
        self.cell(0, 8, f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Coffee V3.0", align="C")

    # ─── 绘图工具 ─────────────────────────────────────────────

    def _draw_line(self, color: tuple, width: float = 0.3) -> None:
        self.set_draw_color(*color)
        self.set_line_width(width)
        self.line(self.MARGIN, self.get_y(), self.PAGE_W - self.MARGIN, self.get_y())

    def _set_color(self, color: tuple) -> None:
        self.set_fill_color(*color)
        self.set_draw_color(*color)

    def _rgb_hex(self, color: tuple) -> str:
        return "#{02x}{02x}{02x}".format(*color)

    def _cn(self, text) -> bool:
        """检测文本是否包含非ASCII字符（中文等）"""
        if not isinstance(text, str):
            return False
        return bool(text and not all(ord(c) < 128 for c in text))

    def _set_font_for_text(self, text, style: str = "", size: float = None) -> None:
        """根据文本内容自动选择字体（中文字 → Hiragino，英文 → helvetica）"""
        if self._cn(text):
            self.set_font(self._cn_font, style, size)
        else:
            self.set_font(self._body_font, style, size)

    def _cell(self, *args, **kwargs) -> None:
        """cell 包装：自动为含中文文本选择正确字体"""
        text = args[2] if len(args) > 2 else kwargs.get("text", "")
        if self._cn(text):
            cur = self._body_font
            self.set_font(self._cn_font)
            self.cell(*args, **kwargs)
            self.set_font(cur)
        else:
            self.cell(*args, **kwargs)

    def _mc(self, *args, **kwargs) -> None:
        """multi_cell 包装：自动为含中文文本选择正确字体"""
        text = args[1] if len(args) > 1 else kwargs.get("text", "")
        if self._cn(text):
            cur = self._body_font
            self.set_font(self._cn_font)
            self.multi_cell(*args, **kwargs)
            self.set_font(cur)
        else:
            self.multi_cell(*args, **kwargs)

    # ─── 区块标题 ─────────────────────────────────────────────

    # ─── 区块标题 ─────────────────────────────────────────────

    def section_title(self, title: str, icon: str = "") -> None:
        """Apple 风格区块标题"""
        self._section_count += 1
        self.ln(6)
        self.set_font(self._title_font, "B", 13)
        self.set_text_color(*AppleColors.TEXT)
        text = f"{icon}  {title}" if icon else title
        self.cell(0, 8, text, ln=True)
        self._draw_line(AppleColors.BORDER, 0.5)
        self.ln(3)

    # ─── 价格卡片 ─────────────────────────────────────────────

    def price_card(self, current: float, change_1d: float, change_30d: float,
                   rsi: float, ma20: float, ma60: float,
                   high_30d: float, low_30d: float,
                   closes: list[float], vol_ratios: list[float]) -> None:
        """
        价格概览卡片 — Apple 风格
        顶部大数字 + 次要信息网格 + 迷你趋势线
        """
        # 背景卡片
        x0 = self.MARGIN
        w = self.PAGE_W - 2 * self.MARGIN
        self._set_color(AppleColors.SURFACE)
        self.rect(x0, self.get_y(), w, 46, "F")

        # 价格大字
        self.set_xy(x0 + 4, self.get_y() + 4)
        self.set_font(self._title_font, "B", 36)
        color = AppleColors.GREEN if change_1d >= 0 else AppleColors.RED
        self.set_text_color(*color)
        sign = "+" if change_1d >= 0 else ""
        self.cell(55, 14, f"{sign}{current:.2f}", align="L")
        self.set_font(self._body_font, size=10)
        self.set_text_color(*AppleColors.LABEL)
        self.cell(0, 14, f"cents/lb", align="L", ln=True)

        # 次要信息行
        self.set_x(x0 + 4)
        self.set_font(self._body_font, size=9)
        self.set_text_color(*AppleColors.LABEL)
        self.cell(28, 5, f"Today: ", align="L")
        self.set_text_color(*color)
        self.cell(20, 5, f"{sign}{change_1d:.2f}%", align="L")
        self.set_text_color(*AppleColors.LABEL)
        self.cell(20, 5, f"30d: ", align="L")
        color30 = AppleColors.GREEN if change_30d >= 0 else AppleColors.RED
        self.set_text_color(*color30)
        self.cell(20, 5, f"{sign}{change_30d:.1f}%", align="L")
        self.set_text_color(*AppleColors.LABEL)
        self.cell(25, 5, f"RSI(14): ", align="L")
        rsi_color = AppleColors.RED if rsi < 35 else AppleColors.GREEN if rsi > 65 else AppleColors.LABEL
        self.set_text_color(*rsi_color)
        self.cell(15, 5, f"{rsi:.1f}", align="L")
        self.ln(6)

        # MA + 30d 区间
        self.set_x(x0 + 4)
        self.set_font(self._body_font, size=9)
        self.set_text_color(*AppleColors.LABEL)
        ma_trend = "^" if current > ma20 else "v"
        self.cell(40, 5, f"MA20: {ma20:.2f} {ma_trend}", align="L")
        ma60_trend = "^" if current > ma60 else "v"
        self.cell(45, 5, f"MA60: {ma60:.2f} {ma60_trend}", align="L")
        self.set_text_color(*AppleColors.LABEL)
        self.cell(35, 5, f"30d Range: {low_30d:.1f}-{high_30d:.1f}", align="L")
        self.ln(7)

        # 近5日收盘趋势（用 fpdf 画线图）
        self.set_x(x0 + 4)
        self._draw_price_sparkline(closes, x0 + 4, self.get_y(), w - 8, 14)
        self.ln(16)

    def _draw_price_sparkline(self, data: list[float], x: float, y: float,
                               width: float, height: float) -> None:
        """在指定区域绘制价格迷你折线图"""
        if not data:
            return
        self.set_draw_color(*AppleColors.PRIMARY)
        self.set_line_width(0.5)

        min_d, max_d = min(data), max(data)
        span = max_d - min_d
        if span == 0:
            span = 1

        step_x = width / max(len(data) - 1, 1)
        pts = []
        for i, v in enumerate(data):
            px = x + i * step_x
            py = y + height - ((v - min_d) / span * (height - 2))
            pts.append((px, py))

        for i in range(len(pts) - 1):
            self.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])

        # 最后一个点标记
        last = pts[-1]
        self.set_fill_color(*AppleColors.PRIMARY)
        self.ellipse(last[0] - 1.5, last[1] - 1.5, 3, 3, "F")

    # ─── 情景表格 ─────────────────────────────────────────────

    def scenario_table(self, scenarios: list) -> None:
        """概率情景表格"""
        self.ln(2)
        # 表头
        self._set_color(AppleColors.SURFACE)
        h = 8
        cols = [28, 30, 22, 58]
        headers = ["Scenario", "Range", "Prob", "Rationale"]
        x_positions = [self.MARGIN]
        for c in cols[:-1]:
            x_positions.append(x_positions[-1] + c)

        # 标题行背景
        self.rect(self.MARGIN, self.get_y(), sum(cols), h, "F")
        self.set_font(self._body_font, "B", 9)
        self.set_text_color(*AppleColors.LABEL)
        for i, (header, xp, cw) in enumerate(zip(headers, x_positions, cols)):
            self.set_xy(xp + 2, self.get_y() + 2)
            self.cell(cw - 2, 5, header, align="L")
        self.ln(h)
        self._draw_line(AppleColors.BORDER, 0.3)
        self.ln(1)

        # 数据行
        for s in scenarios:
            row_h = 9
            # 背景（隔行变色）
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

            # 概率条（灰度）
            self.set_text_color(*AppleColors.LABEL)
            self.cell(cols[3] - 2, 5, prob_bar, align="L")

            self.ln(row_h)

        self._draw_line(AppleColors.BORDER, 0.3)
        self.ln(4)

    # ─── 驱动因子 ─────────────────────────────────────────────

    def drivers_section(self, bearish: list, bullish: list) -> None:
        """驱动因子列表 — 两栏布局"""
        self.ln(2)
        col_w = (self.PAGE_W - 2 * self.MARGIN - 6) / 2

        # 列标题
        self.set_font(self._title_font, "B", 10)
        self.set_text_color(*AppleColors.RED)
        self.cell(col_w, 6, "BEARISH", align="L")
        self.set_text_color(*AppleColors.GREEN)
        self.cell(col_w + 6, 6, "BULLISH", align="R", ln=True)
        self._draw_line(AppleColors.BORDER, 0.3)
        self.ln(2)

        max_rows = max(len(bearish), len(bullish))
        for i in range(max_rows):
            row_y = self.get_y()
            # 左栏
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
            else:
                left_h = 0

            # 右栏
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
            else:
                right_h = 0

            row_h = max(left_h or 0, right_h or 0, 9)
            self.set_y(row_y + row_h)

        self.ln(4)

    # ─── 关联市场 ─────────────────────────────────────────────

    def related_markets_table(self, markets: dict) -> None:
        """关联品种表现表"""
        self.ln(2)
        h = 7
        cols = [(self.PAGE_W - 2 * self.MARGIN) * f for f in [0.45, 0.35, 0.20]]
        headers = ["Market", "30d Change", ""]
        x_pos = [self.MARGIN]
        for c in cols[:-1]:
            x_pos.append(x_pos[-1] + c)

        # 表头
        self._set_color(AppleColors.SURFACE)
        self.rect(self.MARGIN, self.get_y(), sum(cols), h, "F")
        self.set_font(self._body_font, "B", 8.5)
        self.set_text_color(*AppleColors.LABEL)
        for header, xp, cw in zip(headers, x_pos, cols):
            self.set_xy(xp + 2, self.get_y() + 2)
            self.cell(cw - 2, 4, header, align="L")
        self.ln(h)
        self._draw_line(AppleColors.BORDER, 0.3)
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

            # 迷你柱状条
            self._set_color(color)
            self.rect(bar_x, self.get_y() + 0.5, bar_w, 3.5, "F")
            self._set_color(AppleColors.BORDER)
            self.set_line_width(0.3)
            self.rect(bar_x, self.get_y() + 0.5, cols[2] - 6, 3.5, "D")

            self.ln(row_h)

        self._draw_line(AppleColors.BORDER, 0.3)
        self.ln(4)

    # ─── 关键价位 ─────────────────────────────────────────────

    def key_levels(self, support: list, resistance: list, climate_info: dict = None) -> None:
        """关键支撑阻力位"""
        self.ln(2)
        col_w = (self.PAGE_W - 2 * self.MARGIN - 4) / 2

        # 标题行
        self.set_font(self._title_font, "B", 10)
        self.set_text_color(*AppleColors.TEXT)
        self.set_x(self.MARGIN)
        self.cell(col_w, 6, "Support", align="L")
        self.set_x(self.MARGIN + col_w + 4)
        self.cell(col_w, 6, "Resistance", align="L", ln=True)
        self._draw_line(AppleColors.BORDER, 0.3)
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

        # 气候信息
        if climate_info:
            self.ln(2)
            c = climate_info
            phase_color = AppleColors.BLUE if c.get("oni_value", 0) < -0.5 else \
                          AppleColors.RED if c.get("oni_value", 0) > 0.5 else AppleColors.LABEL
            self.set_font(self._body_font, size=8.5)
            self.set_text_color(*AppleColors.LABEL)
            self.cell(25, 5, "Climate / ONI:", align="L")
            self.set_text_color(*phase_color)
            self.set_font(self._body_font, "B", 8.5)
            self._cell(0, 5, f"{c.get('oni_value', 0):+.2f} ({c.get('oni_phase', '')})  {c.get('narrative', '')}",
                      align="L", ln=True)

        self.ln(4)

    # ─── 套保建议 ─────────────────────────────────────────────

    def hedge_advice_panel(self, advice: dict) -> None:
        """套保建议面板"""
        self.ln(2)
        x0 = self.MARGIN
        w = self.PAGE_W - 2 * self.MARGIN

        # 面板背景
        self._set_color(AppleColors.SURFACE)
        self.rect(x0, self.get_y(), w, 28, "F")

        # 顶部色条
        self._set_color(AppleColors.PRIMARY)
        self.rect(x0, self.get_y(), w, 2.5, "F")
        self.ln(2.5)

        # 标题
        self.set_font(self._title_font, "B", 12)
        self.set_text_color(*AppleColors.TEXT)
        self.set_x(x0 + 4)
        self.cell(40, 7, "Hedge Ratio", align="L")
        self.set_font(self._title_font, "B", 20)
        ratio = advice.get("ratio", 0.65)
        ratio_pct = int(ratio * 100)
        self.set_text_color(AppleColors.PRIMARY)
        self.cell(25, 7, f"{ratio_pct}%", align="L")
        self.set_font(self._title_font, "B", 9)
        self.set_text_color(*AppleColors.LABEL)
        self.cell(0, 7, f"Signal: {advice.get('signal', '')}", align="L", ln=True)

        # 叙事
        self.set_font(self._body_font, size=9)
        self.set_text_color(*AppleColors.TEXT)
        self.set_x(x0 + 4)
        self._mc(w - 8, 5, advice.get("narrative", ""), align="L")

        # 触发条件
        self.ln(1)
        self.set_x(x0 + 4)
        self.set_font(self._body_font, size=8.5)
        if advice.get("trigger_below"):
            self.set_text_color(*AppleColors.RED)
            self.cell(0, 5, f"v If price breaks {advice['trigger_below']:.0f} -> increase hedge to 75-80%", align="L")
            self.ln(5)
        if advice.get("trigger_above"):
            self.set_x(x0 + 4)
            self.set_text_color(*AppleColors.GREEN)
            self.cell(0, 5, f"^ If price breaks {advice['trigger_above']:.0f} -> reduce hedge to 50%", align="L")
            self.ln(5)

        self.ln(5)

    # ─── 风险提示 ─────────────────────────────────────────────

    def risk_warnings(self, warnings: list) -> None:
        """风险警告区块"""
        if not warnings:
            return
        self.ln(2)
        x0 = self.MARGIN
        w = self.PAGE_W - 2 * self.MARGIN

        # 黄色背景
        self._set_color((255, 249, 230))
        self.rect(x0, self.get_y(), w, 5 + len(warnings) * 6, "F")

        self.set_font(self._title_font, "B", 9)
        self.set_text_color(*AppleColors.YELLOW)
        self.set_x(x0 + 3)
        self.ln(3)
        self.cell(w - 6, 5, "[!]  Risk Warnings", ln=True)

        self.set_font(self._body_font, size=8.5)
        self.set_text_color(*AppleColors.TEXT)
        for warn in warnings:
            self.set_x(x0 + 3)
            self.cell(w - 6, 5.5, f"- {warn}", ln=True)

        self.ln(6)

    # ─── 核心观点 ─────────────────────────────────────────────

    def outlook_box(self, text: str) -> None:
        """核心观点文本框"""
        self.ln(2)
        x0 = self.MARGIN
        w = self.PAGE_W - 2 * self.MARGIN

        # 左侧色条
        self._set_color(AppleColors.PRIMARY)
        self.rect(x0, self.get_y(), 2, 16, "F")

        # 背景
        self._set_color(AppleColors.SURFACE)
        self.rect(x0 + 2, self.get_y(), w - 2, 16, "F")

        self.set_xy(x0 + 6, self.get_y() + 2)
        self.set_font(self._title_font, "B", 10)
        self.set_text_color(AppleColors.PRIMARY)
        self.cell(20, 5, "OUTLOOK", align="L")
        self.set_font(self._body_font, size=9)
        self.set_text_color(*AppleColors.TEXT)
        self.ln(7)
        self.set_x(x0 + 6)
        self.multi_cell(w - 10, 5, text, align="L")
        self.ln(6)


# ─── 主导出函数 ────────────────────────────────────────────────

def _build_en_report():
    """Build English-only demo report for PDF export (avoids CJK font complexity)."""
    from dataclasses import dataclass, field
    from datetime import date, timedelta

    @dataclass
    class MarketSnapshot:
        ticker: str = "KC=F"; current: float = 293.70
        change_1d_pct: float = -0.10; change_30d_pct: float = -15.4
        high_30d: float = 383.85; low_30d: float = 278.65
        volume_ratio: float = 1.5; ma20: float = 300.43; ma60: float = 309.38
        rsi_14: float = 38.6
        close_5d: list = field(default_factory=lambda: [295.40, 298.05, 286.10, 294.05, 293.70])
        vol_ratio_5d: list = field(default_factory=lambda: [1.5, 0.7, 2.0, 1.7, 1.5])

    @dataclass
    class ClimateSnapshot:
        oni_value: float = -0.39; oni_phase: str = "NEUTRAL"
        oni_period: str = "DJF 2026"; narrative: str = "La Nina weakening to neutral, no major climate premium in Q1 2026"

    @dataclass
    class Level:
        price: float = 0; label: str = ""; strength: str = "MEDIUM"

    @dataclass
    class Scenario:
        label: str = ""; direction: str = "NEUTRAL"
        price_min: float = 0; price_max: float = 0
        probability: float = 0.0; rationale: list = field(default_factory=list)

    @dataclass
    class SupportParam:
        category: str = ""; param_name: str = ""; current_value: str = ""
        signal: str = ""; weight: str = "WEAK"; narrative: str = ""

    @dataclass
    class ResistParam(SupportParam): pass

    @dataclass
    class HedgeAdvice:
        ratio: float = 0.65; signal: str = "MEDIUM_HEDGE"; narrative: str = ""
        trigger_below: float = None; trigger_above: float = None

    @dataclass
    class PredictionReport:
        ticker: str = "KC=F"; report_date: date = field(default_factory=date.today)
        forecast_week_start: date = None; forecast_week_end: date = None
        market: MarketSnapshot = None; related_markets: dict = field(default_factory=dict)
        climate: ClimateSnapshot = None; resistance_levels: list = field(default_factory=list)
        support_levels: list = field(default_factory=list); scenarios: list = field(default_factory=list)
        bullish_params: list = field(default_factory=list); bearish_params: list = field(default_factory=list)
        hedge_advice: HedgeAdvice = None; outlook: str = ""; risk_warnings: list = field(default_factory=list)

    m = MarketSnapshot()
    climate = ClimateSnapshot()
    support_levels = [
        Level(price=288.30, label="Key Support", strength="KEY"),
        Level(price=284.60, label="Feb Low", strength="KEY"),
        Level(price=280.00, label="Deep Support", strength="MEDIUM"),
    ]
    resistance_levels = [
        Level(price=301.70, label="Near Resistance", strength="KEY"),
        Level(price=304.50, label="21-day MA", strength="MEDIUM"),
        Level(price=309.75, label="Prior High", strength="MEDIUM"),
    ]
    scenarios = [
        Scenario(label="Bearish", direction="BEARISH", price_min=278, price_max=288,
                 probability=0.35, rationale=["Macro risk-off continues, Gold breaks down, 288 support breached"]),
        Scenario(label="Neutral", direction="NEUTRAL", price_min=288, price_max=302,
                 probability=0.40, rationale=["Range-bound, 288-302 consolidation, direction unclear"]),
        Scenario(label="Rally", direction="BULLISH", price_min=302, price_max=312,
                 probability=0.20, rationale=["288 holds + short covering, technical rebound"]),
        Scenario(label="Bullish", direction="BULLISH", price_min=312, price_max=330,
                 probability=0.05, rationale=["Macro safe-haven + weather catalyst needed, low probability"]),
    ]
    bearish = [
        ResistParam("Technical", "MA Bearish Alignment", "Price<MA20<MA60", "Clear downtrend", "STRONG", "Layers of MA resistance, rallies fail"),
        ResistParam("Technical", "Lower Highs Sequence", "352->333->309->301", "Downtrend intact", "STRONG", "Each rally prints a lower high"),
        ResistParam("Macro", "Gold Selloff", "GC=F -6.9%", "Global risk-off", "STRONG", "Gold breaks down, commodities under systemic pressure"),
        ResistParam("Macro", "DJIA Drop", "DJIA -4.0%", "Risk assets sold", "MEDIUM", "Macro environment hostile to risk assets"),
        ResistParam("Technical", "RSI Not Oversold", "RSI=38.6", "No oversold bounce yet", "MEDIUM", "No technical rebound condition"),
        ResistParam("Seasonal", "Brazil Harvest Peak", "April supply surge", "Peak annual supply", "MEDIUM", "Annual supply cycle at maximum"),
        ResistParam("Climate", "La Nina Fading", "ONI -0.39->0", "No weather premium", "MEDIUM", "Climate premium has unwound"),
        ResistParam("Commodity", "Sugar Also Falls", "SB=F -1.3%", "Soft commodities down", "MEDIUM", "Not a single-name move, systemic"),
    ]
    bullish = [
        SupportParam("Technical", "288 Key Support", "293.70 vs 288.30", "5.4 cents to support", "MEDIUM", "Limited downside if 288 holds"),
        SupportParam("Technical", "RSI Mid-Low", "RSI=38.6", "Not oversold, room to run", "WEAK", "Volume picked up but no tech bounce yet"),
        SupportParam("Technical", "Apr 7 Volume Spike", "1.9x avg volume", "Selling pressure released", "MEDIUM", "If 288 holds, volume flips bullish"),
        SupportParam("Seasonal", "Feb Historical Low", "284.60 area", "Seasonal bottom zone", "MEDIUM", "April sits in annual low range"),
        SupportParam("Fundamental", "Historical Low Stocks", "ICE certified stocks low", "Structural support", "MEDIUM", "Deep selloff unlikely given stocks"),
        SupportParam("Macro", "Cocoa Contra", "CC=F +0.8%", "Sector rotation", "WEAK", "Agri strength may spill into coffee"),
    ]
    hedge = HedgeAdvice(
        ratio=0.65, signal="MEDIUM_HEDGE",
        narrative="Maintain 65% static hedge, wait for 288 breakout direction before adjusting",
        trigger_below=288.30, trigger_above=301.70,
    )
    outlook = (
        "Price neutral-to-weak next week, core range 284-302. "
        "Macro risk-off + MA bearish alignment + downtrend pressure "
        "outweigh structural support from low stocks. "
        "288 key support faces test. Maintain 65% hedge if 288 holds; "
        "increase to 75-80% on break below 288; "
        "reduce to 50% on break above 301.70."
    )
    risks = [
        "Gold acceleration below 4600 could trigger broad commodity selloff, rapid 288 test",
        "USD strength / BRL weakness could trigger Brazilian export selling pressure",
        "April rainfall forecast improvement could ease supply concerns and cap rallies",
    ]

    today = date.today()
    days_ahead = (7 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    week_start = today + timedelta(days=days_ahead)
    week_end = week_start + timedelta(days=4)

    return PredictionReport(
        ticker="KC=F",
        report_date=today,
        forecast_week_start=week_start,
        forecast_week_end=week_end,
        market=m,
        related_markets={"Gold (GC=F)": -6.9, "Sugar (SB=F)": -1.3, "DJIA": -4.0},
        climate=climate,
        resistance_levels=resistance_levels,
        support_levels=support_levels,
        scenarios=scenarios,
        bullish_params=bullish,
        bearish_params=bearish,
        hedge_advice=hedge,
        outlook=outlook,
        risk_warnings=risks,
    )


def export_report_to_pdf(report, output_path: str) -> str:
    """
    将 PredictionReport 导出为 Apple 风格 PDF

    Args:
        report: PredictionReport 实例
        output_path: PDF 输出路径

    Returns:
        实际保存的文件路径
    """
    pdf = CoffeePDF()
    pdf.add_page()

    # 封面信息
    pdf.ln(2)

    # 标题
    pdf.set_font(pdf._title_font, "B", 22)
    pdf.set_text_color(*AppleColors.TEXT)
    pdf.cell(0, 12, "Coffee Futures Weekly Outlook", align="L", new_x="LMARGIN", new_y="NEXT")

    # 元信息
    pdf.set_font(pdf._body_font, size=10)
    pdf.set_text_color(*AppleColors.LABEL)
    week_str = f"{report.forecast_week_start.strftime('%B %d')} - {report.forecast_week_end.strftime('%B %d, %Y')}"
    pdf.cell(0, 6, f"{report.ticker}   |   Report: {report.report_date}   |   Forecast: {week_str}", ln=True)
    pdf.ln(2)
    pdf._draw_line(AppleColors.BORDER, 0.5)
    pdf.ln(4)

    # ─── 市场快照 ──────────────────────────────────────────────
    if report.market:
        m = report.market
        pdf.price_card(
            current=m.current,
            change_1d=m.change_1d_pct or 0,
            change_30d=m.change_30d_pct or 0,
            rsi=m.rsi_14,
            ma20=m.ma20,
            ma60=m.ma60,
            high_30d=m.high_30d,
            low_30d=m.low_30d,
            closes=m.close_5d,
            vol_ratios=m.vol_ratio_5d,
        )

    # ─── 关联市场 ──────────────────────────────────────────────
    if report.related_markets:
        pdf.related_markets_table(report.related_markets)

    # ─── 关键价位 & 气候 ──────────────────────────────────────
    if report.support_levels or report.resistance_levels or report.climate:
        climate_dict = {}
        if report.climate:
            c = report.climate
            climate_dict = {
                "oni_value": c.oni_value,
                "oni_phase": c.oni_phase,
                "narrative": c.narrative,
            }
        pdf.key_levels(
            support=report.support_levels or [],
            resistance=report.resistance_levels or [],
            climate_info=climate_dict or None,
        )

    # ─── 情景分析 ──────────────────────────────────────────────
    if report.scenarios:
        pdf.section_title("Scenario Analysis", "[SCENARIO]")
        pdf.scenario_table(report.scenarios)

    # ─── 驱动因子 ──────────────────────────────────────────────
    if report.bullish_params or report.bearish_params:
        pdf.section_title("Market Drivers", "[DRIVERS]")
        pdf.drivers_section(
            bearish=list(report.bearish_params or []),
            bullish=list(report.bullish_params or []),
        )

    # ─── 套保建议 ──────────────────────────────────────────────
    if report.hedge_advice:
        pdf.section_title("Hedge Advice", "[HEDGE]")
        advice = {
            "ratio": report.hedge_advice.ratio,
            "signal": report.hedge_advice.signal,
            "narrative": report.hedge_advice.narrative,
            "trigger_below": report.hedge_advice.trigger_below,
            "trigger_above": report.hedge_advice.trigger_above,
        }
        pdf.hedge_advice_panel(advice)

    # ─── 核心观点 ──────────────────────────────────────────────
    if report.outlook:
        pdf.section_title("Outlook", "[OUTLOOK]")
        pdf.outlook_box(report.outlook)

    # ─── 风险提示 ──────────────────────────────────────────────
    if report.risk_warnings:
        pdf.risk_warnings(report.risk_warnings)

    # ─── 保存 ──────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    pdf.output(output_path)
    return output_path


# ─── CLI 入口 ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    sys.path.insert(0, str(__file__).rsplit("/", 1)[0])
    try:
        from reports.prediction_report import PredictionReport
    except ImportError:
        from reports.coffee_tui import demo_report as _demo
        PredictionReport = None

    parser = argparse.ArgumentParser(description="Export Coffee Report to PDF")
    parser.add_argument("-o", "--output", default="coffee_outlook.pdf",
                        help="Output PDF path (default: coffee_outlook.pdf)")
    parser.add_argument("--a4", action="store_true", default=True,
                        help="A4 page size (default)")
    args = parser.parse_args()

    if PredictionReport:
        report = PredictionReport.__new__(PredictionReport)
        # 用英文 demo 数据（避免 CJK 字体问题）
        report = _build_en_report()
    else:
        from reports.coffee_tui import demo_report
        report = demo_report()

    output = export_report_to_pdf(report, args.output)
    print(f"PDF saved: {output}")
