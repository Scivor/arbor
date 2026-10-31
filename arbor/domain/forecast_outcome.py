"""Outcome labels from explicitly supplied session closes, never report proxies.

Calendar completeness and source authenticity must be independently verified.
This module neither calibrates forecasts nor authorizes trading.
"""
from dataclasses import dataclass
from datetime import datetime
import math


def aware(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')


@dataclass(frozen=True)
class FrozenForecast:
    forecast_id: str
    contract_id: str
    published_at: datetime
    data_cutoff: datetime
    reference_price: float
    lower_return: float
    upper_return: float
    model_version: str
    calendar_version: str


@dataclass(frozen=True)
class ObservedClose:
    contract_id: str
    session_close: datetime
    available_at: datetime
    price: float
    source: str


def label_fifth_session(forecast, session_closes, observations, *, evaluated_at):
    """Count five supplied session closes strictly after publication.

    Missing fifth-session data stays pending; later observations cannot replace it.
    Return thresholds are fractions; both boundary values belong to flat.
    """
    for value in (forecast.published_at, forecast.data_cutoff, evaluated_at):
        aware(value)
    if forecast.data_cutoff > forecast.published_at or evaluated_at < forecast.published_at:
        raise ValueError('invalid publication or evaluation chronology')
    if not all(isinstance(v, str) and v.strip() for v in (
            forecast.forecast_id, forecast.contract_id, forecast.model_version, forecast.calendar_version)):
        raise ValueError('forecast, contract, model and calendar identifiers required')
    if not math.isfinite(forecast.reference_price) or forecast.reference_price <= 0:
        raise ValueError('positive reference price required')
    if not all(math.isfinite(v) for v in (forecast.lower_return, forecast.upper_return)) or not forecast.lower_return < forecast.upper_return:
        raise ValueError('ordered finite frozen thresholds required')
    sessions = list(session_closes)
    for value in sessions:
        aware(value)
    if sessions != sorted(set(sessions)):
        raise ValueError('calendar must be unique and ordered')
    future = [v for v in sessions if v > forecast.published_at]
    if len(future) < 5:
        raise ValueError('calendar must cover five future sessions')
    target = future[4]
    matches = []
    for item in observations:
        aware(item.session_close)
        aware(item.available_at)
        if item.available_at < item.session_close:
            raise ValueError('close cannot be available before session closes')
        if not item.source.strip() or not math.isfinite(item.price) or item.price <= 0:
            raise ValueError('valid sourced close required')
        if item.contract_id == forecast.contract_id and item.session_close == target and item.available_at <= evaluated_at:
            matches.append(item)
    if len(matches) > 1:
        raise ValueError('ambiguous duplicate target closes')
    result = dict(forecast_id=forecast.forecast_id, contract_id=forecast.contract_id,
                  target_close=target.isoformat(), calendar_version=forecast.calendar_version,
                  model_version=forecast.model_version, status='pending', actual=None,
                  calibration_validated=False)
    if matches:
        close = matches[0]
        change = close.price / forecast.reference_price - 1
        actual = 'down' if close.price < forecast.reference_price*(1+forecast.lower_return) else 'up' if close.price > forecast.reference_price*(1+forecast.upper_return) else 'flat'
        result.update(status='labeled', actual=actual, return_fraction=change,
                      price=close.price, source=close.source, available_at=close.available_at.isoformat())
    return result
