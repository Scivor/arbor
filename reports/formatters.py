"""Shared report formatting helpers."""

from __future__ import annotations


def format_number(
    value: float | None,
    *,
    decimals: int = 2,
    signed: bool = False,
    suffix: str = "",
    na: str = "N/A",
) -> str:
    """Format plain numeric values with optional sign and suffix."""
    if value is None:
        return na
    if signed:
        return f"{value:+.{decimals}f}{suffix}"
    return f"{value:.{decimals}f}{suffix}"


def format_price(
    value: float | None,
    *,
    decimals: int = 2,
    suffix: str = "",
    na: str = "N/A",
) -> str:
    """Format numeric prices consistently."""
    return format_number(value, decimals=decimals, suffix=suffix, na=na)


def format_percent(
    value: float | None,
    *,
    decimals: int = 1,
    signed: bool = False,
    absolute: bool = False,
    scale: float = 1.0,
    na: str = "N/A",
) -> str:
    """Format percent-like values with optional scaling and sign handling."""
    if value is None:
        return na
    number = abs(value) if absolute else value
    number *= scale
    if signed:
        return f"{number:+.{decimals}f}%"
    return f"{number:.{decimals}f}%"


def format_range(
    low: float | None,
    high: float | None,
    *,
    decimals: int = 0,
    separator: str = "–",
    na: str = "N/A",
) -> str:
    """Format price ranges consistently."""
    if low is None or high is None:
        return na
    return f"{low:.{decimals}f}{separator}{high:.{decimals}f}"


def format_rsi(value: float | None, *, decimals: int = 1, na: str = "N/A") -> str:
    """Keep RSI text precision consistent."""
    return format_number(value, decimals=decimals, na=na)


def format_confidence(value: float | None, *, na: str = "N/A") -> str:
    """Format confidence ratios as report copy."""
    if value is None:
        return na
    return f"置信度 {value:.0%}"


def format_signed_number(value: float | None, *, decimals: int = 2, na: str = "N/A") -> str:
    """Format signed numeric values without units."""
    return format_number(value, decimals=decimals, signed=True, na=na)


def format_oni(value: float | None, *, decimals: int = 2, na: str = "N/A") -> str:
    """Format ONI values consistently."""
    return format_signed_number(value, decimals=decimals, na=na)


def format_distance(value: float | None, *, decimals: int = 1, na: str = "N/A") -> str:
    """Format price distances consistently."""
    return format_number(value, decimals=decimals, suffix="¢", na=na)
