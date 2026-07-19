"""
reports/exporters/__init__.py
Plugin-based report export architecture.

All exporters implement the ExporterPlugin protocol:
  export(report, dest=None) -> str | None

Auto-discovery: exporters register themselves via entry_points (future)
or are manually imported here for now.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    from reports.pipeline import Report


# ─────────────────────────────────────────────────────────────────────────────
# Plugin protocol
# ─────────────────────────────────────────────────────────────────────────────

class ExporterPlugin(Protocol):
    """Protocol that all report exporters must implement."""

    name: str
    format: str          # file extension e.g. "txt", "json", "pdf"
    mime_type: str       # MIME type e.g. "text/plain", "application/json"

    def export(self, report: "Report", dest: Optional[str] = None) -> str | None:
        """Export the report.

        Args:
            report: The report object from reports.pipeline.
            dest:   Output file path. None = write to stdout / return string.

        Returns:
            For string formats: the output as a string (even if also written to dest).
            For non-string formats (Rich console): None (output goes to stdout).
            Raises on failure.
        """
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Built-in exporters (lazy import to avoid hard dependencies)
# ─────────────────────────────────────────────────────────────────────────────

def _text_export(report: "Report", dest: Optional[str] = None) -> Optional[str]:
    from reports.exporters.text_exporter import export_text
    out = export_text(report)
    if dest:
        open(dest, "w").write(out)
    else:
        print(out)
    return out


def _json_export(report: "Report", dest: Optional[str] = None) -> str:
    from reports.exporters.json_exporter import export_json
    out = export_json(report)
    if dest:
        open(dest, "w", encoding="utf-8").write(out)
    else:
        print(out)
    return out


def _html_export(report: "Report", dest: Optional[str] = None, lang: str = "zh") -> str:
    dest = dest or "coffee_outlook.html"
    from reports.exporters.html_to_pdf import build_report_html
    html = build_report_html(report, lang=lang)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(html)
    return html


def _markdown_export(report: "Report", dest: Optional[str] = None, lang: str = "zh") -> str:
    from reports.exporters.markdown_exporter import export_markdown
    out = export_markdown(report, lang=lang)
    if dest:
        open(dest, "w", encoding="utf-8").write(out)
    else:
        print(out)
    return out


def _pdf_export(report: "Report", dest: Optional[str] = None, lang: str = "zh") -> str:
    from reports.exporters.html_to_pdf import export_pdf
    pdf_path = export_pdf(report, dest=dest, lang=lang)
    return pdf_path


# ─────────────────────────────────────────────────────────────────────────────
# Exporter registry
# ─────────────────────────────────────────────────────────────────────────────

_FORMATTERS: dict[str, ExporterPlugin] = {}


def _register_builtin():
    """Register built-in exporters."""
    global _FORMATTERS
    _FORMATTERS = {
        "text": _InlineExporter("text", "txt", "text/plain", _text_export),
        "json": _InlineExporter("json", "json", "application/json", _json_export),
        "html": _InlineExporter("html", "html", "text/html", _html_export),
        "pdf":  _InlineExporter("pdf",  "pdf",  "application/pdf", _pdf_export),
        "markdown": _InlineExporter("markdown", "md", "text/markdown", _markdown_export),
    }


class _InlineExporter:
    """Lightweight exporter wrapper for functions."""
    __slots__ = ("name", "format", "mime_type", "_fn")

    def __init__(self, name: str, fmt: str, mime: str, fn):
        self.name = name
        self.format = fmt
        self.mime_type = mime
        self._fn = fn

    def export(self, report: "Report", dest: Optional[str] = None) -> Optional[str]:
        return self._fn(report, dest)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
_register_builtin()


def get_exporter(name: str) -> ExporterPlugin:
    """Get an exporter by name (e.g. 'text', 'json', 'html')."""
    if not _FORMATTERS:
        _register_builtin()
    if name not in _FORMATTERS:
        raise ValueError(f"Unknown exporter '{name}'. Available: {list(_FORMATTERS.keys())}")
    return _FORMATTERS[name]


def list_exporters() -> list[str]:
    """List all registered exporter names."""
    if not _FORMATTERS:
        _register_builtin()
    return list(_FORMATTERS.keys())


def export_report(
    report: "Report",
    format: str,
    dest: Optional[str] = None,
) -> Optional[str]:
    """Export a report using the specified format.

    Args:
        report:  Report from reports.pipeline.
        format:  Exporter name ('text', 'json', 'html', 'pdf').
        dest:    Output path (optional).

    Returns:
        String output for text/json/html.
    """
    exporter = get_exporter(format)
    return exporter.export(report, dest)


# Re-export convenience functions for direct imports
from reports.exporters.text_exporter import export_text  # noqa: E402 — 注册代码之后的刻意 re-export
from reports.exporters.json_exporter import export_json  # noqa: E402 — 注册代码之后的刻意 re-export

__all__ = [
    "ExporterPlugin",
    "get_exporter",
    "list_exporters",
    "export_report",
    "export_text",
    "export_json",
]
