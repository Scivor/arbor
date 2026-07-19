"""
domains/supply/oni_monitor.py
ONI (Oceanic Niño Index) 监测器 — thresholds externalized to config/regimes.yaml
"""

import requests
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from core.events import EventBus
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

    ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

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
        """获取当前 ONI 值（解析 ASCII 文本，取最新一行 ANOM）"""
        import time
        for attempt in range(3):
            try:
                resp = self.session.get(self.ONI_URL, timeout=(5, 10))
                resp.raise_for_status()
                lines = resp.text.strip().split('\n')
                # 跳过标题行，从末尾找第一个有效数据行
                for line in reversed(lines):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            # SEAS YR TOTAL ANOM
                            anom = float(parts[3])
                            return anom
                        except ValueError:
                            continue
                return None
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[ONI Monitor] Fetch error after 3 retries: {e}")
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
