"""
tests/test_scoring_config.py
regimes.yaml 的 scoring 块与 cluster / half_life_days 字段解析。
"""

import textwrap

from core.regime_config import RegimeConfigLoader
from core.state.scoring import ScoringConfig
from core.types.enums import EventType


def _write(tmp_path, body: str):
    p = tmp_path / "regimes.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_parses_cluster_and_half_life(tmp_path):
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules:
          FROST_WARNING:
            adjustment: 0.20
            min_severity: 3
            cluster: brazil_supply
            half_life_days: 90
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    rule = loader.get_adjustment_rule("FROST_WARNING")
    assert rule.cluster == "brazil_supply"
    assert rule.half_life_days == 90.0


def test_missing_cluster_falls_back_to_misc(tmp_path):
    """旧 YAML 无 cluster 字段时不炸，落到 misc 簇。"""
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules:
          FROST_WARNING:
            adjustment: 0.20
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    rule = loader.get_adjustment_rule("FROST_WARNING")
    assert rule.cluster == "misc"
    assert rule.half_life_days == 30.0


def test_scoring_block_parsed(tmp_path):
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules: {}
        scoring:
          baseline: 0.60
          span_up: 0.25
          span_down: 0.40
          tanh_k: 0.7
          rank_decay: 0.4
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    cfg = loader.scoring
    assert cfg == ScoringConfig(baseline=0.60, span_up=0.25,
                                span_down=0.40, tanh_k=0.7, rank_decay=0.4)


def test_scoring_block_absent_uses_defaults(tmp_path):
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules: {}
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    assert loader.scoring == ScoringConfig()


def test_event_rules_maps_to_enum(tmp_path):
    """event_rules() 产出 scoring.py 直接可用的 dict，跳过非 EventType 的键。"""
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules:
          FROST_WARNING:
            adjustment: 0.20
            min_severity: 3
            cluster: brazil_supply
            half_life_days: 90
          DROUGHT_ONI:
            adjustment: 0.15
            cluster: climate
            half_life_days: 180
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    rules = loader.event_rules()
    assert EventType.FROST_WARNING in rules
    assert rules[EventType.FROST_WARNING].cluster == "brazil_supply"
    assert rules[EventType.FROST_WARNING].half_life_days == 90.0
    # DROUGHT_ONI 是 regime 名而非 EventType 成员 —— 静默跳过
    assert len(rules) == 1
