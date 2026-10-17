"""
reports/llm_commentary.py
周报「采购下一步建议」— 单轮 LLM 合成（不走 agent 工具循环）。

报告数据装配完毕后，把关键字段压缩成纯文本上下文喂给 LLM，
输出面向进口采购的行动建议。无 API key 或任何调用异常 → 静默返回 None
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
    "你是 Arbor 采购顾问——面向中国咖啡生豆进口商的决策智能体，不是聊天机器人，也不是行情解说员。\n"
    "任务：综合给定的情景/ML/到库成本/政策/战绩数据，直接告诉采购「下一步怎么办」。\n"
    "硬性输出约定: 正文第一行必须是机器可读标记 [DIRECTION:X]，X ∈ {上涨, 下跌, 横盘}；\n"
    "标记之后才是建议正文，180-280 字，固定五段：\n"
    "【现在怎么做】采购节奏（分批/观望/适度补库）+ 套保松紧，必须给可执行动作，禁止只复述指标\n"
    "【时机好不好】相对到库成本/主导情景，一句说清「现在下单划不划算」\n"
    "【为什么】最多 3 条，每条注明依据的数据；系统内部分歧要点名并给取舍\n"
    "【别踩的坑】至少 1 条反向情景或失效条件\n"
    "【下周盯什么】1-2 个触发条件（价位/事件/基差），便于采购跟进\n"
    "语言：用采购听得懂的生意话（锁成本、分批、等等），少用 RSI/Brier 等黑话；"
    "若必须引用战绩，用「近期方向判断参考价值有限/尚可」表达。\n"
    "铁律：只用给定数据，禁止编造数字；数据缺失的维度直接跳过不提；"
    "不承诺收益、不下单、不改客户真实仓位；凯利/事件影子仅作对照。"
)

# 英文版：正文英文输出；[DIRECTION:X] 值仍为中文（归因链路只用中文三值，保持一致）
_SYSTEM_PROMPT_EN = (
    "You are Arbor's Procurement Advisor for Chinese green-coffee importers — "
    "an actionable decision agent, not a chatbot or market narrator. "
    "Write the advice body in ENGLISH.\n"
    "Task: synthesize the provided scenario/ML/landed-cost/policy/scorecard data "
    "into a direct next-step recommendation.\n"
    "Hard output contract: the FIRST line must be a machine-readable marker [DIRECTION:X] "
    "where X ∈ {上涨, 下跌, 横盘} (Chinese values only — consumed by our attribution pipeline); "
    "then the English advice body, 180-280 words, exactly five sections:\n"
    "[Do now] buying pace (stagger / wait / restock modestly) + hedge tightness — actionable, no metric dumps\n"
    "[Timing] one sentence on whether buying now is favorable vs landed cost / dominant scenario\n"
    "[Why] at most 3 items, each citing data; name internal conflicts and pick a side\n"
    "[Watch-out] at least 1 counter-scenario or invalidation\n"
    "[Watch next week] 1-2 triggers (price / event / basis) for follow-up\n"
    "Language: importer business English (lock cost, stagger buys, wait); avoid jargon dumps. "
    "If citing scorecard, say judgment reliability is limited/acceptable — not raw Brier numbers.\n"
    "Rules: use only provided data; never invent numbers; skip missing dimensions; "
    "no return promises, no order placement, no live position changes; Kelly/event tilt are shadow-only."
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

    sc = getattr(report, "scenario_scorecard", None)
    if sc and sc.get("n", 0) > 0:
        brier = sc.get("mean_brier")
        brier_s = f"{brier:.3f}" if brier is not None else "—"
        skill = "有技能" if sc.get("has_skill") else "技能未证实"
        lines.append(
            f"情景记分: n={sc['n']} 区间覆盖 {sc.get('interval_coverage', 0):.0%} "
            f"严格方向 {sc.get('strict_direction_rate', 0):.0%} Brier {brier_s}（{skill}）"
        )

    tilt = getattr(report, "scenario_event_tilt", None)
    if tilt and tilt.get("active"):
        probs = " / ".join(
            f"{t['direction']} {t['probability']:.0%}"
            for t in tilt.get("tilted", [])
        )
        lines.append(f"事件影子情景: {probs}（仅对照，不改套保）")
        for r in (tilt.get("reasons") or [])[:3]:
            lines.append(f"  影子依据: {r}")

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
    生成采购下一步建议（单轮 LLM 调用）。

    Args:
        report: PredictionReport。
        lang:   "zh" 中文建议 | "en" 英文建议（[DIRECTION:X] 值仍为中文三值）。

    Returns:
        (清洗后正文, direction)；无 API key 或任何异常 → None（静默，报告不含此板块）。
    """
    try:
        from arbor.infrastructure.secrets import load_llm_api_key
        api_key, provider = load_llm_api_key()
    except Exception as e:
        logger.warning("llm_commentary: 读取 API key 失败: %s", e)
        return None
    if not api_key:
        logger.info("llm_commentary: 未配置 API key，跳过采购建议")
        return None

    try:
        llm = ChatOpenAI(
            model=_MODEL,
            temperature=0.3,
            max_tokens=800,
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
