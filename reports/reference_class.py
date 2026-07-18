"""
reports/reference_class.py
参考类基础概率（超级预测 Phase 2）— 给情景概率一个外部视角的经验锚点。

参考类: 与当前市场状态（RSI、30 日动量）相似的历史周窗口，
统计其后 5 个交易日的方向分布（up/flat/down，±1% 阈值，
与 reports/history.compute_prediction_review 同口径）。

用法:
    python -m reports.reference_class --validate   # 回看验证参考类技能
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

from reports.indicators import compute_rsi
from sources.coffee.kc_history import fetch_kc_daily  # noqa: F401 — 数据获取已下沉 sources 层（M4）

logger = logging.getLogger(__name__)

# 方向分类阈值（±1%）与参考类筛选容差
_DIR_THRESHOLD = 0.01
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
    """参考类筛选: |ΔRSI| ≤ 5 且 |Δmom30| ≤ 0.03 的历史窗口，统计方向计数。"""
    counts = {"up": 0, "flat": 0, "down": 0}
    for w in weeks:
        if abs(w["rsi"] - rsi) <= _RSI_TOL and abs(w["mom30"] - mom30) <= _MOM_TOL:
            counts[w["direction"]] += 1
    return {"counts": counts, "n": sum(counts.values())}


# ─────────────────────────────────────────────────────────────────────────────
# 基础概率
# ─────────────────────────────────────────────────────────────────────────────

def compute_base_rates(market, df: pd.DataFrame | None = None) -> dict | None:
    """
    参考类基础概率: 与当前 RSI + 30 日动量相似的历史周，其后 5 日方向的经验分布。

    Returns:
        {"up","flat","down","n_analogs","years"}（频率和为 1）；
        market 为 None、缺 rsi/动量字段或 df 为空 → None；
        无相似样本 → n_analogs=0，频率降级为均匀先验 1/3。
    """
    if market is None:
        return None
    cur_rsi = getattr(market, "rsi_14", None)
    cur_mom = getattr(market, "change_30d_pct", None)  # 小数形式（如 -0.154）
    if cur_rsi is None or cur_mom is None:
        return None

    if df is None:
        df = fetch_kc_daily()
    if df is None or df.empty:
        return None

    closes = [float(c) for c in df["Close"].tolist()]
    weeks = _weekly_features(closes)
    if not weeks:
        return None

    m = _match_analogs(weeks, float(cur_rsi), float(cur_mom))
    n = m["n"]
    years = round(len(closes) / 252, 1)  # 按 252 交易日/年估算

    if n == 0:
        logger.info("compute_base_rates: 无相似历史样本，降级为均匀先验")
        return {"up": 1 / 3, "flat": 1 / 3, "down": 1 / 3, "n_analogs": 0, "years": years}
    return {
        "up": m["counts"]["up"] / n,
        "flat": m["counts"]["flat"] / n,
        "down": m["counts"]["down"] / n,
        "n_analogs": n,
        "years": years,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 回看验证
# ─────────────────────────────────────────────────────────────────────────────

def _validate(n_windows: int = 52):
    """
    回看最近 n_windows 个周窗口: 每个窗口仅用其之前的数据算参考类频率，
    对后 5 日实际方向记三分类 Brier，与均匀基准 0.6667 对比。
    """
    from reports.history import compute_brier

    df = fetch_kc_daily()
    closes = [float(c) for c in df["Close"].tolist()]
    all_weeks = _weekly_features(closes)
    recent = all_weeks[-n_windows:]

    # 类别 → compute_brier 可识别的方向标签
    cat_dir = {"up": "上涨", "flat": "横盘", "down": "下跌"}

    briers = []
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
        briers.append(compute_brier(scenarios, w["direction"]))

    mean_brier = sum(briers) / len(briers)
    print(f"参考类 Brier 均值: {mean_brier:.4f}（{len(briers)} 个窗口，均匀基准 0.6667，低于基准即有技能）")
    print(f"平均参考类样本数: {sum(n_analogs_list) / len(n_analogs_list):.1f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if "--validate" in sys.argv:
        _validate()
    else:
        print("用法: python -m reports.reference_class --validate")
