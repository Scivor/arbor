"""
reports/exporters/json_exporter.py
JSON export for API / machine-readable output.
"""

from __future__ import annotations

import json
from reports.models import PredictionReport


def export_json(report: PredictionReport, fp=None, indent: int = 2) -> str:
    """
    Render `report` as JSON.

    Args:
        report: PredictionReport instance.
        fp: file-like object to write to (optional). If None, returns str.
        indent: JSON indentation level (default 2).

    Returns:
        The rendered JSON string (also written to `fp` if provided).
    """
    text = report.to_json()
    if fp is not None:
        json.loads(text)  # validate
        fp.write(text)
    return text
