"""
tests/test_new_sources.py
ICO I-CIP 现货 + 广期所咖啡（脚手架）数据源 — 无网络
"""

from types import SimpleNamespace

import pandas as pd
import pytest

from core.cost.landed_cost import LandedCostCalculator
from reports.demo_data import demo_report
from reports.exporters.html_to_pdf import build_report_html
from reports.exporters.markdown_exporter import export_markdown
from reports.models import ChinaImportSnapshot
from sources.coffee.gfex_coffee import GFEXCoffeeSource, compute_spread
from sources.coffee.ico_spot import ICOSpotSource


# ── ICO I-CIP 现货 ────────────────────────────────────────────────────────────

_ICO_TEXT = """ICO Indicator Prices - July 2026 (I-CIP)

14-Jul 288.00 380.00 350.00 320.00 185.00
15-Jul 287.00 381.00 351.00 321.00 186.00

16-Jul 286.87 382.66 352.91 321.88 186.27

17-Jul
18-Jul
Average 290.60 383.00 353.00 322.00 186.50
DoD Change -2.3% 0.5% 0.4% 0.3% -0.1%
"""


class _FakePDF:
    """假 pdfplumber.open 返回对象（context manager，单页）"""

    def __init__(self, text):
        self.pages = [SimpleNamespace(extract_text=lambda: text)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def ico_env(tmp_path, monkeypatch):
    """缓存命中（新鲜 tmp 文件）+ 假 pdfplumber，全程无网络"""
    cache = tmp_path / "icip.pdf"
    cache.write_bytes(b"%PDF-fake")
    monkeypatch.setattr("sources.coffee.ico_spot._CACHE_PATH", cache)
    return cache


def test_ico_fetch_latest_day(ico_env, monkeypatch):
    monkeypatch.setattr("pdfplumber.open", lambda src: _FakePDF(_ICO_TEXT))
    out = ICOSpotSource().fetch()
    assert out["date"] == "16-Jul"          # 最后一个非空日行（未来日期空行跳过）
    assert out["icip"] == 286.87
    assert out["colombian_milds"] == 382.66
    assert out["robustas"] == 186.27
    assert out["month_avg"] == 290.60
    assert out["dod_change_pct"] == -2.3
    assert out["source"] == "ICO I-CIP"


def test_ico_fetch_empty_text_raises(ico_env, monkeypatch):
    monkeypatch.setattr("pdfplumber.open", lambda src: _FakePDF("   "))
    with pytest.raises(RuntimeError, match="文本提取为空"):
        ICOSpotSource().fetch()


def test_ico_parse_no_day_raises():
    with pytest.raises(RuntimeError, match="未解析到任何日行"):
        ICOSpotSource._parse("header only\nno data lines")


# ── GFEX 脚手架 ───────────────────────────────────────────────────────────────

def _contracts_df(with_coffee: bool) -> pd.DataFrame:
    rows = {"品种": ["螺纹钢", "鸡蛋"], "合约代码": ["RB2609", "JD2609"]}
    if with_coffee:
        rows["品种"].append("咖啡")
        rows["合约代码"].append("CF2609")
    return pd.DataFrame(rows)


def test_gfex_is_available(monkeypatch):
    monkeypatch.setattr(GFEXCoffeeSource, "_contracts",
                        lambda self: _contracts_df(with_coffee=True))
    assert GFEXCoffeeSource().is_available() is True

    monkeypatch.setattr(GFEXCoffeeSource, "_contracts",
                        lambda self: _contracts_df(with_coffee=False))
    assert GFEXCoffeeSource().is_available() is False


def test_gfex_fetch_unavailable_raises(monkeypatch):
    monkeypatch.setattr(GFEXCoffeeSource, "_contracts",
                        lambda self: _contracts_df(with_coffee=False))
    with pytest.raises(RuntimeError, match="尚未上市"):
        GFEXCoffeeSource().fetch()


def test_gfex_contracts_failure_is_not_available(monkeypatch):
    def _boom(self):
        raise ConnectionError("akshare down")
    monkeypatch.setattr(GFEXCoffeeSource, "_contracts", _boom)
    assert GFEXCoffeeSource().is_available() is False


def test_compute_spread_anchor():
    # KC=F 300¢/lb, fx 7.2 → 300 × 22.0462 × 7.2 = 47619.79 元/吨
    out = compute_spread(gfex_close=48000.0, kc_cents_lb=300.0, fx_rate=7.2)
    assert out["kc_cny_mt"] == pytest.approx(47619.79, abs=0.01)
    assert out["spread_cny_mt"] == pytest.approx(48000.0 - 47619.79, abs=0.01)
    assert out["spread_pct"] == pytest.approx((48000.0 - 47619.79) / 47619.79, abs=1e-3)
    assert out["gfex_close"] == 48000.0


# ── 报告集成（三展示面）──────────────────────────────────────────────────────

_ICO = {"date": "16-Jul", "icip": 286.87, "month_avg": 290.60, "dod_change_pct": -2.3,
        "colombian_milds": 382.66, "other_milds": 352.91,
        "brazilian_naturals": 321.88, "robustas": 186.27, "source": "ICO I-CIP"}
_GFEX = {"contract": "CF2609", "close": 48000.0, "date": "2026-07-16",
         "spread_cny_mt": 380.21, "spread_pct": 0.008, "kc_cny_mt": 47619.79,
         "source": "GFEX/akshare"}


def _report_with_ico_gfex(ico=None, gfex=None):
    landed = LandedCostCalculator().calculate(285.0, 7.25, 0.75)
    report = demo_report()
    report.china_import = ChinaImportSnapshot(
        fx_rate=7.25, fx_source="Yahoo Finance", landed=landed,
        ico_spot=ico, gfex=gfex,
    )
    return report


def test_ico_gfex_rendered_everywhere():
    report = _report_with_ico_gfex(ico=_ICO, gfex=_GFEX)
    text = report.to_text()
    assert "ICO 现货" in text and "286.87" in text
    assert "广期所咖啡" in text and "48000" in text

    html = build_report_html(report, lang="zh")
    assert "ICO 综合现货 286.87 ¢/lb（月均 290.60，日变动 -2.3%）" in html
    assert "广期所咖啡 48000 元/吨" in html
    assert "内外盘价差" in html

    md = export_markdown(report)
    assert "ICO 综合现货 286.87 ¢/lb" in md
    assert "广期所咖啡 48000 元/吨" in md


def test_ico_gfex_none_hidden():
    report = _report_with_ico_gfex(ico=None, gfex=None)
    assert "ICO 现货" not in report.to_text()
    assert "广期所咖啡" not in report.to_text()
    html = build_report_html(report, lang="zh")
    assert "ICO 综合现货" not in html
    assert "广期所咖啡" not in html
    md = export_markdown(report)
    assert "ICO 综合现货" not in md
    assert "广期所咖啡" not in md
