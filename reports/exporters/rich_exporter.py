"""
reports/exporters/rich_exporter.py
Rich console export for enhanced terminal output.
"""

from __future__ import annotations

from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

from reports.models import PredictionReport


def _sparkline(data: list[float], width: int = 30) -> str:
    """Render a price trend line with Unicode block characters."""
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
    """Volume ratio bar with colour coding."""
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
    """Scenario probability bar."""
    filled = int(prob * width)
    return f"{'█' * filled}{'░' * (width - filled)} {prob:.0%}"


def _driver_bar(weight: str) -> str:
    """Driver factor weight bar."""
    mapping = {"STRONG": ("bold red", 3), "MEDIUM": ("yellow", 2), "WEAK": ("dim white", 1)}
    style, count = mapping.get(weight, ("dim", 1))
    return f"[{style}]{'▓' * count}[/{style}]{'░' * (3 - count)}"


def _icon(direction: str) -> str:
    return {"BEARISH": "🔴", "NEUTRAL": "⚪", "BULLISH": "🟢"}.get(direction, "⚪")


def export_rich(report: PredictionReport, console=None) -> None:
    """
    Render `report` to a Rich console.

    Args:
        report: PredictionReport instance.
        console: Optional rich.Console instance.
                 If None, a new force_terminal Console is created.
    """
    if not _HAS_RICH:
        raise RuntimeError("rich is not installed — run: pip install rich")

    if console is None:
        console = Console(force_terminal=True)

    m = report.market
    r = report

    console.print()
    console.rule("[bold cyan]☕  COFFEE FUTURES WEEKLY OUTLOOK [/]", style="cyan")

    # Meta
    week_str = f"{r.forecast_week_start.strftime('%b %d')} – {r.forecast_week_end.strftime('%b %d')}"
    console.print(f"  [bold]{r.ticker}[/]   Report: [cyan]{r.report_date}[/]   Forecast: [yellow]{week_str}[/]")
    console.print()

    # ── Market Snapshot ──────────────────────────────────────────
    if m:
        chg_1d = f"{m.change_1d_pct:+.2f}%" if m.change_1d_pct is not None else "N/A"
        chg_30d = f"{m.change_30d_pct:+.1f}%" if m.change_30d_pct is not None else "N/A"
        rsi_sig = "[red]OB[/]" if m.rsi_14 < 35 else "[green]OS[/]" if m.rsi_14 > 65 else "[dim]N[/]"
        trend = "▲" if m.current < m.ma20 else "▼"
        price_color = "dark_green" if m.change_1d_pct >= 0 else "dark_red"

        snap = Table(show_header=False, padding=(0, 1))
        snap.add_column(style="bold", width=18)
        snap.add_column()

        price_str = f"[bold white on {price_color}]{m.current:.2f}[/]"
        snap.add_row("Price", f"{price_str}  ({chg_1d} today, {chg_30d} 30d)  RSI: {m.rsi_14:.1f} {rsi_sig}")
        snap.add_row("MA20", f"{m.ma20:.2f}  {trend} {'above' if m.current > m.ma20 else 'below'}  30d: {m.low_30d:.2f}–{m.high_30d:.2f}")
        snap.add_row("MA60", f"{m.ma60:.2f}  {'▲ above' if m.current > m.ma60 else '▼ below'}")

        spark = _sparkline(m.close_5d, 36)
        snap.add_row("Trend", f"[cyan]{spark}[/cyan]")

        vol_row = "  ".join(_vol_bar(v) for v in m.vol_ratio_5d)
        snap.add_row("Volume", vol_row)

        console.print(Panel(snap, title="[bold cyan]📊 MARKET SNAPSHOT[/]", border_style="cyan", padding=1))
        console.print()

    # ── Related Markets ──────────────────────────────────────────
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

    # ── Climate & Levels ─────────────────────────────────────────
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

    # ── Scenario Analysis ────────────────────────────────────────
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

    # ── Drivers ───────────────────────────────────────────────────
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

    # ── Hedge Advice ─────────────────────────────────────────────
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

    # ── Outlook ───────────────────────────────────────────────────
    if r.outlook:
        console.print(Panel(
            f"[bold yellow]{r.outlook}[/]",
            title="[bold cyan]💡 OUTLOOK[/]",
            border_style="cyan",
            padding=1,
        ))
        console.print()

    # ── Risk Warnings ─────────────────────────────────────────────
    if r.risk_warnings:
        warn_text = "\n".join(f"  ⚠️  {w}" for w in r.risk_warnings)
        console.print(Panel(warn_text, title="[bold red]⚠️ RISK WARNINGS[/]", border_style="red", padding=1))
        console.print()

    console.rule(style="dim")
