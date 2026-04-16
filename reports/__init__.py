"""
reports/__init__.py
Coffee V3 Reports Package

Submodules:
    models      -- Core dataclass definitions
    pipeline    -- Report generation orchestration
    demo_data   -- Seed data for testing/demo
    cli         -- Command-line interface
    exporters   -- Export format handlers (PDF, JSON, text, rich)
"""

from reports.models import (
    MarketSnapshot,
    ClimateSnapshot,
    Scenario,
    Level,
    SupportParam,
    ResistParam,
    HedgeAdvice,
    PredictionReport,
    build_report,
)

__all__ = [
    "MarketSnapshot",
    "ClimateSnapshot",
    "Scenario",
    "Level",
    "SupportParam",
    "ResistParam",
    "HedgeAdvice",
    "PredictionReport",
    "build_report",
]
