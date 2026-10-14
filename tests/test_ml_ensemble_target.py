"""ML ensemble 目标价加权 — 无网络"""

import pytest

from models.ml_advisor import MLAdvice, MLSignal, _get_ml_advice_uncached


def test_ensemble_weights_price_targets(monkeypatch):
    a = MLAdvice(MLSignal.BULLISH, 0.8, -0.08, ["a"], price_target_30d=320.0, model_type="hedge_model")
    b = MLAdvice(MLSignal.BULLISH, 0.2, -0.02, ["b"], price_target_30d=280.0, model_type="timesfm")

    monkeypatch.setattr("models.ml_advisor._get_hedge_model_advice", lambda current_price=None: a)
    monkeypatch.setattr("models.ml_advisor._get_timesfm_advice", lambda: b)

    out = _get_ml_advice_uncached(300.0)
    assert out.model_type == "ensemble"
    # 0.8*320 + 0.2*280 = 312
    assert out.price_target_30d == pytest.approx(312.0)


def test_ensemble_disagreement_reduces_confidence(monkeypatch):
    a = MLAdvice(MLSignal.BEARISH, 0.6, 0.06, ["a"], price_target_30d=200.0, model_type="hedge_model")
    b = MLAdvice(MLSignal.BEARISH, 0.6, 0.06, ["b"], price_target_30d=300.0, model_type="timesfm")
    monkeypatch.setattr("models.ml_advisor._get_hedge_model_advice", lambda current_price=None: a)
    monkeypatch.setattr("models.ml_advisor._get_timesfm_advice", lambda: b)
    out = _get_ml_advice_uncached(250.0)
    # 同向投票置信度本为 1.0，分歧折减 ×0.8 → 0.8
    assert out.confidence == pytest.approx(0.8)
    assert any("分歧" in r for r in out.rationale)
