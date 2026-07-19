"""
tests/test_usda_fas.py
USDA FAS 批量 CSV 数据源 — 无网络（合成 CSV fixture）
"""

import pandas as pd
import pytest

from sources.supply.usda_fas import USDAFASSource

# 合成 CSV：FAS 两字母码 + 长格式 + 多年/多月（验证最新年选择）
_CSV = """Commodity_Code,Commodity_Description,Country_Code,Country_Name,Market_Year,Calendar_Year,Month,Attribute_ID,Attribute_Description,Unit_ID,Unit_Description,Value
0711100,"Coffee, Green",BR,"Brazil",2024,2023,12,001,"Production",02,"(1000 60 KG BAGS)",60000.0
0711100,"Coffee, Green",BR,"Brazil",2025,2025,06,001,"Production",02,"(1000 60 KG BAGS)",63000.0
0711100,"Coffee, Green",BR,"Brazil",2025,2025,06,090,"Exports",02,"(1000 60 KG BAGS)",40750.0
0711100,"Coffee, Green",BR,"Brazil",2025,2025,06,091,"Imports",02,"(1000 60 KG BAGS)",75.0
0711100,"Coffee, Green",BR,"Brazil",2025,2025,06,092,"Domestic Consumption",02,"(1000 60 KG BAGS)",22280.0
0711100,"Coffee, Green",BR,"Brazil",2025,2025,06,093,"Ending Stocks",02,"(1000 60 KG BAGS)",485.0
0711100,"Coffee, Green",VM,"Vietnam",2025,2025,06,001,"Production",02,"(1000 60 KG BAGS)",31000.0
0711100,"Coffee, Green",VM,"Vietnam",2025,2025,06,090,"Exports",02,"(1000 60 KG BAGS)",25000.0
0711100,"Coffee, Green",VM,"Vietnam",2025,2025,06,091,"Imports",02,"(1000 60 KG BAGS)",0.0
0711100,"Coffee, Green",VM,"Vietnam",2025,2025,06,092,"Domestic Consumption",02,"(1000 60 KG BAGS)",3500.0
0711100,"Coffee, Green",VM,"Vietnam",2025,2025,06,093,"Ending Stocks",02,"(1000 60 KG BAGS)",1200.0
"""


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(
        USDAFASSource, "_load_df",
        lambda self: pd.read_csv(__import__("io").StringIO(_CSV)),
    )
    return USDAFASSource(cache_dir=str(tmp_path))


def test_fetch_country_latest_year_and_mapping(source):
    d = source.fetch_country("BRA")
    assert d is not None
    assert d.country == "BRA"
    assert d.market_year == "2025"          # 最新年（2024 被跳过）
    assert d.production == 63000.0
    assert d.exports == 40750.0
    assert d.imports == 75.0
    assert d.consumption == 22280.0
    assert d.ending_stocks == 485.0


def test_fetch_country_specific_year(source):
    d = source.fetch_country("BRA", year="2024")
    assert d is not None
    assert d.market_year == "2024"
    assert d.production == 60000.0


def test_fetch_country_unknown_iso(source):
    assert source.fetch_country("XXX") is None


def test_fetch_all(source):
    results = source.fetch_all()
    countries = {d.country for d in results}
    assert countries == {"BRA", "VNM"}     # 其余国家无数据 → 跳过
    assert all(d.production > 0 for d in results)


def test_check_and_publish_detects_production_change(source):
    # 先种一份旧年缓存（同市场年，产量不同 → 触发变更事件）
    from core.types.market import USDACoffeeData
    from datetime import datetime as dt
    old = USDACoffeeData(
        country="BRA", commodity="Coffee, Green", market_year="2025",
        production=59000.0, exports=0, imports=0, consumption=0,
        ending_stocks=0, timestamp=dt.now(),
    )
    source._save_cache(old)

    events = source.check_and_publish()
    assert len(events) == 1
    e = events[0]
    assert "上调" in e.narrative and "BRA" in e.narrative
    assert e.severity >= 1
