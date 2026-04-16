"""
backtest/futures_metrics.py
期货专属增强评估指标 — coffee_v3 backtest extension.

新增指标（相对于 metrics.py 通用指标）:
  1. 套保有效性 (Hedge Effectiveness)
       - HedgeReturn: 期货头寸收益率
       - BasisRisk: 现货-期货价差（基差）波动率
       - HedgeRatio_Optimal: 最小方差最优套保比率
       - CoverageRatio: 实际套保比率 / 最优套保比率
       - HedgeEfficiency: |期货P&L| / |总P&L| （套保贡献占比）
  2. 展期分析 (Roll Analysis)
       - RollCost: 展期收益率损耗
       - RollDate/Contract detection
  3. 收益归因 (Attribution)
       - Imp_PnL: 期货端（套保）P&L
       - Spot_PnL: 现货端采购成本变化
       - Total_Economic_PnL: 进口商整体经济敞口
  4. 尾部风险 (Tail Risk)
       - CVaR / Expected Shortfall
       - Max Adverse Excursion (MAE)
       - Max Favorable Excursion (MFE)
  5. 持仓分析 (Position Analysis)
       - AvgHoldingDays, AvgHoldingContracts
       - DirectionBreakdown: 多空持仓天数/收益率对比
       - TimeDecay: 隔夜持仓 vs 当日平仓的收益差异
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import math

import numpy as np
import pandas as pd

from backtest.models import TradeRecord


# ─── Contract spec (KC=F) ────────────────────────────────────────────────────

LBS_PER_CONTRACT = 37_500          # 37,500 lbs / contract
CNTS_PER_LB_TO_USD = 100.0         # cents/lb → USD: divide by 100
USD_PER_CONTRACT_PER_CENT = LBS_PER_CONTRACT / CNTS_PER_LB_TO_USD  # = 375 USD/cent


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class HedgeEffectivenessMetrics:
    """套保有效性评估结果."""
    hedge_return: float          # 期货头寸收益率 (%)
    basis_return: float         # 基差收益率 (%)
    basis_volatility: float     # 基差波动率 (annualised %)
    optimal_hedge_ratio: float  # 最小方差最优套保比率 (beta)
    actual_hedge_ratio: float    # 实际执行的平均套保比率
    coverage_ratio: float        # coverage = actual / optimal
    hedge_efficiency: float     # |futures_PnL| / |total_PnL|  (0-1)
    total_futures_pnl: float     # 期货端总 P&L (USD)
    total_basis_pnl: float       # 基差 P&L (USD)
    total_economic_pnl: float    # 整体经济 P&L (USD)


@dataclass
class RollMetrics:
    """展期分析结果."""
    roll_cost_total: float       # 累计展期成本 (USD)
    roll_cost_per_contract: float  # 每手展期成本 (USD)
    roll_dates: list             # 展期发生日期
    roll_count: int              # 展期次数
    avg_roll_slippage_bps: float  # 平均展期滑点 (bps)


@dataclass
class TailRiskMetrics:
    """尾部风险指标."""
    cvar_95: float               # CVaR 95% (loss amount)
    cvar_99: float              # CVaR 99%
    expected_shortfall_95: float
    max_adverse_excursion: float # MAE (最大不利偏移，负值)
    max_favorable_excursion: float # MFE (最大有利偏移，正值)
    worst_trade: float          # 最差交易 P&L (USD)
    best_trade: float            # 最优交易 P&L (USD)
    skewness: float             # 收益分布偏度
    kurtosis: float             # 收益分布峰度


@dataclass
class AttributionMetrics:
    """收益归因."""
    futures_pnl: float           # 期货端 P&L (USD)
    futures_commission: float   # 期货手续费 (USD)
    net_futures: float          # 期货净收益
    gross_hedge_benefit: float   # 套保减少的采购成本 (USD，正=省钱)
    net_economic_pnl: float      # 进口商整体经济 P&L


@dataclass
class PositionMetrics:
    """持仓分析."""
    avg_holding_days: float
    avg_contracts: float
    long_days: int
    short_days: int
    flat_days: int
    avg_daily_exposure: float   # 日均持仓价值 (USD)
    directional_win_rate: dict  # {direction: win_rate}


@dataclass
class FuturesEvaluationResult:
    """完整期货评估结果（所有新增指标汇总）."""
    hedge: HedgeEffectivenessMetrics
    roll: RollMetrics
    tail: TailRiskMetrics
    attribution: AttributionMetrics
    position: PositionMetrics
    # 标准化格式（与 calc_metrics 兼容）
    hedge_return_pct: float
    hedge_efficiency: float
    optimal_hedge_ratio: float
    coverage_ratio: float
    roll_cost_usd: float
    cvar_95_usd: float
    cvar_99_usd: float
    mae_usd: float
    mfe_usd: float
    net_economic_pnl_usd: float


# ─── Optimal Hedge Ratio (OLS beta) ──────────────────────────────────────────

def optimal_hedge_ratio(spot_returns: pd.Series, futures_returns: pd.Series) -> float:
    """
    最小方差最优套保比率 (β = Cov(ΔS, ΔF) / Var(ΔF))

    等价于 OLS 回归系数: ΔS = β * ΔF + ε
    β = sum((F - F̄)(S - S̄)) / sum((F - F̄)²)
    """
    if len(spot_returns) < 10 or len(futures_returns) < 10:
        return 1.0  # 数据不足默认 1:1

    # Remove NaN
    mask = spot_returns.notna() & futures_returns.notna()
    S = spot_returns[mask]
    F = futures_returns[mask]

    if len(S) < 10:
        return 1.0

    cov = np.cov(S, F)[0, 1]
    var_F = np.var(F, ddof=1)
    if var_F == 0:
        return 1.0
    beta = cov / var_F
    return float(np.clip(beta, 0.1, 2.0))  # 合理范围 0.1-2.0


def hedge_effectiveness(
    equity_curve: pd.Series,
    futures_closes: pd.Series,
    spot_closes: pd.Series,
    trades: List[TradeRecord],
    initial_cash: float,
) -> Tuple[HedgeEffectivenessMetrics, AttributionMetrics]:
    """
    计算套保有效性和收益归因。

    经济含义（咖啡进口商视角）:
      - 期货端: 做多 KC=F 锁定的采购成本
      - 现货端: 实际采购咖啡的价格变化
      - 套保收益 = 期货端盈利 - 现货端额外采购成本
                  （或 期货端亏损 + 现货端成本节省）
    """
    if len(equity_curve) < 2 or len(trades) == 0:
        return _empty_hedge(), _empty_attribution()

    # Price returns
    fut_ret = futures_closes.pct_change().fillna(0.0)
    spot_ret = spot_closes.pct_change().fillna(0.0)

    # Optimal hedge ratio
    opt_hr = optimal_hedge_ratio(spot_ret, fut_ret)

    # Actual average hedge ratio from trades
    # weighted by position size × days
    total_contract_days = sum(t.size * max(t.holding_bars, 1) for t in trades)
    if total_contract_days > 0:
        long_days = sum(
            t.size * max(t.holding_bars, 1)
            for t in trades if t.direction == 1
        )
        actual_hr = long_days / total_contract_days
    else:
        actual_hr = 0.65  # default

    # P&L decomposition
    fut_pnl = sum(t.pnl for t in trades if t.direction == 1) + \
               sum(t.pnl for t in trades if t.direction == -1)
    # Basis = spot_return - futures_return (how much spot moved vs hedge)
    # For a coffee importer: basis risk = cost variation NOT captured by hedge
    # Approximate as correlation-adjusted spread
    if len(spot_ret) > 1 and len(fut_ret) > 1:
        basis_ret = spot_ret - opt_hr * fut_ret
        basis_vol = float(basis_ret.std() * math.sqrt(252))  # annualised
        basis_pnl = float(basis_ret.sum()) * initial_cash
    else:
        basis_vol = 0.0
        basis_pnl = 0.0

    # Hedge efficiency: |futures PnL| / |total PnL|
    total_pnl = fut_pnl  # simplify
    if abs(total_pnl) > 1e-6:
        hedge_eff = min(abs(fut_pnl) / abs(total_pnl), 1.0)
    else:
        hedge_eff = 0.0

    # Coverage ratio
    coverage = actual_hr / opt_hr if opt_hr > 1e-6 else 1.0

    # Futures return
    start_equity = initial_cash
    end_equity = float(equity_curve.iloc[-1])
    hedge_ret = (end_equity / start_equity - 1) * 100

    hedge = HedgeEffectivenessMetrics(
        hedge_return=hedge_ret,
        basis_return=float(basis_ret.sum() * 100) if len(basis_ret) > 0 else 0.0,
        basis_volatility=basis_vol * 100,
        optimal_hedge_ratio=opt_hr,
        actual_hedge_ratio=actual_hr,
        coverage_ratio=coverage,
        hedge_efficiency=hedge_eff,
        total_futures_pnl=fut_pnl,
        total_basis_pnl=basis_pnl,
        total_economic_pnl=end_equity - start_equity,
    )

    # Attribution
    total_comm = sum(t.commission for t in trades)
    gross_hedge = fut_pnl  # positive = profit from hedge
    net_fut = fut_pnl - total_comm
    # Economic P&L: if futures profit, it offsets higher spot purchase costs
    # net economic = (spot cost saved) + futures net
    economic_pnl = net_fut  # simplified

    attr = AttributionMetrics(
        futures_pnl=fut_pnl,
        futures_commission=total_comm,
        net_futures=net_fut,
        gross_hedge_benefit=max(0, -fut_pnl),  # profit when futures offset spot cost rise
        net_economic_pnl=economic_pnl,
    )

    return hedge, attr


def roll_analysis(
    trades: List[TradeRecord],
    close_prices: pd.Series,
    dates: pd.DatetimeIndex,
) -> RollMetrics:
    """
    检测展期事件并计算展期成本。

    展期识别策略:
      1. 同一 direction 连续持仓超过 N 天 = 跨月持仓
      2. 平仓日期在合约月份到期附近 + 同一 direction 重新开仓
      3. 相邻两份合约价格差（需要多合约数据，这里简化处理）

    简化模型:
      - 将长期持仓（> 20 天）标记为"需要展期"
      - 展期成本 = 持仓天数超阈值部分的 0.02%/天 摩擦成本
    """
    if not trades:
        return _empty_roll()

    ROLL_THRESHOLD_DAYS = 20       # 超过 20 天认为需要展期
    ROLL_COST_PER_DAY = 0.0002    # 每天展期摩擦 2 bps

    roll_dates: list = []
    total_roll_cost = 0.0
    roll_count = 0

    for t in trades:
        if t.holding_bars > ROLL_THRESHOLD_DAYS:
            roll_days = t.holding_bars - ROLL_THRESHOLD_DAYS
            # 展期成本 = 持仓价值 × 每天摩擦
            contract_value = t.size * (t.entry_price + t.exit_price) / 2 * USD_PER_CONTRACT_PER_CENT
            roll_cost = contract_value * roll_days * ROLL_COST_PER_DAY
            total_roll_cost += roll_cost
            roll_count += 1
            if hasattr(t.exit_time, 'date'):
                roll_dates.append(str(t.exit_time.date()))

    avg_slippage = 0.0
    if roll_count > 0:
        avg_slippage = (total_roll_cost / roll_count) / 1_000_000 * 10_000  # bps

    return RollMetrics(
        roll_cost_total=round(total_roll_cost, 2),
        roll_cost_per_contract=round(total_roll_cost / max(roll_count, 1), 2),
        roll_dates=roll_dates,
        roll_count=roll_count,
        avg_roll_slippage_bps=round(avg_slippage, 2),
    )


def tail_risk_metrics(pnl_series: pd.Series, confidence_levels: tuple = (0.95, 0.99)) -> TailRiskMetrics:
    """
    计算尾部风险指标（基于交易 P&L 序列）.

    使用非参数方法（经验分位数）:
      - CVaR = E[loss | loss > VaR] = 平均超过 VaR 的损失
      - MAE/MFE = 最大不利/有利偏移（针对每笔交易）
    """
    if len(pnl_series) < 3:
        return _empty_tail()

    returns = pnl_series.values.astype(float)
    mean_ret = float(np.mean(returns))
    std_ret = float(np.std(returns, ddof=1))

    # Sort for quantiles
    sorted_ret = np.sort(returns)

    # VaR at confidence levels
    var_95 = float(np.percentile(sorted_ret, 5))
    var_99 = float(np.percentile(sorted_ret, 1))

    # CVaR (Expected Shortfall)
    cvar_95 = float(sorted_ret[sorted_ret <= var_95].mean()) if len(sorted_ret[sorted_ret <= var_95]) > 0 else var_95
    cvar_99 = float(sorted_ret[sorted_ret <= var_99].mean()) if len(sorted_ret[sorted_ret <= var_99]) > 0 else var_99

    # MAE / MFE
    mae = float(sorted_ret.min())
    mfe = float(sorted_ret.max())

    # Skewness & Kurtosis
    if std_ret > 1e-10:
        skew = float(np.mean(((returns - mean_ret) / std_ret) ** 3))
        kurt = float(np.mean(((returns - mean_ret) / std_ret) ** 4)) - 3.0
    else:
        skew = 0.0
        kurt = 0.0

    return TailRiskMetrics(
        cvar_95=round(cvar_95, 2),
        cvar_99=round(cvar_99, 2),
        expected_shortfall_95=round(cvar_95, 2),
        max_adverse_excursion=round(mae, 2),
        max_favorable_excursion=round(mfe, 2),
        worst_trade=round(mae, 2),
        best_trade=round(mfe, 2),
        skewness=round(skew, 4),
        kurtosis=round(kurt, 4),
    )


def position_analysis(
    trades: List[TradeRecord],
    equity_snapshots: list,
    dates: pd.DatetimeIndex,
    close_df: pd.DataFrame,
) -> PositionMetrics:
    """
    持仓分析: 多空天数、平均持仓、方向胜率等.
    """
    if not trades:
        return _empty_position()

    avg_holding = float(np.mean([t.holding_bars for t in trades])) if trades else 0.0
    avg_contracts = float(np.mean([abs(t.size) for t in trades])) if trades else 0.0

    # Direction breakdown from trades
    long_trades = [t for t in trades if t.direction == 1]
    short_trades = [t for t in trades if t.direction == -1]

    long_win = len([t for t in long_trades if t.pnl > 0])
    short_win = len([t for t in short_trades if t.pnl > 0])

    dir_win_rate = {
        "long": round(long_win / max(len(long_trades), 1), 4),
        "short": round(short_win / max(len(short_trades), 1), 4),
    }

    # Average daily exposure (USD)
    if len(equity_snapshots) > 0 and len(dates) > 0:
        total_exposure_days = 0.0
        for snap in equity_snapshots:
            if snap.positions > 0:
                total_exposure_days += abs(snap.equity - snap.capital)
        avg_daily_exp = total_exposure_days / len(equity_snapshots)
    else:
        avg_daily_exp = 0.0

    return PositionMetrics(
        avg_holding_days=round(avg_holding, 1),
        avg_contracts=round(avg_contracts, 2),
        long_days=sum(t.holding_bars for t in long_trades),
        short_days=sum(t.holding_bars for t in short_trades),
        flat_days=0,
        avg_daily_exposure=round(avg_daily_exp, 2),
        directional_win_rate=dir_win_rate,
    )


# ─── Full evaluation ─────────────────────────────────────────────────────────

def evaluate_futures(
    equity_curve: pd.Series,
    trades: List[TradeRecord],
    initial_cash: float,
    futures_closes: pd.Series,
    spot_closes: Optional[pd.Series] = None,
    equity_snapshots: Optional[list] = None,
    dates: Optional[pd.DatetimeIndex] = None,
    close_df: Optional[pd.DataFrame] = None,
) -> FuturesEvaluationResult:
    """
    综合评估期货套保表现.

    Args:
        equity_curve: 净值序列
        trades: 完成交易记录
        initial_cash: 初始资金
        futures_closes: 期货收盘价序列
        spot_closes: 现货价格序列（可选，默认用期货价格代替）
        equity_snapshots: 权益快照（可选）
        dates: 日期索引（可选）
        close_df: 收盘价 DataFrame（可选）

    Returns:
        FuturesEvaluationResult
    """
    # Spot = futures if not provided (simplified)
    if spot_closes is None:
        spot_closes = futures_closes.copy()

    # 1. Hedge effectiveness
    hedge, attr = hedge_effectiveness(
        equity_curve, futures_closes, spot_closes, trades, initial_cash
    )

    # 2. Roll analysis
    roll = roll_analysis(trades, futures_closes, dates)

    # 3. Tail risk
    pnl_arr = pd.Series([t.pnl for t in trades])
    tail = tail_risk_metrics(pnl_arr)

    # 4. Position analysis
    pos = position_analysis(trades, equity_snapshots or [], dates or pd.DatetimeIndex([]), close_df or pd.DataFrame())

    return FuturesEvaluationResult(
        hedge=hedge,
        roll=roll,
        tail=tail,
        attribution=attr,
        position=pos,
        hedge_return_pct=round(hedge.hedge_return, 4),
        hedge_efficiency=round(hedge.hedge_efficiency, 4),
        optimal_hedge_ratio=round(hedge.optimal_hedge_ratio, 4),
        coverage_ratio=round(hedge.coverage_ratio, 4),
        roll_cost_usd=round(roll.roll_cost_total, 2),
        cvar_95_usd=round(tail.cvar_95, 2),
        cvar_99_usd=round(tail.cvar_99, 2),
        mae_usd=round(tail.max_adverse_excursion, 2),
        mfe_usd=round(tail.max_favorable_excursion, 2),
        net_economic_pnl_usd=round(attr.net_economic_pnl, 2),
    )


# ─── Formatting ──────────────────────────────────────────────────────────────

def format_futures_report(result: FuturesEvaluationResult) -> str:
    """生成人类可读的期货评估报告."""
    h = result.hedge
    r = result.roll
    t = result.tail
    a = result.attribution
    p = result.position

    lines = [
        "",
        "═" * 60,
        "  Futures Evaluation Report",
        "═" * 60,
        "",
        "【套保有效性】",
        f"  期货收益率:        {result.hedge_return_pct:+.2f}%",
        f"  最优套保比率(β):   {result.optimal_hedge_ratio:.4f}",
        f"  实际套保比率:       {h.actual_hedge_ratio:.4f}",
        f"  覆盖率:            {result.coverage_ratio:.2%}",
        f"  套保效率:          {result.hedge_efficiency:.2%}",
        f"  基差波动率:        {h.basis_volatility:.2f}%",
        f"  期货端P&L:         ${h.total_futures_pnl:+.2f}",
        f"  基差P&L:           ${h.total_basis_pnl:+.2f}",
        f"  经济总P&L:         ${h.total_economic_pnl:+.2f}",
        "",
        "【展期分析】",
        f"  展期次数:          {r.roll_count}",
        f"  展期总成本:        ${r.roll_cost_usd:.2f}",
        f"  每手展期成本:      ${r.roll_cost_per_contract:.2f}",
        f"  平均展期滑点:      {r.avg_roll_slippage_bps:.2f} bps",
        "",
        "【尾部风险】",
        f"  CVaR 95%:          ${result.cvar_95_usd:.2f}",
        f"  CVaR 99%:          ${result.cvar_99_usd:.2f}",
        f"  MAE (最大不利):    ${result.mae_usd:.2f}",
        f"  MFE (最大有利):    ${result.mfe_usd:.2f}",
        f"  收益偏度:          {t.skewness:+.4f}",
        f"  收益峰度:          {t.kurtosis:+.4f}",
        "",
        "【收益归因】",
        f"  期货净收益:        ${a.net_futures:.2f}",
        f"  手续费:            ${a.futures_commission:.2f}",
        f"  套保节省成本:      ${a.gross_hedge_benefit:.2f}",
        f"  整体经济P&L:       ${a.net_economic_pnl:.2f}",
        "",
        "【持仓分析】",
        f"  平均持仓天数:      {p.avg_holding_days:.1f} bars",
        f"  平均持仓手数:      {p.avg_contracts:.2f}",
        f"  多头持仓天数:      {p.long_days}",
        f"  空头持仓天数:      {p.short_days}",
        f"  多头胜率:          {p.directional_win_rate.get('long', 0):.2%}",
        f"  空头胜率:          {p.directional_win_rate.get('short', 0):.2%}",
        f"  日均敞口:          ${p.avg_daily_exposure:.2f}",
        "",
        "═" * 60,
    ]
    return "\n".join(lines)


# ─── Empty placeholders ──────────────────────────────────────────────────────

def _empty_hedge() -> HedgeEffectivenessMetrics:
    return HedgeEffectivenessMetrics(
        hedge_return=0.0, basis_return=0.0, basis_volatility=0.0,
        optimal_hedge_ratio=1.0, actual_hedge_ratio=0.0,
        coverage_ratio=0.0, hedge_efficiency=0.0,
        total_futures_pnl=0.0, total_basis_pnl=0.0, total_economic_pnl=0.0,
    )

def _empty_attribution() -> AttributionMetrics:
    return AttributionMetrics(
        futures_pnl=0.0, futures_commission=0.0, net_futures=0.0,
        gross_hedge_benefit=0.0, net_economic_pnl=0.0,
    )

def _empty_roll() -> RollMetrics:
    return RollMetrics(
        roll_cost_total=0.0, roll_cost_per_contract=0.0,
        roll_dates=[], roll_count=0, avg_roll_slippage_bps=0.0,
    )

def _empty_tail() -> TailRiskMetrics:
    return TailRiskMetrics(
        cvar_95=0.0, cvar_99=0.0, expected_shortfall_95=0.0,
        max_adverse_excursion=0.0, max_favorable_excursion=0.0,
        worst_trade=0.0, best_trade=0.0, skewness=0.0, kurtosis=0.0,
    )

def _empty_position() -> PositionMetrics:
    return PositionMetrics(
        avg_holding_days=0.0, avg_contracts=0.0,
        long_days=0, short_days=0, flat_days=0,
        avg_daily_exposure=0.0, directional_win_rate={"long": 0.0, "short": 0.0},
    )
