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
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_PATH = Path.home() / ".arbor" / "cache" / "kc_daily.csv"
_CACHE_TTL = timedelta(days=7)

# 方向分类阈值（±1%）与参考类筛选容差
_DIR_THRESHOLD = 0.01
_RSI_TOL = 5.0
_MOM_TOL = 0.03


# ─────────────────────────────────────────────────────────────────────────────
# 数据获取（带本地缓存）
# ─────────────────────────────────────────────────────────────────────────────

def fetch_kc_daily(years: int = 5) -> pd.DataFrame:
    """
    拉取 KC=F 日线收盘价，缓存到 ~/.arbor/cache/kc_daily.csv（TTL 7 天，按 mtime）。
    缓存新鲜则直接读缓存；任何网络/解析失败抛出异常，由调用方兜底。
    """
    if _CACHE_PATH.exists():
        age = datetime.now() - datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime)
        if age < _CACHE_TTL:
            try:
                df = pd.read_csv(_CACHE_PATH, index_col=0, parse_dates=True)
                if not df.empty:
                    logger.info("fetch_kc_daily: 使用缓存（%d 行，age %s）", len(df), age)
                    return df
            except Exception as e:
                logger.warning("fetch_kc_daily: 缓存读取失败，改为实时拉取: %s", e)

    import yfinance as yf
    df = yf.download("KC=F", period=f"{years}y", interval="1d",
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError("yfinance 返回空数据")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()

    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(_CACHE_PATH)
    except Exception as e:
        logger.warning("fetch_kc_daily: 缓存写入失败: %s", e)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 历史特征计算
# ─────────────────────────────────────────────────────────────────────────────

def _rsi(closes: list[float], period: int = 14) -> float:
    """
    RSI(14) — 口径与 reports/pipeline.fetch_market_snapshot 完全一致:
    最近 period 个交易日涨跌幅的简单平均（非 Wilder 指数平滑）。
    """
    if len(closes) < 2:
        return 50.0
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    avg_gain = sum(gains[-period:]) / period if len(gains) >= period else sum(gains) / len(gains)
    avg_loss = sum(losses[-period:]) / period if len(losses) >= period else sum(losses) / len(losses)
    rs = avg_gain / avg_loss if avg_loss else 0
    return round(100 - 100 / (1 + rs), 1)


def _weekly_features(closes: list[float]) -> list[dict]:
    """
    逐周（5 个交易日步长）计算历史特征:
    RSI(14)、30 日动量（小数形式）、后 5 个交易日方向（±1% 分 up/flat/down）。
    末尾不足"后 5 日"的数据不产出窗口。
    """
    weeks = []
    for end in range(30, len(closes) - 5, 5):
        rsi = _rsi(closes[: end + 1])
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
