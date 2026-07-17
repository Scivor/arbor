"""
tests/test_ice_inventory_source.py
ICE 咖啡库存数据源单元测试
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from core.events import reset_event_bus
from core.types.enums import Domain, EventType
from sources.inventory.ice_inventory import InventorySource, ManualICESource


@pytest.fixture
def sample_csv():
    """提供一份示例 CSV 文件路径，并在测试后清理"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "certified", "pending"])
        writer.writerow(["2026-07-01", 450, 50])
        writer.writerow(["2026-07-07", 380, 40])
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.mark.unit
def test_fetch_reads_latest_row_from_csv(sample_csv):
    src = InventorySource(file_path=sample_csv)
    data = src.fetch()
    assert data is not None
    assert data.certified == 380.0
    assert data.pending == 40.0
    assert data.total == 420.0
    assert data.report_date == "2026-07-07"


@pytest.mark.unit
def test_is_available_when_file_exists(sample_csv):
    src = InventorySource(file_path=sample_csv)
    assert src.is_available() is True


@pytest.mark.unit
def test_is_available_when_manual_data_set():
    src = InventorySource(file_path="/nonexistent/ice_inventory.csv")
    assert src.is_available() is False
    src.set_inventory(500)
    assert src.is_available() is True


@pytest.mark.unit
def test_manual_ice_source_wraps_inventory_source():
    src = ManualICESource(file_path="/nonexistent/ice_inventory.csv")
    src.set_inventory(550, pending=50, report_date="2026-04-04")
    data = src.fetch()
    assert data is not None
    assert data.certified == 550.0
    assert data.pending == 50.0


@pytest.mark.unit
def test_critical_inventory_event(sample_csv):
    reset_event_bus()
    with open(sample_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "certified", "pending"])
        writer.writerow(["2026-07-07", 150, 10])  # < 200 万包

    src = InventorySource(file_path=sample_csv)
    events = src.check_and_publish()

    assert any(e.event_type == EventType.ICE_INVENTORY_CRITICAL for e in events)
    assert all(e.domain == Domain.SUPPLY for e in events)


@pytest.mark.unit
def test_low_inventory_event(sample_csv):
    reset_event_bus()
    with open(sample_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "certified", "pending"])
        writer.writerow(["2026-07-07", 350, 10])  # 200–400 万包之间

    src = InventorySource(file_path=sample_csv)
    events = src.check_and_publish()

    assert any(e.event_type == EventType.ICE_INVENTORY_DROP for e in events)
    assert not any(e.event_type == EventType.ICE_INVENTORY_CRITICAL for e in events)


@pytest.mark.unit
def test_inventory_spike_event(sample_csv):
    reset_event_bus()
    with open(sample_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "certified", "pending"])
        writer.writerow(["2026-06-30", 100, 10])
        writer.writerow(["2026-07-07", 500, 10])  # 单周飙升 400%

    src = InventorySource(file_path=sample_csv)
    events = src.check_and_publish()

    assert any(e.event_type == EventType.ICE_INVENTORY_SPIKE for e in events)
