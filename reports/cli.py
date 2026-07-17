"""
reports/cli.py
Command-line interface for the reports package.

Usage:
    python -m reports.cli                  # text format (demo data)
    python -m reports.cli --format json    # JSON output
    python -m reports.cli --format html    # HTML output
    python -m reports.cli --ticker KC=F    # live data for KC=F
    python -m reports.cli --demo           # demo mode
"""

import argparse
import sys
from datetime import datetime
from reports.pipeline import run, PipelineConfig
from reports.exporters import export_text, export_json

try:
    from reports.exporters.html_to_pdf import build_report_html
    _HAS_HTML = True
except Exception:
    _HAS_HTML = False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m reports",
        description="Arbor Report Generator",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json", "html", "pdf"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--demo", "-d",
        action="store_true",
        help="Use built-in demo data (skip live fetches)",
    )
    parser.add_argument(
        "--ticker", "-t",
        default="KC=F",
        help="Futures ticker to report on (default: KC=F)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path.",
    )
    parser.add_argument(
        "--lang", "-l",
        default="zh",
        choices=["zh", "en"],
        help="Report language: zh=Chinese, en=English (default: zh)",
    )
    args = parser.parse_args(argv)

    config = PipelineConfig(
        ticker=args.ticker,
        use_demo_data=args.demo,
        output_format=args.format,
    )
    report = run(config)

    if args.format == "text":
        output = export_text(report)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        else:
            print(output)

    elif args.format == "json":
        output = export_json(report)
        dest = args.output or "stdout.json"
        with open(dest, "w") as f:
            f.write(output)
        print(f"JSON written to {dest}")

    elif args.format == "html":
        dest = args.output or "coffee_outlook.html"
        if not _HAS_HTML:
            print("Error: HTML builder not available", file=sys.stderr)
            return 1
        html = build_report_html(report, lang=args.lang)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"HTML written to {dest}")

    elif args.format == "pdf":
        dest = args.output or f"coffee_outlook_{datetime.now().strftime('%Y-%m-%d')}.pdf"
        if not _HAS_HTML:
            print("Error: HTML builder not available", file=sys.stderr)
            return 1
        from reports.exporters.html_to_pdf import export_pdf
        pdf_path = export_pdf(report, dest=dest, lang=args.lang)
        print(f"PDF written to {pdf_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
