"""Paper close accepts an ExitReason value instead of calling the class."""

import pytest

from arbor.application.paper_trading.engine import PaperTradingEngine
from arbor.domain.trading import ExitReason, HedgeAction, coerce_exit_reason


def _engine(tmp_path) -> PaperTradingEngine:
    return PaperTradingEngine(db_path=tmp_path / "paper.db", initial_equity=100_000.0)


def test_coerce_accepts_value_and_name():
    assert coerce_exit_reason("manual_close") == ExitReason.MANUAL_CLOSE
    assert coerce_exit_reason(ExitReason.RATIO_CHANGED) == "ratio_changed"
    assert coerce_exit_reason("SIGNAL_CLOSE") == "signal"


def test_coerce_rejects_unknown_text():
    with pytest.raises(ValueError, match="unknown exit reason"):
        coerce_exit_reason("ratio_reduced")


def test_close_with_reason_string_realizes_pnl(tmp_path):
    engine = _engine(tmp_path)
    engine.open_position(price=200.0, tons=37.5, hedge_ratio=0.80)
    pnl, commission = engine.close_position(210.0, "manual_close")

    assert engine._position is None
    assert commission == 15.0
    assert pnl == pytest.approx(205.462)
    assert engine._trades[-1].exit_reason == "manual_close"
    assert engine._trades[-1].narrative == "Paper close: manual_close"

    row = engine.db._get_conn().execute(
        "SELECT exit_reason, is_paper FROM hedge_trades WHERE action = ?",
        ("close_hedge",),
    ).fetchone()
    assert row["exit_reason"] == "manual_close"
    assert row["is_paper"] == 1
    engine.close()


def test_sync_to_zero_closes_without_constructing_exit_reason(tmp_path):
    engine = _engine(tmp_path)
    engine.open_position(price=200.0, tons=375.0, hedge_ratio=0.80)
    message = engine.sync_to_ratio(0.0, 205.0, 375.0)

    assert engine._position is None
    assert message.startswith("CLOSED")
    assert engine._trades[-1].exit_reason == ExitReason.RATIO_CHANGED
    engine.close()


def test_close_when_flat_does_not_require_a_known_reason(tmp_path):
    engine = _engine(tmp_path)
    assert engine.close_position(200.0, "manual_close") == (0.0, 0.0)
    engine.close()


def test_reduction_closes_only_the_dropped_contracts(tmp_path):
    engine = _engine(tmp_path)
    engine.sync_to_ratio(0.80, 200.0, 375.0)
    opened_at = engine._position.entry_time

    message = engine.sync_to_ratio(0.40, 210.0, 375.0)

    assert message.startswith("ADJUSTED to 4 contracts")
    assert engine._position.contracts == 4
    assert engine._position.size_tons == 150.0
    assert engine._position.hedge_ratio == 0.40
    assert engine._position.entry_price == 200.0
    assert engine._position.entry_time == opened_at
    closes = [t for t in engine._trades if t.action == HedgeAction.CLOSE_HEDGE]
    opens = [t for t in engine._trades if t.action == HedgeAction.BUY_HEDGE]
    assert len(opens) == 1
    assert len(closes) == 1
    assert closes[0].size == 150.0
    assert closes[0].hedge_ratio == 0.80
    assert closes[0].commission == 60.0
    assert closes[0].pnl == pytest.approx(821.848)
    engine.close()


def test_adjust_without_a_new_ratio_keeps_the_open_one(tmp_path):
    engine = _engine(tmp_path)
    engine.open_position(price=200.0, tons=300.0, hedge_ratio=0.80)
    assert engine.adjust_position(150.0, 205.0) is True
    assert engine._position.contracts == 4
    assert engine._position.entry_price == 200.0
    assert engine._position.hedge_ratio == 0.80
    engine.close()


def test_scale_up_adds_contracts_and_blends_the_entry(tmp_path):
    engine = _engine(tmp_path)
    engine.sync_to_ratio(0.40, 200.0, 375.0)
    opened_at = engine._position.entry_time

    message = engine.sync_to_ratio(0.80, 210.0, 375.0)

    assert message.startswith("ADJUSTED to 8 contracts @ 205.00")
    assert engine._position.contracts == 8
    assert engine._position.size_tons == 300.0
    assert engine._position.entry_price == pytest.approx(205.0)
    assert engine._position.entry_time == opened_at
    assert engine._position.hedge_ratio == 0.80
    assert engine.mark_to_market(210.0) == pytest.approx(881.848)
    closes = [t for t in engine._trades if t.action == HedgeAction.CLOSE_HEDGE]
    opens = [t for t in engine._trades if t.action == HedgeAction.BUY_HEDGE]
    assert closes == []
    assert len(opens) == 2
    assert opens[-1].size == 150.0
    assert opens[-1].entry_price == 210.0
    assert opens[-1].commission == 60.0
    assert opens[-1].pnl == 0.0
    assert opens[-1].hedge_ratio == 0.80
    engine.close()


def test_reduction_after_add_lifts_the_newest_lot(tmp_path):
    engine = _engine(tmp_path)
    engine.sync_to_ratio(0.40, 200.0, 375.0)
    opened_at = engine._position.entry_time
    engine.sync_to_ratio(0.80, 210.0, 375.0)

    message = engine.sync_to_ratio(0.40, 220.0, 375.0)

    assert message.startswith("ADJUSTED to 4 contracts @ 200.00")
    assert engine._position.contracts == 4
    assert engine._position.entry_price == 200.0
    assert engine._position.entry_time == opened_at
    assert engine._position.hedge_ratio == 0.40
    closes = [t for t in engine._trades if t.action == HedgeAction.CLOSE_HEDGE]
    assert len(closes) == 1
    assert closes[0].entry_price == 210.0
    assert closes[0].size == 150.0
    assert closes[0].commission == 60.0
    assert closes[0].pnl == pytest.approx(821.848)
    assert engine.mark_to_market(220.0) == pytest.approx(1763.696)
    engine.close()


def test_full_close_books_each_lot(tmp_path):
    engine = _engine(tmp_path)
    engine.sync_to_ratio(0.40, 200.0, 375.0)
    engine.sync_to_ratio(0.80, 210.0, 375.0)
    pnl, commission = engine.close_position(220.0, "manual_close")

    assert engine._position is None
    assert commission == 120.0
    assert pnl == pytest.approx(2525.544)
    closes = [t for t in engine._trades if t.action == HedgeAction.CLOSE_HEDGE]
    assert [(c.entry_price, c.size) for c in closes] == [(200.0, 150.0), (210.0, 150.0)]
    engine.close()


def test_small_ratio_step_holds_size_and_stores_the_new_ratio(tmp_path):
    engine = _engine(tmp_path)
    engine.sync_to_ratio(0.80, 200.0, 375.0)
    message = engine.sync_to_ratio(0.82, 202.0, 375.0)
    assert message.startswith("HOLD 8 contracts")
    assert "82%" in message
    assert engine._position.contracts == 8
    assert engine._position.entry_price == 200.0
    assert engine._position.hedge_ratio == pytest.approx(0.82)
    engine.close()


def test_restart_restores_lots_ratio_and_realized_cash(tmp_path):
    path = tmp_path / "paper.db"
    engine = PaperTradingEngine(db_path=path, initial_equity=100_000.0)
    engine.sync_to_ratio(0.40, 200.0, 375.0)
    engine.sync_to_ratio(0.80, 210.0, 375.0)
    engine.sync_to_ratio(0.40, 220.0, 375.0)
    equity = engine._equity
    engine.db.close()

    restored = PaperTradingEngine(db_path=path, initial_equity=100_000.0)
    pos = restored._position
    assert pos is not None
    assert pos.contracts == 4
    assert pos.entry_price == 200.0
    assert pos.hedge_ratio == 0.40
    assert [(lot.entry_price, lot.contracts) for lot in pos.lots] == [(200.0, 4)]
    assert restored._equity == pytest.approx(equity)
    assert restored.mark_to_market(220.0) == pytest.approx(1763.696)
    restored.db.close()


def test_restart_after_flat_close_keeps_realized_pnl(tmp_path):
    path = tmp_path / "paper.db"
    engine = PaperTradingEngine(db_path=path, initial_equity=100_000.0)
    engine.open_position(price=200.0, tons=37.5, hedge_ratio=0.80)
    engine.close_position(210.0, "manual_close")
    equity = engine._equity
    engine.db.close()

    restored = PaperTradingEngine(db_path=path, initial_equity=100_000.0)
    assert restored._position is None
    assert restored._equity == pytest.approx(equity)
    restored.db.close()


def test_restart_keeps_a_ratio_step_that_did_not_change_size(tmp_path):
    path = tmp_path / "paper.db"
    engine = PaperTradingEngine(db_path=path, initial_equity=100_000.0)
    engine.sync_to_ratio(0.80, 200.0, 375.0)
    engine.sync_to_ratio(0.82, 202.0, 375.0)
    engine.db.close()

    restored = PaperTradingEngine(db_path=path, initial_equity=100_000.0)
    assert restored._position.contracts == 8
    assert restored._position.entry_price == 200.0
    assert restored._position.hedge_ratio == pytest.approx(0.82)
    restored.db.close()


def test_unknown_reason_leaves_the_position_open(tmp_path):
    engine = _engine(tmp_path)
    engine.open_position(price=200.0, tons=37.5, hedge_ratio=0.80)
    with pytest.raises(ValueError, match="unknown exit reason"):
        engine.close_position(210.0, "ratio_reduced")
    assert engine._position is not None
    engine.close()
