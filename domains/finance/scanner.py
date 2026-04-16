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


@dataclass
class PriceData:
    """价格数据"""
    current: float
    open: float
    high_30d: float
    low_30d: float
    change_1d_pct: float
    change_30d_pct: float


@dataclass
class FXData:
    """汇率数据"""
    usd_cny: float
    usd_cny_change_pct: float
    eur_usd: float


class FinanceDomainScanner(BaseDomainScanner):
    """
    金融域总扫描器
    thresholds 从 config/regimes.yaml 读取，不再硬编码

    Sherlock 等价设计:
      Sherlock 硬编码 site detection 逻辑在 sherlock.py
      → FinanceDomainScanner 的阈值从 regimes.yaml 读取

      Sherlock sites = SitesInformation() + site_data_all = {site.name: site.information}
      → loader = get_regime_loader(); regimes = loader.regimes

      Sherlock errorMsg/errorType/errorCode 全部在 data.json
      → FinanceDomainScanner 的 threshold/condition/source 全部在 regimes.yaml
    """

    # ============================================================
    # Sherlock 等价: 硬编码回退默认值 (regimes.yaml 不可用时)
    # ============================================================
    _DEFAULT_PRICE_SHOCK_THRESHOLD = 0.05
    _DEFAULT_PRICE_EXTREME_THRESHOLD = 0.20
    _DEFAULT_FX_SHOCK_THRESHOLD = 0.02

    def __init__(self, bus: Optional[EventBus] = None, scan_interval: int = 300):
        super().__init__(bus=bus, scan_interval=scan_interval)
        from domains.finance.polymarket_client import PolymarketClient

        self.poly = PolymarketClient()

        # Sherlock 等价: self._site_data = {site.name: site.information}
        #                if args.site_list: site_data = {k:v for k,v in ... if k in args.site_list}
        self._loader = get_regime_loader()
        self._loader.load()
        self._finance_regimes = self._loader.get_regimes_by_domain("FINANCE")

        # 历史数据
        self._last_price: Optional[float] = None
        self._price_30d: list[float] = []
        self._last_fx: Optional[float] = None

    # ============================================================
    # Sherlock 等价: get_threshold() — 运行时从 loader 读取阈值
    # ============================================================

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
        """获取 KC=F 价格"""
        try:
            import yfinance as yf
            ticker = yf.Ticker("KCN26.NYB")  # 正确: ICE 官方合约
            data = ticker.history(period="1d")
            if not data.empty:
                return float(data['Close'].iloc[-1])
        except ImportError:
            print("[Finance] yfinance not installed, skipping live price")
        except Exception as e:
            print(f"[Finance] Price fetch error: {e}")
        return None

    def _fetch_fx(self) -> Optional[FXData]:
        """获取汇率数据"""
        try:
            import yfinance as yf
            ticker = yf.Ticker("CNY=X")
            data = ticker.history(period="1d")
            if not data.empty:
                usd_cny = float(data['Close'].iloc[-1])
                if len(data) >= 2:
                    prev = float(data['Close'].iloc[-2])
                    change = (usd_cny - prev) / prev
                else:
                    change = 0.0

                ticker2 = yf.Ticker("EUR=X")
                data2 = ticker2.history(period="1d")
                eur_usd = float(data2['Close'].iloc[-1]) if not data2.empty else 1.09

                return FXData(
                    usd_cny=usd_cny,
                    usd_cny_change_pct=change,
                    eur_usd=eur_usd,
                )
        except ImportError:
            print("[Finance] yfinance not installed, skipping FX")
        except Exception as e:
            print(f"[Finance] FX fetch error: {e}")
        return None

    def _build_market_data(self, price: float, fx: Optional[FXData]) -> dict:
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

    def check_polymarket_and_publish(self) -> List[CoffeeEvent]:
        """
        检查 Polymarket 并发布事件
        委托给 PolymarketMonitor 处理，金融域扫描器不再直接实现逻辑
        """
        from domains.finance.polymarket_monitor import PolymarketMonitor
        monitor = PolymarketMonitor(bus=self.bus)
        return monitor.check_and_publish()

    def scan_all(self) -> List[CoffeeEvent]:
        """执行所有金融域检查"""
        events = []

        events.extend(self.check_price_and_publish())
        events.extend(self.check_fx_and_publish())
        events.extend(self.check_polymarket_and_publish())

        return events

    def print_polymarket_summary(self):
        """打印 Polymarket 当前信号摘要"""
        try:
            signals = self.poly.get_relevant_signals()
        except Exception as e:
            print(f"[Polymarket] Error: {e}")
            return

        print(f"\n{'='*65}")
        print(f"  Polymarket 相关信号 ({len(signals)} 个市场)")
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
