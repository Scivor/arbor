"""
reports/cli.py
Command-line interface for the reports package.

Usage:
    python -m reports.cli                  # text format (demo data)
    python -m reports.cli --format rich   # Rich console output
    python -m reports.cli --format json    # JSON output
    python -m reports.cli --format pdf     # PDF (ASCII, requires fpdf2)
    python -m reports.cli --format html --chinese   # Chinese HTML (open in browser, Print>Save as PDF)
    python -m reports.cli --ticker KC=F    # live data for KC=F
    python -m reports.cli --demo           # demo mode
"""

import argparse
import sys
from reports.pipeline import run, PipelineConfig
from reports.exporters import export_text, export_json, export_rich

try:
    from reports.exporters.pdf_exporter import export_pdf as _export_pdf
    _HAS_FPDF = True
except Exception:
    _HAS_FPDF = False

try:
    from reports.exporters.html_to_pdf import build_chinese_html
    _HAS_HTML = True
except Exception:
    _HAS_HTML = False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m reports",
        description="Coffee Futures Weekly Outlook — Report Generator",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "rich", "json", "pdf", "html"],
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
        "--chinese",
        action="store_true",
        help="Use Chinese language for HTML output (open in browser, Print > Save as PDF)",
    )
    args = parser.parse_args(argv)

    # Run pipeline
    config = PipelineConfig(
        ticker=args.ticker,
        use_demo_data=args.demo,
        output_format=args.format,
    )
    report = run(config)

    # Export
    if args.format == "text":
        output = export_text(report)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        else:
            print(output)

    elif args.format == "rich":
        try:
            export_rich(report)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.format == "json":
        output = export_json(report)
        dest = args.output or "stdout.json"
        with open(dest, "w") as f:
            f.write(output)
        print(f"JSON written to {dest}")

    elif args.format == "pdf":
        dest = args.output or "coffee_outlook.pdf"
        if not _HAS_FPDF:
            print("Error: PDF export requires fpdf2 — pip install fpdf2",
                  file=sys.stderr)
            return 1
        _export_pdf(report, dest)
        print(f"PDF written to {dest}")

    elif args.format == "html":
        dest = args.output or "coffee_outlook.html"
        if args.chinese:
            if not _HAS_HTML:
                print("Error: HTML builder not available", file=sys.stderr)
                return 1
            html = build_chinese_html(report)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"Chinese HTML written to {dest}")
            print("  → Open in browser and use File > Print > Save as PDF")
        else:
            html = build_chinese_html(report)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"HTML written to {dest}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
