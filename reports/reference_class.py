"""
reports/reference_class.py
气候频率基础概率 — 情景概率的经验锚点。

证据（2026-07 对照实验）: 条件化（RSI/动量相似窗口筛选）在全部容差下
输给无条件气候频率（最佳 0.6496 vs 气候频率 0.5815，均匀基准 0.6667），
条件化为负贡献。生产路径因此改用无条件频率：全部历史周其后 5 个交易日
的方向分布（up/flat/down，±1% 阈值，与 compute_prediction_review 同口径）。

用法:
    python -m reports.reference_class --validate   # 参考类 vs 气候频率 对照
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

from reports.indicators import compute_rsi
from sources.coffee.kc_history import fetch_kc_daily  # noqa: F401 — 数据获取已下沉 sources 层（M4）

logger = logging.getLogger(__name__)

# 方向分类阈值（±1%）
_DIR_THRESHOLD = 0.01

# 参考类筛选容差 — 已证伪（2026-07 对照实验: 0.6496 vs 0.5815），
# 仅供 --validate 对照使用，禁止用于生产路径
_RSI_TOL = 5.0
_MOM_TOL = 0.03


# ─────────────────────────────────────────────────────────────────────────────
# 历史特征计算
# ─────────────────────────────────────────────────────────────────────────────

def _weekly_features(closes: list[float]) -> list[dict]:
    """
    逐周（5 个交易日步长）计算历史特征:
    RSI(14)、30 日动量（小数形式）、后 5 个交易日方向（±1% 分 up/flat/down）。
    末尾不足"后 5 日"的数据不产出窗口。
    RSI 口径: reports/indicators.compute_rsi（简单平均，与 pipeline 一致）。
    """
    weeks = []
    for end in range(30, len(closes) - 5, 5):
        rsi = compute_rsi(closes[: end + 1])
        mom30 = (closes[end] - closes[end - 30]) / closes[end - 30]
        fwd_ret = (closes[end + 5] - closes[end]) / closes[end]
        direction = "up" if fwd_ret > _DIR_THRESHOLD else "down" if fwd_ret < -_DIR_THRESHOLD else "flat"
        weeks.append({"end": end, "rsi": rsi, "mom30": mom30, "direction": direction})
    return weeks


def _match_analogs(weeks: list[dict], rsi: float, mom30: float) -> dict:
    """
    参考类筛选: |ΔRSI| ≤ 5 且 |Δmom30| ≤ 0.03 的历史窗口，统计方向计数。

    已证伪（2026-07 对照实验: 条件化 Brier 0.6496 vs 无条件 0.5815）—
    仅供 --validate 对照，禁止用于生产路径。
    """
    counts = {"up": 0, "flat": 0, "down": 0}
    for w in weeks:
        if abs(w["rsi"] - rsi) <= _RSI_TOL and abs(w["mom30"] - mom30) <= _MOM_TOL:
            counts[w["direction"]] += 1
    return {"counts": counts, "n": sum(counts.values())}


# ─────────────────────────────────────────────────────────────────────────────
# 基础概率（无条件气候频率）
# ─────────────────────────────────────────────────────────────────────────────

def compute_base_rates(market=None, df: pd.DataFrame | None = None) -> dict | None:
    """
    气候频率基础概率: 全部历史周其后 5 日方向的无条件分布。

    生产口径（证据驱动）: 不做 RSI/动量条件化筛选——对照实验证明条件化
    是负贡献（0.6496 vs 0.5815，均匀基准 0.6667）。

    Args:
        market: 保留签名兼容旧调用方，不再参与任何筛选。
        df:     KC=F 日线（None 时内部 fetch_kc_daily()）。

    Returns:
        {"up","flat","down","n_analogs","years"}（频率和为 1，n_analogs=全部周数）；
        df 为空或无有效周窗口 → None。
    """
    if df is None:
        df = fetch_kc_daily()
    if df is None or df.empty:
        return None

    closes = [float(c) for c in df["Close"].tolist()]
    weeks = _weekly_features(closes)
    if not weeks:
        return None

    counts = {"up": 0, "flat": 0, "down": 0}
    for w in weeks:
        counts[w["direction"]] += 1
    n = len(weeks)
    return {
        "up": counts["up"] / n,
        "flat": counts["flat"] / n,
        "down": counts["down"] / n,
        "n_analogs": n,
        "years": round(len(closes) / 252, 1),  # 按 252 交易日/年估算
    }


# ─────────────────────────────────────────────────────────────────────────────
# 回看验证
# ─────────────────────────────────────────────────────────────────────────────

def _validate(n_windows: int = 52):
    """
    回看最近 n_windows 个周窗口: 参考类（条件化筛选）vs 气候频率（无条件分布）
    两个口径对后 5 日实际方向记三分类 Brier，与均匀基准 0.6667 对照。
    每个窗口仅用其之前的数据（无前视）。
    """
    from reports.history import compute_brier

    df = fetch_kc_daily()
    closes = [float(c) for c in df["Close"].tolist()]
    all_weeks = _weekly_features(closes)
    recent = all_weeks[-n_windows:]

    # 类别 → compute_brier 可识别的方向标签
    cat_dir = {"up": "上涨", "flat": "横盘", "down": "下跌"}

    rc_briers = []       # 参考类（条件化，已证伪，仅对照）
    climate_briers = []  # 气候频率（无条件，生产口径）
    n_analogs_list = []
    for w in recent:
        # 仅用该窗口之前的历史（closes[:end] 内窗口的后 5 日终点 ≤ end-1，无前视）
        hist_weeks = _weekly_features(closes[: w["end"]])

        m = _match_analogs(hist_weeks, w["rsi"], w["mom30"])
        n_analogs_list.append(m["n"])
        if m["n"]:
            probs = {k: v / m["n"] for k, v in m["counts"].items()}
        else:
            probs = {"up": 1 / 3, "flat": 1 / 3, "down": 1 / 3}
        scenarios = [{"direction": cat_dir[cat], "probability": p} for cat, p in probs.items()]
        rc_briers.append(compute_brier(scenarios, w["direction"]))

        if hist_weeks:
            counts = {"up": 0, "flat": 0, "down": 0}
            for h in hist_weeks:
                counts[h["direction"]] += 1
            probs = {k: v / len(hist_weeks) for k, v in counts.items()}
        else:
            probs = {"up": 1 / 3, "flat": 1 / 3, "down": 1 / 3}
        scenarios = [{"direction": cat_dir[cat], "probability": p} for cat, p in probs.items()]
        climate_briers.append(compute_brier(scenarios, w["direction"]))

    n = len(rc_briers)
    print(f"参考类 Brier 均值: {sum(rc_briers) / n:.4f}（{n} 个窗口，均匀基准 0.6667，低于基准即有技能）")
    print(f"气候频率 Brier 均值: {sum(climate_briers) / n:.4f}（同窗口对照，无条件分布）")
    print(f"平均参考类样本数: {sum(n_analogs_list) / n:.1f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if "--validate" in sys.argv:
        _validate()
    else:
        print("用法: python -m reports.reference_class --validate")
