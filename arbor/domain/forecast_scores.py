"""Offline diagnostics using labeled archives; never a calibration approval."""
from datetime import datetime
import math

CLASSES = {'up', 'flat', 'down'}
DEFAULT = {'up': .25, 'flat': .5, 'down': .25}


def cohort(row):
    frozen = row['frozen_forecast']
    return tuple(frozen[k] for k in ('contract_id', 'model_version', 'calendar_version',
                                    'lower_return', 'upper_return'))


def grouped_scores(report, probabilities):
    """Separate incompatible labels and provide deterministic nonoverlap subsets."""
    score_labels(report, probabilities)  # validate the complete input before grouping
    groups = {}
    for row in report['results']:
        groups.setdefault(cohort(row), []).append(row)
    output = []
    for key, rows in sorted(groups.items()):
        ordered = sorted(rows, key=lambda r: (datetime.fromisoformat(r['frozen_forecast']['published_at']), r['forecast_id']))
        selected, excluded = [], []
        end = None
        for row in ordered:
            start = datetime.fromisoformat(row['frozen_forecast']['published_at'])
            target = datetime.fromisoformat(row['target_close'])
            if end is None or start >= end:
                selected.append(row)
                end = target
            else:
                excluded.append(row['forecast_id'])
        def evaluate(subset):
            return score_labels({'results':subset}, {r['forecast_id']:probabilities[r['forecast_id']] for r in subset})
        output.append(dict(contract_id=key[0], model_version=key[1], calendar_version=key[2],
            lower_return=key[3], upper_return=key[4], all_windows=evaluate(ordered),
            nonoverlapping=evaluate(selected), selected_ids=[r['forecast_id'] for r in selected],
            excluded_overlap_ids=excluded))
    return output


def score_labels(report, probabilities):
    rows = report['results']
    ids = {r['forecast_id'] for r in rows}
    if len(ids) != len(rows):
        raise ValueError('duplicate forecast ids in score input')
    if not isinstance(probabilities, dict):
        raise ValueError('probabilities must be an object')
    for row in rows:
        if row['status'] not in ('pending', 'labeled'):
            raise ValueError('unknown label status')
        if row['status'] == 'labeled' and row.get('actual') not in CLASSES:
            raise ValueError('invalid actual direction')
    if set(probabilities) != ids:
        raise ValueError('probabilities must cover exactly the archive forecast ids')
    for values in probabilities.values():
        if not isinstance(values, dict) or set(values) != CLASSES:
            raise ValueError('exactly up, flat, down probabilities required')
        if any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in values.values()):
            raise ValueError('invalid probability')
        if not math.isclose(sum(values.values()), 1., rel_tol=0, abs_tol=1e-9):
            raise ValueError('probabilities must sum to one')
    scored = []
    for row in rows:
        if row['status'] != 'labeled':
            continue
        published = datetime.fromisoformat(row['frozen_forecast']['published_at'])
        # Only outcomes actually available at this forecast's publication.
        known = [r for r in rows if r['status'] == 'labeled' and cohort(r) == cohort(row)
                 and datetime.fromisoformat(r['available_at']) <= published
                 and datetime.fromisoformat(r['frozen_forecast']['published_at']) < published]
        counts = {k:1+sum(r['actual']==k for r in known) for k in CLASSES}
        history = {k:v/sum(counts.values()) for k,v in counts.items()}
        def brier(probs):
            return sum((probs[k]-int(row['actual']==k))**2 for k in CLASSES)
        scored.append(dict(forecast_id=row['forecast_id'], actual=row['actual'],
            brier=brier(probabilities[row['forecast_id']]), default_brier=brier(DEFAULT),
            uniform_brier=2/3, historical_brier=brier(history),
            historical_probabilities=history, historical_samples=len(known)))
    def mean(key):
        return sum(r[key] for r in scored)/len(scored) if scored else None
    return dict(n_scored=len(scored), n_pending=len(rows)-len(scored), rows=scored,
        mean_brier=mean('brier'), default_mean_brier=mean('default_brier'),
        historical_mean_brier=mean('historical_brier'), uniform_mean_brier=mean('uniform_brier'),
        has_skill=False, calibration_validated=False,
        limitation='Overlapping horizons are retained; descriptive scores are not independent-sample evidence.')
