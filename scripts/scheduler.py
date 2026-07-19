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
from datetime import date
from pathlib import Path

# ── Ensure project root on path ────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from reports.pipeline import run, PipelineConfig
from reports.exporters.html_to_pdf import build_report_html, html_to_pdf
from reports.exporters.markdown_exporter import export_markdown
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

        # ── Generate Markdown (公众号友好) ──
        md_path = report_dir / "report.md"
        md_path.write_text(export_markdown(report), encoding="utf-8")
        logger.info("Markdown saved: %s", md_path)

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

    # ── 自校准：根据历史复盘微调系数（Phase B，不阻塞出报）──
    try:
        from reports.learning import recalibrate
        result = recalibrate()
        if result["changed"]:
            from core.notify.ops_alert import send_ops_alert
            lines = "\n".join(
                f"• {c['param']}: {c['old']:.3f} → {c['new']:.3f}（{c['reason']}，n={result['n_samples']}）"
                for c in result["changed"]
            )
            send_ops_alert(f"🔧 <b>Arbor 自校准已调整</b>\n{lines}")
    except Exception as e:
        logger.warning("recalibrate failed: %s", e)

    logger.info(
        "Published report %s | Forecast: %s ~ %s | Hedge: %s | ML: %s",
        today_str,
        report.forecast_week_start,
        report.forecast_week_end,
        report.hedge_advice.signal if report.hedge_advice else "N/A",
        report.ml_snapshot.signal if report.ml_snapshot else "N/A",
    )

    # ── 数据源健康评估：降级/失败时 Telegram 告警（未配置则静默跳过）──
    try:
        level, problems = assess_report_health(report)
        if level != "ok":
            from core.notify.ops_alert import send_ops_alert
            icon = "🔴" if level == "critical" else "🟡"
            outcome = "失败" if level == "critical" else "降级"
            send_ops_alert(
                f"{icon} <b>Arbor 周报 {today_str} 生成{outcome}</b>\n"
                + "\n".join(f"• {p}" for p in problems)
            )
    except Exception as e:
        logger.warning("Health alert failed: %s", e)

    return report_dir


def assess_report_health(report) -> tuple[str, list[str]]:
    """
    评估周报数据源健康度。

    Returns:
        (level, problems): level ∈ {"ok", "degraded", "critical"}
        critical = 无价格数据，报告不成立；degraded = 次要板块缺失
    """
    if report is None:
        return "critical", ["报告对象为 None"]
    if report.market is None:
        return "critical", ["KC=F 价格数据缺失（yfinance 可能失效）"]
    problems: list[str] = []
    if report.climate is None:
        problems.append("ONI 气候数据缺失")
    if report.ml_snapshot is None:
        problems.append("ML 预测缺失")
    if getattr(report, "china_import", None) is None:
        problems.append("中国进口板块缺失（汇率/到库成本/政策）")
    return ("degraded" if problems else "ok"), problems


# ── Scheduler ────────────────────────────────────────────────────────────────

def _job_with_alerts(**kwargs):
    """APScheduler 任务包装：生成失败时 Telegram 告警后再抛出。"""
    try:
        generate_and_publish(**kwargs)
    except Exception as e:
        logger.error("Scheduled report failed: %s", e, exc_info=True)
        try:
            from core.notify.ops_alert import send_ops_alert
            from html import escape as _esc
            send_ops_alert(f"🔴 <b>Arbor 周报定时任务失败</b>\n<code>{_esc(str(e))}</code>")
        except Exception:
            pass
        raise


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
        _job_with_alerts,
        trigger=CronTrigger(day_of_week="sat", hour=hour, minute=minute),
        kwargs={
            "output_dir": output_dir,
            "output_format": output_format,
            "forecast_offset": 1,
        },
        id="weekly_report",
        name="Arbor Weekly Report",
        replace_existing=True,
        misfire_grace_time=3600,  # 机器休眠唤醒后 1 小时内仍补跑
        coalesce=True,
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
        "--alert-test", action="store_true",
        help="Send a test ops alert via Telegram and exit",
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

    if args.alert_test:
        from core.notify.ops_alert import send_ops_alert
        ok = send_ops_alert(
            "✅ <b>Arbor 告警链路测试</b>\n看到这条消息说明 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 配置正确。"
        )
        print("✓ alert sent" if ok else "✗ alert NOT sent（未配置或发送失败，加 -v 看日志）")
        return 0 if ok else 1

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
