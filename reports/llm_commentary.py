"""
reports/llm_commentary.py
周报 AI 分析师点评 — 单轮 LLM 合成（不走 agent 工具循环）。

报告数据装配完毕后，把关键字段压缩成纯文本上下文喂给 LLM，
输出 150-250 字中文点评。无 API key 或任何调用异常 → 静默返回 None
（报告不含此板块，绝不影响出报）。
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

_MODEL = "deepseek-chat"
# base_url 按 _load_api_key 的 provider 决定（与 agent.agents.analyst 同口径）
_BASE_URLS = {"deepseek": "https://api.deepseek.com", "openai": None}

# 方向标记（点评入归因：正文第一行的机器可读标记）
_DIRECTION_RE = re.compile(r"^\[DIRECTION:(上涨|下跌|横盘)\]\s*")

_SYSTEM_PROMPT = (
    "你是资深咖啡大宗商品分析师。基于给定数据写中文点评。\n"
    "硬性输出约定: 正文第一行必须是机器可读标记 [DIRECTION:X]，X ∈ {上涨, 下跌, 横盘}；\n"
    "标记之后才是点评正文，150-250 字，固定四段：\n"
    "【核心判断】方向 + 概率%（必须给数字，禁止 0%/100%）\n"
    "【关键依据】最多 3 条，每条注明依据的数据\n"
    "【风险提示】至少 1 条反向证据\n"
    "【给进口商的一句话建议】\n"
    "只用给定数据，禁止编造数字；数据缺失的维度直接跳过不提。"
)

# 英文版：正文英文输出；[DIRECTION:X] 值仍为中文（归因链路只用中文三值，保持一致）
_SYSTEM_PROMPT_EN = (
    "You are a senior coffee commodity analyst. Write the commentary in ENGLISH.\n"
    "Hard output contract: the FIRST line must be a machine-readable marker [DIRECTION:X] "
    "where X ∈ {上涨, 下跌, 横盘} (Chinese values only — consumed by our attribution pipeline); "
    "then the English commentary body, 150-250 words, exactly four sections:\n"
    "[Core View] direction + probability % (a number, never 0%/100%)\n"
    "[Key Evidence] at most 3 items, each citing the data used\n"
    "[Risk] at least 1 piece of counter-evidence\n"
    "[One-line advice for the importer]\n"
    "Use only the provided data; never invent numbers; skip dimensions whose data is missing."
)


def _build_context(report) -> str:
    """把报告关键字段压缩成紧凑纯文本上下文（None 字段跳过）。"""
    lines = [
        f"报告日期: {report.report_date} | 预测周: {report.forecast_week_start} – {report.forecast_week_end} | 合约: {report.ticker}",
    ]

    m = report.market
    if m:
        lines.append(
            f"现价: {m.current:.2f} ¢/lb | 日涨跌 {m.change_1d_pct:+.2%} | 30日涨跌 {m.change_30d_pct:+.2%} | "
            f"RSI(14) {m.rsi_14:.1f} | MA20 {m.ma20:.2f} | MA60 {m.ma60:.2f}"
        )

    if report.climate:
        c = report.climate
        lines.append(f"气候: ONI {c.oni_value:+.2f} ({c.oni_phase}, {c.oni_period})")

    if report.scenarios:
        sc = " | ".join(
            f"{s.direction} {s.probability:.0%} [{s.price_min:.0f}–{s.price_max:.0f}]"
            for s in report.scenarios
        )
        lines.append(f"情景: {sc}")

    if report.bullish_params:
        lines.append("利多: " + "、".join(p.param_name for p in report.bullish_params[:3]))
    if report.bearish_params:
        lines.append("利空: " + "、".join(p.param_name for p in report.bearish_params[:3]))

    if report.ml_snapshot:
        ml = report.ml_snapshot
        lines.append(f"ML 信号: {ml.signal}（置信度 {ml.confidence:.0%}，{ml.model_type}）")

    ci = getattr(report, "china_import", None)
    if ci:
        if ci.fx_rate is not None:
            lines.append(f"USD/CNY: {ci.fx_rate:.4f}")
        if ci.landed:
            lines.append(
                f"到库成本: {ci.landed.total_cost_cny_jin:.2f} CNY/斤（{ci.landed.total_cost_usd_mt:.0f} USD/MT）"
            )
        if ci.policy_events:
            lines.append("政策事件: " + "；".join(ev.get("narrative", "") for ev in ci.policy_events[:3]))

    rc = getattr(report, "reference_class", None)
    if rc:
        lines.append(
            f"参考类: 近 {rc.get('years', 5):.0f} 年 {rc.get('n_analogs', 0)} 个相似周，"
            f"涨 {rc.get('up', 0):.0%} / 横 {rc.get('flat', 0):.0%} / 跌 {rc.get('down', 0):.0%}"
        )

    k = getattr(report, "kelly_shadow", None)
    if k:
        if k.get("active"):
            lines.append(f"凯利影子: 建议 {k['suggested_ratio']:.0%}（edge {k.get('edge', 0):+.0%}）")
        else:
            lines.append(f"凯利影子: {k.get('reason', '')}")

    if report.outlook:
        lines.append(f"系统展望: {report.outlook}")

    return "\n".join(lines)


def _parse_direction(text: str) -> tuple[str, str]:
    """
    剥离首行 [DIRECTION:X] 标记，返回（清洗后正文, direction）。
    标记缺失/非法 → direction 记 "横盘"（正文保留，logger.info 记录）。
    """
    m = _DIRECTION_RE.match(text)
    if m:
        return text[m.end():].strip(), m.group(1)
    logger.info("llm_commentary: 未找到方向标记，按横盘处理")
    return text, "横盘"


def generate_commentary(report, lang: str = "zh") -> Optional[tuple[str, str]]:
    """
    生成 AI 分析师点评（单轮 LLM 调用）。

    Args:
        report: PredictionReport。
        lang:   "zh" 中文点评 | "en" 英文点评（[DIRECTION:X] 值仍为中文三值）。

    Returns:
        (清洗后正文, direction)；无 API key 或任何异常 → None（静默，报告不含此板块）。
    """
    try:
        from agent.agents.analyst import _load_api_key
        api_key, provider = _load_api_key()
    except Exception as e:
        logger.warning("llm_commentary: 读取 API key 失败: %s", e)
        return None
    if not api_key:
        logger.info("llm_commentary: 未配置 API key，跳过 AI 点评")
        return None

    try:
        llm = ChatOpenAI(
            model=_MODEL,
            temperature=0.3,
            max_tokens=600,
            api_key=api_key,
            base_url=_BASE_URLS.get(provider),
        )
        resp = llm.invoke([
            ("system", _SYSTEM_PROMPT_EN if lang == "en" else _SYSTEM_PROMPT),
            ("human", _build_context(report)),
        ])
        text = (resp.content or "").strip()
        if not text:
            return None
        return _parse_direction(text)
    except Exception as e:
        logger.warning("llm_commentary: 生成失败: %s", e)
        return None
