"""
tests/test_learning.py
有界自校准（Phase B）测试 — 无网络
"""

import json

import pytest

from reports.learning import load_learned, load_review_memory, recalibrate, learning_status
from reports.pipeline import compute_levels_and_scenarios
from tests.test_pipeline_formatting import _market_snapshot


@pytest.fixture
def learn_env(tmp_path, monkeypatch):
    """隔离的学习环境：历史目录 + learned/changelog 路径全部指向 tmp"""
    hist = tmp_path / "history"
    hist.mkdir()
    monkeypatch.setattr("reports.history._HISTORY_DIR", hist)
    monkeypatch.setattr("reports.learning.LEARNED_PATH", tmp_path / "learned_adjustments.json")
    monkeypatch.setattr("reports.learning.CHANGELOG_PATH", tmp_path / "learned_changelog.jsonl")
    return tmp_path


def _write(dir_path, report_date, price, ml_signal, band_min, band_max):
    """写一期 weekly_summary JSON（模式同 tests/test_attribution.py）"""
    data = {
        "report_date": report_date,
        "forecast_week_start": report_date,
        "forecast_week_end": report_date,
        "current_price": price,
        "change_1d_pct": 0.0,
        "change_30d_pct": 0.0,
        "rsi_14": 50.0,
        "ml_signal": ml_signal,
        "ml_confidence": 0.5,
        "ml_price_target_30d": None,
        "hedge_ratio": 0.65,
        "hedge_signal": "MEDIUM_HEDGE",
        "dominant_scenario_direction": "横盘",
        "dominant_scenario_prob": 0.5,
        "dominant_scenario_min": band_min,
        "dominant_scenario_max": band_max,
        "outlook": "测试",
        "drivers": [],
    }
    (dir_path / f"weekly_summary_{report_date}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _seed_pairs(dir_path, n_pairs, ml_mode="wrong", band_mode="neutral"):
    """
    造 n_pairs 对相邻样本（日期间隔 1 天，全部 ≤8 天窗口内）。

    ml_mode:   "wrong" 全错(BULLISH+连跌) | "right" 全对(BULLISH+连涨) | "mixed" 对错各半
    band_mode: "neutral" 命中率 50%（不触发调整） | "hit" 全命中 | "miss" 全偏离
    """
    prices = []
    p = 400.0
    for i in range(n_pairs + 1):
        prices.append(round(p, 2))
        if ml_mode == "wrong":
            p *= 0.98       # 实际下跌 >1%，BULLISH 全错
        elif ml_mode == "right":
            p *= 1.02       # 实际上涨 >1%，BULLISH 全对
        else:               # mixed: 涨跌交替 >1%，BULLISH 对错各半
            p *= 1.02 if i % 2 == 0 else 1 / 1.02

    for i in range(n_pairs + 1):
        d = f"2026-07-{i + 1:02d}"
        nxt = prices[i + 1] if i < n_pairs else None
        if nxt is None or band_mode == "hit":
            bmin, bmax = 0.0, 9999.0
        elif band_mode == "miss":
            bmin, bmax = nxt + 1000.0, nxt + 2000.0
        else:  # neutral: 奇偶交替 → 命中率恰好 50%
            bmin, bmax = (nxt - 1.0, nxt + 1.0) if i % 2 == 0 else (nxt + 1000.0, nxt + 2000.0)
        _write(dir_path, d, prices[i], "BULLISH", bmin, bmax)


def _changelog_lines(env) -> list[dict]:
    path = env / "learned_changelog.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ── 样本不足不动作 ────────────────────────────────────────────────────────────

def test_recalibrate_insufficient_samples(learn_env):
    _seed_pairs(learn_env / "history", 5, ml_mode="wrong", band_mode="neutral")
    result = recalibrate()
    assert result["changed"] == []
    assert result["n_samples"] == 5
    assert result["ml_accuracy"] is None
    assert result["band_hit_rate"] is None
    assert result["current"] == {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}
    assert not (learn_env / "learned_changelog.jsonl").exists()


# ── ml_bias_scale ─────────────────────────────────────────────────────────────

def test_recalibrate_low_ml_accuracy_shrinks_bias(learn_env):
    _seed_pairs(learn_env / "history", 8, ml_mode="wrong", band_mode="neutral")
    result = recalibrate()
    assert result["ml_accuracy"] == 0.0
    assert result["band_hit_rate"] == 0.5
    assert len(result["changed"]) == 1
    c = result["changed"][0]
    assert c["param"] == "ml_bias_scale"
    assert c["old"] == 1.0 and c["new"] == pytest.approx(0.9)
    assert result["current"]["ml_bias_scale"] == pytest.approx(0.9)
    assert result["current"]["scenario_band_scale"] == 1.0
    # 写回 + changelog 一条
    saved = json.loads((learn_env / "learned_adjustments.json").read_text())
    assert saved["ml_bias_scale"] == pytest.approx(0.9)
    log = _changelog_lines(learn_env)
    assert len(log) == 1
    assert log[0]["param"] == "ml_bias_scale"
    assert log[0]["old"] == 1.0 and log[0]["new"] == pytest.approx(0.9)
    assert log[0]["n_samples"] == 8 and log[0]["reason"]


def test_recalibrate_high_ml_accuracy_recovers_toward_baseline(learn_env):
    """单向降级器：准确时仅向 1.0 回归，永不放大超过基准"""
    _seed_pairs(learn_env / "history", 8, ml_mode="right", band_mode="neutral")

    # 基准 1.0 + 全对 → 不动作（上限即 1.0，不放大）
    r0 = recalibrate()
    assert r0["ml_accuracy"] == 1.0
    assert r0["current"]["ml_bias_scale"] == 1.0
    assert r0["changed"] == []

    # 已被降级到 0.9 + 全对 → ×1.05 = 0.945 向基准回归一步
    (learn_env / "learned_adjustments.json").write_text(
        json.dumps({"ml_bias_scale": 0.9, "scenario_band_scale": 1.0})
    )
    r1 = recalibrate()
    assert r1["current"]["ml_bias_scale"] == pytest.approx(0.945)
    assert r1["changed"][0]["old"] == 0.9

    # 0.98 → ×1.05 = 1.029 → 钳到 1.0；再到 1.0 后不再变
    (learn_env / "learned_adjustments.json").write_text(
        json.dumps({"ml_bias_scale": 0.98, "scenario_band_scale": 1.0})
    )
    r2 = recalibrate()
    assert r2["current"]["ml_bias_scale"] == 1.0
    r3 = recalibrate()
    assert r3["changed"] == []
    assert len(_changelog_lines(learn_env)) == 2


def test_recalibrate_neutral_ml_excluded_from_accuracy(learn_env):
    """NEUTRAL 信号不做方向主张：从准确率样本剔除，不触发降级/回归"""
    hist = learn_env / "history"
    prices = []
    p = 400.0
    for _ in range(9):
        prices.append(round(p, 2))
        p *= 0.97  # 大跌——若 NEUTRAL 被误计为"对"，会在错误的方向上给模型加分
    for i in range(9):
        nxt = prices[i + 1] if i < 8 else None
        bmin, bmax = (nxt - 1.0, nxt + 1.0) if (nxt is not None and i % 2 == 0) \
            else (prices[i] + 1000.0, prices[i] + 2000.0)  # band 命中率 50%，不触发
        _write(hist, f"2026-07-{i + 1:02d}", prices[i], "NEUTRAL", bmin, bmax)

    r = recalibrate()
    assert r["ml_accuracy"] == 1.0   # 无方向样本 → 默认不降级
    assert r["changed"] == []
    assert r["current"]["ml_bias_scale"] == 1.0


# ── scenario_band_scale ───────────────────────────────────────────────────────

def test_recalibrate_band_too_narrow_widens(learn_env):
    _seed_pairs(learn_env / "history", 8, ml_mode="mixed", band_mode="miss")
    result = recalibrate()
    assert result["band_hit_rate"] == 0.0
    assert result["ml_accuracy"] == 0.5  # 中性区，ml 不动
    assert len(result["changed"]) == 1
    c = result["changed"][0]
    assert c["param"] == "scenario_band_scale"
    assert c["old"] == 1.0 and c["new"] == pytest.approx(1.1)
    assert result["current"]["scenario_band_scale"] == pytest.approx(1.1)


def test_recalibrate_band_too_wide_shrinks_and_clamps(learn_env):
    _seed_pairs(learn_env / "history", 8, ml_mode="mixed", band_mode="hit")

    r1 = recalibrate()
    assert r1["band_hit_rate"] == 1.0
    assert r1["current"]["scenario_band_scale"] == pytest.approx(0.95)

    # 手动压到 0.72，下一次 ×0.95=0.684 → 钳到下限 0.7
    (learn_env / "learned_adjustments.json").write_text(
        json.dumps({"ml_bias_scale": 1.0, "scenario_band_scale": 0.72})
    )
    r2 = recalibrate()
    assert r2["current"]["scenario_band_scale"] == 0.7
    assert r2["changed"][0]["old"] == 0.72

    # 已在下限：不再变更
    r3 = recalibrate()
    assert r3["changed"] == []
    assert r3["current"]["scenario_band_scale"] == 0.7
    assert len(_changelog_lines(learn_env)) == 2


# ── load_learned 容错 ─────────────────────────────────────────────────────────

def test_load_learned_defaults_when_missing(learn_env):
    assert load_learned() == {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}


def test_load_learned_corrupted_json(learn_env):
    (learn_env / "learned_adjustments.json").write_text("not-json{{{", encoding="utf-8")
    assert load_learned() == {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}


def test_load_learned_partial_keys(learn_env):
    (learn_env / "learned_adjustments.json").write_text(
        json.dumps({"ml_bias_scale": 0.8}), encoding="utf-8"
    )
    assert load_learned() == {"ml_bias_scale": 0.8, "scenario_band_scale": 1.0}


def test_load_learned_clamps_out_of_bounds_values(learn_env):
    """装载即钳制：被篡改/手工编辑的状态文件不能突破有界承诺"""
    (learn_env / "learned_adjustments.json").write_text(
        json.dumps({"ml_bias_scale": 1.2, "scenario_band_scale": 9.9}), encoding="utf-8"
    )
    assert load_learned() == {"ml_bias_scale": 1.0, "scenario_band_scale": 1.5}


# ── 情景区间宽度缩放 ──────────────────────────────────────────────────────────

def test_band_scale_widens_scenarios_center_unchanged():
    market = _market_snapshot(rsi_14=61.9, close_5d=[320.0, 324.0, 328.0, 332.0, 336.7])
    _, _, s_base = compute_levels_and_scenarios(market, None)
    _, _, s_10 = compute_levels_and_scenarios(market, None, band_scale=1.0)
    _, _, s_15 = compute_levels_and_scenarios(market, None, band_scale=1.5)

    # 默认参数与 1.0 完全一致
    assert [(s.price_min, s.price_max) for s in s_base] == [(s.price_min, s.price_max) for s in s_10]

    for a, b in zip(s_10, s_15):
        assert (b.price_max - b.price_min) > (a.price_max - a.price_min)
        center_a = (a.price_min + a.price_max) / 2
        center_b = (b.price_min + b.price_max) / 2
        assert center_a == pytest.approx(center_b, abs=1.0)  # 中心不变（容忍取整偏移）


# ── learning_status + web 区块 ────────────────────────────────────────────────

def test_learning_status_and_track_record_block(learn_env):
    _seed_pairs(learn_env / "history", 8, ml_mode="wrong", band_mode="neutral")
    recalibrate()

    status = learning_status()
    assert status["n_samples"] == 8
    assert status["ml_accuracy"] == 0.0
    assert status["current"]["ml_bias_scale"] == pytest.approx(0.9)
    assert len(status["changelog"]) == 1

    from web.track_record import build_track_record_html
    record = {"total": 1, "hit_rate": 1.0, "direction_rate": 1.0, "hedge_rate": 1.0,
              "weeks": [{"report_date": "2026-07-01", "badge": "命中", "direction": "横盘",
                         "predicted_min": 390.0, "predicted_max": 410.0,
                         "actual_price": 400.0, "price_change_pct": 0.5}],
              "pending": None}
    html = build_track_record_html(record, [], status)
    assert "系数自校准" in html
    assert "ml_bias_scale" in html and "0.90" in html
    assert "区间命中率 50%" in html
    assert "1.00 → 0.90" in html          # changelog 行
    assert "暂无校准记录" not in html

    # learning=None → 区块不渲染
    assert "系数自校准" not in build_track_record_html(record, [], None)


def test_track_record_learning_insufficient_samples():
    from web.track_record import build_track_record_html
    record = {"total": 1, "hit_rate": 1.0, "direction_rate": 1.0, "hedge_rate": 1.0,
              "weeks": [{"report_date": "2026-07-01", "badge": "命中", "direction": "横盘",
                         "predicted_min": 390.0, "predicted_max": 410.0,
                         "actual_price": 400.0, "price_change_pct": 0.5}],
              "pending": None}
    learning = {"current": {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0},
                "n_samples": 3, "min_samples": 8,
                "ml_accuracy": None, "band_hit_rate": None, "changelog": []}
    html = build_track_record_html(record, [], learning)
    assert "样本不足 3/8" in html
    assert "未校准" in html
    assert "暂无校准记录" in html


# ── M3: web 兜底隔离 / L1: scale 存证 ─────────────────────────────────────────

def test_track_record_page_resilient_to_optional_data_failure(monkeypatch):
    """可选数据（driver_stats / learning_status）失败时战绩页仍 200，主内容在位"""
    from fastapi.testclient import TestClient
    from web.app import app

    def boom(*a, **k):
        raise RuntimeError("optional data broken")

    monkeypatch.setattr("reports.history.compute_driver_stats", boom)
    monkeypatch.setattr("reports.learning.learning_status", boom)

    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/track-record/")
    assert r.status_code == 200
    assert "预测战绩" in r.text or "暂无历史复盘数据" in r.text


def test_save_summary_records_learned_scales(tmp_path, monkeypatch):
    """ReportSummary 存证当期生效的自校准系数；旧格式 JSON（无此键）加载兼容"""
    from reports.demo_data import demo_report
    from reports.history import ReportSummary, save_report_summary

    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    monkeypatch.setattr(
        "reports.learning.load_learned",
        lambda: {"ml_bias_scale": 0.9, "scenario_band_scale": 1.1},
    )
    monkeypatch.setattr(
        "reports.learning.load_review_memory",
        lambda: {"hedge_conviction": 0.9, "driver_trust": {"RSI超买": 0.8}},
    )

    path = save_report_summary(demo_report())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["learned_scales"] == {
        "ml_bias_scale": 0.9,
        "scenario_band_scale": 1.1,
        "hedge_conviction": 0.9,
        "driver_trust": {"RSI超买": 0.8},
    }

    del data["learned_scales"]  # 模拟旧格式
    s = ReportSummary(**data)
    assert s.learned_scales == {}


# ── 近期记忆：套保持信 / 驱动因子信任 ─────────────────────────────────────────

def _write_case(dir_path, report_date, price, *, ml_signal="NEUTRAL", hedge_ratio=0.65,
                band_min=0.0, band_max=9999.0, drivers=None, direction="横盘"):
    data = {
        "report_date": report_date,
        "forecast_week_start": report_date,
        "forecast_week_end": report_date,
        "current_price": price,
        "change_1d_pct": 0.0,
        "change_30d_pct": 0.0,
        "rsi_14": 50.0,
        "ml_signal": ml_signal,
        "ml_confidence": 0.5,
        "ml_price_target_30d": None,
        "hedge_ratio": hedge_ratio,
        "hedge_signal": "TIGHT" if hedge_ratio >= 0.70 else "MEDIUM_HEDGE",
        "dominant_scenario_direction": direction,
        "dominant_scenario_prob": 0.5,
        "dominant_scenario_min": band_min,
        "dominant_scenario_max": band_max,
        "outlook": "测试",
        "drivers": drivers or [],
    }
    (dir_path / f"weekly_summary_{report_date}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _seed_hedges(dir_path, moves, hedge_ratio=0.80, drivers_for=None, hedge_for=None,
                 direction_for=None):
    """
    moves: 每一对的价格方向，"up" 或 "down"（幅度 2%，超过 ±1% 判定线）。
    最后一期没有下一跳，只用来给倒数第二期当实际价。
    drivers_for(pair_index, direction) → drivers list，缺省不写驱动。
    区间奇偶交替，命中率 50%，不触发现有的区间系数。
    """
    price = 400.0
    prices = [price]
    for move in moves:
        price = round(price * (1.02 if move == "up" else 0.98), 2)
        prices.append(price)
    for i, current in enumerate(prices):
        nxt = prices[i + 1] if i < len(moves) else None
        if nxt is None or i % 2 == 0:
            bmin, bmax = (0.0, 9999.0) if nxt is None else (nxt - 1.0, nxt + 1.0)
        else:
            bmin, bmax = nxt + 1000.0, nxt + 2000.0
        if nxt is None:
            bmin, bmax = 0.0, 9999.0
        drivers = []
        if drivers_for is not None and i < len(moves):
            drivers = drivers_for(i, moves[i])
        ratio = hedge_for(i) if hedge_for is not None and i < len(moves) else hedge_ratio
        direction = "横盘"
        if direction_for is not None and i < len(moves):
            direction = direction_for(i, moves[i])
        _write_case(
            dir_path, f"2026-07-{i + 1:02d}", current,
            hedge_ratio=ratio, band_min=bmin, band_max=bmax, drivers=drivers,
            direction=direction,
        )


def test_recalibrate_failed_hedges_lower_conviction(learn_env):
    """偏紧套保却连涨：近期套保有效率为 0，持信降到 0.9。两个旧系数不动。"""
    _seed_hedges(learn_env / "history", ["up"] * 8, hedge_ratio=0.80)
    result = recalibrate()
    assert result["memory"]["hedge_accuracy"] == 0.0
    assert result["ml_accuracy"] == 1.0  # NEUTRAL 不进方向样本
    assert result["band_hit_rate"] == 0.5
    conviction = [c for c in result["changed"] if c["param"] == "hedge_conviction"]
    assert len(conviction) == 1
    assert conviction[0]["old"] == 1.0 and conviction[0]["new"] == pytest.approx(0.9)
    assert result["current"] == {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}
    assert result["memory"]["hedge_conviction"] == pytest.approx(0.9)


def test_recalibrate_good_hedges_recover_conviction_and_clamp(learn_env):
    _seed_hedges(learn_env / "history", ["down"] * 8, hedge_ratio=0.80)
    (learn_env / "learned_adjustments.json").write_text(
        json.dumps({"ml_bias_scale": 1.0, "scenario_band_scale": 1.0, "hedge_conviction": 0.9})
    )
    recovered = recalibrate()
    assert recovered["memory"]["hedge_conviction"] == pytest.approx(0.945)

    (learn_env / "learned_adjustments.json").write_text(
        json.dumps({"ml_bias_scale": 1.0, "scenario_band_scale": 1.0, "hedge_conviction": 0.62})
    )
    # 换一组成立不住的套保，把 0.62×0.9 钳到下限 0.6
    for path in (learn_env / "history").glob("weekly_summary_*.json"):
        path.unlink()
    _seed_hedges(learn_env / "history", ["up"] * 8, hedge_ratio=0.80)
    clamped = recalibrate()
    assert clamped["memory"]["hedge_conviction"] == 0.6
    again = recalibrate()
    assert all(c["param"] != "hedge_conviction" for c in again["changed"])


def test_recalibrate_recent_hedges_outweigh_old_misses(learn_env):
    """等权只有 5/12 会继续降权；近期 5 对叫对，加权后越过 65%，持信往回走。"""
    moves = ["up"] * 7 + ["down"] * 5
    _seed_hedges(learn_env / "history", moves, hedge_ratio=0.80)
    (learn_env / "learned_adjustments.json").write_text(
        json.dumps({"ml_bias_scale": 1.0, "scenario_band_scale": 1.0, "hedge_conviction": 0.9})
    )
    result = recalibrate()
    assert result["memory"]["hedge_accuracy"] > 0.65
    assert result["memory"]["hedge_conviction"] == pytest.approx(0.945)
    assert "向基准回归" in result["changed"][0]["reason"]


def test_neutral_hedges_do_not_dilute_conviction(learn_env):
    """停在 65% 的周不再算叫对。四次偏紧叫错就够降持信，即使另外四周中性。"""
    def ratio(i):
        return 0.80 if i < 4 else 0.65

    _seed_hedges(learn_env / "history", ["up"] * 8, hedge_for=ratio)
    result = recalibrate()
    assert result["memory"]["hedge_accuracy"] == 0.0
    assert result["memory"]["hedge_conviction"] == pytest.approx(0.9)
    assert result["current"] == {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}

    for path in (learn_env / "history").glob("weekly_summary_*.json"):
        path.unlink()
    (learn_env / "learned_adjustments.json").unlink()
    # 只有两次表态：样本不够，持信不动
    _seed_hedges(
        learn_env / "history", ["up"] * 8,
        hedge_for=lambda i: 0.80 if i < 2 else 0.65,
    )
    short = recalibrate()
    assert short["memory"]["hedge_accuracy"] is None
    assert short["changed"] == []
    assert short["memory"]["hedge_conviction"] == 1.0


def test_recalibrate_driver_trust_shrinks_and_fades(learn_env):
    """看跌因子连着被涨市打脸就降权；从报告里消失之后，信任再慢慢回到 1。"""
    def failing(i, direction):
        if i >= 4:
            return []
        return [{"param_name": "RSI超买", "signal": "看跌", "weight": "高", "category": "技术"}]

    _seed_hedges(learn_env / "history", ["up"] * 4 + ["down"] * 4, hedge_ratio=0.65, drivers_for=failing)
    first = recalibrate()
    assert first["memory"]["driver_trust"]["RSI超买"] == pytest.approx(0.9)
    assert first["memory"]["hedge_conviction"] == 1.0
    assert any(c["param"] == "driver_trust:RSI超买" for c in first["changed"])

    # 下一轮历史里这个因子不再出现：0.9×1.05=0.945，而不是继续停在原地
    for path in (learn_env / "history").glob("weekly_summary_*.json"):
        path.unlink()
    _seed_hedges(learn_env / "history", ["up"] * 8, hedge_ratio=0.65)
    faded = recalibrate()
    assert faded["memory"]["driver_trust"]["RSI超买"] == pytest.approx(0.945)
    assert any("未再出现" in c["reason"] for c in faded["changed"])


def test_recalibrate_recent_driver_hits_restore_trust(learn_env):
    def named(i, direction):
        signal = "看跌"
        return [{"param_name": "均线空头排列", "signal": signal, "weight": "高", "category": "技术"}]

    _seed_hedges(
        learn_env / "history",
        ["up"] * 7 + ["down"] * 5,
        hedge_ratio=0.65,
        drivers_for=named,
    )
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "hedge_conviction": 1.0,
        "driver_trust": {"均线空头排列": 0.8},
    }))
    result = recalibrate()
    assert result["memory"]["driver_trust"]["均线空头排列"] == pytest.approx(0.84)


def test_recalibrate_keeps_trust_until_enough_samples(learn_env):
    def rare(i, direction):
        if i >= 2:
            return []
        return [{"param_name": "La Nina", "signal": "看涨", "weight": "高", "category": "气候"}]

    # 两次应验也不够 4 个样本：既不降也不因「没出现」而淡忘
    _seed_hedges(learn_env / "history", ["up"] * 8, hedge_ratio=0.65, drivers_for=rare)
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0, "scenario_band_scale": 1.0, "driver_trust": {"La Nina": 0.8},
    }))
    result = recalibrate()
    assert result["changed"] == []
    assert result["memory"]["driver_trust"]["La Nina"] == pytest.approx(0.8)


def test_load_review_memory_clamps_and_drops_garbage(learn_env):
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 0.8,
        "hedge_conviction": 9,
        "driver_trust": {"A": 0.1, "B": "nope", "": 0.5, "C": 1.2, "D": 0.8},
        "direction_trust": {"up": 0.1, "down": 1.0, "flat": 0.7, "nope": 0.5},
        "band_center_shift": 9,
        "flat_trust": 0.1,
    }), encoding="utf-8")
    assert load_learned()["ml_bias_scale"] == 0.8
    memory = load_review_memory()
    assert memory["hedge_conviction"] == 1.0
    assert memory["driver_trust"] == {"A": 0.5, "D": 0.8}
    assert memory["direction_trust"] == {"up": 0.6}
    assert memory["band_center_shift"] == 0.03
    assert memory["flat_trust"] == 0.6


def test_apply_review_memory_changes_next_report():
    """信任和持信要进下一期：权重降档、RSI 贡献变小、套保比率靠回 65%。"""
    from datetime import datetime

    from arbor.domain.types.enums import Domain, EventType
    from arbor.domain.types.event import CoffeeEvent
    from reports.learning import (
        apply_driver_weights,
        apply_hedge_conviction,
        ml_trust_multiplier,
        scale_trusted_events,
    )
    from reports.models import HedgeAdvice, ResistParam, SupportParam

    bullish = [SupportParam("技术", "5日动量强势", "1", "看涨", "高", "涨")]
    bearish = [ResistParam("技术", "RSI超买", "70", "看跌", "高", "热")]
    apply_driver_weights(bullish, bearish, {"RSI超买": 0.8, "5日动量强势": 0.95})
    assert bearish[0].weight == "中"
    assert bullish[0].weight == "高"  # 0.95 还在原档

    fresh = [ResistParam("技术", "RSI超买", "70", "看跌", "高", "热")]
    apply_driver_weights([], fresh, {"RSI超买": 0.9})
    assert fresh[0].weight == "中"  # 第一次降权就改报告里的档

    apply_driver_weights(bearish, [], {"RSI超买": 0.7})
    assert bearish[0].weight == "弱"

    assert ml_trust_multiplier("ensemble", "BEARISH", {"ensemble 看跌信号": 0.8}) == pytest.approx(0.8)
    assert ml_trust_multiplier("ensemble", "NEUTRAL", {"ensemble 中性信号": 0.5}) == 1.0
    assert ml_trust_multiplier("ensemble", "BULLISH", {}) == 1.0

    events = [
        CoffeeEvent(EventType.RSI_EXTREME, Domain.FINANCE, datetime(2026, 7, 1), 3, -0.10, "超买", "pipeline"),
        CoffeeEvent(EventType.RSI_EXTREME, Domain.FINANCE, datetime(2026, 7, 1), 3, 0.10, "超卖", "pipeline"),
    ]
    scale_trusted_events(events, {"RSI超买": 0.5})
    assert events[0].value == pytest.approx(-0.05)
    assert events[1].value == pytest.approx(0.10)

    hedge = HedgeAdvice(ratio=0.80, signal="套保偏紧", narrative="[套保偏紧] 主导因子: technical | 合约: KC=F")
    apply_hedge_conviction(hedge, 0.6)
    assert hedge.ratio == pytest.approx(0.74)
    assert hedge.signal == "维持中性"
    assert hedge.narrative.startswith("[维持中性]")
    untouched = HedgeAdvice(ratio=0.80, signal="套保偏紧", narrative="[套保偏紧] x")
    apply_hedge_conviction(untouched, 1.0)
    assert untouched.ratio == 0.80 and untouched.signal == "套保偏紧"


def test_untrusted_driver_gives_its_scenario_to_flat():
    """看跌却不可靠时，下跌概率让给横盘。RSI 不重复计算，空信任不改数字。"""
    from reports.learning import apply_driver_scenario_tilt, sync_dominant_scenario_event
    from reports.models import ResistParam, Scenario, SupportParam
    from reports.report_events import scenario_event

    def pack(up, flat, down):
        return [
            Scenario("涨", "上涨", 400, 420, up, []),
            Scenario("盘", "横盘", 390, 410, flat, []),
            Scenario("跌", "下跌", 370, 400, down, []),
        ]

    same = pack(0.25, 0.40, 0.35)
    before = [(s.direction, s.probability) for s in same]
    assert apply_driver_scenario_tilt(same, [], [], {}) is False
    assert [(s.direction, s.probability) for s in same] == before

    bearish = [ResistParam("技术", "均线空头排列", "MA", "看跌", "高", "空")]
    moved = pack(0.25, 0.40, 0.35)
    assert apply_driver_scenario_tilt(moved, [], bearish, {"均线空头排列": 0.5}) is True
    by = {s.direction: s.probability for s in moved}
    assert by["下跌"] == pytest.approx(0.31, abs=0.001)
    assert by["横盘"] == pytest.approx(0.44, abs=0.001)
    assert by["上涨"] == pytest.approx(0.25, abs=0.001)
    assert sum(by.values()) == pytest.approx(1.0)

    rsi = [ResistParam("技术", "RSI超买", "70", "看跌", "高", "热")]
    untouched = pack(0.25, 0.40, 0.35)
    assert apply_driver_scenario_tilt(untouched, [], rsi, {"RSI超买": 0.5}) is False

    crowded = [ResistParam("技术", f"因子{i}", "x", "看跌", "高", "x") for i in range(6)]
    capped = pack(0.25, 0.40, 0.35)
    apply_driver_scenario_tilt(capped, [], crowded, {f"因子{i}": 0.5 for i in range(6)})
    assert {s.direction: s.probability for s in capped}["下跌"] == pytest.approx(0.29, abs=0.001)

    events = [scenario_event(moved[2])]
    sync_dominant_scenario_event(events, moved)
    assert "横盘" in events[0].narrative


def test_untrusted_driver_nudges_hedge_against_its_signal():
    """均线、气候这类没有单独数值通道的因子，不可靠时直接改下一期比率。"""
    from reports.learning import apply_driver_hedge_nudge, driver_hedge_nudge, scale_analyst_event
    from reports.models import HedgeAdvice, ResistParam, SupportParam
    from datetime import datetime
    from arbor.domain.types.enums import Domain, EventType
    from arbor.domain.types.event import CoffeeEvent

    bearish = [
        ResistParam("技术", "均线空头排列", "MA", "看跌", "高", "空"),
        ResistParam("技术", "RSI超买", "70", "看跌", "高", "热"),
        ResistParam("ML模型", "ensemble 看跌信号", "0.6", "看跌", "高", "模型"),
    ]
    bullish = [SupportParam("气候", "La Nina", "ONI", "看涨", "高", "旱")]
    trust = {"均线空头排列": 0.8, "RSI超买": 0.5, "ensemble 看跌信号": 0.5, "La Nina": 0.9}
    # 只有均线 −2 个点、La Nina +1 个点；RSI 和 ML 不重复计算
    assert driver_hedge_nudge(bullish, bearish, trust) == pytest.approx(-0.01)

    hedge = HedgeAdvice(ratio=0.70, signal="维持中性", narrative="[维持中性] 主导因子: technical")
    apply_driver_hedge_nudge(hedge, [], [bearish[0]], {"均线空头排列": 0.8})
    assert hedge.ratio == pytest.approx(0.68)
    assert hedge.signal == "维持中性"

    capped = [ResistParam("技术", f"因子{i}", "x", "看跌", "高", "x") for i in range(6)]
    assert driver_hedge_nudge([], capped, {f"因子{i}": 0.5 for i in range(6)}) == pytest.approx(-0.06)

    same = HedgeAdvice(ratio=0.70, signal="维持中性", narrative="[维持中性] x")
    apply_driver_hedge_nudge(same, bullish, bearish, {})
    assert same.ratio == 0.70

    event = CoffeeEvent(
        EventType.LLM_COMMENTARY, Domain.FINANCE, datetime(2026, 7, 1), 3, 0.08, "看跌", "llm",
    )
    scale_analyst_event(event, {"AI 分析师点评": 0.5})
    assert event.value == pytest.approx(0.04)
    untouched = CoffeeEvent(
        EventType.LLM_COMMENTARY, Domain.FINANCE, datetime(2026, 7, 1), 3, 0.08, "看跌", "llm",
    )
    scale_analyst_event(untouched, {})
    assert untouched.value == pytest.approx(0.08)


def test_track_record_shows_review_memory():
    from web.track_record import build_track_record_html
    record = {"total": 1, "hit_rate": 1.0, "direction_rate": 1.0, "hedge_rate": 0.4,
              "weeks": [{"report_date": "2026-07-01", "badge": "偏离", "direction": "横盘",
                         "predicted_min": 390.0, "predicted_max": 410.0,
                         "actual_price": 430.0, "price_change_pct": 2.0}],
              "pending": None, "mean_brier": None, "bss": None, "calibration": [], "resolution": None}
    learning = {
        "current": {"ml_bias_scale": 0.9, "scenario_band_scale": 1.0},
        "n_samples": 8, "min_samples": 8, "ml_accuracy": 0.4, "band_hit_rate": 0.5,
        "changelog": [{
            "ts": "2026-08-01T00:00:00", "param": "band_center_shift",
            "old": 0.0, "new": -0.005, "reason": "情景中心偏高",
        }],
        "memory": {
            "hedge_conviction": 0.9,
            "hedge_accuracy": 0.38,
            "driver_trust": {"RSI超买": 0.81},
            "direction_trust": {"up": 0.9},
            "band_center_shift": -0.005,
            "flat_trust": 0.9,
        },
    }
    stats = [{"param_name": "RSI超买", "samples": 4, "hits": 1, "rate": 0.25}]
    html = build_track_record_html(record, stats, learning)
    assert "套保持信" in html and "hedge_conviction" in html and "0.90" in html
    assert "有方向的套保有效率 38%" in html
    assert "停在中性的周不给套保持信加分" in html
    assert "情景概率让给横盘" in html
    assert "按方向信任让给横盘" in html
    assert "方向信任" in html and "上涨 0.90" in html
    assert "区间中心" in html and "下移 0.50%" in html
    assert "每步 0.5 个百分点" in html
    assert "0.00 → -0.005" in html
    assert "横盘信任" in html and ">0.90<" in html
    assert "分给上涨和下跌" in html
    assert "压低的驱动" in html and "RSI超买 0.81" in html
    assert "<th>信任</th>" in html and ">0.81<" in html


def test_recalibrate_wrong_up_calls_lower_direction_trust(learn_env):
    """连续把上涨说成主导情景、价格却下跌：上涨信任降到 0.9。套保停在中性，旧系数不动。"""
    _seed_hedges(
        learn_env / "history", ["down"] * 8, hedge_ratio=0.65,
        direction_for=lambda i, move: "上涨",
    )
    result = recalibrate()
    assert result["memory"]["direction_trust"]["up"] == pytest.approx(0.9)
    assert result["memory"]["hedge_conviction"] == 1.0
    assert result["current"]["ml_bias_scale"] == 1.0
    assert result["current"]["scenario_band_scale"] == 1.0
    assert result["band_hit_rate"] == 0.5
    changed = [c for c in result["changed"] if c["param"] == "direction_trust:up"]
    assert len(changed) == 1
    assert "概率让给横盘" in changed[0]["reason"]
    saved = json.loads((learn_env / "learned_adjustments.json").read_text())
    assert saved["direction_trust"]["up"] == pytest.approx(0.9)


def test_recalibrate_right_up_calls_recover_direction_trust(learn_env):
    _seed_hedges(
        learn_env / "history", ["up"] * 8, hedge_ratio=0.65,
        direction_for=lambda i, move: "上涨",
    )
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "direction_trust": {"up": 0.9},
    }))
    result = recalibrate()
    assert result["memory"]["direction_trust"]["up"] == pytest.approx(0.945)
    assert result["memory"]["hedge_conviction"] == 1.0


def test_recalibrate_few_direction_calls_do_not_move_trust(learn_env):
    """主张不足 4 次：不降，也不因样本少而淡忘。"""
    _seed_hedges(
        learn_env / "history", ["up"] * 8, hedge_ratio=0.65,
        direction_for=lambda i, move: "上涨" if i < 3 else "横盘",
    )
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "direction_trust": {"up": 0.8},
    }))
    result = recalibrate()
    assert result["changed"] == []
    assert result["memory"]["direction_trust"]["up"] == pytest.approx(0.8)


def test_recalibrate_absent_direction_fades_and_survives_other_writes(learn_env):
    """本期全是横盘时，旧的上涨信任向 1.0 淡。另一次只改 ML 时，方向信任仍写在文件里。"""
    _seed_hedges(learn_env / "history", ["up"] * 8, hedge_ratio=0.65)
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "direction_trust": {"up": 0.8},
    }))
    faded = recalibrate()
    assert faded["memory"]["direction_trust"]["up"] == pytest.approx(0.84)
    assert faded["memory"]["hedge_conviction"] == 1.0
    assert faded["current"]["ml_bias_scale"] == 1.0

    for path in (learn_env / "history").glob("weekly_summary_*.json"):
        path.unlink()
    _seed_hedges(
        learn_env / "history", ["down"] * 8, hedge_ratio=0.65,
        direction_for=lambda i, move: "上涨" if i < 3 else "横盘",
    )
    for path in (learn_env / "history").glob("weekly_summary_*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["ml_signal"] = "BULLISH"
        path.write_text(json.dumps(data), encoding="utf-8")
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "direction_trust": {"up": 0.8},
    }))
    moved = recalibrate()
    assert moved["current"]["ml_bias_scale"] == pytest.approx(0.9)
    assert moved["memory"]["direction_trust"]["up"] == pytest.approx(0.8)
    saved = json.loads((learn_env / "learned_adjustments.json").read_text())
    assert saved["direction_trust"]["up"] == pytest.approx(0.8)
    assert saved["ml_bias_scale"] == pytest.approx(0.9)


def test_wrong_direction_gives_its_probability_to_flat():
    """上涨信任 0.9 时，40% 的上涨变成 36%，让出的 4 个点给横盘。没有横盘则不改。"""
    from reports.learning import apply_direction_trust
    from reports.models import Scenario

    def pack(up, flat, down):
        return [
            Scenario("涨", "上涨", 400, 420, up, []),
            Scenario("盘", "横盘", 390, 410, flat, []),
            Scenario("跌", "下跌", 370, 400, down, []),
        ]

    moved = pack(0.40, 0.35, 0.25)
    assert apply_direction_trust(moved, {"up": 0.9}) is True
    by = {s.direction: s.probability for s in moved}
    assert by["上涨"] == pytest.approx(0.36, abs=0.001)
    assert by["横盘"] == pytest.approx(0.39, abs=0.001)
    assert by["下跌"] == pytest.approx(0.25, abs=0.001)

    same = pack(0.40, 0.35, 0.25)
    before = [(s.direction, s.probability) for s in same]
    assert apply_direction_trust(same, {}) is False
    assert apply_direction_trust(same, {"up": 1.0}) is False
    assert [(s.direction, s.probability) for s in same] == before

    no_flat = [
        Scenario("涨", "上涨", 400, 420, 0.60, []),
        Scenario("跌", "下跌", 370, 400, 0.40, []),
    ]
    assert apply_direction_trust(no_flat, {"up": 0.5}) is False
    assert [s.probability for s in no_flat] == [0.60, 0.40]


def _seed_center(dir_path, *, high: bool):
    """
    8 对。偶数对的区间中心贴着现价：high 时中心在现价上方 4% 且罩不住下一周；
    否则中心落在下一周价格上。奇数对用远离现价的宽区间，只负责把命中率维持在 50%。
    """
    price = 400.0
    prices = [price]
    for _ in range(8):
        price = round(price * 0.98, 2)
        prices.append(price)
    for i, current in enumerate(prices):
        nxt = prices[i + 1] if i < 8 else None
        if nxt is None:
            bmin, bmax = (0.0, 9999.0)
        elif i % 2 == 1:
            # high 时用罩住一切的宽区间凑满 50% 命中；否则用远离现价的脱靶区间。
            bmin, bmax = (0.0, 9999.0) if high else (nxt + 1000.0, nxt + 2000.0)
        elif high:
            mid = current * 1.04
            half = current * 0.01
            bmin, bmax = mid - half, mid + half
        else:
            bmin, bmax = nxt - 1.0, nxt + 1.0
        _write_case(
            dir_path, f"2026-08-{i + 1:02d}", current,
            hedge_ratio=0.65, band_min=bmin, band_max=bmax,
        )


def test_recalibrate_high_center_steps_band_down(learn_env):
    """区间中心连续停在现价上方：下一期偏移走低 0.5 个百分点。宽度和套保不动。"""
    _seed_center(learn_env / "history", high=True)
    result = recalibrate()
    assert result["memory"]["band_center_shift"] == -0.005
    assert result["current"] == {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}
    assert result["memory"]["hedge_conviction"] == 1.0
    assert result["band_hit_rate"] == 0.5
    changed = [c for c in result["changed"] if c["param"] == "band_center_shift"]
    assert len(changed) == 1
    assert changed[0]["old"] == 0.0 and changed[0]["new"] == -0.005
    assert "区间下移" in changed[0]["reason"]

    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "band_center_shift": -0.03,
    }))
    floored = recalibrate()
    assert floored["memory"]["band_center_shift"] == -0.03
    assert all(c["param"] != "band_center_shift" for c in floored["changed"])


def test_recalibrate_centered_bands_walk_shift_back_toward_zero(learn_env):
    _seed_center(learn_env / "history", high=False)
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "band_center_shift": -0.02,
    }))
    result = recalibrate()
    assert result["memory"]["band_center_shift"] == -0.015
    assert result["current"]["scenario_band_scale"] == 1.0
    assert [c["param"] for c in result["changed"]] == ["band_center_shift"]


def test_recalibrate_few_anchored_bands_do_not_move_center(learn_env):
    _seed_center(learn_env / "history", high=True)
    # 只留 3 个贴近现价的区间。2026-08-07 改成宽区间后，中心样本不够 4 对。
    path = learn_env / "history" / "weekly_summary_2026-08-07.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["dominant_scenario_min"] = 0.0
    data["dominant_scenario_max"] = 9999.0
    path.write_text(json.dumps(data), encoding="utf-8")
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "band_center_shift": -0.01,
    }))
    result = recalibrate()
    assert result["changed"] == []
    assert result["memory"]["band_center_shift"] == -0.01


def test_band_center_shift_clamps_and_moves_prices():
    """偏移 -1% 时，400 附近的区间整体下移 4。0 和倒挂区间不改。"""
    from reports.learning import apply_band_center_shift
    from reports.models import Scenario

    bands = [
        Scenario("涨", "上涨", 400, 420, 0.25, []),
        Scenario("盘", "横盘", 390, 410, 0.40, []),
        Scenario("跌", "下跌", 370, 400, 0.35, []),
    ]
    assert apply_band_center_shift(bands, -0.01, 400) is True
    assert [s.price_min for s in bands] == [396, 386, 366]
    assert [s.price_max for s in bands] == [416, 406, 396]
    assert [s.probability for s in bands] == [0.25, 0.40, 0.35]

    same = [Scenario("盘", "横盘", 390, 410, 0.4, [])]
    assert apply_band_center_shift(same, 0.0, 400) is False
    assert same[0].price_min == 390 and same[0].price_max == 410

    tiny = [Scenario("盘", "横盘", 10, 10.2, 1.0, [])]
    assert apply_band_center_shift(tiny, -0.03, 400) is False
    assert tiny[0].price_min == 10 and tiny[0].price_max == 10.2


def _seed_flat_calls(dir_path, *, wrong: bool):
    """
    8 对横盘主张。偶数对的区间罩住现价、半宽约 2%，算一次横盘。
    wrong 时价格每步跌 2%，中心落在下一周价格上，所以区间中心误差是 0。
    奇数对用远离现价的脱靶区间，把区间命中率维持在 50%。
    """
    price = 400.0
    prices = [price]
    for _ in range(8):
        price = round(price * (0.98 if wrong else 1.004), 2)
        prices.append(price)
    for i, current in enumerate(prices):
        nxt = prices[i + 1] if i < 8 else None
        if nxt is None:
            bmin, bmax = 0.0, 9999.0
        elif i % 2 == 1:
            bmin, bmax = nxt + 1000.0, nxt + 2000.0
        elif wrong:
            half = abs(current - nxt)
            bmin, bmax = nxt - half, nxt + half
        else:
            half = current * 0.02
            bmin, bmax = current - half, current + half
        _write_case(
            dir_path, f"2026-09-{i + 1:02d}", current,
            hedge_ratio=0.65, band_min=bmin, band_max=bmax, direction="横盘",
        )


def test_recalibrate_wrong_flat_calls_lower_flat_trust(learn_env):
    """横盘区间罩住现价、价格却连跌：横盘信任降到 0.9。区间中心和套保不动。"""
    _seed_flat_calls(learn_env / "history", wrong=True)
    result = recalibrate()
    assert result["memory"]["flat_trust"] == pytest.approx(0.9)
    assert result["memory"]["band_center_shift"] == 0.0
    assert result["memory"]["hedge_conviction"] == 1.0
    assert result["current"] == {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}
    assert result["band_hit_rate"] == 0.5
    changed = [c for c in result["changed"] if c["param"] == "flat_trust"]
    assert len(changed) == 1
    assert "分给涨跌" in changed[0]["reason"]

    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "flat_trust": 0.6,
    }))
    floored = recalibrate()
    assert floored["memory"]["flat_trust"] == 0.6
    assert all(c["param"] != "flat_trust" for c in floored["changed"])


def test_recalibrate_right_flat_calls_recover_trust(learn_env):
    _seed_flat_calls(learn_env / "history", wrong=False)
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "flat_trust": 0.9,
    }))
    result = recalibrate()
    assert result["memory"]["flat_trust"] == pytest.approx(0.945)
    assert result["current"]["scenario_band_scale"] == 1.0
    assert [c["param"] for c in result["changed"]] == ["flat_trust"]


def test_recalibrate_few_flat_calls_do_not_move_trust(learn_env):
    _seed_flat_calls(learn_env / "history", wrong=True)
    path = learn_env / "history" / "weekly_summary_2026-09-07.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["dominant_scenario_min"] = data["current_price"] + 1000.0
    data["dominant_scenario_max"] = data["current_price"] + 2000.0
    path.write_text(json.dumps(data), encoding="utf-8")
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "flat_trust": 0.8,
    }))
    result = recalibrate()
    assert result["changed"] == []
    assert result["memory"]["flat_trust"] == pytest.approx(0.8)


def test_recalibrate_absent_flat_calls_fade_trust(learn_env):
    _seed_hedges(
        learn_env / "history", ["up"] * 8, hedge_ratio=0.65,
        direction_for=lambda i, move: "上涨",
    )
    (learn_env / "learned_adjustments.json").write_text(json.dumps({
        "ml_bias_scale": 1.0,
        "scenario_band_scale": 1.0,
        "flat_trust": 0.8,
    }))
    result = recalibrate()
    assert result["memory"]["flat_trust"] == pytest.approx(0.84)
    assert result["memory"]["hedge_conviction"] == 1.0
    assert result["current"]["ml_bias_scale"] == 1.0


def test_wrong_flat_gives_its_probability_to_the_two_sides():
    """横盘信任 0.9 时，40% 的横盘变成 36%，涨跌各得 2 个点。没有涨跌情景则不改。"""
    from reports.learning import apply_flat_trust
    from reports.models import Scenario

    bands = [
        Scenario("涨", "上涨", 400, 420, 0.30, []),
        Scenario("盘", "横盘", 390, 410, 0.40, []),
        Scenario("跌", "下跌", 370, 400, 0.30, []),
    ]
    assert apply_flat_trust(bands, 0.9) is True
    by = {s.direction: s.probability for s in bands}
    assert by["横盘"] == pytest.approx(0.36, abs=0.001)
    assert by["上涨"] == pytest.approx(0.32, abs=0.001)
    assert by["下跌"] == pytest.approx(0.32, abs=0.001)

    same = [Scenario("盘", "横盘", 390, 410, 0.40, [])]
    assert apply_flat_trust(same, 0.5) is False
    assert same[0].probability == 0.40
    untouched = [
        Scenario("涨", "上涨", 400, 420, 0.30, []),
        Scenario("盘", "横盘", 390, 410, 0.40, []),
        Scenario("跌", "下跌", 370, 400, 0.30, []),
    ]
    assert apply_flat_trust(untouched, 1.0) is False
    assert [s.probability for s in untouched] == [0.30, 0.40, 0.30]
