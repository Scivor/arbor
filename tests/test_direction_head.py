"""独立方向头：信号来自分类器 P(up)，目标价来自回归外推 — 不经 hedge_ratio。"""

from types import SimpleNamespace

import numpy as np
import pytest

from models.ml_advisor import MLSignal, _get_hedge_model_advice


class _FakeClf:
    def __init__(self, proba_up: float):
        self._p = proba_up

    def predict_proba(self, X):
        # shape (n, 2): [P(down), P(up)]
        n = len(X)
        return np.array([[1.0 - self._p, self._p]] * n)


class _FakeReg:
    def __init__(self, ret: float):
        self._r = ret

    def predict(self, X):
        return np.array([self._r] * len(X))


class _FakeFE:
    _scaler = object()

    def get_X(self, df, scaler=None, fit=False):
        return np.zeros((3, 4)), ["a", "b", "c", "d"]


def _patch_model(monkeypatch, proba_up: float, ret_5d: float):
    model = SimpleNamespace(
        feature_engine=_FakeFE(),
        _clf=_FakeClf(proba_up),
        _reg=_FakeReg(ret_5d),
    )
    mgr = SimpleNamespace(model=model, load=lambda: True)
    monkeypatch.setattr("models.model_manager.ModelManager", lambda: mgr)
    monkeypatch.setattr(
        "models.ml_advisor._get_latest_features",
        lambda: __import__("pandas").DataFrame({"x": [1, 2, 3]}),
    )


def test_direction_head_bullish_from_proba(monkeypatch):
    _patch_model(monkeypatch, proba_up=0.72, ret_5d=0.03)
    out = _get_hedge_model_advice(300.0)
    assert out.signal == MLSignal.BULLISH
    assert out.model_type == "direction_head"
    assert out.bias < 0  # 上涨 → 减少套保
    # 5d 3% → 30d ≈ 12.6% → 300 * 1.126
    assert out.price_target_30d == pytest.approx(300.0 * (1 + 0.03 * 21 / 5), abs=0.05)


def test_direction_head_bearish_from_proba(monkeypatch):
    _patch_model(monkeypatch, proba_up=0.30, ret_5d=-0.04)
    out = _get_hedge_model_advice(300.0)
    assert out.signal == MLSignal.BEARISH
    assert out.bias > 0
    assert out.price_target_30d < 300.0


def test_direction_head_neutral_band(monkeypatch):
    _patch_model(monkeypatch, proba_up=0.52, ret_5d=0.01)
    out = _get_hedge_model_advice(300.0)
    assert out.signal == MLSignal.NEUTRAL
    assert out.bias == 0.0


def test_direction_head_ignores_hedge_ratio(monkeypatch):
    """即便 ModelManager 有 recommend，方向头也不走 hedge_ratio 路径。"""
    called = {"recommend": False}

    class SpyMgr:
        def __init__(self):
            self.model = SimpleNamespace(
                feature_engine=_FakeFE(),
                _clf=_FakeClf(0.80),
                _reg=_FakeReg(0.02),
            )

        def load(self):
            return True

        def _recommend_from_df(self, *a, **k):
            called["recommend"] = True
            raise AssertionError("must not call hedge-ratio recommend")

    monkeypatch.setattr("models.model_manager.ModelManager", SpyMgr)
    monkeypatch.setattr(
        "models.ml_advisor._get_latest_features",
        lambda: __import__("pandas").DataFrame({"x": [1, 2, 3]}),
    )
    out = _get_hedge_model_advice(280.0)
    assert out.signal == MLSignal.BULLISH
    assert called["recommend"] is False
