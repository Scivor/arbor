"""Transactional multi-batch paper account; no broker orders.

One shared cash balance and margin budget. Reductions precede additions;
addition priority is explicit input order. All open contracts require dated
quotes for valuation. Existing positions are not automatically liquidated.
"""
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from arbor.domain.procurement import KC_CONTRACT_TONNES as KC, futures_pnl, nonnegative, plan_procurement


@dataclass(frozen=True)
class ContractQuote:
    price: float
    as_of: date


class PortfolioPaperEngine:
    def __init__(self, db_path, *, account_id='default', initial_equity=None, commission=15.):
        if not account_id.strip():
            raise ValueError('account_id required')
        nonnegative('commission', commission)
        path = Path(db_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.account_id = account_id
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS paper_portfolio_accounts (
                account_id TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS paper_portfolio_operations (
                account_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                request_hash TEXT NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(account_id, operation_id));
        ''')
        try:
            self.conn.execute('BEGIN IMMEDIATE')
            row = self.conn.execute('SELECT state FROM paper_portfolio_accounts WHERE account_id=?', (account_id,)).fetchone()
            if row is None:
                if initial_equity is None:
                    raise ValueError('initial_equity required for a new account')
                nonnegative('initial_equity', initial_equity)
                state = dict(initial_equity=initial_equity, cash=initial_equity, commission=commission,
                             positions={}, as_of=None, version=0, mode='PAPER_PORTFOLIO', currency='USD')
                self.conn.execute('INSERT INTO paper_portfolio_accounts VALUES (?,?)', (account_id, json.dumps(state)))
            else:
                state = json.loads(row[0])
                if initial_equity is not None and initial_equity != state['initial_equity']:
                    raise ValueError('existing account capital differs; reopening cannot reset cash')
                if commission != state['commission']:
                    raise ValueError('existing account commission differs')
            self.conn.execute('COMMIT')
        except Exception:
            self.conn.execute('ROLLBACK')
            self.conn.close()
            raise

    def snapshot(self):
        """Last persisted valuation, NOT a fresh market quote."""
        row = self.conn.execute('SELECT state FROM paper_portfolio_accounts WHERE account_id=?', (self.account_id,)).fetchone()
        return json.loads(row[0])

    def history(self):
        rows = self.conn.execute('SELECT operation_id, result FROM paper_portfolio_operations WHERE account_id=? ORDER BY rowid', (self.account_id,))
        return [{'operation_id': row[0], **json.loads(row[1])} for row in rows]

    def close(self):
        self.conn.close()

    def sync_batches(self, batches, *, quotes, margins, as_of, operation_id, close_batch_ids=()):
        """Atomically revalue, close/reduce, allocate and save a paper account.

        Retry the SAME operation_id and payload to retrieve its original result
        without trading twice. Another payload under that id is rejected.
        Unmentioned batches remain open, with their margin reserved.
        """
        if not operation_id.strip():
            raise ValueError('operation_id required')
        batches = list(batches)
        close_batch_ids = list(close_batch_ids)
        ids = [b.batch_id for b in batches]
        if len(set(ids)) != len(ids) or len(set(close_batch_ids)) != len(close_batch_ids):
            raise ValueError('duplicate batch ids')
        if set(ids) & set(close_batch_ids):
            raise ValueError('cannot both close and resize a batch')
        for b in batches:
            b.validate(as_of)
            if b.contract_id not in quotes or not math.isclose(quotes[b.contract_id].price, b.kc_price_cents_lb, rel_tol=1e-12):
                raise ValueError('missing or mismatched batch contract quote')
        for key, quote in quotes.items():
            if quote.as_of != as_of or not math.isfinite(quote.price) or quote.price <= 0:
                raise ValueError(f'invalid or stale quote: {key}')
        payload = json.dumps(dict(batches=[asdict(b) for b in batches],
            quotes={k: asdict(q) for k,q in quotes.items()}, margins=margins,
            as_of=as_of, close_batch_ids=close_batch_ids), default=str, sort_keys=True, allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            saved = self.conn.execute('SELECT request_hash,result FROM paper_portfolio_operations WHERE account_id=? AND operation_id=?',
                                      (self.account_id, operation_id)).fetchone()
            if saved:
                if saved[0] != digest:
                    raise ValueError('operation_id already used with different inputs')
                result = json.loads(saved[1])
                self.conn.execute('COMMIT')
                return result
            state = self.snapshot()
            if state['as_of'] and as_of.isoformat() < state['as_of']:
                raise ValueError('cannot backdate an account operation')
            positions = state['positions']
            required = {p['contract_id'] for p in positions.values()} | {b.contract_id for b in batches}
            for contract in required:
                if contract not in quotes or contract not in margins:
                    raise ValueError(f'quote and margin required for every open contract: {contract}')
                if not math.isfinite(margins[contract]) or margins[contract] <= 0:
                    raise ValueError('margin must be positive and finite')
            for b in batches:
                if b.batch_id in positions and positions[b.batch_id]['contract_id'] != b.contract_id:
                    raise ValueError('close old contract explicitly before rolling this batch')
            for batch_id in close_batch_ids:
                if batch_id not in positions:
                    raise ValueError(f'cannot close unknown batch: {batch_id}')
            fee = state['commission']
            trades = []
            def equity():
                return state['cash'] + sum(futures_pnl(p['entry_price'], quotes[p['contract_id']].price, p['contracts']*KC) for p in positions.values())
            def reserved():
                return sum(p['contracts']*(margins[p['contract_id']]+fee) for p in positions.values())
            def reduce(batch_id, target):
                p = positions[batch_id]
                count = p['contracts']-target
                if count <= 0:
                    return
                price = quotes[p['contract_id']].price
                gross = futures_pnl(p['entry_price'], price, count*KC)
                state['cash'] += gross-count*fee
                trades.append(dict(batch_id=batch_id, contract_id=p['contract_id'], action='close',
                                   contracts=count, price=price, gross_pnl=gross, commission=count*fee))
                p['contracts'] = target
                if target == 0:
                    del positions[batch_id]
            targets = {b.batch_id: plan_procurement(purchase_tonnes=b.purchase_tonnes,
                priced_tonnes=b.priced_tonnes, target_ratio=b.target_ratio).target_contracts for b in batches}
            for batch_id in close_batch_ids:
                reduce(batch_id, 0)
            for b in batches:
                if b.batch_id in positions:
                    reduce(b.batch_id, targets[b.batch_id])
            # Inspect persisted deadlines after reductions, before caller metadata
            # can replace them. A date edit must not bypass an overdue position.
            blocked_batches = sorted(key for key, p in positions.items()
                if as_of.isoformat() >= p['batch']['exit_deadline']
                or as_of.isoformat() > p['batch']['pricing_date'])
            plans = []
            for b in batches:
                existing = positions.get(b.batch_id, {}).get('contracts', 0)
                wanted = max(0, targets[b.batch_id]-existing)
                free = max(0., equity()-reserved())
                affordable = math.floor(free/(margins[b.contract_id]+2*fee))
                count = 0 if blocked_batches else min(wanted, affordable)
                price = quotes[b.contract_id].price
                if count:
                    p = positions.setdefault(b.batch_id, dict(batch_id=b.batch_id, contract_id=b.contract_id,
                        contracts=0, entry_price=0.))
                    p['entry_price'] = (p['entry_price']*existing+price*count)/(existing+count)
                    p['contracts'] += count
                    state['cash'] -= count*fee
                    trades.append(dict(batch_id=b.batch_id, contract_id=b.contract_id, action='open',
                                       contracts=count, price=price, gross_pnl=0., commission=count*fee))
                actual = existing+count
                remaining = b.purchase_tonnes-b.priced_tonnes
                plans.append(dict(batch_id=b.batch_id, contract_id=b.contract_id,
                    target_contracts=targets[b.batch_id], actual_contracts=actual,
                    unpriced_tonnes=remaining, residual_tonnes=max(0., remaining-actual*KC),
                    cash_limited=wanted > affordable,
                    risk_blocked=bool(blocked_batches) and wanted > 0,
                    blocking_batch_ids=blocked_batches if wanted > 0 else []))
                if b.batch_id in positions:
                    metadata = json.loads(json.dumps(asdict(b), default=str))
                    if b.batch_id in blocked_batches:
                        for field in ('pricing_date', 'exit_deadline'):
                            metadata[field] = positions[b.batch_id]['batch'][field]
                    positions[b.batch_id]['batch'] = metadata
            state['equity'] = equity()
            state['unrealized_pnl'] = state['equity']-state['cash']
            state['margin_required'] = sum(p['contracts']*margins[p['contract_id']] for p in positions.values())
            state['closing_fee_reserve'] = sum(p['contracts']*fee for p in positions.values())
            state['available_budget'] = max(0., state['equity']-reserved())
            state['margin_shortfall'] = max(0., state['margin_required']-state['equity'])
            state['deadline_alerts'] = [
                {'batch_id': key, 'exit_deadline': p['batch']['exit_deadline'],
                 'pricing_date': p['batch']['pricing_date'], 'action': 'review_or_close_explicitly'}
                for key, p in positions.items()
                if as_of.isoformat() >= p['batch']['exit_deadline']
                or as_of.isoformat() > p['batch']['pricing_date']]
            state['additions_blocked'] = bool(blocked_batches)
            state['blocking_batch_ids'] = blocked_batches
            state['as_of'] = as_of.isoformat()
            state['quotes'] = {k: asdict(v) for k,v in quotes.items()}
            state['margins'] = margins
            state['version'] += 1
            result = dict(state=state, plans=plans, trades=trades, allocation_order=ids)
            serialized = json.dumps(result, default=str, allow_nan=False)
            self.conn.execute('UPDATE paper_portfolio_accounts SET state=? WHERE account_id=?',
                              (json.dumps(state, default=str, allow_nan=False), self.account_id))
            self.conn.execute('INSERT INTO paper_portfolio_operations VALUES (?,?,?,?)',
                              (self.account_id, operation_id, digest, serialized))
            self.conn.execute('COMMIT')
            return json.loads(serialized)
        except Exception:
            self.conn.execute('ROLLBACK')
            raise
