"""
domains/supply/oni_monitor.py
ONI (Oceanic Niño Index) 监测器 — thresholds externalized to config/regimes.yaml
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor
from core.regime_config import get_regime_loader

if TYPE_CHECKING:
    pass


class ONIMonitor(BaseMonitor):
    """
    NOAA ONI 指数监测器
    thresholds 从 config/regimes.yaml 读取，不再硬编码

    Sherlock 等价:
      ONI index value       → Sherlock username
      EL_NINO_THRESHOLD     → Sherlock errorCode (HTTP status)
      EL_NINO_CONFIRMED     → Sherlock QueryStatus.CLAIMED
    """

    ONI_URL = "https://origin.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php"

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})

        # Sherlock 等价: self._site_data = {site.name: site.information}
        self._loader = get_regime_loader()
        self._loader.load()

        # 历史 ONI 值
        self._oni_history: list[dict] = []
        self._last_published_value: Optional[float] = None

    # Sherlock 等价: get_threshold() — 运行时从 loader 读取阈值
    def _el_nino_threshold(self) -> float:
        r = self._loader.get_regime("EL_NINO_CONFIRMED")
        return r.threshold if r else 0.5

    def _la_nina_threshold(self) -> float:
        r = self._loader.get_regime("LA_NINA_CONFIRMED")
        return r.threshold if r else -0.5

    def _strong_el_nino(self) -> float:
        r = self._loader.get_regime("EL_NINO_CONFIRMED")
        return r.threshold_extreme if r and r.severity_extreme else 1.5

    def _strong_la_nina(self) -> float:
        r = self._loader.get_regime("LA_NINA_CONFIRMED")
        return r.threshold_extreme if r and r.severity_extreme else -1.5

    def _drought_threshold(self) -> float:
        r = self._loader.get_regime("DROUGHT_ONI")
        return r.threshold if r else 1.0

    def fetch_current_oni(self) -> Optional[float]:
        """获取当前 ONI 值"""
        try:
            resp = self.session.get(self.ONI_URL, timeout=15)
            resp.raise_for_status()

            # 解析 HTML 表格
            root = ET.fromstring(resp.text)
            tables = root.findall('.//table')

            for table in tables:
                rows = table.findall('.//tr')
                for row in rows:
                    cells = row.findall('.//td')
                    if len(cells) >= 13:
                        try:
                            year_text = cells[0].text.strip()
                            if not year_text.replace('-', '').isdigit():
                                continue
                            year = int(year_text)

                            # 获取最新一季的 ONI 值 (倒序找最新的非空值)
                            for i in range(12, 3, -1):
                                val_text = cells[i].text.strip()
                                if val_text:
                                    oni_val = float(val_text)
                                    return oni_val
                        except (ValueError, IndexError):
                            continue
            return None

        except Exception as e:
            print(f"[ONI Monitor] Fetch error: {e}")
            return None

    def check_and_publish(self) -> Optional[CoffeeEvent]:
        """
        检查 ONI 值并发布事件
        thresholds 全部从 regimes.yaml 读取，不再硬编码
        """
        oni = self.fetch_current_oni()
        if oni is None:
            return None

        # Sherlock 等价: 等阈值触发后 publish event
        # 这里是 regime detector 模式
        market_data = {"oni_index": {"oni_value": oni}}
        detections = self._loader.detect_all(
            market_data,
            regime_names=["DROUGHT_ONI", "EL_NINO_CONFIRMED", "LA_NINA_CONFIRMED"]
        )

        if not detections:
            return None

        # 取 severity 最高的检测
        best = max(detections, key=lambda d: d["regime"].resolve_severity(d["value"]))
        regime = best["regime"]

        # Sherlock 等价: regime.name → QueryStatus 映射
        event_type_map = {
            "EL_NINO_CONFIRMED": EventType.EL_NINO_CONFIRMED,
            "LA_NINA_CONFIRMED": EventType.LA_NINA_CONFIRMED,
            "DROUGHT_ONI": EventType.ONI_THRESHOLD_CROSS,
        }
        event_type = event_type_map.get(regime.name, EventType.ONI_THRESHOLD_CROSS)

        event = CoffeeEvent(
            event_type=event_type,
            domain=Domain.SUPPLY,
            timestamp=datetime.now(),
            severity=regime.resolve_severity(best["value"]),
            value=best["value"],
            narrative=regime.resolve_narrative(best["value"]),
            source="NOAA ONI",
            metadata={
                "oni_current": oni,
                "regime": regime.name,
                "hedge_action": regime.hedge_action,
            }
        )

        self.bus.publish(event)
        self._last_published_value = oni
        return event
