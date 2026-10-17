"""HedgeModel.recommend_hedge 方向头调整 — clf 1=UP，不含网络"""

import pandas as pd
import pytest

from models.hedge_model import HedgeModel, ModelOutput


def _minimal_df():
    return pd.DataFrame([{
        "oni": 0.0,
        "oni_phase": "NEUTRAL",
        "frost_season": 0,
        "rsi_14": 50.0,
        "volatility_20d": 0.02,
        "price_rank_60d": 0.5,
        "momentum_20d": 0.0,
    }])


def _run(model, *, pred_dir: float, pred_ret: float):
    model._fitted = True
    model.predict_direction = lambda df: ModelOutput(
        prediction=pred_dir, confidence=0.8, model_name="clf", feature_importance={},
    )
    model.predict_return = lambda df: ModelOutput(
        prediction=pred_ret, confidence=0.8, model_name="reg", feature_importance={},
    )
    return model.recommend_hedge(_minimal_df(), current_price=300.0, total_tons=100.0)


@pytest.mark.unit
def test_up_and_positive_return_reduces_hedge():
    rec = _run(HedgeModel(), pred_dir=1.0, pred_ret=0.08)
    assert any("Predicted rise" in r for r in rec.rationale)
    # 基准 65% − 10% 方向调整 = 55%（其余 adj 为 0）
    assert rec.hedge_ratio == pytest.approx(0.55)


@pytest.mark.unit
def test_down_and_negative_return_increases_hedge():
    rec = _run(HedgeModel(), pred_dir=0.0, pred_ret=-0.08)
    assert any("Predicted drop" in r for r in rec.rationale)
    assert rec.hedge_ratio == pytest.approx(0.75)


@pytest.mark.unit
def test_mismatched_dir_and_return_no_dir_adj():
    # 旧 bug：prediction==1 却要求 return<-5% — 现已要求同向一致
    rec = _run(HedgeModel(), pred_dir=1.0, pred_ret=-0.08)
    assert not any("Predicted" in r for r in rec.rationale)
    assert rec.hedge_ratio == pytest.approx(0.65)
