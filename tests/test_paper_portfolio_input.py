import json
import subprocess
import sys

import pytest

from cli.paper_portfolio import load_request


@pytest.mark.parametrize('raw', [
    '{"quotes":{},"quotes":{},"margins_usd":{}}',
    '{"quotes":{},"margins_usd":{},"reduce_to_contracts":{"lot-1":0,"lot-1":1}}',
    '{"quotes":{},"margins_usd":{},"initial_equity_usd":NaN}',
    '{"quotes":{},"margins_usd":{"KC-2026-12":Infinity}}',
    '{"quotes":{},"margins_usd":{},"reduce_to_contract":{}}',
    '{"quotes":{},"margins_usd":{},"reduce_to_contracts":false}',
    '{"quotes":{},"margins_usd":{},"batches":{}}',
    '{"quotes":{},"margins_usd":{},"close_batch_ids":"lot-1"}',
    '{"quotes":{},"margins_usd":{},"initial_equity_usd":1e999}',
    '[]', 'null', '{}',
])
def test_ambiguous_cli_request_fails_before_creating_account(tmp_path, raw):
    source = tmp_path/'input.json'
    source.write_text(raw)
    db = tmp_path/'account.db'
    result = subprocess.run([sys.executable, '-m', 'cli.paper_portfolio', str(source),
        '--db', str(db), '--operation-id', 'bad', '--as-of', '2026-10-30'],
        capture_output=True, text=True)
    assert result.returncode == 2
    assert 'error:' in result.stderr
    assert 'Traceback' not in result.stderr
    assert not db.exists()


def test_valid_request_preserves_reduction_targets():
    data = {'quotes':{}, 'margins_usd':{}, 'reduce_to_contracts':{'lot-1':0}}
    assert load_request(json.dumps(data)) == data
