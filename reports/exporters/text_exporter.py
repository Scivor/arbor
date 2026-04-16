"""
reports/exporters/text_exporter.py
Plain-text export for terminal / log output.
"""

from __future__ import annotations

from reports.models import PredictionReport


def export_text(report: PredictionReport, fp=None) -> str:
    """
    Render `report` as plain text.

    Args:
        report: PredictionReport instance.
        fp: file-like object to write to (optional). If None, returns str.

    Returns:
        The rendered text (also written to `fp` if provided).
    """
    text = report.to_text()
    if fp is not None:
        fp.write(text)
    return text
