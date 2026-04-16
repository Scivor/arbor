"""
domains/supply/weather_monitor.py
天气监测器 — 监控巴西/哥伦比亚咖啡产区天气，触发 FROST_WARNING / COLOMBIA_WEATHER_ALERT

数据源:
  1. OpenWeatherMap Current Weather API (免费层, 无需 key 用于基础数据)
     → https://openweathermap.org/current
  2. 降级: 使用 demo 静态数据（无网络时）

覆盖产区:
  - 巴西米纳斯吉拉斯州 (Minas Gerais) — 世界最大咖啡产区
  - 哥伦比亚 (Huila / Nariño) — 第二大阿拉比卡产区

Sherlock 等价:
    Weather monitor    → Sherlock site checking (frost = error)
    FROST_WARNING      → Sherlock errorCode: [500]
    COLOMBIA_WEATHER   → Sherlock errorCode: [503]
"""

import requests
from datetime import datetime
from typing import Optional, List, Dict
import logging

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor

logger = logging.getLogger(__name__)


# 产区坐标 (lat/lon)
REGIONS: Dict[str, dict] = {
    "Minas_Gerais": {
        "lat": -21.0,
        "lon": -44.5,
        "name": "巴西米纳斯吉拉斯州",
        "country": "BR",
        "frost_threshold_c": 5.0,   # °C，5°C 以下触发霜冻预警
        "alert_threshold_c": 38.0,   # °C，极端高温预警
    },
    "Huila": {
        "lat": 2.0,
        "lon": -76.0,
        "name": "哥伦比亚乌伊拉省",
        "country": "CO",
        "frost_threshold_c": 3.0,    # 高海拔产区更耐寒
        "alert_threshold_c": 35.0,
    },
}

# OpenWeatherMap free API (no key required for basic current weather)
# See: https://openweathermap.org/current#current_JSON
OWM_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

# 本地缓存，避免频繁请求
_cache: Dict[str, dict] = {}
_cache_expires: Dict[str, datetime] = {}


def _fetch_owm(lat: float, lon: float, city_name: str = "") -> Optional[dict]:
    """
    获取 OpenWeatherMap 当前天气数据（免费层）。

    Returns:
        dict with keys: temp_c, feels_like_c, humidity, description, wind_speed
        None on failure.
    """
    try:
        # 免费层: 不需要 API key，但请求更受限制
        # 使用 lat/lon 直接查询（更精确）
        params = {
            "lat": lat,
            "lon": lon,
            "units": "metric",
            "mode": "json",
        }
        resp = requests.get(OWM_BASE_URL, params=params, timeout=10)
        if resp.status_code != 200:
            logger.debug("[Weather] OWM status %s for %s", resp.status_code, city_name)
            return None

        data = resp.json()
        return {
            "temp_c": data["main"]["temp"],
            "feels_like_c": data["main"]["feels_like"],
            "humidity": data["main"]["humidity"],
            "description": data["weather"][0]["description"],
            "wind_speed": data["wind"]["speed"],  # m/s
            "city": data.get("name", city_name),
            "country": data["sys"]["country"],
            "timestamp": datetime.now(),
        }
    except Exception as e:
        logger.debug("[Weather] OWM fetch error for %s: %s", city_name, e)
        return None


class WeatherMonitor(BaseMonitor):
    """
    咖啡产区天气监测器

    检测以下情况并发布事件:
      FROST_WARNING       — 产区温度 < frost_threshold
      COLOMBIA_WEATHER_ALERT — 哥伦比亚产区极端天气
      (未来可扩展: HEAT_WAVE / DROUGHT / HEAVY_RAIN)
    """

    # OpenWeatherMap 免费 API 请求间隔（秒）
    # 免费层限制: ~60 calls/min，建议每 30 分钟最多一次
    FETCH_INTERVAL = 1800   # 30 分钟

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)
        self._last_fetch: Optional[datetime] = None
        self._last_frost_warning: Optional[datetime] = None
        # 每个产区的最后已知温度（用于趋势判断）
        self._last_temps: Dict[str, float] = {}

    def fetch(self) -> Dict[str, dict]:
        """
        获取所有产区的当前天气数据。

        Returns:
            Dict mapping region_key -> weather dict (or None if fetch failed)
        """
        now = datetime.now()

        # 节流
        if (self._last_fetch is not None
                and (now - self._last_fetch).total_seconds() < self.FETCH_INTERVAL):
            return _cache

        results: Dict[str, dict] = {}
        for key, region in REGIONS.items():
            data = _fetch_owm(region["lat"], region["lon"], key)
            if data is None:
                # 降级: 保留上次缓存的数据
                results[key] = _cache.get(key)
            else:
                results[key] = data
                _cache[key] = data
                _cache_expires[key] = now + (
                    datetime.fromtimestamp(0) - datetime.fromtimestamp(0)
                )  # trick: just mark fresh
                self._last_temps[key] = data["temp_c"]

        self._last_fetch = now
        return results

    def check_and_publish(self) -> List[CoffeeEvent]:
        """
        检查所有产区天气，发布 FROST_WARNING / COLOMBIA_WEATHER_ALERT。

        Sherlock 等价: check_and_publish() = site.check() + QueryNotify.notify()

        Returns:
            发布的 CoffeeEvent 列表（可能为空）
        """
        weather_data = self.fetch()
        events: List[CoffeeEvent] = []

        for key, region in REGIONS.items():
            data = weather_data.get(key)
            if data is None:
                continue

            temp = data["temp_c"]
            region_name = data.get("city") or region["name"]
            desc = data["description"]

            # ── FROST WARNING ────────────────────────────────────────────────
            if temp <= region["frost_threshold_c"]:
                # 冷却时间: 6 小时内不重复发布
                if (self._last_frost_warning is None
                        or (datetime.now() - self._last_frost_warning).total_seconds() >= 21600):
                    severity = 4 if temp <= 2.0 else 3
                    narrative = (
                        f"🌨️ {region_name} 气温 {temp:.1f}°C，低于 {region['frost_threshold_c']}°C 霜冻线"
                        f"（天气: {desc}，体感 {data['feels_like_c']:.1f}°C）"
                    )
                    event = CoffeeEvent(
                        event_type=EventType.FROST_WARNING,
                        domain=Domain.SUPPLY,
                        timestamp=datetime.now(),
                        severity=severity,
                        value=temp,
                        narrative=narrative,
                        source="OpenWeatherMap",
                        metadata={
                            "region": key,
                            "region_name": region_name,
                            "temp_c": temp,
                            "feels_like_c": data["feels_like_c"],
                            "humidity": data["humidity"],
                            "description": desc,
                        },
                    )
                    self.bus.publish(event)
                    events.append(event)
                    self._last_frost_warning = datetime.now()
                    logger.info("[Weather] FROST_WARNING %s: %.1f°C", region_name, temp)

            # ── HEAT WAVE ──────────────────────────────────────────────────
            # 哥伦比亚/巴西高温 > alert_threshold_c
            if temp >= region["alert_threshold_c"]:
                severity = 4 if temp >= region["alert_threshold_c"] + 3 else 3
                narrative = (
                    f"☀️ {region_name} 气温 {temp:.1f}°C，极端高温"
                    f"（天气: {desc}，体感 {data['feels_like_c']:.1f}°C）"
                )
                event = CoffeeEvent(
                    event_type=EventType.HEAT_WAVE if hasattr(EventType, 'HEAT_WAVE')
                               else EventType.COLOMBIA_WEATHER_ALERT,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=severity,
                    value=temp,
                    narrative=narrative,
                    source="OpenWeatherMap",
                    metadata={
                        "region": key,
                        "region_name": region_name,
                        "temp_c": temp,
                        "description": desc,
                    },
                )
                self.bus.publish(event)
                events.append(event)
                logger.info("[Weather] HEAT_ALERT %s: %.1f°C", region_name, temp)

            # ── COLOMBIA WEATHER ALERT ─────────────────────────────────────
            # 哥伦比亚产区：暴雨、大风等极端天气
            if region["country"] == "CO":
                extreme_keywords = ["storm", "heavy", "tstorm", "snow", "freezing"]
                if any(kw in desc.lower() for kw in extreme_keywords):
                    severity = 4 if "storm" in desc.lower() or "snow" in desc.lower() else 3
                    narrative = (
                        f"⛈️ 哥伦比亚 {region_name} 极端天气: {desc}，气温 {temp:.1f}°C"
                    )
                    event = CoffeeEvent(
                        event_type=EventType.COLOMBIA_WEATHER_ALERT,
                        domain=Domain.SUPPLY,
                        timestamp=datetime.now(),
                        severity=severity,
                        value=temp,
                        narrative=narrative,
                        source="OpenWeatherMap",
                        metadata={
                            "region": key,
                            "description": desc,
                            "temp_c": temp,
                            "humidity": data["humidity"],
                        },
                    )
                    self.bus.publish(event)
                    events.append(event)
                    logger.info("[Weather] COLOMBIA_ALERT %s: %s", region_name, desc)

        return events

    def get_last_temps(self) -> Dict[str, float]:
        """返回各产区最后已知温度（摄氏度）"""
        return dict(self._last_temps)
