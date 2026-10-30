"""Offline diagnostics using labeled archives; never a calibration approval."""
from datetime import datetime
import math

CLASSES = {'up', 'flat', 'down'}
DEFAULT = {'up': .25, 'flat': .5, 'down': .25}


def score_labels(report, probabilities):
    rows = report['results']
    ids = {r['forecast_id'] for r in rows}
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
        known = [r for r in rows if r['status'] == 'labeled'
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
