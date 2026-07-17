#!/usr/bin/env python3
"""
scripts/weekly_report_daemon.py
咖啡期货周报定时生成守护进程

功能:
  - 每周一早上 9:00 自动生成下周预测报告 (HTML)
  - 接入 ML 模型预测结果
  - 支持立即运行一次 (--now)
  - 支持自定义输出目录 (--output-dir)

用法:
  python scripts/weekly_report_daemon.py              # 守护模式，每周一 9:00 执行
  python scripts/weekly_report_daemon.py --now        # 立即生成一份报告
  python scripts/weekly_report_daemon.py --now --output-dir ./reports_output
  python scripts/weekly_report_daemon.py --cron-hour 8 --cron-minute 30  # 自定义时间

输出:
  {output_dir}/weekly_report_YYYY-MM-DD.html
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Ensure project root on path ────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from reports.pipeline import run, PipelineConfig
from reports.exporters import export_report
from reports.history import save_report_summary, load_last_week_summary, compute_prediction_review

logger = logging.getLogger("weekly_daemon")


# ─────────────────────────────────────────────────────────────────────────────
# Email Distribution
# ─────────────────────────────────────────────────────────────────────────────

def _send_report_email(report, html_path: Path) -> None:
    """
    Send the weekly report via SMTP if COFFEE_SMTP_* env vars are configured.
    Gracefully skips if not configured.
    """
    host = os.getenv("COFFEE_SMTP_HOST")
    port = int(os.getenv("COFFEE_SMTP_PORT", "587"))
    user = os.getenv("COFFEE_SMTP_USER")
    password = os.getenv("COFFEE_SMTP_PASS")
    to_addrs = os.getenv("COFFEE_SMTP_TO", "")
    from_addr = os.getenv("COFFEE_SMTP_FROM", user or "coffee-report@localhost")

    if not host or not to_addrs:
        logger.debug("SMTP not configured (COFFEE_SMTP_HOST/TO missing), skipping email.")
        return

    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【咖啡期货周报】{report.ticker} {report.report_date} | ML:{report.ml_snapshot.signal if report.ml_snapshot else 'N/A'}"
    msg["From"] = from_addr
    msg["To"] = to_addrs

    # Plain text preview
    text_body = f"""咖啡期货周报 {report.report_date}
合约: {report.ticker}
当前价格: {report.market.current if report.market else 'N/A'}
ML信号: {report.ml_snapshot.signal if report.ml_snapshot else 'N/A'}
套保建议: {report.hedge_advice.signal if report.hedge_advice else 'N/A'} ({report.hedge_advice.ratio if report.hedge_advice else 0:.0%})
预测区间: {report.forecast_week_start} ~ {report.forecast_week_end}

详见附件 HTML 报告。
"""
    msg.attach(MIMEText(text_body, "plain", "utf-8"))

    # HTML body (inline the report)
    html_content = html_path.read_text(encoding="utf-8")
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Attach HTML file
    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(html_path.read_bytes())
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        f"attachment; filename={html_path.name}",
    )
    msg.attach(attachment)

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        if user and password:
            server.login(user, password)
        server.sendmail(from_addr, to_addrs.split(","), msg.as_string())

    logger.info("Report email sent to %s", to_addrs)


# ─────────────────────────────────────────────────────────────────────────────
# Report Generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_weekly_report(
    output_dir: Path,
    forecast_offset: int = 1,
    output_format: str = "html",
) -> Path:
    """
    生成周报并保存为 HTML 或 PDF。

    Args:
        output_dir: 输出目录
        forecast_offset: 0=本周, 1=下周, 2=下下周
        output_format: 'html' | 'pdf'

    Returns:
        保存的文件路径
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    today_str = date.today().strftime("%Y-%m-%d")
    ext = "pdf" if output_format == "pdf" else "html"
    dest = output_dir / f"weekly_report_{today_str}.{ext}"

    logger.info("Generating weekly report (format=%s, forecast_offset=%d)...", output_format, forecast_offset)

    config = PipelineConfig(
        ticker="KC=F",
        use_demo_data=False,       # 拉取实时数据
        output_format=output_format,
        forecast_week_offset=forecast_offset,
    )

    report = run(config)

    # Export
    export_report(report, format=output_format, dest=str(dest))

    # Save summary for next week's prediction review
    try:
        save_report_summary(report)
    except Exception as e:
        logger.warning("Failed to save report summary: %s", e)

    # Send email if SMTP configured (attach HTML for now)
    if output_format == "html":
        try:
            _send_report_email(report, dest)
        except Exception as e:
            logger.warning("Email send failed: %s", e)

    logger.info("Report saved: %s", dest)
    logger.info(
        "  Forecast: %s ~ %s | Hedge: %s | ML: %s",
        report.forecast_week_start,
        report.forecast_week_end,
        report.hedge_advice.signal if report.hedge_advice else "N/A",
        report.ml_snapshot.signal if report.ml_snapshot else "N/A",
    )

    return dest


# ─────────────────────────────────────────────────────────────────────────────
# Scheduling
# ─────────────────────────────────────────────────────────────────────────────

def _next_monday_9am(hour: int, minute: int) -> datetime:
    """计算下一个周一的指定时间。"""
    now = datetime.now()
    days_ahead = 7 - now.weekday()  # Monday = 0
    if days_ahead == 7 and now.hour < hour:
        days_ahead = 0
    elif days_ahead == 7 and now.hour == hour and now.minute < minute:
        days_ahead = 0
    next_run = (now + timedelta(days=days_ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if next_run <= now:
        next_run += timedelta(days=7)
    return next_run


def run_daemon(output_dir: Path, cron_hour: int = 9, cron_minute: int = 0) -> None:
    """
    守护模式：每周一早上生成报告。
    """
    logger.info("Weekly Report Daemon started")
    logger.info("Schedule: Every Monday at %02d:%02d", cron_hour, cron_minute)
    logger.info("Output dir: %s", output_dir)

    while True:
        next_run = _next_monday_9am(cron_hour, cron_minute)
        sleep_seconds = (next_run - datetime.now()).total_seconds()

        logger.info("Next run at %s (sleeping %.0f seconds)...", next_run, sleep_seconds)
        time.sleep(sleep_seconds)

        try:
            generate_weekly_report(output_dir, forecast_offset=1, output_format=args.format)
        except Exception as e:
            logger.error("Report generation failed: %s", e, exc_info=True)

        # 防止同一分钟内重复执行
        time.sleep(60)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Arbor Weekly Report Daemon",
    )
    parser.add_argument(
        "--now", action="store_true",
        help="Run immediately once and exit (no daemon mode)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="output/weekly",
        help="Output directory for reports (default: output/weekly)",
    )
    parser.add_argument(
        "--cron-hour", type=int, default=9,
        help="Hour for weekly execution (default: 9)",
    )
    parser.add_argument(
        "--cron-minute", type=int, default=0,
        help="Minute for weekly execution (default: 0)",
    )
    parser.add_argument(
        "--forecast-offset", type=int, default=1,
        help="Week offset: 0=current, 1=next (default: 1)",
    )
    parser.add_argument(
        "--format", type=str, default="html", choices=["html", "pdf"],
        help="Output format: html or pdf (default: html)",
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
            dest = generate_weekly_report(
                output_dir,
                forecast_offset=args.forecast_offset,
                output_format=args.format,
            )
            print(f"\n✓ Report generated: {dest}")
            return 0
        except Exception as e:
            logger.error("Failed: %s", e, exc_info=True)
            print(f"\n✗ Error: {e}")
            return 1

    # Daemon mode
    try:
        run_daemon(output_dir, cron_hour=args.cron_hour, cron_minute=args.cron_minute)
    except KeyboardInterrupt:
        logger.info("Daemon stopped by user.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
