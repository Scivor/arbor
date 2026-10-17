"""
reports/procurement_briefing.py
无 LLM 时的规则版「采购下一步建议」——用报告已有字段拼出五段行动建议。

不替代 LLM 文案质量，只保证：没 key / 调用失败时，周报与聊天页仍有可执行简报。
方向三值与归因链路一致：上涨 / 下跌 / 横盘。

另提供：从已发布周报 HTML 读取本期简报（供 web 聊天页与 Agent 工具共用）。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent.parent / "web" / "static" / "reports"
_BRIEFING_FILENAME = "briefing.json"


def _dominant_direction(report) -> str:
    """主导情景方向 → 上涨/下跌/横盘；无情景时看 ML。"""
    if report.scenarios:
        top = max(report.scenarios, key=lambda s: s.probability)
        d = (top.direction or "").strip()
        if d in ("上涨", "下跌", "横盘"):
            return d
        # 英文 demo 兼容
        mapping = {"up": "上涨", "down": "下跌", "flat": "横盘",
                   "bullish": "上涨", "bearish": "下跌", "neutral": "横盘"}
        return mapping.get(d.lower(), "横盘")

    ml = report.ml_snapshot
    if ml:
        sig = (ml.signal or "").upper()
        if sig in ("BULLISH", "BUY", "UP"):
            return "上涨"
        if sig in ("BEARISH", "SELL", "DOWN"):
            return "下跌"
    return "横盘"


def _landed_line(report) -> Optional[str]:
    ci = getattr(report, "china_import", None)
    if not ci or not ci.landed:
        return None
    return f"{ci.landed.total_cost_cny_jin:.2f} CNY/斤"


def _hedge_line(report, lang: str = "zh") -> Optional[str]:
    h = report.hedge_advice
    if not h:
        return None
    sig = (h.signal or "").upper()
    if lang == "en":
        sig_label = {
            "HIGH_HEDGE": "tight",
            "MEDIUM_HEDGE": "neutral-tight",
            "LOW_HEDGE": "loose",
            "NO_HEDGE": "unhedged",
        }.get(sig, h.signal)
    else:
        sig_label = {
            "HIGH_HEDGE": "偏紧",
            "MEDIUM_HEDGE": "中性偏紧",
            "LOW_HEDGE": "偏松",
            "NO_HEDGE": "不加保",
        }.get(sig, h.signal)
    return f"{h.ratio:.0%}（{sig_label}）"


def _scenario_line(report) -> Optional[str]:
    if not report.scenarios:
        return None
    top = max(report.scenarios, key=lambda s: s.probability)
    # 展示用中文方向（demo 情景可能是 BEARISH/NEUTRAL/BULLISH）
    d = _dominant_direction(report)
    return f"{d} {top.probability:.0%}（{top.price_min:.0f}–{top.price_max:.0f}）"


def _ml_line(report) -> Optional[str]:
    ml = report.ml_snapshot
    if not ml:
        return None
    return f"{ml.signal}（置信度 {ml.confidence:.0%}）"


def _scorecard_soft(report) -> Optional[str]:
    sc = getattr(report, "scenario_scorecard", None)
    if not sc or not sc.get("n"):
        return None
    if sc.get("has_skill"):
        return "近期情景方向判断尚可参考"
    return "近期情景方向判断参考价值有限，动作宜保守"


def build_procurement_briefing(report, lang: str = "zh") -> tuple[str, str]:
    """
    规则拼装采购建议。

    Returns:
        (正文, direction)  — direction ∈ {上涨, 下跌, 横盘}
    """
    direction = _dominant_direction(report)
    if lang == "en":
        return _build_en(report, direction), direction
    return _build_zh(report, direction), direction


def _build_zh(report, direction: str) -> str:
    landed = _landed_line(report)
    hedge = _hedge_line(report, lang="zh")
    scenario = _scenario_line(report)
    ml = _ml_line(report)
    soft = _scorecard_soft(report)

    if direction == "下跌":
        do_now = "本周现货分批小幅补库，不宜一次性锁满；套保维持偏紧。"
        timing = "主导情景偏弱，逢低分批优于追空敞口。"
        if landed:
            timing = f"到库成本约 {landed}，主导情景偏弱，宜分批不宜一把锁满。"
    elif direction == "上涨":
        do_now = "适度提前补库、节奏略加快；套保可略松但仍保留底仓保护。"
        timing = "上行概率抬升，拖延补库的机会成本升高。"
        if landed:
            timing = f"到库约 {landed}，上行概率抬升，拖延补库成本升高。"
    else:
        do_now = "观望为主、刚性需求才补；套保维持中性，暂不主动大幅调仓。"
        timing = "方向不明，现在下单性价比一般，优先控节奏。"
        if landed:
            timing = f"到库约 {landed}，方向不明，现在下单性价比一般。"

    if hedge:
        do_now = do_now.rstrip("。") + f"。当前系统建议套保 {hedge}。"

    why_parts = []
    if scenario:
        why_parts.append(f"主导情景 {scenario}")
    if ml:
        # ML 信号转成采购话：BEARISH→偏弱
        ml_soft = ml.replace("BEARISH", "偏弱").replace("BULLISH", "偏强").replace("NEUTRAL", "中性")
        why_parts.append(f"模型 {ml_soft}")
    if landed:
        why_parts.append(f"到库 {landed}")
    if soft:
        why_parts.append(soft)
    why = "；".join(why_parts[:3]) if why_parts else "依据本期情景与系统套保建议综合判断"

    risk = "若供给冲击或关税突发，分批节奏应立刻暂停加仓。"
    if report.risk_warnings:
        risk = report.risk_warnings[0]

    watch = "下周盯 KC 关键支撑/阻力突破，以及关税与汇率异动。"
    h = report.hedge_advice
    if h and (h.trigger_below or h.trigger_above):
        parts = []
        if h.trigger_below:
            parts.append(f"跌破 {h.trigger_below:.0f}")
        if h.trigger_above:
            parts.append(f"升破 {h.trigger_above:.0f}")
        watch = "下周盯 " + " / ".join(parts) + "，以及关税与汇率新闻。"

    return (
        f"【现在怎么做】{do_now}\n"
        f"【时机好不好】{timing}\n"
        f"【为什么】{why}\n"
        f"【别踩的坑】{risk}\n"
        f"【下周盯什么】{watch}"
    )


def _build_en(report, direction: str) -> str:
    landed = _landed_line(report)
    hedge = _hedge_line(report, lang="en")
    scenario = _scenario_line(report)
    ml = _ml_line(report)
    soft = _scorecard_soft(report)

    if direction == "下跌":
        do_now = "Stagger small spot restocks this week; keep hedge on the tight side."
        timing = "Dominant scenario leans soft — stagger buys rather than leave full exposure open."
        if landed:
            timing = f"Landed ~{landed}; scenario soft — stagger, do not lock all at once."
    elif direction == "上涨":
        do_now = "Restock a bit earlier; hedge can ease slightly but keep a floor."
        timing = "Upside odds rising — waiting raises opportunity cost."
        if landed:
            timing = f"Landed ~{landed}; upside odds rising — delay costs more."
    else:
        do_now = "Wait unless need is firm; hold a neutral hedge, no big rebalance."
        timing = "Direction unclear — buying now is only average value; pace first."
        if landed:
            timing = f"Landed ~{landed}; direction unclear — pace over size."

    if hedge:
        do_now = do_now.rstrip(".") + f" System hedge now {hedge}."

    why_parts = []
    if scenario:
        why_parts.append(f"scenario {scenario}")
    if ml:
        why_parts.append(f"ML {ml}")
    if landed:
        why_parts.append(f"landed {landed}")
    if soft:
        why_parts.append(soft)
    why = "; ".join(why_parts[:3]) if why_parts else "based on this week's scenarios and hedge advice"

    risk = "If a supply shock or tariff surprise hits, pause adding inventory."
    if report.risk_warnings:
        risk = report.risk_warnings[0]

    watch = "Watch KC support/resistance breaks, plus tariff and FX moves."
    h = report.hedge_advice
    if h and (h.trigger_below or h.trigger_above):
        parts = []
        if h.trigger_below:
            parts.append(f"break below {h.trigger_below:.0f}")
        if h.trigger_above:
            parts.append(f"break above {h.trigger_above:.0f}")
        watch = "Watch " + " / ".join(parts) + ", plus tariff and FX news."

    return (
        f"[Do now] {do_now}\n"
        f"[Timing] {timing}\n"
        f"[Why] {why}\n"
        f"[Watch-out] {risk}\n"
        f"[Watch next week] {watch}"
    )


DEFAULT_SUGGESTIONS_ZH = [
    "这周该不该买",
    "套保要紧还是松",
    "到库成本怎么看",
    "如果跌破支撑怎么办",
]

DEFAULT_SUGGESTIONS_EN = [
    "Should we buy this week?",
    "Tighten or loosen the hedge?",
    "How to read landed cost?",
    "What if support breaks?",
]


def extract_briefing_from_html(html: str) -> Optional[str]:
    """从周报 HTML 抽出「采购下一步建议」纯文本。"""
    m = re.search(
        r'class="outlook-box ai-commentary"[^>]*>(.*?)</div>',
        html,
        re.S,
    )
    if not m:
        return None
    raw = m.group(1)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = (
        raw.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return raw.strip() or None


def briefing_payload(report, report_date: str = "") -> dict[str, Any]:
    """结构化简报 sidecar（供聊天页 / Agent 工具稳定读取）。"""
    return {
        "report_date": report_date or str(getattr(report, "report_date", "")),
        "direction": getattr(report, "llm_direction", None),
        "zh": getattr(report, "llm_commentary", None),
        "en": getattr(report, "llm_commentary_en", None),
        "source": "llm_or_rule",
    }


def write_briefing_sidecar(report, report_dir: Path, report_date: str = "") -> Optional[Path]:
    """
    写出 briefing.json。无中文简报时跳过。
    Returns: 写入路径或 None
    """
    if not getattr(report, "llm_commentary", None):
        return None
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / _BRIEFING_FILENAME
    payload = briefing_payload(report, report_date=report_date or report_dir.name)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_briefing_from_dir(report_dir: Path) -> Optional[str]:
    """优先读 briefing.json，否则回退 HTML 抽取。"""
    report_dir = Path(report_dir)
    side = report_dir / _BRIEFING_FILENAME
    if side.exists():
        try:
            data = json.loads(side.read_text(encoding="utf-8"))
            text = (data.get("zh") or "").strip()
            if text:
                return text
        except Exception as e:
            logger.warning("briefing.json 读取失败 %s: %s", side, e)
    html_path = report_dir / "report.html"
    if html_path.exists():
        try:
            return extract_briefing_from_html(html_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def load_latest_published_briefing(
    reports_dir: Optional[Path] = None,
) -> Optional[Tuple[str, str]]:
    """
    读取最新已发布周报中的采购简报。

    Returns:
        (report_date, briefing_text) 或 None
    """
    root = Path(reports_dir) if reports_dir else _DEFAULT_REPORTS_DIR
    if not root.exists():
        return None
    dates = sorted(
        (
            p.name
            for p in root.iterdir()
            if p.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", p.name)
        ),
        reverse=True,
    )
    for d in dates:
        text = load_briefing_from_dir(root / d)
        if text:
            return d, text
    return None


def format_followup_context(briefing: str, user_message: str, report_date: str = "") -> str:
    """把本期简报与用户追问拼成 Agent 输入（简报为已发布立场，追问只澄清）。"""
    date_line = f"（报告日 {report_date}）" if report_date else ""
    return (
        f"【本期已发布采购简报】{date_line}\n"
        f"{briefing.strip()}\n\n"
        f"【用户追问】\n"
        f"{user_message.strip()}\n\n"
        "请以本期简报为默认立场作答；若用户在追问某一点，只澄清该点，"
        "必要时用工具核对最新数字；不要推翻简报除非工具显示数据已显著变化。"
    )
