"""ModelManager recommend 路径：close→price 与委托 recommend_hedge — 无网络"""

import pandas as pd

from models.hedge_model import HedgeRecommendation
from models.model_manager import ModelManager, _ensure_price_col


def test_ensure_price_col_renames_close():
    df = pd.DataFrame({"close": [1.0, 2.0], "volume": [10, 20]})
    out = _ensure_price_col(df)
    assert "price" in out.columns
    assert list(out["price"]) == [1.0, 2.0]


def test_ensure_price_col_keeps_existing_price():
    df = pd.DataFrame({"price": [3.0], "close": [9.0]})
    out = _ensure_price_col(df)
    assert out["price"].iloc[0] == 3.0


def test_recommend_from_df_delegates_to_hedge_model(monkeypatch):
    mgr = ModelManager()
    mgr._loaded = True
    called = {}

    class FakeModel:
        def recommend_hedge(self, df, current_price, total_tons, risk_budget_usd=100_000):
            called["args"] = (len(df), current_price, total_tons)
            return HedgeRecommendation(
                hedge_ratio=0.55, target_tons=55.0, confidence=0.7,
                rationale=["delegated"], model_signals={}, risk_factors=[],
            )

    mgr.model = FakeModel()
    rec = mgr._recommend_from_df(
        pd.DataFrame({"x": [1, 2, 3]}), current_price=300.0, total_tons=100.0,
    )
    assert called["args"] == (3, 300.0, 100.0)
    assert rec.hedge_ratio == 0.55
    assert rec.rationale == ["delegated"]
