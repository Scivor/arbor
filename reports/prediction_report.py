"""
reports/prediction_report.py
Backwards-compatibility shim.

All symbols are re-exported from reports.models.
Old import path: from reports.prediction_report import PredictionReport
New import path: from reports.models import PredictionReport
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
