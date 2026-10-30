"""Offline fifth-session labels; supplied data provenance is not independently verified."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

from arbor.domain.forecast_scores import score_labels
from arbor.domain.forecast_outcome import FrozenForecast, ObservedClose, label_fifth_session, aware


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def evaluate_archive(raw, *, evaluated_at):
    aware(evaluated_at)
    data = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(data, dict) or set(data) != {'forecasts', 'calendars', 'observations'}:
        raise ValueError('archive requires exactly forecasts, calendars, observations')
    if not isinstance(data['forecasts'], list) or not isinstance(data['observations'], list) or not isinstance(data['calendars'], dict):
        raise ValueError('invalid archive collections')
    observations = []
    for row in data['observations']:
        values = dict(row)
        for key in ('session_close', 'available_at'):
            values[key] = datetime.fromisoformat(values[key])
        observations.append(ObservedClose(**values))
    forecasts = []
    for row in data['forecasts']:
        values = dict(row)
        for key in ('published_at', 'data_cutoff'):
            values[key] = datetime.fromisoformat(values[key])
        forecasts.append(FrozenForecast(**values))
    ids = [f.forecast_id for f in forecasts]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate forecast ids')
    results = []
    for forecast in forecasts:
        calendar = data['calendars'][forecast.calendar_version]
        if not isinstance(calendar, list):
            raise ValueError('calendar must be a list of session-close timestamps')
        result = label_fifth_session(forecast, [datetime.fromisoformat(v) for v in calendar],
                                     observations, evaluated_at=evaluated_at)
        if result['status'] == 'pending':
            result['reason'] = ('target_session_not_closed' if evaluated_at < datetime.fromisoformat(result['target_close'])
                                else 'target_close_missing_or_not_available')
        result['frozen_forecast'] = next(row for row in data['forecasts'] if row['forecast_id'] == forecast.forecast_id)
        results.append(result)
    return dict(mode='OFFLINE_LABELS_ONLY', archive_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                evaluated_at=evaluated_at.isoformat(), total=len(results),
                labeled=sum(r['status']=='labeled' for r in results), results=results,
                calibration_validated=False, provenance_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--evaluated-at', required=True, type=datetime.fromisoformat)
    parser.add_argument('--probabilities', type=Path, help='Optional forecast-id to up/flat/down probability JSON')
    args = parser.parse_args()
    try:
        result = evaluate_archive(args.input.read_text(encoding='utf-8'), evaluated_at=args.evaluated_at)
        if args.probabilities:
            probabilities = json.loads(args.probabilities.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
            result['probability_diagnostics'] = score_labels(result, probabilities)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
