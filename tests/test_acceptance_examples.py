"""Exercise shipped runbook JSON through public CLIs with disposable accounts."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from arbor.application.paper_trading.portfolio import PortfolioPaperEngine

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return json.loads(subprocess.check_output([sys.executable, '-m', *args], cwd=ROOT, text=True))


def test_shipped_forecast_example_labels_and_pending():
    args = ('cli.forecast_labels','docs/examples/forecast-labels.json',
            '--probabilities','docs/examples/forecast-probabilities.json','--evaluated-at')
    result = run(*args,'2026-11-09T20:00:00+00:00')
    assert result['labeled'] == 1
    assert result['results'][0]['actual'] == 'up'
    assert result['probability_diagnostics']['mean_brier'] == pytest.approx(.26)
    assert result['grouped_diagnostics'][0]['nonoverlapping']['n_scored'] == 1
    assert not result['provenance_verified']
    assert not result['probability_diagnostics']['has_skill']
    pending = run(*args,'2026-11-05T20:00:00+00:00')
    assert pending['labeled'] == 0
    assert pending['results'][0]['reason'] == 'target_session_not_closed'
    assert pending['probability_diagnostics']['mean_brier'] is None


def test_shipped_portfolio_example_retry_preview_and_stale_execution(tmp_path):
    db = tmp_path/'account.db'
    args = ('cli.paper_portfolio','docs/examples/paper-portfolio.json','--db',str(db),
            '--account','acceptance-demo','--as-of','2026-10-30')
    first = run(*args,'--operation-id','initial')
    assert first == run(*args,'--operation-id','initial')
    assert first['state']['cash'] == 19955
    assert first['state']['margin_required'] == 15000
    preview = run(*args,'--dry-run')
    assert not preview['proposed_trades']
    account = PortfolioPaperEngine.open_readonly(db,account_id='acceptance-demo')
    try:
        assert account.snapshot() == first['state']
        assert len(account.history()) == 1
        run(*args,'--operation-id','intervening')
        before = account.snapshot()
        payload = json.loads((ROOT/'docs/examples/paper-portfolio.json').read_text())
        payload['expected_version'] = preview['base_version']
        request = tmp_path/'stale.json'
        request.write_text(json.dumps(payload))
        failed = subprocess.run([sys.executable,'-m','cli.paper_portfolio',str(request),
            '--db',str(db),'--account','acceptance-demo','--as-of','2026-10-30',
            '--operation-id','stale'],cwd=ROOT,capture_output=True,text=True)
        assert failed.returncode == 2
        assert 'version changed' in failed.stderr
        assert account.snapshot() == before
        assert len(account.history()) == 2
    finally:
        account.close()
