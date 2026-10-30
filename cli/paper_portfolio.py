"""Persistent multi-batch PAPER account CLI. No broker connection or orders."""
import argparse
from datetime import date
import json
import math
import sqlite3
from pathlib import Path

from arbor.application.paper_trading.portfolio import ContractQuote, PortfolioPaperEngine
from arbor.domain.purchase_batch import batch_from_dict


def load_request(text):
    """Reject ambiguous JSON before opening or creating an account database."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON field: {key}')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f'non-finite JSON number: {value}')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('JSON number exceeds finite range')
        return number

    data = json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=invalid_constant, parse_float=finite_float)
    if not isinstance(data, dict):
        raise ValueError('request must be a JSON object')
    allowed = {'initial_equity_usd', 'commission_usd', 'batches', 'quotes',
               'margins_usd', 'close_batch_ids', 'reduce_to_contracts', 'expected_version'}
    unknown = set(data)-allowed
    if unknown:
        raise ValueError(f'unknown request fields: {", ".join(sorted(unknown))}')
    for field in ('quotes', 'margins_usd'):
        if field not in data or not isinstance(data[field], dict):
            raise ValueError(f'{field} must be a JSON object')
    if 'reduce_to_contracts' in data and not isinstance(data['reduce_to_contracts'], dict):
        raise ValueError('reduce_to_contracts must be a JSON object')
    for field in ('batches', 'close_batch_ids'):
        if field in data and not isinstance(data[field], list):
            raise ValueError(f'{field} must be a JSON array')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--db', required=True)
    parser.add_argument('--account', default='default')
    parser.add_argument('--operation-id')
    parser.add_argument('--dry-run', action='store_true', help='Preview an existing account without saving')
    parser.add_argument('--as-of', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    if not args.dry_run and not args.operation_id:
        parser.error('--operation-id is required unless --dry-run is used')
    engine = None
    try:
        data = load_request(args.input.read_text(encoding='utf-8'))
        if args.dry_run:
            engine = PortfolioPaperEngine.open_readonly(args.db, account_id=args.account)
            state = engine.snapshot()
            for field, stored in (('initial_equity_usd', 'initial_equity'), ('commission_usd', 'commission')):
                if field in data and data[field] != state[stored]:
                    raise ValueError(f'{field} differs from existing account')
        else:
            engine = PortfolioPaperEngine(args.db, account_id=args.account,
                initial_equity=data.get('initial_equity_usd'), commission=data.get('commission_usd', 15.))
        action = engine.preview_batches if args.dry_run else engine.sync_batches
        operation = {} if args.dry_run else {'operation_id': args.operation_id}
        result = action([batch_from_dict(b) for b in data.get('batches', [])],
            quotes={k: ContractQuote(v['price'], date.fromisoformat(v['as_of'])) for k,v in data['quotes'].items()},
            margins=data['margins_usd'], as_of=args.as_of, **operation,
            close_batch_ids=data.get('close_batch_ids', []),
            reduce_to_contracts=data.get('reduce_to_contracts', {}),
            expected_version=data.get('expected_version'))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    finally:
        if engine:
            engine.close()


if __name__ == '__main__':
    main()
