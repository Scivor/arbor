"""
agent/tools/analysis.py
分析面工具 — Agent 读取复盘 / 校准 / 影子数据（全部只读无副作用）
"""

from langchain.tools import tool


@tool
def get_track_record() -> str:
    """获取周报预测战绩汇总：已复盘期数、区间命中率、方向正确率、套保有效率、平均 Brier、BSS、区分度。"""
    try:
        from reports.history import compute_track_record
        rec = compute_track_record()
        if not rec.get("total"):
            return "暂无数据（历史复盘不足）"
        mean_brier = rec.get("mean_brier")
        bss = rec.get("bss")
        resolution = rec.get("resolution")
        return (
            f"已复盘 {rec['total']} 期（待复盘 {rec.get('pending') or '—'}）\n"
            f"区间命中率 {rec['hit_rate']:.0%} | 方向正确率 {rec['direction_rate']:.0%} "
            f"| 套保有效率 {rec['hedge_rate']:.0%}\n"
            f"平均 Brier {f'{mean_brier:.3f}' if mean_brier is not None else '暂无数据'}（基准 0.667） "
            f"| BSS {f'{bss:+.2f}' if bss is not None else '暂无数据'} "
            f"| 区分度 {f'{resolution:.3f}' if resolution is not None else '暂无数据'}"
        )
    except Exception as e:
        return f"[get_track_record] 错误: {e}"


@tool
def get_driver_stats() -> str:
    """获取驱动因子应验率表（仅样本 ≥2 的因子）：因子 / 应验率 / 样本数。"""
    try:
        from reports.history import compute_driver_stats
        stats = [s for s in compute_driver_stats() if s.get("samples", 0) >= 2]
        if not stats:
            return "暂无足够复盘样本（需 ≥2 期）"
        lines = ["驱动因子应验率:"]
        for s in stats[:10]:
            lines.append(f"  {s['param_name']}: {s['rate']:.0%}（{s['samples']} 样本）")
        return "\n".join(lines)
    except Exception as e:
        return f"[get_driver_stats] 错误: {e}"


@tool
def get_learning_status() -> str:
    """获取系数自校准状态：ml_bias、scenario_band、套保持信、套保偏向、被压低的驱动、方向信任、区间中心、横盘信任、概率锐度、扇面宽度、ML 目标偏移，以及最近 3 条调整。"""
    try:
        from reports.learning import learning_status
        st = learning_status()
        cur = st["current"]
        lines = [
            f"ml_bias_scale {cur['ml_bias_scale']:.2f} | scenario_band_scale {cur['scenario_band_scale']:.2f}",
            f"复盘样本 {st['n_samples']}/{st['min_samples']}",
        ]
        memory = st.get("memory") or {}
        if "hedge_conviction" in memory:
            lines.append(f"hedge_conviction {float(memory['hedge_conviction']):.2f}")
        trust = memory.get("driver_trust") or {}
        if trust:
            discounted = ", ".join(f"{name} {float(value):.2f}" for name, value in list(trust.items())[:5])
            lines.append(f"压低的驱动: {discounted}")
        direction = memory.get("direction_trust") or {}
        if direction:
            labels = {"up": "上涨", "down": "下跌"}
            shown = ", ".join(
                f"{labels.get(str(side), str(side))} {float(value):.2f}"
                for side, value in list(direction.items())[:4]
            )
            lines.append(f"方向信任: {shown}")
        try:
            shift = float(memory.get("band_center_shift") or 0.0)
        except (TypeError, ValueError):
            shift = 0.0
        if abs(shift) >= 0.0025:
            side = "下移" if shift < 0 else "上移"
            lines.append(f"区间中心 {side} {abs(shift) * 100:.2f}%")
        try:
            flat_trust = float(memory.get("flat_trust", 1.0))
        except (TypeError, ValueError):
            flat_trust = 1.0
        if flat_trust < 0.999:
            lines.append(f"横盘信任 {flat_trust:.2f}")
        try:
            sharpness = float(memory.get("prob_sharpness", 1.0))
        except (TypeError, ValueError):
            sharpness = 1.0
        if sharpness < 0.999:
            lines.append(f"概率锐度 {sharpness:.2f}")
        try:
            lean = float(memory.get("hedge_lean") or 0.0)
        except (TypeError, ValueError):
            lean = 0.0
        if abs(lean) >= 0.005:
            side = "少套" if lean < 0 else "多套"
            lines.append(f"套保偏向 {side} {abs(lean) * 100:.2f} 个百分点")
        try:
            fan_width = float(memory.get("fan_width", 1.0))
        except (TypeError, ValueError):
            fan_width = 1.0
        if fan_width > 1.001:
            lines.append(f"扇面宽度 {fan_width:.2f}")
        try:
            target_shift = float(memory.get("ml_target_shift") or 0.0)
        except (TypeError, ValueError):
            target_shift = 0.0
        if abs(target_shift) >= 0.0025:
            side = "下移" if target_shift < 0 else "上移"
            lines.append(f"ML 目标 {side} {abs(target_shift) * 100:.2f}%")
        changelog = st.get("changelog") or []
        if changelog:
            lines.append("最近调整:")
            for e in changelog[-3:]:
                lines.append(
                    f"  {str(e.get('ts', ''))[:16]} {e.get('param')}: "
                    f"{e.get('old')} → {e.get('new')}（{e.get('reason', '')}）"
                )
        else:
            lines.append("暂无调整记录")
        return "\n".join(lines)
    except Exception as e:
        return f"[get_learning_status] 错误: {e}"


@tool
def get_kelly_shadow() -> str:
    """获取最近一期周报的凯利仓位影子建议（只读影子，不影响实际套保建议）。"""
    try:
        from reports.history import load_summaries
        summaries = load_summaries()
        ks = summaries[-1].kelly_shadow if summaries else {}
        if not ks:
            return "暂无凯利影子数据"
        edge = ks.get("edge")
        return (
            f"凯利影子（{summaries[-1].report_date}）: "
            f"建议 {ks.get('suggested_ratio', 0.65):.0%} "
            f"| edge {f'{edge:+.0%}' if edge is not None else '—'} "
            f"| {'激活' if ks.get('active') else '未激活（维持基线）'}"
        )
    except Exception as e:
        return f"[get_kelly_shadow] 错误: {e}"


@tool
def get_reference_class() -> str:
    """获取基础概率：近 5 年全部历史周其后 5 日方向的无条件分布（气候频率）。"""
    try:
        from reports.pipeline import fetch_market_snapshot
        from reports.reference_class import compute_base_rates
        rates = compute_base_rates(fetch_market_snapshot())
        if not rates:
            return "基础概率数据不可用"
        return (
            f"基础概率（近 {rates['years']:.0f} 年 {rates['n_analogs']} 个历史周）: "
            f"涨 {rates['up']:.0%} / 横 {rates['flat']:.0%} / 跌 {rates['down']:.0%}"
        )
    except Exception as e:
        return f"[get_reference_class] 错误: {e}"


# DecisionDB 无 domain 列；按 EventType 名过滤政策相关事件
_POLICY_EVENT_TYPES = frozenset({
    "china_tariff_change", "export_ban",
    "ldc_status_gained", "ldc_status_lost",
    "pesticide_standard_change",
    "trade_war_new_round", "trade_war_deescalation",
    "poly_trade_war_escalate", "poly_trade_war_deescalate",
    "poly_hormuz_normal", "poly_trump_visit_china",
})


@tool
def get_policy_events() -> str:
    """获取最近政策事件（近 7 天，来自事件持久化库 DecisionDB）。"""
    try:
        # weekly summary 不含 china_import 快照，改从事件持久化库取近 7 天记录
        from datetime import datetime, timedelta
        from arbor.infrastructure.persistence import DecisionDB
        start = (datetime.now() - timedelta(days=7)).isoformat()
        # 多取再过滤：库内混有供给/金融事件
        df = DecisionDB().get_events(start=start, limit=40)
        if df is None or df.empty:
            return "近 7 日无政策事件记录"
        if "event_type" in df.columns:
            df = df[df["event_type"].astype(str).str.lower().isin(_POLICY_EVENT_TYPES)]
        if df.empty:
            return "近 7 日无政策事件记录"
        lines = ["近 7 日政策事件:"]
        for row in df.head(5).itertuples():
            lines.append(
                f"  [{str(row.timestamp)[:16]}] sev={row.severity} "
                f"{row.event_type} | {str(row.narrative)[:60]}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"[get_policy_events] 错误: {e}"
