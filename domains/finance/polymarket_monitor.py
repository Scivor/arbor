"""
domains/finance/polymarket_monitor.py
Polymarket 预测市场独立监测器

独立运行，监控与咖啡/宏观相关的预测市场概率
独立于 FinanceDomainScanner，可单独调度

数据源: gamma-api.polymarket.com (CLOB API)

已发现的关键 API 行为 (2026-04-10):
  - outcomePrices 字段: 可能是 JSON 字符串或 Python list，需 json.loads() 解析
  - 存储路径: /Users/duncan/coffee_v3/.swarm/runs/
  - 频率限制: 建议 5 分钟一次
"""

from datetime import datetime
from typing import Optional, List, Dict
import logging

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor
from domains.finance.polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)


class PolymarketMonitor(BaseMonitor):
    """
    Polymarket 预测市场独立监测器

    检测以下市场信号并发布对应 CoffeeEvent:
      POLY_CLIMATE_HOT       — 气候相关 (El Nino / La Nina / 高温概率 ≥ 70%)
      POLY_CLIMATE_COLD       — 低温/La Nina 概率
      POLY_TRADE_WAR_ESCALATE — 关税/贸易战风险升级
      POLY_TRADE_WAR_DEESCALATE — 贸易战缓和
      POLY_FX_VOLATILE        — 外汇波动率上升
      POLY_HORMUZ_NORMAL      — 霍尔木兹海峡正常化
      POLY_TRUMP_VISIT_CHINA  — 特朗普访华概率高
      WTI_OIL_SHOCK           — 油价冲击 (通过咖啡物流成本传导)
      CHINA_VISIT_CONFIRMED   — 特朗普访华确认

    冷却策略: 同一事件类型 24 小时内不重复发布 (cooldown=86400s)
    """

    # 扫描间隔 (秒) — Polymarket API 建议不超过每分钟一次
    SCAN_INTERVAL = 300  # 5 分钟

    # 概率阈值
    _PROB_CLIMATE_THRESHOLD = 0.70
    _PROB_TRADE_WAR_THRESHOLD = 0.60
    _PROB_TRUMP_VISIT_THRESHOLD = 0.70
    _PROB_OIL_THRESHOLD = 0.30
    _PROB_HORMUZ_NORMAL_THRESHOLD = 0.30

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)
        self._client = PolymarketClient()
        # 冷却追踪: event_type -> last_published_time
        self._cooldown: Dict[str, datetime] = {}
        self._cooldown_seconds = 86400  # 24 小时

    def _is_cooldown(self, event_type: EventType) -> bool:
        """检查事件类型是否在冷却中"""
        last = self._cooldown.get(event_type.value)
        if last is None:
            return False
        return (datetime.now() - last).total_seconds() < self._cooldown_seconds

    def _mark_published(self, event_type: EventType):
        """标记事件已发布"""
        self._cooldown[event_type.value] = datetime.now()

    def check_and_publish(self) -> List[CoffeeEvent]:
        """
        拉取 Polymarket 相关市场信号，发布 CoffeeEvent。

        Returns:
            发布的 CoffeeEvent 列表
        """
        events: List[CoffeeEvent] = []

        try:
            signals = self._client.get_relevant_signals()
        except Exception as e:
            logger.warning("[PolymarketMonitor] Failed to fetch signals: %s", e)
            return events

        # ── 1. 气候信号 ────────────────────────────────────────────────────────
        climate_kws = ['el nino', 'la nina', 'weather', 'temperature']
        for question, data in signals.items():
            prob = data.get('prob')
            if prob is None:
                continue

            q_lower = question.lower()
            if not any(kw in q_lower for kw in climate_kws):
                continue

            # 高温/El Nino 信号
            if prob >= self._PROB_CLIMATE_THRESHOLD:
                if self._is_cooldown(EventType.POLY_CLIMATE_HOT):
                    continue

                severity = 3 if prob >= 0.80 else 2
                narrative = (
                    f"Polymarket: {question[:60]} — {prob:.0%} 概率"
                )
                event = CoffeeEvent(
                    event_type=EventType.POLY_CLIMATE_HOT,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=severity,
                    value=prob,
                    narrative=narrative,
                    source="Polymarket",
                    metadata=data,
                )
                self.bus.publish(event)
                events.append(event)
                self._mark_published(EventType.POLY_CLIMATE_HOT)
                logger.info(
                    "[PolymarketMonitor] POLY_CLIMATE_HOT: %s (%.0f%%)",
                    question[:50], prob * 100
                )

        # ── 2. 贸易战/关税信号 ──────────────────────────────────────────────────
        trade_kws = ['tariff', 'trade war']
        for question, data in signals.items():
            prob = data.get('prob')
            if prob is None:
                continue

            q_lower = question.lower()
            if not any(kw in q_lower for kw in trade_kws):
                continue

            # 特朗普访华 — 使用已有的 POLY_TRUMP_VISIT_CHINA enum
            if ('visit china' in q_lower) or ('trump' in q_lower and 'china' in q_lower):
                if prob >= self._PROB_TRUMP_VISIT_THRESHOLD:
                    if not self._is_cooldown(EventType.POLY_TRUMP_VISIT_CHINA):
                        event = CoffeeEvent(
                            event_type=EventType.POLY_TRUMP_VISIT_CHINA,
                            domain=Domain.FINANCE,
                            timestamp=datetime.now(),
                            severity=2,
                            value=prob,
                            narrative=f"Polymarket: 特朗普访华 {prob:.0%}，贸易关系可能改善",
                            source="Polymarket",
                            metadata=data,
                        )
                        self.bus.publish(event)
                        events.append(event)
                        self._mark_published(EventType.POLY_TRUMP_VISIT_CHINA)

            # 贸易战升级
            if prob >= self._PROB_TRADE_WAR_THRESHOLD:
                if self._is_cooldown(EventType.POLY_TRADE_WAR_ESCALATE):
                    continue

                severity = 3 if prob >= 0.75 else 2
                event = CoffeeEvent(
                    event_type=EventType.POLY_TRADE_WAR_ESCALATE,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=severity,
                    value=prob,
                    narrative=f"Polymarket: {question[:55]} — {prob:.0%}",
                    source="Polymarket",
                    metadata=data,
                )
                self.bus.publish(event)
                events.append(event)
                self._mark_published(EventType.POLY_TRADE_WAR_ESCALATE)

        # ── 3. 霍尔木兹海峡 ────────────────────────────────────────────────────
        for question, data in signals.items():
            prob = data.get('prob')
            if prob is None:
                continue

            q_lower = question.lower()
            if 'hormuz' not in q_lower and 'middle east' not in q_lower:
                continue

            # prob < 0.30 = 正常化概率高
            if prob < (1 - self._PROB_HORMUZ_NORMAL_THRESHOLD):
                if self._is_cooldown(EventType.POLY_HORMUZ_NORMAL):
                    continue

                event = CoffeeEvent(
                    event_type=EventType.POLY_HORMUZ_NORMAL,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=2,
                    value=1 - prob,
                    narrative=f"Polymarket: 霍尔木兹正常化 {prob:.0%}，海运风险降低",
                    source="Polymarket",
                    metadata=data,
                )
                self.bus.publish(event)
                events.append(event)
                self._mark_published(EventType.POLY_HORMUZ_NORMAL)

        # ── 4. 油价冲击 ────────────────────────────────────────────────────────
        oil_kws = ['wti', 'crude oil', 'brent']
        for question, data in signals.items():
            prob = data.get('prob')
            if prob is None:
                continue

            q_lower = question.lower()
            if not any(kw in q_lower for kw in oil_kws):
                continue

            if 'high' in q_lower and prob >= self._PROB_OIL_THRESHOLD:
                if self._is_cooldown(EventType.WTI_OIL_SHOCK):
                    continue

                event = CoffeeEvent(
                    event_type=EventType.WTI_OIL_SHOCK,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=2,
                    value=prob,
                    narrative=f"Polymarket: WTI 油价看涨 {prob:.0%}，关注海运费变动",
                    source="Polymarket",
                    metadata=data,
                )
                self.bus.publish(event)
                events.append(event)
                self._mark_published(EventType.WTI_OIL_SHOCK)

        # ── 5. 外汇波动率 ────────────────────────────────────────────────────────
        fx_kws = ['dollar', 'usd', 'forex', 'federal reserve', 'fed rate', 'inflation']
        for question, data in signals.items():
            prob = data.get('prob')
            if prob is None:
                continue

            q_lower = question.lower()
            if not any(kw in q_lower for kw in fx_kws):
                continue

            if prob >= 0.65:
                if self._is_cooldown(EventType.POLY_FX_VOLATILE):
                    continue

                event = CoffeeEvent(
                    event_type=EventType.POLY_FX_VOLATILE,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=2,
                    value=prob,
                    narrative=f"Polymarket: 外汇波动率上升 {prob:.0%}",
                    source="Polymarket",
                    metadata=data,
                )
                self.bus.publish(event)
                events.append(event)
                self._mark_published(EventType.POLY_FX_VOLATILE)

        return events

    def get_summary(self) -> dict:
        """返回当前 Polymarket 信号摘要（不发布事件）"""
        try:
            signals = self._client.get_relevant_signals()
        except Exception as e:
            return {"error": str(e)}

        categories = {
            "climate": [],
            "trade": [],
            "oil_mideast": [],
            "fx": [],
        }

        climate_kws = ['el nino', 'la nina', 'weather', 'temperature']
        trade_kws = ['tariff', 'trade war']
        oil_kws = ['wti', 'crude oil', 'brent', 'hormuz', 'middle east']
        fx_kws = ['dollar', 'usd', 'forex', 'federal reserve', 'fed rate']

        for q, d in signals.items():
            q_lower = q.lower()
            if any(kw in q_lower for kw in climate_kws):
                categories["climate"].append({"question": q, **d})
            elif any(kw in q_lower for kw in trade_kws):
                categories["trade"].append({"question": q, **d})
            elif any(kw in q_lower for kw in oil_kws):
                categories["oil_mideast"].append({"question": q, **d})
            elif any(kw in q_lower for kw in fx_kws):
                categories["fx"].append({"question": q, **d})

        return categories

    def print_summary(self):
        """打印信号摘要到控制台"""
        summary = self.get_summary()
        if "error" in summary:
            print(f"[PolymarketMonitor] Error: {summary['error']}")
            return

        print(f"\n{'=' * 65}")
        print(f"  Polymarket 信号 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
        print(f"{'=' * 65}")

        for cat, label in [
            ("climate", "气候"),
            ("trade", "贸易战"),
            ("oil_mideast", "油价/中东"),
            ("fx", "外汇"),
        ]:
            items = summary.get(cat, [])
            if not items:
                continue
            print(f"\n  [{label}] ({len(items)} 个市场)")
            for item in items[:5]:  # 最多显示 5 个
                print(f"    {item['question'][:55]}")
                print(f"      概率: {item['prob']:.1%} | 量: {item.get('volume', 0):,.0f}")

        print(f"\n{'=' * 65}")
