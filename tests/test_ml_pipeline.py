import numpy as np
import pandas as pd
import pytest


@pytest.mark.unit
def test_get_ml_advice_marks_no_models_as_none(monkeypatch):
    from models import ml_advisor

    def fail_hedge_model(_current_price):
        raise RuntimeError("missing hedge model")

    monkeypatch.setattr(ml_advisor, "_get_hedge_model_advice", fail_hedge_model)
    monkeypatch.setattr(ml_advisor, "_get_timesfm_advice", lambda: None)
    ml_advisor.invalidate_cache()

    advice = ml_advisor.get_ml_advice(use_cache=False, current_price=336.7)

    assert advice.model_type == "none"
    assert advice.confidence == 0.0
    assert advice.rationale == ["No ML models available"]


@pytest.mark.unit
def test_fetch_ml_snapshot_returns_none_when_models_unavailable(monkeypatch):
    from models.ml_advisor import MLAdvice, MLSignal
    from reports import pipeline

    monkeypatch.setattr(
        "models.ml_advisor.get_ml_advice",
        lambda use_cache=True, current_price=None: MLAdvice(
            signal=MLSignal.NEUTRAL,
            confidence=0.0,
            bias=0.0,
            rationale=["No ML models available"],
            model_type="none",
        ),
    )

    assert pipeline.fetch_ml_snapshot(current_price=336.7) is None


@pytest.mark.unit
def test_get_ml_advice_preserves_single_model_type(monkeypatch):
    from models import ml_advisor
    from models.ml_advisor import MLAdvice, MLSignal

    def fail_hedge_model(_current_price):
        raise RuntimeError("missing hedge model")

    monkeypatch.setattr(ml_advisor, "_get_hedge_model_advice", fail_hedge_model)
    monkeypatch.setattr(
        ml_advisor,
        "_get_timesfm_advice",
        lambda: MLAdvice(
            signal=MLSignal.BEARISH,
            confidence=0.7,
            bias=0.08,
            rationale=["TimesFM fallback"],
            price_target_30d=267.7,
            model_type="timesfm",
        ),
    )
    ml_advisor.invalidate_cache()

    advice = ml_advisor.get_ml_advice(use_cache=False, current_price=336.7)

    assert advice.model_type == "timesfm"
    assert advice.price_target_30d == pytest.approx(267.7)


@pytest.mark.unit
def test_timesfm_simulated_fallback_returns_forecast(monkeypatch):
    from models import timesfm_adapter
    from models.timesfm_adapter import TimesFMAdapter

    monkeypatch.setattr(
        timesfm_adapter,
        "_get_timesfm_model",
        lambda use_mps=True: (None, "simulated", {0.1: 0, 0.3: 2, 0.5: 4, 0.7: 6, 0.9: 8}),
    )
    monkeypatch.setattr(TimesFMAdapter, "get_current_price", lambda self: 300.0)
    monkeypatch.setattr(
        "backtest.loader.HistoryLoader.load_kc_futures",
        lambda self, start, end: pd.DataFrame({"close": np.linspace(280.0, 300.0, 180)}),
    )

    forecast = TimesFMAdapter().get_forecast(horizon=30)

    assert forecast is not None
    assert isinstance(forecast, float)
    assert forecast > 0
