#!/usr/bin/env python3
"""
scripts/scheduler.py
Coffee Futures Report — APScheduler-based weekly publisher.

Trigger: Every Saturday at 03:00 CST (Beijing time).
Rationale: ICE Coffee futures close Friday 13:30 ET ≈ Saturday 02:30 CST.

Usage:
  python scripts/scheduler.py              # Daemon mode (runs forever)
  python scripts/scheduler.py --now        # Run immediately once
  python scripts/scheduler.py --now --pdf  # Run immediately, output PDF only
  python scripts/scheduler.py --hour 4 --minute 0  # Custom schedule
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

# ── Ensure project root on path ────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from reports.pipeline import run, PipelineConfig
from reports.exporters.html_to_pdf import build_report_html, html_to_pdf
from reports.history import save_report_summary

logger = logging.getLogger("report_scheduler")

# ── Output paths ─────────────────────────────────────────────────────────────
DEFAULT_WEB_REPORTS_DIR = _PROJECT_ROOT / "web" / "static" / "reports"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def generate_and_publish(
    output_dir: Path,
    output_format: str = "both",  # 'html' | 'pdf' | 'both'
    forecast_offset: int = 1,
) -> Path:
    """Generate report and publish to web directory."""
    today_str = date.today().strftime("%Y-%m-%d")
    report_dir = _ensure_dir(output_dir / today_str)

    logger.info("Generating report (date=%s, format=%s)...", today_str, output_format)

    config = PipelineConfig(
        ticker="KC=F",
        use_demo_data=False,
        output_format="html",
        forecast_week_offset=forecast_offset,
    )
    report = run(config)

    html_path = report_dir / "report.html"
    pdf_path = report_dir / "report.pdf"

    # ── Generate HTML (zh + en) ──
    if output_format in ("html", "both"):
        html_zh = build_report_html(report, lang="zh")
        html_path.write_text(html_zh, encoding="utf-8")
        html_en_path = report_dir / "report_en.html"
        html_en = build_report_html(report, lang="en")
        html_en_path.write_text(html_en, encoding="utf-8")
        logger.info("HTML saved: %s (zh) + %s (en)", html_path, html_en_path)

    # ── Generate PDF ──
    if output_format in ("pdf", "both"):
        html = build_report_html(report, lang="zh")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html)
            tmp_html = f.name
        try:
            html_to_pdf(tmp_html, str(pdf_path))
            logger.info("PDF saved: %s", pdf_path)
        finally:
            os.unlink(tmp_html)

    # ── Save summary for prediction review ──
    try:
        save_report_summary(report)
    except Exception as e:
        logger.warning("Failed to save report summary: %s", e)

    logger.info(
        "Published report %s | Forecast: %s ~ %s | Hedge: %s | ML: %s",
        today_str,
        report.forecast_week_start,
        report.forecast_week_end,
        report.hedge_advice.signal if report.hedge_advice else "N/A",
        report.ml_snapshot.signal if report.ml_snapshot else "N/A",
    )

    return report_dir


# ── Scheduler ────────────────────────────────────────────────────────────────

def run_scheduler(
    output_dir: Path,
    hour: int = 3,
    minute: int = 0,
    output_format: str = "both",
) -> None:
    """Run APScheduler in blocking mode."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as e:
        logger.error("APScheduler not installed: %s", e)
        sys.exit(1)

    scheduler = BlockingScheduler()

    scheduler.add_job(
        generate_and_publish,
        trigger=CronTrigger(day_of_week="sat", hour=hour, minute=minute),
        kwargs={
            "output_dir": output_dir,
            "output_format": output_format,
            "forecast_offset": 1,
        },
        id="weekly_report",
        name="Arbor Weekly Report",
        replace_existing=True,
    )

    logger.info("Scheduler started. Next run: Saturday %02d:%02d CST", hour, minute)
    logger.info("Output directory: %s", output_dir)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")
        scheduler.shutdown()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Coffee Futures Report Scheduler",
    )
    parser.add_argument(
        "--now", action="store_true",
        help="Run immediately once and exit",
    )
    parser.add_argument(
        "--output-dir", type=str,
        default=str(DEFAULT_WEB_REPORTS_DIR),
        help="Output directory for reports (default: web/static/reports)",
    )
    parser.add_argument(
        "--format", type=str, default="both",
        choices=["html", "pdf", "both"],
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--hour", type=int, default=3,
        help="Hour for weekly execution, 0-23 (default: 3)",
    )
    parser.add_argument(
        "--minute", type=int, default=0,
        help="Minute for weekly execution, 0-59 (default: 0)",
    )
    parser.add_argument(
        "--forecast-offset", type=int, default=1,
        help="Week offset: 0=current, 1=next (default: 1)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    output_dir = Path(args.output_dir).expanduser().resolve()

    if args.now:
        try:
            dest = generate_and_publish(
                output_dir=output_dir,
                output_format=args.format,
                forecast_offset=args.forecast_offset,
            )
            print(f"\n✓ Report published: {dest}")
            return 0
        except Exception as e:
            logger.error("Failed: %s", e, exc_info=True)
            print(f"\n✗ Error: {e}")
            return 1

    # Daemon mode
    run_scheduler(
        output_dir=output_dir,
        hour=args.hour,
        minute=args.minute,
        output_format=args.format,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
