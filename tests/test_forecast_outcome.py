from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pytest
from arbor.domain.forecast_outcome import FrozenForecast, ObservedClose, label_fifth_session

BASE = datetime(2026,10,30,20,tzinfo=timezone.utc)
SESSIONS = [BASE+timedelta(days=i) for i in (3,4,5,6,7,10)]
F = FrozenForecast('f1','KC-2026-12',BASE,BASE,200,-.01,.01,'v1','calendar-1')


def test_exact_fifth_session_not_later_proxy():
    later = ObservedClose(F.contract_id,SESSIONS[5],SESSIONS[5],220,'fixture')
    assert label_fifth_session(F,SESSIONS,[later],evaluated_at=SESSIONS[5])['status'] == 'pending'


@pytest.mark.parametrize('price,actual', [(198,'flat'),(202,'flat'),(197,'down'),(203,'up')])
def test_frozen_thresholds_and_available_time(price,actual):
    close = ObservedClose(F.contract_id,SESSIONS[4],SESSIONS[4]+timedelta(hours=1),price,'fixture')
    assert label_fifth_session(F,SESSIONS,[close],evaluated_at=SESSIONS[4])['status'] == 'pending'
    result = label_fifth_session(F,SESSIONS,[close],evaluated_at=SESSIONS[5])
    assert result['actual'] == actual
    assert not result['calibration_validated']
    with pytest.raises(ValueError,match='duplicate'):
        label_fifth_session(F,SESSIONS,[close,close],evaluated_at=SESSIONS[5])


def test_calendar_contract_and_chronology_guards():
    close = ObservedClose('KC-2027-03',SESSIONS[4],SESSIONS[4],220,'fixture')
    assert label_fifth_session(F,SESSIONS,[close],evaluated_at=SESSIONS[5])['status'] == 'pending'
    for calendar in (SESSIONS[:4],SESSIONS[::-1],SESSIONS+[SESSIONS[-1]]):
        with pytest.raises(ValueError):
            label_fifth_session(F,calendar,[],evaluated_at=SESSIONS[5])
    with pytest.raises(ValueError):
        label_fifth_session(replace(F,data_cutoff=SESSIONS[0]),SESSIONS,[],evaluated_at=SESSIONS[5])
