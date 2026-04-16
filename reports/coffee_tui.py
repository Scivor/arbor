"""
reports/coffee_tui.py
Coffee Futures Weekly Outlook — Rich + Textual TUI

运行方式:
    python3 -m reports.coffee_tui              # 自动检测：TUI 或纯文本
    python3 -m reports.coffee_tui --text-only   # 强制 Rich 文本
    python3 -m reports.coffee_tui --json        # JSON 输出
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from typing import Optional

# ─── Rich 组件（v14 兼容）──────────────────────────────────────
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console(force_terminal=True)

# ─── Textual 组件 ─────────────────────────────────────────────
try:
    from textual.app import App, ComposeResult
    from textual.widgets import Static, Header, Footer
    _HAS_TEXTUAL = True
except ImportError:
    _HAS_TEXTUAL = False


# ─── 辅助函数 ──────────────────────────────────────────────────

def _sparkline(data: list[float], width: int = 30) -> str:
    """用纯文符渲染价格趋势线"""
    if not data:
        return ""
    min_d, max_d = min(data), max(data)
    span = max_d - min_d
    if span == 0:
        chars = ["─"] * len(data)
    else:
        scale = (width - 1) / span
        chars = []
        for v in data:
            pos = int((v - min_d) * scale)
            chars.append("─" * pos + "·")
    return "".join(chars[-width:]) if len(chars) > width else "".join(chars)


def _vol_bar(ratio: float) -> str:
    """成交量比柱状图"""
    filled = min(int(ratio), 4)
    if ratio >= 2.0:
        return f"[red]{'█' * filled}{'░' * (4 - filled)}[/red]{ratio:.1f}x"
    elif ratio >= 1.5:
        return f"[yellow]{'█' * filled}{'░' * (4 - filled)}[/yellow]{ratio:.1f}x"
    elif ratio >= 1.0:
        return f"[green]{'█' * filled}{'░' * (4 - filled)}[/green]{ratio:.1f}x"
    else:
        return f"[dim]{'░' * 4}[/dim]{ratio:.1f}x"


def _prob_bar(prob: float, width: int = 18) -> str:
    """情景概率条"""
    filled = int(prob * width)
    return f"{'█' * filled}{'░' * (width - filled)} {prob:.0%}"


def _driver_bar(weight: str) -> str:
    """驱动因子权重条"""
    mapping = {"STRONG": ("bold red", 3), "MEDIUM": ("yellow", 2), "WEAK": ("dim white", 1)}
    style, count = mapping.get(weight, ("dim", 1))
    return f"[{style}]{'▓' * count}[/{style}]{'░' * (3 - count)}"


def _icon(direction: str) -> str:
    return {"BEARISH": "🔴", "NEUTRAL": "⚪", "BULLISH": "🟢"}.get(direction, "⚪")


# ─── Rich 渲染 ───────────────────────────────────────────────

def render_report_rich(report) -> None:
    """将报告渲染为 Rich 控制台输出"""
    m = report.market
    r = report

    console.print()
    console.rule("[bold cyan]☕  COFFEE FUTURES WEEKLY OUTLOOK [/]", style="cyan")

    # 元信息
    week_str = f"{r.forecast_week_start.strftime('%b %d')} – {r.forecast_week_end.strftime('%b %d')}"
    console.print(f"  [bold]{r.ticker}[/]   Report: [cyan]{r.report_date}[/]   Forecast: [yellow]{week_str}[/]")
    console.print()

    # ── 市场快照 ──────────────────────────────────────────────
    if m:
        chg_1d = f"{m.change_1d_pct:+.2f}%" if m.change_1d_pct is not None else "N/A"
        chg_30d = f"{m.change_30d_pct:+.1f}%" if m.change_30d_pct is not None else "N/A"
        rsi_sig = "[red]OB[/]" if m.rsi_14 < 35 else "[green]OS[/]" if m.rsi_14 > 65 else "[dim]N[/]"
        trend = "▼" if m.current < m.ma20 else "▲"
        price_color = "dark_green" if m.change_1d_pct >= 0 else "dark_red"

        snap = Table(show_header=False, padding=(0, 1))
        snap.add_column(style="bold", width=18)
        snap.add_column()

        price_str = f"[bold white on {price_color}]{m.current:.2f}[/]"
        snap.add_row("Price", f"{price_str}  ({chg_1d} today, {chg_30d} 30d)  RSI: {m.rsi_14:.1f} {rsi_sig}")
        snap.add_row("MA20", f"{m.ma20:.2f}  {trend} {'above' if m.current > m.ma20 else 'below'}  30d: {m.low_30d:.2f}–{m.high_30d:.2f}")
        snap.add_row("MA60", f"{m.ma60:.2f}  {'▲ above' if m.current > m.ma60 else '▼ below'}")

        # 趋势线（文符版）
        spark = _sparkline(m.close_5d, 36)
        snap.add_row("Trend", f"[cyan]{spark}[/cyan]")

        # 成交量
        vol_row = "  ".join(_vol_bar(v) for v in m.vol_ratio_5d)
        snap.add_row("Volume", vol_row)

        console.print(Panel(snap, title="[bold cyan]📊 MARKET SNAPSHOT[/]", border_style="cyan", padding=1))
        console.print()

    # ── 关联市场 ──────────────────────────────────────────────
    if r.related_markets:
        rel = Table(show_header=True, box=None, header_style="bold dim")
        rel.add_column("Market", style="dim")
        rel.add_column("30d Change", justify="right")
        rel.add_column("Bar", width=14)
        for name, chg in r.related_markets.items():
            icon = "▲" if chg > 0 else "▼"
            color = "green" if chg > 0 else "red"
            bar_w = min(int(abs(chg) / 1.5), 10)
            bar = f"[{color}]{'▓' * bar_w}[/{color}]{'░' * (10 - bar_w)}"
            rel.add_row(name, f"[{color}]{icon} {chg:+.1f}%[/{color}]", bar)
        console.print(Panel(rel, title="[bold cyan]🔗 RELATED MARKETS[/]", border_style="cyan", padding=1))
        console.print()

    # ── 气候 & 关键价位 ───────────────────────────────────────
    if r.climate or r.support_levels or r.resistance_levels:
        climate_lvl = Table(show_header=False, box=None, padding=(0, 1))
        if r.climate:
            c = r.climate
            phase_icon = "❄️" if c.oni_value < -0.5 else "🔥" if c.oni_value > 0.5 else "🌊"
            phase_color = "blue" if c.oni_value < -0.5 else "red" if c.oni_value > 0.5 else "cyan"
            climate_lvl.add_row("Climate", f"ONI: [{phase_color}]{c.oni_value:+.2f}[/{phase_color}] ({c.oni_phase}) {phase_icon}")
            climate_lvl.add_row("", f"[dim]{c.narrative}[/dim]")
        if r.support_levels:
            sup = "  ".join(f"[yellow]{l.price:.2f}[/yellow] ({l.label})" for l in r.support_levels)
            climate_lvl.add_row("Support", sup)
        if r.resistance_levels:
            res = "  ".join(f"[red]{l.price:.2f}[/red] ({l.label})" for l in r.resistance_levels)
            climate_lvl.add_row("Resistance", res)
        console.print(Panel(climate_lvl, title="[bold cyan]🌡️ LEVELS & CLIMATE[/]", border_style="cyan", padding=1))
        console.print()

    # ── 情景分析 ──────────────────────────────────────────────
    if r.scenarios:
        scen = Table(show_header=True, box=None, header_style="bold dim")
        scen.add_column("Scenario", width=10)
        scen.add_column("Range", justify="right", width=14)
        scen.add_column("Prob", justify="right", width=8)
        scen.add_column("Probability Bar", width=22)
        scen.add_column("Rationale", width=38)
        for s in r.scenarios:
            icon = _icon(s.direction)
            color = "red" if s.direction == "BEARISH" else "green" if s.direction == "BULLISH" else "white"
            prob_bar = _prob_bar(s.probability)
            rationale = s.rationale[0] if s.rationale else ""
            dim = "dim" if s.probability < 0.15 else ""
            scen.add_row(
                f"[{color}]{icon} {s.label}[/{color}]",
                f"[{color}]{s.price_min:.0f}–{s.price_max:.0f}[/{color}]",
                f"[bold]{s.probability:.0%}[/]",
                prob_bar,
                f"[dim]{rationale}[/dim]",
                style=dim,
            )
        console.print(Panel(scen, title="[bold cyan]🎯 SCENARIO ANALYSIS[/]", border_style="cyan", padding=1))
        console.print()

    # ── 驱动因子 ──────────────────────────────────────────────
    if r.bullish_params or r.bearish_params:
        drv = Table(show_header=False, box=None, padding=(0, 1))
        if r.bearish_params:
            rows = []
            for p in r.bearish_params:
                w = _driver_bar(p.weight)
                rows.append(f"  {w}  [red]{p.param_name}[/red]: {p.current_value}  [dim]{p.narrative}[/dim]")
            drv.add_row("[bold red]BEARISH[/]", "\n".join(rows))
        if r.bullish_params:
            rows = []
            for p in r.bullish_params:
                w = _driver_bar(p.weight)
                rows.append(f"  {w}  [green]{p.param_name}[/green]: {p.current_value}  [dim]{p.narrative}[/dim]")
            drv.add_row("[bold green]BULLISH[/]", "\n".join(rows))
        console.print(Panel(drv, title="[bold cyan]📈 DRIVERS[/]", border_style="cyan", padding=1))
        console.print()

    # ── 套保建议 ──────────────────────────────────────────────
    if r.hedge_advice:
        h = r.hedge_advice
        advice_lines = [
            f"  [bold]Signal:[/bold] [yellow]{h.signal}[/yellow]    [bold]Ratio:[/bold] [white on green]{int(h.ratio * 100)}%[/]",
            f"  {h.narrative}",
        ]
        if h.trigger_below:
            advice_lines.append(f"  [red]↓[/red] Break [{h.trigger_below:.0f}] → increase hedge to 75-80%")
        if h.trigger_above:
            advice_lines.append(f"  [green]↑[/green] Break [{h.trigger_above:.0f}] → reduce hedge to 50%")
        console.print(Panel("\n".join(advice_lines), title="[bold cyan]🛡️ HEDGE ADVICE[/]", border_style="cyan", padding=1))
        console.print()

    # ── 核心观点 ──────────────────────────────────────────────
    if r.outlook:
        console.print(Panel(
            f"[bold yellow]{r.outlook}[/]",
            title="[bold cyan]💡 OUTLOOK[/]",
            border_style="cyan",
            padding=1,
        ))
        console.print()

    # ── 风险提示 ──────────────────────────────────────────────
    if r.risk_warnings:
        warn_text = "\n".join(f"  ⚠️  {w}" for w in r.risk_warnings)
        console.print(Panel(warn_text, title="[bold red]⚠️ RISK WARNINGS[/]", border_style="red", padding=1))
        console.print()

    console.rule(style="dim")


# ─── Textual TUI 应用 ──────────────────────────────────────────

if _HAS_TEXTUAL:
    class CoffeeTUI(App):
        """交互式 Coffee Futures TUI — Textual 驱动"""

        CSS = """
        Screen { background: $surface; }
        Header { background: $primary; color: $text; }
        #title-bar {
            dock: top;
            height: 3;
            background: $primary;
            content-align: center middle;
            color: $text;
            text-style: bold;
        }
        .panel {
            border: solid $primary;
            margin: 0 1;
            padding: 1 2;
            height: auto;
        }
        """

        TITLE = "☕ Coffee Futures Weekly Outlook"
        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
        ]

        def __init__(self, report, **kwargs):
            super().__init__(**kwargs)
            self.report = report

        def compose(self) -> ComposeResult:
            yield Header()
            r = self.report
            m = r.market

            week_str = f"{r.forecast_week_start.strftime('%b %d')} – {r.forecast_week_end.strftime('%b %d')}"
            yield Static(
                f"[bold cyan]☕[/] [bold]{r.ticker}[/]  Weekly Outlook  |  {r.report_date}  |  {week_str}",
                id="title-bar",
            )

            if m:
                chg_1d = f"{m.change_1d_pct:+.2f}%" if m.change_1d_pct is not None else "N/A"
                chg_30d = f"{m.change_30d_pct:+.1f}%" if m.change_30d_pct is not None else "N/A"
                rsi_c = "red" if m.rsi_14 < 35 else "green" if m.rsi_14 > 65 else "white"
                ma_trend = "▲" if m.current > m.mac20 else "▼"
                price_style = "dark_green" if m.change_1d_pct >= 0 else "dark_red"

                content = (
                    f"[bold white on {price_style}]{m.current:.2f}[/] [dim]cents/lb[/dim]\n"
                    f"[dim]Today:[/dim] {chg_1d}   [dim]30d:[/dim] {chg_30d}\n"
                    f"[dim]RSI(14):[/dim] [{rsi_c}]{m.rsi_14:.1f}[/{rsi_c}]  "
                    f"[dim]MA20:[/dim] {m.ma20:.2f} [{ma_trend}]  [dim]MA60:[/dim] {m.ma60:.2f}\n"
                    f"[dim]30d Range:[/dim] {m.low_30d:.2f} – {m.high_30d:.2f}\n"
                    f"[dim]5d Closes:[/dim] {'  '.join(f'{c:.1f}' for c in m.close_5d)}\n"
                    f"[dim]Vol Ratios:[/dim] {'  '.join(f'{v:.1f}x' for v in m.vol_ratio_5d)}"
                )
                yield Static(content, classes="panel")

            if r.related_markets:
                lines = []
                for name, chg in r.related_markets.items():
                    icon = "▲" if chg > 0 else "▼"
                    color = "green" if chg > 0 else "red"
                    lines.append(f"[{color}]{icon} {name}[/{color}]: [{color}]{chg:+.1f}%[/{color}]")
                yield Static("\n".join(lines), classes="panel")

            if r.scenarios:
                lines = []
                for s in r.scenarios:
                    icon = _icon(s.direction)
                    color = "red" if s.direction == "BEARISH" else "green" if s.direction == "BULLISH" else "white"
                    prob_bar = _prob_bar(s.probability)
                    lines.append(f"  {icon} [{color}]{s.label}[/{color}]  {s.price_min:.0f}–{s.price_max:.0f}  {s.probability:.0%}  {prob_bar}")
                    if s.rationale:
                        lines.append(f"      [dim]{s.rationale[0]}[/dim]")
                yield Static("\n".join(lines), classes="panel")

            if r.bullish_params or r.bearish_params:
                lines = []
                if r.bearish_params:
                    lines.append("[bold red]BEARISH[/]")
                    for p in r.bearish_params:
                        w = _driver_bar(p.weight)
                        lines.append(f"  {w}  [red]{p.param_name}[/red]: {p.current_value}")
                if r.bullish_params:
                    lines.append("")
                    lines.append("[bold green]BULLISH[/]")
                    for p in r.bullish_params:
                        w = _driver_bar(p.weight)
                        lines.append(f"  {w}  [green]{p.param_name}[/green]: {p.current_value}")
                yield Static("\n".join(lines), classes="panel")

            if r.hedge_advice:
                h = r.hedge_advice
                lines = [
                    f"[bold]Ratio:[/bold] [white on green]{int(h.ratio * 100)}%[/]   [bold]Signal:[/bold] {h.signal}",
                    f"  {h.narrative}",
                ]
                if h.trigger_below:
                    lines.append(f"  [red]↓[/red] Break {h.trigger_below:.0f} → increase hedge to 75-80%")
                if h.trigger_above:
                    lines.append(f"  [green]↑[/green] Break {h.trigger_above:.0f} → reduce hedge to 50%")
                yield Static("\n".join(lines), classes="panel")

            if r.outlook:
                lines = [f"[bold yellow]{r.outlook}[/]"]
                if r.risk_warnings:
                    lines.append("")
                    lines.append("[bold red]Risk Warnings:[/bold]")
                    for rw in r.risk_warnings:
                        lines.append(f"  ⚠️  {rw}")
                yield Static("\n".join(lines), classes="panel")

            yield Footer()

        def action_refresh(self) -> None:
            pass

else:
    CoffeeTUI = None


# ─── 演示数据 ─────────────────────────────────────────────────

def demo_report():
    """构建演示报告（用于 --text-only 或无 prediction_report.py 时）"""
    sys.path.insert(0, str(__file__).rsplit("/", 1)[0])
    try:
        from reports.prediction_report import (
            MarketSnapshot, ClimateSnapshot, Level, Scenario,
            SupportParam, ResistParam, HedgeAdvice, PredictionReport,
        )
    except ImportError:
        # 内联最小类型定义（无 prediction_report.py 时）
        from dataclasses import dataclass, field
        @dataclass
        class MarketSnapshot:
            ticker: str = "KC=F"; current: float = 293.70
            change_1d_pct: float = -0.10; change_30d_pct: float = -15.4
            high_30d: float = 383.85; low_30d: float = 278.65
            volume_ratio: float = 1.5; ma20: float = 300.43; ma60: float = 309.38
            rsi_14: float = 38.6; close_5d: list = field(default_factory=list)
            vol_ratio_5d: list = field(default_factory=list)
        @dataclass
        class ClimateSnapshot:
            oni_value: float = -0.39; oni_phase: str = "NEUTRAL"
            oni_period: str = "DJF 2026"; narrative: str = ""
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

    m = MarketSnapshot(
        ticker="KC=F", current=293.70,
        change_1d_pct=-0.10, change_30d_pct=-15.4,
        high_30d=383.85, low_30d=278.65,
        volume_ratio=1.5, ma20=300.43, ma60=309.38,
        rsi_14=38.6,
        close_5d=[295.40, 298.05, 286.10, 294.05, 293.70],
        vol_ratio_5d=[1.5, 0.7, 2.0, 1.7, 1.5],
    )
    climate = ClimateSnapshot(
        oni_value=-0.39, oni_phase="NEUTRAL",
        oni_period="DJF 2026",
        narrative="La Niña 已减弱至中性，2026年Q1无显著气候溢价",
    )
    support_levels = [
        Level(price=288.30, label="关键支撑", strength="KEY"),
        Level(price=284.60, label="2月低点", strength="KEY"),
        Level(price=280.00, label="深度支撑", strength="MEDIUM"),
    ]
    resistance_levels = [
        Level(price=301.70, label="近期阻力", strength="KEY"),
        Level(price=304.50, label="21日均线", strength="MEDIUM"),
        Level(price=309.75, label="前高", strength="MEDIUM"),
    ]
    scenarios = [
        Scenario(label="看跌", direction="BEARISH", price_min=278, price_max=288,
                 probability=0.35, rationale=["宏观继续risk-off，标金破位，跌破288关键支撑"]),
        Scenario(label="中性", direction="NEUTRAL", price_min=288, price_max=302,
                 probability=0.40, rationale=["区间震荡，288-302之间消化"]),
        Scenario(label="反弹", direction="BULLISH", price_min=302, price_max=312,
                 probability=0.20, rationale=["288撑住+空头回补，技术修复性反弹"]),
        Scenario(label="看涨", direction="BULLISH", price_min=312, price_max=330,
                 probability=0.05, rationale=["需宏观避险+天气题材共振，概率极低"]),
    ]
    bullish = [
        SupportParam("技术面", "288关键支撑", "293.70 vs 288.30", "距支撑5.4c", "MEDIUM", "若守住288，下跌空间有限"),
        SupportParam("技术面", "RSI中性偏低", "RSI=38.6", "未超卖但有余量", "WEAK", "量能放大"),
        SupportParam("技术面", "Apr 7暴跌放量", "1.9x均量", "空头力量释放", "MEDIUM", "若288撑住，量能转利多"),
        SupportParam("季节性", "2月历史低点", "284.60", "季节性底部区域", "MEDIUM", "4月处于年度低位"),
        SupportParam("基本面", "库存历史低位", "ICE认证库存偏低", "结构性支撑", "MEDIUM", "封杀深跌空间"),
        SupportParam("宏观", "可可逆势走强", "CC=F +0.8%", "板块内部轮动", "WEAK", "农产品强势可能带动"),
    ]
    bearish = [
        ResistParam("技术面", "均线空头排列", "价格<MA20<MA60", "清晰下行趋势", "STRONG", "均线层层压制"),
        ResistParam("技术面", "趋势高点下移", "352→333→309→301", "下降通道完整", "STRONG", "每次反弹创更低高点"),
        ResistParam("宏观", "标金大跌", "GC=F -6.9%", "全球risk-off", "STRONG", "黄金破位，商品系统性承压"),
        ResistParam("宏观", "标普下跌", "DJIA -4.0%", "风险资产被抛售", "MEDIUM", "宏观环境不利"),
        ResistParam("技术面", "RSI未超卖", "RSI=38.6", "无技术反弹条件", "MEDIUM", "尚无超卖反弹动能"),
        ResistParam("季节性", "巴西采收高峰", "4月供应高峰", "年度供应最充足", "MEDIUM", "年度供应最充足时期"),
        ResistParam("气候", "La Nina趋中性", "ONI -0.39→0", "无天气溢价", "MEDIUM", "气候题材支撑消散"),
        ResistParam("商品", "砂糖同步下跌", "SB=F -1.3%", "软商品普跌", "MEDIUM", "非个别品种，系统性压力"),
    ]
    hedge = HedgeAdvice(
        ratio=0.65, signal="MEDIUM_HEDGE",
        narrative="维持65%静态套保，等288突破方向确认后再调整",
        trigger_below=288.30, trigger_above=301.70,
    )
    outlook = (
        "下周价格中性偏弱，核心区间284–302。宏观risk-off + 均线空头排列 + 趋势下行三重压力 "
        "盖过库存低位的结构性支撑，288关键支撑面临试探。"
    )
    risks = [
        "标金若加速下跌（<4600），商品全线承压，288可能快速被测试",
        "美元走强雷亚尔贬值可能引发巴西咖啡出口抛压",
        "4月降雨预报若改善，供应预期转松，压制价格",
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


# ─── 入口 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Coffee Futures Weekly Outlook")
    parser.add_argument("--text-only", action="store_true", help="Force Rich text output")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    report = demo_report()

    if args.json:
        print(report.to_json() if hasattr(report, "to_json") else "{}")
    elif args.text_only or not sys.stdout.isatty() or not _HAS_TEXTUAL:
        render_report_rich(report)
    else:
        app = CoffeeTUI(report)
        app.run()
