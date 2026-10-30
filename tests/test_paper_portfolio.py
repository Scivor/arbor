from dataclasses import replace
from datetime import date
import sqlite3

import pytest

from arbor.application.paper_trading.portfolio import ContractQuote, PortfolioPaperEngine
from tests.test_purchase_batch import batch, AS_OF


def request(engine, batches=(), *, operation_id='op-1', price=200., as_of=AS_OF, **kwargs):
    return engine.sync_batches(batches, quotes={'KC-2026-12': ContractQuote(price, as_of)},
        margins={'KC-2026-12': 1000.}, as_of=as_of, operation_id=operation_id, **kwargs)


def test_two_batches_share_one_budget_and_allocation_priority(tmp_path):
    e = PortfolioPaperEngine(tmp_path/'account.db', initial_equity=2000)
    out = request(e, [batch(), batch(batch_id='lot-2')])
    assert out['state']['positions']['lot-1']['contracts'] == 1
    assert 'lot-2' not in out['state']['positions']
    assert out['plans'][1]['cash_limited']
    assert out['allocation_order'] == ['lot-1', 'lot-2']
    assert out['state']['cash'] == 1985
    assert out['state']['margin_required'] == 1000
    assert out['state']['available_budget'] == 970
    moved = request(e, [batch(batch_id='lot-2')], operation_id='op-2', close_batch_ids=['lot-1'])
    assert set(moved['state']['positions']) == {'lot-2'}
    assert [t['action'] for t in moved['trades']] == ['close','open']
    assert moved['state']['cash'] == 1955
    e.close()


def test_restart_restores_positions_cash_quotes_history_without_recharging(tmp_path):
    path = tmp_path/'account.db'
    e = PortfolioPaperEngine(path, initial_equity=100000)
    out = request(e, [batch()])
    e.close()
    e = PortfolioPaperEngine(path)
    assert e.snapshot() == out['state']
    assert len(e.history()) == 1
    marked = request(e, operation_id='mark', price=210)
    assert marked['state']['cash'] == 99985
    assert marked['state']['unrealized_pnl'] == pytest.approx(3750)
    assert not marked['trades']
    closed = request(e, operation_id='close', price=210, close_batch_ids=['lot-1'])
    assert closed['state']['cash'] == pytest.approx(103720)
    assert closed['state']['unrealized_pnl'] == 0
    assert not closed['state']['positions']
    e.close()


def test_operation_retry_is_idempotent_and_reuse_with_new_payload_fails(tmp_path):
    e = PortfolioPaperEngine(tmp_path/'account.db', initial_equity=100000)
    first = request(e, [batch()])
    assert request(e, [batch()]) == first
    assert len(e.history()) == 1
    with pytest.raises(ValueError, match='different inputs'):
        request(e, [batch(target_ratio=1)])
    assert e.snapshot() == first['state']
    e.close()


def test_other_open_contract_must_have_fresh_quote_and_margin(tmp_path):
    e = PortfolioPaperEngine(tmp_path/'account.db', initial_equity=100000)
    first = request(e, [batch()])
    with pytest.raises(ValueError, match='every open contract'):
        e.sync_batches([], quotes={}, margins={}, as_of=AS_OF, operation_id='bad')
    with pytest.raises(ValueError, match='stale quote'):
        e.sync_batches([], quotes={'KC-2026-12':ContractQuote(200,date(2026,10,29))},
            margins={'KC-2026-12':1000}, as_of=AS_OF, operation_id='stale')
    assert e.snapshot() == first['state']
    e.close()


def test_failed_audit_insert_rolls_back_cash_and_positions(tmp_path):
    e = PortfolioPaperEngine(tmp_path/'account.db', initial_equity=100000)
    before = e.snapshot()
    e.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON paper_portfolio_operations BEGIN SELECT RAISE(ABORT,'test failure'); END;")
    with pytest.raises(sqlite3.IntegrityError):
        request(e, [batch()])
    assert e.snapshot() == before
    assert e.history() == []
    e.close()


def test_independent_connections_cannot_reuse_reserved_cash(tmp_path):
    path = tmp_path/'account.db'
    first = PortfolioPaperEngine(path, initial_equity=2000)
    second = PortfolioPaperEngine(path)
    request(first, [batch()])
    out = request(second, [batch(batch_id='lot-2')], operation_id='second')
    assert out['plans'][0]['actual_contracts'] == 0
    assert first.snapshot() == second.snapshot()
    first.close()
    second.close()


def test_contract_roll_requires_explicit_close_and_negative_equity_blocks_additions(tmp_path):
    e = PortfolioPaperEngine(tmp_path/'account.db', initial_equity=2000)
    request(e, [batch()])
    changed = replace(batch(), contract_month='2027-03')
    with pytest.raises(ValueError, match='close old contract'):
        e.sync_batches([changed], quotes={'KC-2026-12':ContractQuote(200,AS_OF),
            'KC-2027-03':ContractQuote(200,AS_OF)}, margins={'KC-2026-12':1000,'KC-2027-03':1000},
            as_of=AS_OF, operation_id='roll')
    stressed = request(e, [batch(batch_id='lot-2',kc_price_cents_lb=180)], price=180, operation_id='stress')
    assert stressed['state']['margin_shortfall'] > 0
    assert stressed['plans'][0]['actual_contracts'] == 0
    assert 'lot-1' in stressed['state']['positions']  # no unrequested liquidation
    e.close()


def test_reopening_cannot_reset_capital_and_backdated_ops_are_rejected(tmp_path):
    path = tmp_path/'account.db'
    e = PortfolioPaperEngine(path, initial_equity=2000)
    request(e, [batch()])
    with pytest.raises(ValueError, match='cannot reset'):
        PortfolioPaperEngine(path, initial_equity=100000)
    with pytest.raises(ValueError, match='backdate'):
        request(e, as_of=date(2026,10,29), operation_id='yesterday')
    e.close()


def test_deadline_warning_survives_restart_without_forced_liquidation(tmp_path):
    path = tmp_path/'account.db'
    e = PortfolioPaperEngine(path, initial_equity=100000)
    request(e, [batch()])
    out = request(e, as_of=date(2026,11,25), operation_id='deadline')
    assert out['state']['deadline_alerts'][0]['batch_id'] == 'lot-1'
    assert out['trades'] == []
    e.close()
    restored = PortfolioPaperEngine(path)
    assert restored.snapshot()['deadline_alerts'] == out['state']['deadline_alerts']
    restored.close()

def test_portfolio_cli_retries_persisted_operation_without_duplicate_trade(tmp_path):
    import json
    import subprocess
    import sys
    from dataclasses import asdict
    data = {'initial_equity_usd':2000, 'batches':[asdict(batch())],
            'quotes':{'KC-2026-12':{'price':200.,'as_of':AS_OF.isoformat()}},
            'margins_usd':{'KC-2026-12':1000.}}
    path = tmp_path/'input.json'
    path.write_text(json.dumps(data,default=str))
    command = [sys.executable,'-m','cli.paper_portfolio',str(path),'--db',str(tmp_path/'account.db'),
               '--operation-id','retry','--as-of',AS_OF.isoformat()]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    assert json.loads(first.stdout) == json.loads(second.stdout)
    e = PortfolioPaperEngine(tmp_path/'account.db')
    assert e.snapshot()['version'] == 1
    assert len(e.history()) == 1
    e.close()


def test_concurrent_connections_share_budget(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path/'account.db'
    seed = PortfolioPaperEngine(path, initial_equity=2000)
    seed.close()
    def act(number):
        e = PortfolioPaperEngine(path)
        try:
            return request(e, [batch(batch_id=f'lot-{number}')], operation_id=f'op-{number}')
        finally:
            e.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(act, [1,2]))
    e = PortfolioPaperEngine(path)
    assert sum(p['contracts'] for p in e.snapshot()['positions'].values()) == 1
    assert e.snapshot()['cash'] == 1985
    assert len(e.history()) == 2
    e.close()


def test_overdue_position_blocks_additions_until_explicit_close(tmp_path):
    e = PortfolioPaperEngine(tmp_path/'account.db', initial_equity=100000)
    request(e, [batch()])
    later = date(2026, 11, 25)
    fresh = batch(batch_id='lot-2', pricing_date=date(2026,11,27),
                  exit_deadline=date(2026,11,28))
    out = request(e, [fresh], as_of=later, operation_id='blocked')
    assert out['state']['additions_blocked']
    assert out['plans'][0]['risk_blocked']
    assert not out['plans'][0]['cash_limited']
    assert out['plans'][0]['blocking_batch_ids'] == ['lot-1']
    assert out['trades'] == []
    assert request(e, [fresh], as_of=later, operation_id='blocked') == out
    cleared = request(e, [fresh], as_of=later, operation_id='clear', close_batch_ids=['lot-1'])
    assert not cleared['state']['additions_blocked']
    assert [t['action'] for t in cleared['trades']] == ['close', 'open']
    e.close()


def test_deadline_edit_cannot_hide_overdue_position_and_reduction_still_works(tmp_path):
    e = PortfolioPaperEngine(tmp_path/'account.db', initial_equity=100000)
    original = batch(purchase_tonnes=200, priced_tonnes=0, target_ratio=1)
    first = request(e, [original])
    later = date(2026,11,25)
    revised = replace(original, pricing_date=date(2026,11,27), exit_deadline=date(2026,11,28), target_ratio=.5)
    out = request(e, [revised], as_of=later, operation_id='reduce')
    assert out['state']['additions_blocked']
    assert out['state']['positions']['lot-1']['contracts'] < first['state']['positions']['lot-1']['contracts']
    assert all(t['action'] == 'close' for t in out['trades'])
    assert out['state']['positions']['lot-1']['batch']['exit_deadline'] == original.exit_deadline.isoformat()
    increased = request(e, [replace(revised,target_ratio=1)], as_of=later, operation_id='increase')
    assert increased['plans'][0]['risk_blocked']
    assert increased['trades'] == []
    e.close()
