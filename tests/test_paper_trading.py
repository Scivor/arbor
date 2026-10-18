"""Paper close accepts an ExitReason value instead of calling the class."""

import pytest

from arbor.application.paper_trading.engine import PaperTradingEngine
from arbor.domain.trading import ExitReason, coerce_exit_reason


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


def test_unknown_reason_leaves_the_position_open(tmp_path):
    engine = _engine(tmp_path)
    engine.open_position(price=200.0, tons=37.5, hedge_ratio=0.80)
    with pytest.raises(ValueError, match="unknown exit reason"):
        engine.close_position(210.0, "ratio_reduced")
    assert engine._position is not None
    engine.close()
