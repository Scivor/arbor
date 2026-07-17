"""
domains/finance/scanner.py
金融域总扫描器 — thresholds now externalized to config/regimes.yaml
"""

from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseDomainScanner

# Sherlock 风格: 配置优先，回退次之
from core.regime_config import get_regime_loader
from sources.coffee.yfinance_price import PriceSource
from sources.fx.yfinance import FXSource


class FinanceDomainScanner(BaseDomainScanner):
    """
    金融域总扫描器
    thresholds 从 config/regimes.yaml 读取，不再硬编码
    价格/汇率数据源: sources.coffee.yfinance_price (直接 Yahoo chart API)
    """

    _DEFAULT_PRICE_SHOCK_THRESHOLD = 0.05
    _DEFAULT_PRICE_EXTREME_THRESHOLD = 0.20
    _DEFAULT_FX_SHOCK_THRESHOLD = 0.02

    def __init__(self, bus: Optional[EventBus] = None, scan_interval: int = 300):
        super().__init__(bus=bus, scan_interval=scan_interval)


        # 使用项目内置 PriceSource / FXSource（直接调 Yahoo chart API，比 yfinance 稳定）
        self._price_src = PriceSource()
        self._fx_src = FXSource()

        self._loader = get_regime_loader()
        self._loader.load()
        self._finance_regimes = self._loader.get_regimes_by_domain("FINANCE")

        # 历史数据
        self._last_price: Optional[float] = None
        self._price_30d: list[float] = []
        self._last_fx: Optional[float] = None

    def _price_shock_threshold(self) -> float:
        r = self._finance_regimes.get("PRICE_SHOCK_UP")
        return abs(r.threshold) if r else self._DEFAULT_PRICE_SHOCK_THRESHOLD

    def _price_extreme_threshold(self) -> float:
        r = self._finance_regimes.get("PRICE_30D_EXTREME_UP")
        return abs(r.threshold) if r else self._DEFAULT_PRICE_EXTREME_THRESHOLD

    def _fx_shock_threshold(self) -> float:
        r = self._finance_regimes.get("FX_USD_CNY_SHOCK")
        return abs(r.threshold) if r else self._DEFAULT_FX_SHOCK_THRESHOLD

    def _fetch_kc_price(self) -> Optional[float]:
        """获取 KC=F 价格 — 通过 PriceSource"""
        data = self._price_src.fetch()
        return data.current if data else None

    def _fetch_fx(self) -> Optional["FXData"]:
        """获取汇率数据 — 通过 FXSource"""
        data = self._fx_src.fetch()
        if data is None:
            return None
        # 映射到本地 FXData 格式
        from dataclasses import dataclass
        @dataclass
        class _FXData:
            usd_cny: float
            usd_cny_change_pct: float
            eur_usd: float
        return _FXData(
            usd_cny=data.rate,
            usd_cny_change_pct=data.change_pct,
            eur_usd=1.09,  # FXSource 不提供 EUR/USD，保持默认
        )

    def _build_market_data(self, price: float, fx=None) -> dict:
        """构建 market_data dict 用于 regime 检测"""
        data = {
            "kc_price": {
                "change_1d_pct": 0.0,
                "change_30d_pct": 0.0,
            }
        }

        if self._last_price is not None:
            data["kc_price"]["change_1d_pct"] = (price - self._last_price) / self._last_price

        if len(self._price_30d) >= 2:
            data["kc_price"]["change_30d_pct"] = (price - self._price_30d[0]) / self._price_30d[0]

        if fx:
            data["fx_rate"] = {"change_pct": abs(fx.usd_cny_change_pct)}
        else:
            data["fx_rate"] = {"change_pct": 0.0}

        return data

    def check_price_and_publish(self) -> List[CoffeeEvent]:
        """检查价格变动并发布事件"""
        events = []

        price = self._fetch_kc_price()
        if price is None:
            return events

        # 记录历史
        self._price_30d.append(price)
        if len(self._price_30d) > 30:
            self._price_30d = self._price_30d[-30:]

        if self._last_price is None:
            self._last_price = price
            return events

        # Sherlock 等价: 对 market_data 运行 detect_all，而不是 if/elif 链
        change_1d = (price - self._last_price) / self._last_price

        if len(self._price_30d) >= 2:
            change_30d = (price - self._price_30d[0]) / self._price_30d[0]
        else:
            change_30d = 0.0

        # 构建 market_data 供 regime detector 使用
        market_data = self._build_market_data(price, None)

        # Sherlock 等价: market_data 等价于 Sherlock 的 r.text
        # Sherlock 根据 errorType (message/status_code/response_url) 判断
        # 这里 regime detector 根据 detect_type (threshold/pattern/cross) 判断
        regime_detections = self._loader.detect_all(
            market_data,
            regime_names=["PRICE_SHOCK_UP", "PRICE_SHOCK_DOWN",
                          "PRICE_30D_EXTREME_UP", "PRICE_30D_EXTREME_DOWN"]
        )

        for det in regime_detections:
            regime = det["regime"]
            value = det["value"]

            # 确定 event_type
            if regime.name == "PRICE_SHOCK_UP":
                event_type = EventType.PRICE_SHOCK_UP
            elif regime.name == "PRICE_SHOCK_DOWN":
                event_type = EventType.PRICE_SHOCK_DOWN
            elif regime.name == "PRICE_30D_EXTREME_UP":
                event_type = EventType.PRICE_30D_EXTREME_UP
            elif regime.name == "PRICE_30D_EXTREME_DOWN":
                event_type = EventType.PRICE_30D_EXTREME_DOWN
            else:
                continue

            # 计算方向乘数 (PRICE_SHOCK_DOWN 阈值是负数)
            sign = 1 if value > 0 else -1
            severity = regime.resolve_severity(abs(value)) * sign
            severity = abs(severity)

            event = CoffeeEvent(
                event_type=event_type,
                domain=Domain.FINANCE,
                timestamp=datetime.now(),
                severity=severity,
                value=price,
                narrative=regime.resolve_narrative(value),
                source="ICE/KCN26.NYB",
                metadata={
                    "change_1d": change_1d,
                    "change_30d": change_30d,
                    "regime": regime.name,
                }
            )
            events.append(event)
            self.bus.publish(event)

        self._last_price = price
        return events

    def check_fx_and_publish(self) -> List[CoffeeEvent]:
        """检查汇率变动并发布事件"""
        events = []

        fx_data = self._fetch_fx()
        if fx_data is None:
            return events

        market_data = {
            "fx_rate": {"change_pct": abs(fx_data.usd_cny_change_pct)}
        }

        regime_detections = self._loader.detect_all(
            market_data,
            regime_names=["FX_USD_CNY_SHOCK"]
        )

        if self._last_fx is not None:
            fx_change = abs(fx_data.usd_cny - self._last_fx) / self._last_fx

            for det in regime_detections:
                regime = det["regime"]
                value = det["value"]

                severity = regime.resolve_severity(value)

                event = CoffeeEvent(
                    event_type=EventType.FX_USD_CNY_SHOCK,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=severity,
                    value=fx_data.usd_cny,
                    narrative=regime.resolve_narrative(value),
                    source="Forex",
                    metadata={
                        "usd_cny": fx_data.usd_cny,
                        "change": fx_change,
                        "regime": regime.name,
                    },
                )
                events.append(event)
                self.bus.publish(event)

        self._last_fx = fx_data.usd_cny
        return events

        """
        """
        return monitor.check_and_publish()

    def scan_all(self) -> List[CoffeeEvent]:
        """执行所有金融域检查"""
        events = []

        events.extend(self.check_price_and_publish())
        events.extend(self.check_fx_and_publish())

        return events

        try:
            signals = self.poly.get_relevant_signals()
        except Exception as e:
            return

        print(f"\n{'='*65}")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*65}")

        climate = {k: v for k, v in signals.items()
                  if any(kw in k.lower() for kw in ['el nino', 'la nina', 'weather', 'temperature'])}
        trade = {k: v for k, v in signals.items()
                if any(kw in k.lower() for kw in ['tariff', 'trade', 'china', 'visit'])}
        oil = {k: v for k, v in signals.items()
              if any(kw in k.lower() for kw in ['wti', 'crude', 'oil', 'hormuz', 'middle east'])}
        fx = {k: v for k, v in signals.items()
              if any(kw in k.lower() for kw in ['dollar', 'usd', 'forex', 'federal reserve', 'fed rate'])}

        if climate:
            print(f"\n  [气候] ({len(climate)} 个市场)")
            for q, d in climate.items():
                print(f"    {q[:55]}")
                print(f"      概率: {d['prob']:.1%}  |  量: {d['volume']:,.0f}")
        if trade:
            print(f"\n  [贸易] ({len(trade)} 个市场)")
            for q, d in trade.items():
                print(f"    {q[:55]}")
                print(f"      概率: {d['prob']:.1%}  |  量: {d['volume']:,.0f}")
        if oil:
            print(f"\n  [油价/中东] ({len(oil)} 个市场)")
            for q, d in oil.items():
                print(f"    {q[:55]}")
                print(f"      概率: {d['prob']:.1%}  |  量: {d['volume']:,.0f}")
        if fx:
            print(f"\n  [外汇/美联储] ({len(fx)} 个市场)")
            for q, d in fx.items():
                print(f"    {q[:55]}")
                print(f"      概率: {d['prob']:.1%}  |  量: {d['volume']:,.0f}")

        print(f"\n{'='*65}")
