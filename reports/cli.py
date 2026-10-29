"""
reports/cli.py
预测与套保结果的命令行出口。只输出文本或 JSON。

Usage:
    python -m reports.cli                  # text format (demo data)
    python -m reports.cli --format json    # JSON output
    python -m reports.cli --ticker KC=F    # live data for KC=F
    python -m reports.cli --demo           # demo mode
"""

import argparse
import sys

from reports.exporters import export_json, export_text, list_exporters
from reports.pipeline import PipelineConfig, run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m reports",
        description="Arbor forecast and hedge output",
    )
    parser.add_argument(
        "--format", "-f",
        choices=list_exporters(),
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
