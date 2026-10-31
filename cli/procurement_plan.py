"""Read a batch JSON and print a preview; never place or persist orders."""
import argparse
from datetime import date
import json
from pathlib import Path

from arbor.domain.purchase_batch import batch_from_dict, preview_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--as-of', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'))
        result = preview_batch(batch_from_dict(data['batch']), as_of=args.as_of,
            equity=data['equity_usd'], margin_per_contract=data.get('margin_per_contract_usd'),
            shocks=data.get('shocks', []))
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
