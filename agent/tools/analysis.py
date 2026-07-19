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
    """获取系数自校准状态：当前 ml_bias / scenario_band 系数、复盘样本数、最近 3 条调整记录。"""
    try:
        from reports.learning import learning_status
        st = learning_status()
        cur = st["current"]
        lines = [
            f"ml_bias_scale {cur['ml_bias_scale']:.2f} | scenario_band_scale {cur['scenario_band_scale']:.2f}",
            f"复盘样本 {st['n_samples']}/{st['min_samples']}",
        ]
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


@tool
def get_policy_events() -> str:
    """获取最近政策事件（近 7 天，来自事件持久化库 DecisionDB）。"""
    try:
        # weekly summary 不含 china_import 快照，改从事件持久化库取近 7 天记录
        from datetime import datetime, timedelta
        from core.persistence import DecisionDB
        start = (datetime.now() - timedelta(days=7)).isoformat()
        df = DecisionDB().get_events(start=start, limit=5)
        if df is None or df.empty:
            return "近 7 日无政策事件记录"
        lines = ["近 7 日政策事件:"]
        for row in df.itertuples():
            lines.append(
                f"  [{str(row.timestamp)[:16]}] sev={row.severity} "
                f"{row.event_type} | {str(row.narrative)[:60]}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"[get_policy_events] 错误: {e}"
