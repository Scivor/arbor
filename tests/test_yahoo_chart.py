"""Yahoo chart client — no network."""

import pytest

from sources.yahoo_chart import fetch_chart, fetch_chart_or_none, prior_close


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Resp(self.payload)


def _chart(closes):
    return {
        "chart": {
            "result": [{
                "indicators": {"quote": [{"close": closes}]},
            }],
        },
    }


@pytest.mark.unit
def test_fetch_chart_returns_first_result_and_prior_close():
    session = _Session(_chart([1.0, 0, None, 2.5, 3.0]))
    chart = fetch_chart(session, "KC=F", interval="1d", range_="5d")
    assert chart["indicators"]["quote"][0]["close"][0] == 1.0
    assert prior_close(chart) == 2.5
    assert session.calls[0][0].endswith("/KC=F")
    assert session.calls[0][1]["params"] == {"interval": "1d", "range": "5d"}


@pytest.mark.unit
def test_fetch_chart_empty_payload_is_none():
    session = _Session({"chart": {"result": []}})
    assert fetch_chart(session, "USDCNY=X") is None


@pytest.mark.unit
def test_fetch_chart_or_none_swallows_transport_errors(capsys, monkeypatch):
    monkeypatch.setattr("sources.http_util.time.sleep", lambda *_a, **_k: None)

    class Boom:
        def get(self, url, **kwargs):
            raise RuntimeError("offline")

    assert fetch_chart_or_none(Boom(), "KC=F", label="PriceSource") is None
    out = capsys.readouterr().out
    assert "PriceSource" in out
    assert "offline" in out
