import pytest
from arbor.domain.forecast_scores import score_labels


def row(identifier, published, available, actual='up'):
    return dict(forecast_id=identifier,status='labeled',actual=actual,
        available_at=available, target_close=available, frozen_forecast={'published_at':published, 'contract_id':'KC-2026-12',
        'model_version':'v1','calendar_version':'c1','lower_return':-.01,'upper_return':.01})


def test_history_uses_availability_not_row_order_or_future_labels():
    rows = [row('a','2026-01-01T00:00:00+00:00','2026-01-10T00:00:00+00:00'),
            row('b','2026-01-05T00:00:00+00:00','2026-01-12T00:00:00+00:00'),
            row('c','2026-01-11T00:00:00+00:00','2026-01-20T00:00:00+00:00')]
    probs = {r['forecast_id']:{'up':1.,'flat':0.,'down':0.} for r in rows}
    out = score_labels({'evaluated_at':'2030-01-01T00:00:00+00:00','results':rows[::-1]},probs)
    by_id = {r['forecast_id']:r for r in out['rows']}
    assert by_id['b']['historical_samples'] == 0
    assert by_id['c']['historical_samples'] == 1
    assert by_id['c']['historical_probabilities']['up'] == .5
    assert out['mean_brier'] == 0
    assert not out['has_skill']


def test_probability_validation_and_pending():
    report = {'evaluated_at':'2030-01-01T00:00:00+00:00','results':[{'forecast_id':'a','status':'pending'}]}
    with pytest.raises(ValueError):
        score_labels(report,{})
    with pytest.raises(ValueError):
        score_labels(report,{'a':{'up':.8,'flat':.8,'down':0}})
    out = score_labels(report,{'a':{'up':.25,'flat':.5,'down':.25}})
    assert out['n_pending'] == 1
    assert out['mean_brier'] is None


def test_grouping_and_nonoverlap_are_order_independent():
    from arbor.domain.forecast_scores import grouped_scores
    rows = [row('a','2026-01-01T00:00:00+00:00','2026-01-10T00:00:00+00:00'),
            row('b','2026-01-05T00:00:00+00:00','2026-01-12T00:00:00+00:00'),
            row('c','2026-01-11T00:00:00+00:00','2026-01-20T00:00:00+00:00'),
            row('d','2026-01-11T00:00:00+00:00','2026-01-20T00:00:00+00:00')]
    rows[-1]['frozen_forecast']['model_version'] = 'v2'
    probs = {r['forecast_id']:{'up':1.,'flat':0.,'down':0.} for r in rows}
    result = grouped_scores({'evaluated_at':'2030-01-01T00:00:00+00:00','results':rows},probs)
    assert result == grouped_scores({'evaluated_at':'2030-01-01T00:00:00+00:00','results':rows[::-1]},probs)
    assert result[0]['selected_ids'] == ['a','c']
    assert result[0]['excluded_overlap_ids'] == ['b']
    assert result[1]['all_windows']['rows'][0]['historical_samples'] == 0


@pytest.mark.parametrize('bad', ['sideways', None, ''])
def test_invalid_actual_direction_cannot_be_scored(bad):
    r = row('a','2026-01-01T00:00:00+00:00','2026-01-10T00:00:00+00:00',bad)
    with pytest.raises(ValueError,match='actual direction'):
        score_labels({'evaluated_at':'2030-01-01T00:00:00+00:00','results':[r]},{'a':{'up':.25,'flat':.5,'down':.25}})


def test_duplicate_and_unknown_status_rejected_in_both_entrypoints():
    from arbor.domain.forecast_scores import grouped_scores
    r = row('a','2026-01-01T00:00:00+00:00','2026-01-10T00:00:00+00:00')
    probs = {'a':{'up':.25,'flat':.5,'down':.25}}
    for function in (score_labels,grouped_scores):
        with pytest.raises(ValueError,match='duplicate'):
            function({'evaluated_at':'2030-01-01T00:00:00+00:00','results':[r,r]},probs)
        with pytest.raises(ValueError,match='object'):
            function({'evaluated_at':'2030-01-01T00:00:00+00:00','results':[r]},['a'])
        with pytest.raises(ValueError,match='status'):
            function({'evaluated_at':'2030-01-01T00:00:00+00:00','results':[{**r,'status':'failed'}]},probs)


@pytest.mark.parametrize('target,available,evaluated', [
    ('2025-12-31T00:00:00+00:00','2026-01-10T00:00:00+00:00','2026-01-20T00:00:00+00:00'),
    ('2026-01-10T00:00:00+00:00','2026-01-09T00:00:00+00:00','2026-01-20T00:00:00+00:00'),
    ('2026-01-10T00:00:00+00:00','2026-01-11T00:00:00+00:00','2026-01-10T00:00:00+00:00'),
    ('2026-01-10T00:00:00','2026-01-11T00:00:00+00:00','2026-01-20T00:00:00+00:00'),
])
def test_direct_score_rejects_invalid_outcome_timeline(target,available,evaluated):
    r = row('a','2026-01-01T00:00:00+00:00',available)
    r['target_close'] = target
    with pytest.raises(ValueError):
        score_labels({'results':[r],'evaluated_at':evaluated},
                     {'a':{'up':.25,'flat':.5,'down':.25}})
