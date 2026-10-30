from dataclasses import asdict
import json
import subprocess
import sys
import pytest
from cli.forecast_labels import evaluate_archive
from tests.test_forecast_outcome import F, SESSIONS


def archive():
    return {'forecasts':[asdict(F)], 'calendars':{F.calendar_version:SESSIONS},
            'observations':[dict(contract_id=F.contract_id,session_close=SESSIONS[4],
                available_at=SESSIONS[4],price=203,source='synthetic-test')]}


def test_cli_matches_api_and_preserves_inputs(tmp_path):
    raw = json.dumps(archive(),default=lambda x:x.isoformat())
    path = tmp_path/'archive.json'
    path.write_text(raw)
    result = subprocess.run([sys.executable,'-m','cli.forecast_labels',str(path),
        '--evaluated-at',SESSIONS[-1].isoformat()],capture_output=True,text=True,check=True)
    out = json.loads(result.stdout)
    assert out == evaluate_archive(raw,evaluated_at=SESSIONS[-1])
    assert out['labeled'] == 1
    assert out['results'][0]['actual'] == 'up'
    assert not out['provenance_verified']
    assert path.read_text() == raw


def test_missing_data_stays_pending_and_duplicate_forecasts_rejected():
    data = archive()
    data['observations'] = []
    out = evaluate_archive(json.dumps(data,default=lambda x:x.isoformat()),evaluated_at=SESSIONS[-1])
    assert out['labeled'] == 0
    assert out['results'][0]['reason'] == 'target_close_missing_or_not_available'
    data['forecasts'] *= 2
    with pytest.raises(ValueError,match='duplicate forecast'):
        evaluate_archive(json.dumps(data,default=lambda x:x.isoformat()),evaluated_at=SESSIONS[-1])
