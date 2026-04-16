"""
domains/supply/cot_monitor.py
COT (Commitment of Traders) 报告监测器 — thresholds externalized to config/regimes.yaml
"""

import requests
from datetime import datetime
from typing import Optional, List

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor
from core.regime_config import get_regime_loader


class COTMonitor(BaseMonitor):
    """
    COT (Commitment of Traders) 报告监测器
    thresholds 从 config/regimes.yaml 读取，不再硬编码

    Sherlock 等价:
      COT spec net position    → Sherlock username
      threshold above/below    → Sherlock errorType: status_code
      COT_SPECULATIVE_TOP      → Sherlock QueryStatus.CLAIMED
    """

    COT_URL = "https://www.cftc.gov/sites/default/files/dea/cot/archives/201/f_b.txt"

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        self._last_positions: dict = {}

        # Sherlock 等价: self._site_data = {site.name: site.information}
        self._loader = get_regime_loader()
        self._loader.load()

    def fetch_cot_data(self) -> Optional[dict]:
        """获取 COT 数据"""
        try:
            resp = self.session.get(self.COT_URL, timeout=15)
            resp.raise_for_status()

            # 解析 COT 文本格式
            lines = resp.text.split('\n')
            coffee_data = None

            for line in lines:
                if 'COFFEE' in line.upper() or 'COFFEE' in line:
                    parts = line.split(',')
                    if len(parts) >= 8:
                        coffee_data = {
                            'commercial_long': float(parts[3].strip()),
                            'commercial_short': float(parts[4].strip()),
                            'speculative_long': float(parts[5].strip()),
                            'speculative_short': float(parts[6].strip()),
                            'open_interest': float(parts[7].strip()),
                        }
                        break

            if coffee_data:
                # 计算净头寸 (用于阈值检测)
                total = coffee_data['open_interest']
                if total > 0:
                    coffee_data['spec_net_position'] = (
                        coffee_data['speculative_long'] - coffee_data['speculative_short']
                    )
                    coffee_data['comm_net_position'] = (
                        coffee_data['commercial_long'] - coffee_data['commercial_short']
                    )

            return coffee_data

        except Exception as e:
            print(f"[COT Monitor] Fetch error: {e}")
            return None

    def check_and_publish(self) -> List[CoffeeEvent]:
        """检查 COT 数据并发布事件"""
        data = self.fetch_cot_data()
        if not data:
            return []

        events = []

        # Sherlock 等价: 用 market_data + detect_all 而非 if/elif 链
        # 构建 market_data，格式: {source: {field: value}}
        market_data = {
            "cot_report": {
                "spec_net_position": data.get("spec_net_position", 0),
                "commercial_net_position": data.get("comm_net_position", 0),
                "spec_long_pct": data.get("spec_long_pct", 0),
                "spec_short_pct": data.get("spec_short_pct", 0),
            }
        }

        regime_detections = self._loader.detect_all(
            market_data,
            regime_names=[
                "COT_SPECULATIVE_TOP",
                "COT_SPECULATIVE_BOTTOM",
                "COT_COMMERCIAL_BOTTOM",
            ]
        )

        event_type_map = {
            "COT_SPECULATIVE_TOP": EventType.COT_SPECULATIVE_TOP,
            "COT_SPECULATIVE_BOTTOM": EventType.COT_SPECULATIVE_BOTTOM,
            "COT_COMMERCIAL_BOTTOM": EventType.COT_COMMERCIAL_BOTTOM,
        }

        for det in regime_detections:
            regime = det["regime"]
            value = det["value"]
            event_type = event_type_map.get(regime.name, EventType.COT_SPECULATIVE_TOP)

            # 避免重复触发 (Sherlock 的 status tracking)
            pos_key = regime.name.lower()
            if self._last_positions.get(pos_key) == "fired":
                continue

            event = CoffeeEvent(
                event_type=event_type,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=regime.resolve_severity(value),
                value=value,
                narrative=regime.resolve_narrative(value),
                source="CFTC COT",
                metadata={
                    **data,
                    "regime": regime.name,
                    "hedge_action": regime.hedge_action,
                },
            )
            events.append(event)
            self.bus.publish(event)
            self._last_positions[pos_key] = "fired"

        return events
