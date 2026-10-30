"""Persistent multi-batch PAPER account CLI. No broker connection or orders."""
import argparse
from datetime import date
import json
import sqlite3
from pathlib import Path

from arbor.application.paper_trading.portfolio import ContractQuote, PortfolioPaperEngine
from arbor.domain.purchase_batch import batch_from_dict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--db', required=True)
    parser.add_argument('--account', default='default')
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--as-of', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    engine = None
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'))
        engine = PortfolioPaperEngine(args.db, account_id=args.account,
            initial_equity=data.get('initial_equity_usd'), commission=data.get('commission_usd', 15.))
        result = engine.sync_batches([batch_from_dict(b) for b in data.get('batches', [])],
            quotes={k: ContractQuote(v['price'], date.fromisoformat(v['as_of'])) for k,v in data['quotes'].items()},
            margins=data['margins_usd'], as_of=args.as_of, operation_id=args.operation_id,
            close_batch_ids=data.get('close_batch_ids', []),
            reduce_to_contracts=data.get('reduce_to_contracts', {}))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    finally:
        if engine:
            engine.close()


if __name__ == '__main__':
    main()
