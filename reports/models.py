"""
reports/models.py
Core dataclass definitions for coffee futures reports.
"""

from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.cost.landed_cost import LandedCostBreakdown  # noqa: F401

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 方向归一（M2 单一事实源：中英文 → up/flat/down）
# ─────────────────────────────────────────────────────────────────────────────

DIRECTION_MAP = {
    "上涨": "up", "看涨": "up", "BULLISH": "up",
    "下跌": "down", "看跌": "down", "BEARISH": "down",
    "横盘": "flat", "中性": "flat", "NEUTRAL": "flat",
}

# 每个未知方向值只告警一次（模块级去重）
_UNKNOWN_DIRECTIONS: set = set()


def normalize_direction(direction) -> str:
    """
    归一方向标签到 up/flat/down。
    命中 DIRECTION_MAP 返回映射值；未命中返回 "flat" 并 logger.warning
    （同一未知值整个进程只报一次）。
    """
    if direction in DIRECTION_MAP:
        return DIRECTION_MAP[direction]
    if direction not in _UNKNOWN_DIRECTIONS:
        _UNKNOWN_DIRECTIONS.add(direction)
        logger.warning("未知方向标签 %r，按 flat 处理", direction)
    return "flat"


# ─────────────────────────────────────────────────────────────────────────────
# Market & Climate Snapshots
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MarketSnapshot:
    """市场价格快照"""
    ticker: str
    current: float
    change_1d_pct: float
    change_30d_pct: float
    high_30d: float
    low_30d: float
    volume_ratio: float      # vs 20d avg
    ma20: float
    ma60: float
    rsi_14: float
    close_5d: list[float]   # 近5日收盘价
    vol_ratio_5d: list[float]
    close_30d: list[float] = field(default_factory=list)  # 近30日收盘价（用于画图）


@dataclass
class ClimateSnapshot:
    """气候数据快照"""
    oni_value: float
    oni_phase: str           # 'EL_NINO' | 'LA_NINA' | 'NEUTRAL'
    oni_period: str          # e.g. "DJF 2026"
    narrative: str


# ─────────────────────────────────────────────────────────────────────────────
# Price Levels
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Level:
    """价格关键位"""
    price: float
    label: str               # e.g. "强支撑", "阻力", "心理位"
    strength: str             # 'KEY' | 'MEDIUM' | 'WEAK'


# ─────────────────────────────────────────────────────────────────────────────
# Scenario
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Scenario:
    """单种预测情景"""
    label: str               # e.g. "看跌", "中性", "看涨"
    direction: str           # 'BEARISH' | 'NEUTRAL' | 'BULLISH'
    price_min: float
    price_max: float
    probability: float       # 0.0 - 1.0
    rationale: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Driver Params
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SupportParam:
    """支持参数"""
    category: str
    param_name: str
    current_value: str
    signal: str
    weight: str              # 'STRONG' | 'MEDIUM' | 'WEAK'
    narrative: str


@dataclass
class ResistParam:
    """不利参数"""
    category: str
    param_name: str
    current_value: str
    signal: str
    weight: str
    narrative: str


# ─────────────────────────────────────────────────────────────────────────────
# Hedge Advice
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HedgeAdvice:
    """套保建议"""
    ratio: float
    signal: str              # from HedgeSignal enum
    narrative: str
    trigger_above: Optional[float] = None   # 若突破该价位，调整套保
    trigger_below: Optional[float] = None  # 若跌破该价位，调整套保


@dataclass
class MLSnapshot:
    """ML 模型预测快照"""
    signal: str              # 'BULLISH' | 'NEUTRAL' | 'BEARISH'
    confidence: float        # 0.0–1.0
    bias: float              # 建议比率调整量
    price_target_30d: Optional[float] = None
    model_type: str = "ensemble"   # hedge_model | timesfm | ensemble
    rationale: list[str] = field(default_factory=list)
    # 模型表现指标
    model_accuracy: Optional[float] = None   # 分类准确率
    model_mae: Optional[float] = None        # 回归 MAE
    top_features: list[tuple[str, float]] = field(default_factory=list)  # [(特征名, 重要性), ...]


# ─────────────────────────────────────────────────────────────────────────────
# China Import Snapshot
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChinaImportSnapshot:
    """中国进口商视角快照 — 汇率 / 到库成本 / 政策事件"""
    fx_rate: Optional[float] = None      # USD/CNY 即期汇率
    fx_source: str = ""
    landed: Optional["LandedCostBreakdown"] = None  # 到库成本明细（运行时保持本文件零项目内 import，类型经 TYPE_CHECKING 标注）
    policy_events: list[dict] = field(default_factory=list)  # {event_type, severity, narrative, source, timestamp}


# ─────────────────────────────────────────────────────────────────────────────
# Prediction Report
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PredictionReport:
    """
    咖啡期货预测报告
    包含完整的市场快照、驱动因子、情景分析、套保建议
    """

    # 元信息
    ticker: str = "KC=F"
    report_date: date = field(default_factory=date.today)
    forecast_week_start: date = field(default_factory=date.today)
    forecast_week_end: date = field(default_factory=date.today)
    generated_at: datetime = field(default_factory=datetime.now)

    # 市场快照
    market: Optional[MarketSnapshot] = None

    # 关联市场
    related_markets: dict = field(default_factory=dict)  # {name: change_pct}

    # 气候快照
    climate: Optional[ClimateSnapshot] = None

    # 关键价位
    resistance_levels: list[Level] = field(default_factory=list)
    support_levels: list[Level] = field(default_factory=list)

    # 情景
    scenarios: list[Scenario] = field(default_factory=list)

    # 驱动因子
    bullish_params: list[SupportParam] = field(default_factory=list)
    bearish_params: list[ResistParam] = field(default_factory=list)

    # 套保建议
    hedge_advice: Optional[HedgeAdvice] = None

    # ML 预测
    ml_snapshot: Optional[MLSnapshot] = None

    # 中国进口商视角（汇率 + 到库成本 + 政策事件）
    china_import: Optional[ChinaImportSnapshot] = None

    # 参考类基础概率（超级预测 Phase 2：{up, flat, down, n_analogs, years}）
    reference_class: Optional[dict] = None

    # 凯利仓位影子（Phase 3：{edge, suggested_ratio, active, reason}，只读不改 hedge_advice）
    kelly_shadow: Optional[dict] = None

    # 核心观点
    outlook: str = ""        # 一句话总结
    risk_warnings: list[str] = field(default_factory=list)

    # 专业数据源（新增）
    weather_snapshots: list = field(default_factory=list)   # list[WeatherData]
    cme_settlement: Optional[object] = None                 # CMESettlementData
    usda_psd: list = field(default_factory=list)            # list[USDACoffeeData]
    wb_indicators: list = field(default_factory=list)       # list[WorldBankCoffeeData]

    # 数据来源追溯
    provenance: Optional[object] = None  # ReportProvenance instance

    # ─── 格式化输出 ───────────────────────────────────────────────────────────

    def to_text(self) -> str:
        """生成纯文本格式报告（终端友好）"""
        lines = []

        ticker = self.ticker
        report_date = self.report_date.strftime("%Y-%m-%d")
        week_start = self.forecast_week_start.strftime("%b %d")
        week_end = self.forecast_week_end.strftime("%b %d")
        lines.append("")
        lines.append(f"  {'═' * 74}")
        lines.append(f"  {' COFFEE FUTURES WEEKLY OUTLOOK '::^74}")
        lines.append(f"  {'═' * 74}")
        lines.append(f"  {ticker:<20} Report: {report_date}    Forecast: {week_start} – {week_end}")
        lines.append(f"  {'─' * 74}")
        lines.append("")

        # ─── 市场快照 ───────────────────────────────────────────────
        if self.market:
            m = self.market
            change_1d = f"{m.change_1d_pct:+.1f}%" if m.change_1d_pct is not None else "N/A"
            change_30d = f"{m.change_30d_pct:+.1f}%" if m.change_30d_pct is not None else "N/A"
            rsi_sig = "OB" if m.rsi_14 < 35 else "OS" if m.rsi_14 > 65 else "N"
            vol_sig = "↑VOL" if m.volume_ratio > 1.2 else "↓VOL" if m.volume_ratio < 0.8 else ""

            lines.append(f"  {'[ MARKET SNAPSHOT ]':─^74}")
            lines.append(f"  {'Price':>12}: {m.current:>8.2f}  ({change_1d} today, {change_30d} 30d)  RSI:{m.rsi_14:>5.1f} [{rsi_sig}] {vol_sig}")
            lines.append(f"  {'MA20':>12}: {m.ma20:>8.2f}  {'▲ above' if m.current > m.ma20 else '▼ below':8}    30d Range: {m.low_30d:.2f} – {m.high_30d:.2f}")
            lines.append(f"  {'MA60':>12}: {m.ma60:>8.2f}  {'▲ above' if m.current > m.ma60 else '▼ below':8}")
            lines.append("")
            lines.append(f"  {'Recent Closes':>12}:  " + "  ".join(f"{c:>7.2f}" for c in m.close_5d))
            lines.append(f"  {'Volume Ratio':>12}:  " + "  ".join(f"{v:>5.1f}x" for v in m.vol_ratio_5d))
            lines.append("")

        # ─── 关联市场 ───────────────────────────────────────────────
        if self.related_markets:
            lines.append(f"  {'[ RELATED MARKETS ]':─^74}")
            for name, chg in self.related_markets.items():
                sig = "▲" if chg > 0 else "▼" if chg < 0 else "─"
                lines.append(f"  {name:>12}: {sig} {chg:+.1f}%")
            lines.append("")

        # ─── 气候 ───────────────────────────────────────────────────
        if self.climate:
            c = self.climate
            phase_icon = "🔥" if c.oni_value > 0.5 else "❄️" if c.oni_value < -0.5 else "—"
            lines.append(f"  {'[ CLIMATE ]':─^74}")
            lines.append(f"  ONI ({c.oni_period}): {c.oni_value:+.2f}  {c.oni_phase} {phase_icon}")
            lines.append(f"  {c.narrative}")
            lines.append("")

        # ─── 关键价位 ───────────────────────────────────────────────
        if self.resistance_levels or self.support_levels:
            lines.append(f"  {'[ KEY LEVELS ]':─^74}")
            if self.resistance_levels:
                lines.append(f"  {'Resistance':>12}:  " + "  ".join(f"{lvl.price:>7.2f} ({lvl.label})" for lvl in self.resistance_levels))
            if self.support_levels:
                lines.append(f"  {'Support':>12}:  " + "  ".join(f"{lvl.price:>7.2f} ({lvl.label})" for lvl in self.support_levels))
            lines.append("")

        # ─── 情景分析 ───────────────────────────────────────────────
        if self.scenarios:
            lines.append(f"  {'[ SCENARIO ANALYSIS ]':─^74}")
            for s in self.scenarios:
                dir_icon = "🔴" if s.direction == "BEARISH" else "⚪" if s.direction == "NEUTRAL" else "🟢"
                lines.append(f"  {dir_icon} {s.label:6}  {s.price_min:.0f}–{s.price_max:.0f}  {s.probability:>4.0%}  |  {s.rationale[0] if s.rationale else ''}")
            lines.append("")

        # ─── 参考类基础概率 ─────────────────────────────────────────
        if self.reference_class:
            rc = self.reference_class
            thin = "（样本稀薄，仅供参考）" if rc.get("n_analogs", 0) < 20 else ""
            lines.append(
                f"  {'参考类':>12}: 近 {rc.get('years', 5):.0f} 年相似行情 {rc.get('n_analogs', 0)} 周，"
                f"涨 {rc.get('up', 0):.0%} / 横 {rc.get('flat', 0):.0%} / 跌 {rc.get('down', 0):.0%}{thin}"
            )
            lines.append("")

        # ─── 驱动因子 ───────────────────────────────────────────────
        if self.bullish_params or self.bearish_params:
            lines.append(f"  {'[ DRIVERS ]':─^74}")
            if self.bearish_params:
                lines.append(f"  {'Bearish':>12}:")
                for p in self.bearish_params:
                    w = {"STRONG": "▓▓▓", "MEDIUM": "▓▓", "WEAK": "▓"}
                    lines.append(f"    {w.get(p.weight,'▓'):>4} {p.param_name}: {p.current_value}  {p.narrative}")
            lines.append("")
            if self.bullish_params:
                lines.append(f"  {'Bullish':>12}:")
                for p in self.bullish_params:
                    w = {"STRONG": "▓▓▓", "MEDIUM": "▓▓", "WEAK": "▓"}
                    lines.append(f"    {w.get(p.weight,'▓'):>4} {p.param_name}: {p.current_value}  {p.narrative}")
            lines.append("")

        # ─── ML 预测 ────────────────────────────────────────────────
        if self.ml_snapshot:
            ml = self.ml_snapshot
            lines.append(f"  {'[ ML PREDICTION ]':─^74}")
            sig_icon = "🟢" if ml.signal == "BULLISH" else "🔴" if ml.signal == "BEARISH" else "⚪"
            lines.append(f"  {sig_icon} Signal: {ml.signal}  Confidence: {ml.confidence:.0%}  Model: {ml.model_type}")
            if ml.price_target_30d:
                lines.append(f"  30-Day Target: {ml.price_target_30d:.2f}¢/lb")
            lines.append(f"  Bias: {ml.bias:+.0%} (suggested ratio adjustment)")
            # 模型表现
            perf_parts = []
            if ml.model_accuracy is not None:
                perf_parts.append(f"Dir.Acc={ml.model_accuracy:.1%}")
            if ml.model_mae is not None:
                perf_parts.append(f"MAE={ml.model_mae:.2%}")
            if perf_parts:
                lines.append(f"  Model Performance: {' | '.join(perf_parts)}")
            # 特征重要性
            if ml.top_features:
                lines.append("  Key Features:")
                for name, imp in ml.top_features:
                    bar = "█" * int(min(abs(imp) * 50, 10))
                    lines.append(f"    • {name}: {imp:.4f} {bar}")
            for r in ml.rationale:
                lines.append(f"    • {r}")
            lines.append("")

        # ─── 套保建议 ───────────────────────────────────────────────
        if self.hedge_advice:
            h = self.hedge_advice
            lines.append(f"  {'[ HEDGE ADVICE ]':─^74}")
            lines.append(f"  Ratio: {h.ratio:.0%}  Signal: {h.signal}")
            lines.append(f"  {h.narrative}")
            if h.trigger_below:
                lines.append(f"  ↓ Break {h.trigger_below:.0f} → increase hedge to 75-80%")
            if h.trigger_above:
                lines.append(f"  ↑ Break {h.trigger_above:.0f} → reduce hedge to 50%")
            lines.append("")

        # ─── 凯利仓位影子 ───────────────────────────────────────────
        if self.kelly_shadow:
            k = self.kelly_shadow
            if k.get("active"):
                edge = k.get("edge") or 0.0
                current = f"{self.hedge_advice.ratio:.0%}" if self.hedge_advice else "N/A"
                lines.append(f"  {'凯利视角':>12}: 建议 {k['suggested_ratio']:.0%}（edge {edge:+.0%}）vs 当前建议 {current}")
            else:
                lines.append(f"  {'凯利视角':>12}: {k.get('reason', '')}")
            lines.append("")

        # ─── 中国进口视角 ───────────────────────────────────────────
        if self.china_import:
            ci = self.china_import
            lines.append(f"  {'[ CHINA IMPORT ]':─^74}")
            if ci.fx_rate is not None:
                fx_src = f"  ({ci.fx_source})" if ci.fx_source else ""
                lines.append(f"  {'USD/CNY':>12}: {ci.fx_rate:>8.4f}{fx_src}")
            if ci.landed:
                b = ci.landed
                lines.append(f"  {'到库成本':>12}: {b.total_cost_cny_jin:>8.4f} CNY/斤  ({b.total_cost_usd_mt:.2f} USD/MT)")
                lines.append(f"  {'CYP 占比':>12}: {b.cyp_fraction_pct:>8.1%}  当前套保比率: {b.hedge_ratio_pct:.0%}")
            if ci.policy_events:
                lines.append(f"  {'政策事件':>12}:")
                for ev in ci.policy_events[:5]:
                    sev = "!" * int(ev.get("severity", 0))
                    lines.append(f"    {sev:>5} {ev.get('narrative', '')}")
            else:
                lines.append(f"  {'政策事件':>12}: 近 7 日无显著政策事件")
            lines.append("")

        # ─── 核心观点 ───────────────────────────────────────────────
        lines.append(f"  {'[ OUTLOOK ]':─^74}")
        if self.outlook:
            wrapped = textwrap.wrap(self.outlook, width=68)
            for w in wrapped:
                lines.append(f"  {w}")
        if self.risk_warnings:
            lines.append("")
            lines.append("  ⚠️  Risk Warnings:")
            for rw in self.risk_warnings:
                lines.append(f"      • {rw}")
        lines.append("")
        lines.append(f"  {'─' * 74}")
        lines.append(f"  Generated: {self.generated_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"  {'═' * 74}")
        lines.append("")

        return "\n".join(lines)

    def to_json(self) -> str:
        """输出 JSON 序列化格式"""
        d = asdict(self)
        d["report_date"] = self.report_date.isoformat()
        d["forecast_week_start"] = self.forecast_week_start.isoformat()
        d["forecast_week_end"] = self.forecast_week_end.isoformat()
        d["generated_at"] = self.generated_at.isoformat()
        return json.dumps(d, indent=2, ensure_ascii=False, default=str)

    def to_dict(self) -> dict:
        """输出字典格式（不含日期序列化问题）"""
        # landed 含 datetime timestamp，转 isoformat 保持 JSON 可序列化
        landed_d = asdict(self.china_import.landed) if (self.china_import and self.china_import.landed) else None
        if landed_d and landed_d.get("timestamp") is not None:
            landed_d["timestamp"] = landed_d["timestamp"].isoformat()
        return {
            "meta": {
                "ticker": self.ticker,
                "report_date": self.report_date.isoformat(),
                "forecast_week": f"{self.forecast_week_start.isoformat()} / {self.forecast_week_end.isoformat()}",
                "generated_at": self.generated_at.isoformat(),
            },
            "market": asdict(self.market) if self.market else None,
            "related_markets": self.related_markets,
            "climate": asdict(self.climate) if self.climate else None,
            "levels": {
                "resistance": [asdict(lvl) for lvl in self.resistance_levels],
                "support": [asdict(lvl) for lvl in self.support_levels],
            },
            "scenarios": [asdict(s) for s in self.scenarios],
            "drivers": {
                "bullish": [asdict(p) for p in self.bullish_params],
                "bearish": [asdict(p) for p in self.bearish_params],
            },
            "hedge_advice": asdict(self.hedge_advice) if self.hedge_advice else None,
            "ml_prediction": asdict(self.ml_snapshot) if self.ml_snapshot else None,
            "china_import": {
                "fx_rate": self.china_import.fx_rate,
                "fx_source": self.china_import.fx_source,
                "landed": landed_d,
                "policy_events": self.china_import.policy_events,
            } if self.china_import else None,
            "outlook": self.outlook,
            "risk_warnings": self.risk_warnings,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def build_report(
    ticker: str,
    market: MarketSnapshot,
    related_markets: dict,
    climate: ClimateSnapshot,
    resistance_levels: list[Level],
    support_levels: list[Level],
    scenarios: list[Scenario],
    bullish_params: list[SupportParam],
    bearish_params: list[ResistParam],
    hedge_advice: HedgeAdvice,
    outlook: str,
    risk_warnings: list[str],
    ml_snapshot: Optional[MLSnapshot] = None,
) -> PredictionReport:
    """构建预测报告的便捷工厂函数"""
    today = date.today()
    # 找到下周一
    days_ahead = (7 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    week_start = today + timedelta(days=days_ahead)
    week_end = week_start + timedelta(days=4)

    return PredictionReport(
        ticker=ticker,
        report_date=today,
        forecast_week_start=week_start,
        forecast_week_end=week_end,
        market=market,
        related_markets=related_markets,
        climate=climate,
        resistance_levels=resistance_levels,
        support_levels=support_levels,
        scenarios=scenarios,
        bullish_params=bullish_params,
        bearish_params=bearish_params,
        hedge_advice=hedge_advice,
        ml_snapshot=ml_snapshot,
        outlook=outlook,
        risk_warnings=risk_warnings,
    )
