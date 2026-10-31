import pandas as pd
import pytest

from arbor.domain.procurement import KC_CONTRACT_TONNES as KC, futures_pnl, plan_procurement
from arbor.application.paper_trading.engine import PaperTradingEngine
from backtest.engine import BacktestConfig, CoffeeBacktestEngine


def test_contract_units_and_exposure():
    assert KC == pytest.approx(17.009713875)
    assert futures_pnl(200, 210, KC) == pytest.approx(3750)
    plan = plan_procurement(purchase_tonnes=100, priced_tonnes=80, target_ratio=.7,
                           equity=100000, margin_per_contract=1000)
    assert plan.target_contracts == 0
    assert plan.residual_tonnes == 20


def test_margin_cap_and_missing_margin():
    plan = plan_procurement(purchase_tonnes=100, priced_tonnes=0, target_ratio=1,
                           equity=2050, margin_per_contract=1000, commission_per_contract=15)
    assert plan.target_contracts == 1
    assert plan.cash_limited
    assert plan.margin_required == 1000
    assert not plan_procurement(purchase_tonnes=100, priced_tonnes=0, target_ratio=1).executable


@pytest.mark.parametrize('kwargs', [{'priced_tonnes': 101}, {'target_ratio': 1.1},
    {'purchase_tonnes': float('nan')}, {'margin_per_contract': 0}])
def test_invalid_exposure_is_rejected(kwargs):
    values = dict(purchase_tonnes=100, priced_tonnes=0, target_ratio=.65)
    values.update(kwargs)
    with pytest.raises(ValueError):
        plan_procurement(**values)


def paper(tmp_path, **kwargs):
    return PaperTradingEngine(db_path=tmp_path/'paper.db', **kwargs)


def test_paper_no_forced_one_lot_and_no_missing_margin(tmp_path):
    engine = paper(tmp_path)
    assert 'BLOCKED' in engine.sync_to_ratio(1, 200, 100)
    engine.margin_per_contract = 1000
    assert 'FLAT' in engine.sync_to_ratio(1, 200, 1)
    assert engine._position is None
    assert engine._equity == 100000
    engine.close()


def test_paper_cash_and_pnl_not_double_counted(tmp_path):
    engine = paper(tmp_path, margin_per_contract=1000)
    engine.open_position(200, KC, 1)
    assert engine.mark_to_market(210) == pytest.approx(3750)
    assert engine.mark_to_market(210) == pytest.approx(3750)
    assert engine.get_summary()['current_equity'] == pytest.approx(103735)
    pnl, fee = engine.close_position(210, 'manual_close')
    assert pnl == pytest.approx(3735)
    assert fee == 15
    assert engine.get_summary()['current_equity'] == pytest.approx(103720)
    engine.close()


def test_fully_priced_purchase_closes_existing_hedge(tmp_path):
    engine = paper(tmp_path, margin_per_contract=1000)
    engine.sync_to_ratio(1, 200, KC*2)
    assert engine._position.contracts == 2
    assert 'CLOSED' in engine.sync_to_ratio(1, 200, KC*2, priced_tons=KC*2)
    assert engine._position is None
    engine.close()


def test_reduction_below_one_lot_closes_and_margin_shortfall_visible(tmp_path):
    engine = paper(tmp_path, initial_equity=5000, margin_per_contract=1000)
    engine.sync_to_ratio(1, 200, KC)
    engine.mark_to_market(180)
    assert engine.get_summary()['margin_shortfall'] > 0
    engine.sync_to_ratio(1, 180, KC/2)
    assert engine._position is None
    engine.close()


def config(**kwargs):
    values = dict(start_date='2026-01-01', end_date='2026-12-31', initial_equity=100000,
        coffee_tons_per_month=KC*2, contract_size=KC, commission_per_contract=5,
        initial_hedge_ratio=.5, min_hedge_ratio=0, max_hedge_ratio=1)
    values.update(kwargs)
    return BacktestConfig(**values)


def prices():
    return pd.DataFrame({'price': [200., 210., 210., 220.]},
                        index=pd.to_datetime(['2026-01-02','2026-01-30','2026-02-02','2026-02-27']))


def test_backtest_accumulates_pnl_actual_months_fees_and_separate_cash():
    engine = CoffeeBacktestEngine(config(), prices())
    out = engine.run([])
    static = out['static_hedge']
    assert static.total_tonnes == pytest.approx(KC*4)
    assert static.hedge_pnl == pytest.approx(7500-20)
    assert static.total_cost == pytest.approx(322500)
    assert static.equity_final == pytest.approx(107480)
    assert out['no_hedge'].equity_final == 100000
    assert static.net_cost_per_ton == pytest.approx((322500-7480)/(KC*4))
    assert engine._static_equity_curve[-1]['equity'] == static.equity_final
    assert engine.run([])['static_hedge'] == static  # reruns start clean


def test_backtest_cash_budget_can_prevent_trades():
    engine = CoffeeBacktestEngine(config(initial_equity=500, margin_per_contract=1000), prices())
    out = engine.run([])
    assert out['static_hedge'].total_trades == 0
    assert out['event_hedge'].hedge_pnl == 0
    assert out['event_hedge'].margin_constrained


def test_off_bar_event_observed_only_after_publication(monkeypatch):
    seen = []
    def scorer(events, now):
        seen.append([e.timestamp for e in events])
        return .5
    monkeypatch.setattr('core.state.engine.compute_hedge_from_events', scorer)
    ts = pd.Timestamp('2026-01-10 12:00')
    engine = CoffeeBacktestEngine(config(), prices())
    engine.run([dict(timestamp=ts, event_type='FROST_WARNING', severity=3)])
    assert seen[0] == []
    assert seen[1] == [ts]


def test_price_direction_does_not_certify_hedge_effectiveness(tmp_path, monkeypatch):
    from tests.test_track_record import _seed_history
    from reports.history import compute_track_record, compute_prediction_review, load_summaries
    from web.track_record import build_track_record_html
    _seed_history(tmp_path)
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    review = compute_prediction_review(load_summaries()[0], 330)
    assert review.hedge_advice_correct is None
    assert "不能由价格方向判定" in review.review_text
    record = compute_track_record()
    assert record['hedge_rate'] is None
    assert '套保效果待核验' in build_track_record_html(record)
