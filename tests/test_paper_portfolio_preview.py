from dataclasses import asdict
from datetime import date
import json
import subprocess
import sys

import pytest

from arbor.application.paper_trading.portfolio import ContractQuote, PortfolioPaperEngine
from tests.test_purchase_batch import batch, AS_OF
from tests.test_paper_portfolio import request


def inputs(as_of=AS_OF, price=200):
    return dict(quotes={'KC-2026-12':ContractQuote(price,as_of)},
                margins={'KC-2026-12':1000}, as_of=as_of)


def test_preview_matches_execution_without_mutation_or_operation_id(tmp_path):
    path = tmp_path/'account.db'
    e = PortfolioPaperEngine(path, initial_equity=2000)
    before = e.snapshot()
    readonly = PortfolioPaperEngine.open_readonly(path)
    preview = readonly.preview_batches([batch(), batch(batch_id='lot-2')], **inputs())
    assert preview['mode'] == 'PREVIEW_NO_ORDER'
    assert preview['base_version'] == 0
    assert readonly.snapshot() == before
    assert readonly.history() == []
    assert not readonly.conn.in_transaction
    result = request(e, [batch(), batch(batch_id='lot-2')])
    assert preview['projected_state'] == result['state']
    assert preview['proposed_trades'] == result['trades']
    assert preview['plans'] == result['plans']
    readonly.close()
    e.close()


def test_preview_uses_latest_state_and_keeps_overdue_reduction_rules(tmp_path):
    path = tmp_path/'account.db'
    e = PortfolioPaperEngine(path, initial_equity=100000)
    readonly = PortfolioPaperEngine.open_readonly(path)
    request(e, [batch(target_ratio=1)])
    before = e.snapshot()
    later = date(2026,11,25)
    preview = readonly.preview_batches([], **inputs(later,210), reduce_to_contracts={'lot-1':1})
    assert preview['base_version'] == 1
    assert preview['projected_state']['additions_blocked']
    assert preview['proposed_trades'][0]['contracts'] == 1
    assert preview['proposed_trades'][0]['gross_pnl'] == pytest.approx(3750)
    assert e.snapshot() == before
    assert len(e.history()) == 1
    with pytest.raises(ValueError, match='cannot increase'):
        readonly.preview_batches([], **inputs(), reduce_to_contracts={'lot-1':3})
    assert not readonly.conn.in_transaction
    assert readonly.snapshot() == before
    readonly.close()
    e.close()


def test_cli_dry_run_does_not_create_database_or_account(tmp_path):
    source = tmp_path/'input.json'
    source.write_text(json.dumps({'quotes':{},'margins_usd':{}}))
    path = tmp_path/'absent.db'
    command = [sys.executable,'-m','cli.paper_portfolio',str(source),'--db',str(path),
               '--as-of',AS_OF.isoformat(),'--dry-run']
    missing = subprocess.run(command,capture_output=True,text=True)
    assert missing.returncode == 2
    assert not path.exists()
    e = PortfolioPaperEngine(path, initial_equity=2000)
    missing_account = subprocess.run(command+['--account','missing'],capture_output=True,text=True)
    assert missing_account.returncode == 2
    assert e.conn.execute('SELECT count(*) FROM paper_portfolio_accounts').fetchone()[0] == 1
    source.write_text(json.dumps({'batches':[asdict(batch())],
        'quotes':{'KC-2026-12':{'price':200,'as_of':AS_OF.isoformat()}},
        'margins_usd':{'KC-2026-12':1000}},default=str))
    success = subprocess.run(command,capture_output=True,text=True,check=True)
    assert json.loads(success.stdout)['proposed_trades'][0]['action'] == 'open'
    assert e.snapshot()['version'] == 0
    assert e.history() == []
    e.close()


def test_version_guard_rejects_stale_preview_but_allows_exact_retry(tmp_path):
    e = PortfolioPaperEngine(tmp_path/'account.db', initial_equity=100000)
    preview = e.preview_batches([batch()], **inputs())
    request(e, operation_id='other')
    before = e.snapshot()
    with pytest.raises(ValueError, match='version changed'):
        request(e, [batch()], operation_id='execute', expected_version=preview['base_version'])
    assert e.snapshot() == before
    assert len(e.history()) == 1
    result = request(e, [batch()], operation_id='execute', expected_version=1)
    request(e, operation_id='later')
    assert request(e, [batch()], operation_id='execute', expected_version=1) == result
    assert len(e.history()) == 3
    e.close()
