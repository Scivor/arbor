"""
backtest/exchange.py
Qlib 风格 Exchange — Coffee V3.0 P0 借鉴

关键改进（对比原 engine.py）:
1. 双向手续费: 开仓 + 平仓分开计费
2. Cash limit: 资金不足时自动裁剪订单，不直接拒绝
3. Critical price 公式: 费用=min_cost 时反推最大可交易量
4. 滑点模型: deal_price = mid_price * (1 + slippage_bps * direction)
5. Volume limit: CME 咖啡期货日均成交量限制，防止流动性冲击
6. 部分成交: 订单量 > 成交量限制时按比例成交
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import math

import numpy as np


class OrderDir(Enum):
    BUY = 1   # 买入套保（做多期货，对冲采购成本上涨）
    SELL = -1 # 卖出套保（做空期货）


@dataclass
class Order:
    """订单"""
    stock_id: str           # 合约代码，如 "KC=F"
    amount: float           # 数量（吨），正数表示开仓/增仓
    direction: OrderDir
    start_time: datetime
    end_time: datetime
    # 以下字段由 Exchange 成交时填充
    deal_amount: float = 0.0
    deal_price: float = 0.0
    factor: float = 1.0     # 合约乘数因子


@dataclass
class Account:
    """
    账户 — 参考 Qlib Account + AccumulatedInfo
    累计追踪: 收益(rtn)、费用(cost)、换手(turnover)
    """
    initial_equity: float
    current_equity: float = 0.0
    # 累计指标
    total_return: float = 0.0    # 累计收益（不含费用）
    total_cost: float = 0.0      # 累计费用
    total_turnover: float = 0.0 # 累计换手（买入+卖出）

    def __post_init__(self):
        self.current_equity = self.initial_equity

    def update_order(self, order: Order, trade_val: float, cost: float, trade_price: float):
        """订单成交后更新账户

        注意: deal_amount 和 deal_price 已在 _calc_trade_info_by_order 中写入 order 对象。

        期货套保语义（不同于 Qlib 股票语义）:
        - 买入开仓: 支付手续费（margin 单独处理）
        - 卖出平仓: 收到货款 - 手续费 = 净收现金
        - trade_val 仅用于计算 PnL，不从 equity 扣减（margin 是另一层）
        """
        if order.direction == OrderDir.BUY:
            # 买入：扣除手续费
            self.current_equity -= cost
        else:
            # 卖出：收到货款 - 手续费 = 净收现金
            self.current_equity += trade_val - cost

        self.total_cost += cost
        self.total_turnover += abs(trade_val)  # 累计换手（仅统计用）

    def update_market_to_market(self, unrealized_pnl: float):
        """每日盯市更新未实现盈亏"""
        self.current_equity = self.initial_equity + self.total_return + unrealized_pnl

    @property
    def leverage(self) -> float:
        """当前杠杆率"""
        return max(0, abs(self.total_turnover) / max(1, self.current_equity))


@dataclass
class ExchangeConfig:
    """
    Exchange 配置 — 对应 Qlib Exchange.__init__ 参数

    咖啡期货 (KC=F) 参数:
    - CME 咖啡每张合约 = 37,500 lbs = 17.01 t
    - 典型日内买卖手续费: $25-50/round-trip (约 $1.4-2.8/吨)
    """
    freq: str = "day"
    # 成交价
    deal_price_type: str = "$close"   # "$close", "$open", "$mid"
    # 手续费
    open_cost: float = 1.5            # 开仓费率 (% of trade_val)
    close_cost: float = 1.5           # 平仓费率 (% of trade_val)
    min_cost: float = 30.0            # 每笔最低手续费 (USD)
    # 滑点 (basis points, 100bps = 1%)
    slippage_bps: float = 1.0         # 单边滑点 1bps ≈ $0.0002/lb
    # 资金限制
    cash_limit_enabled: bool = True
    # 流动性限制
    volume_limit_pct: float = 0.05   # 单笔不超过日成交量的 5%
    # 涨跌停（咖啡期货无日内限制，但可设预警线）
    limit_threshold: Optional[float] = None


class CoffeeExchange:
    """
    Qlib 风格 Exchange — 负责订单撮合与费用计算

    核心流程:
        order → check_order() → _calc_trade_info_by_order() → Account.update_order()
                                      ↓
                              deal_price, trade_val, trade_cost
    """

    def __init__(self, config: ExchangeConfig, price_df: 'pd.DataFrame'):
        """
        Args:
            config: Exchange 配置
            price_df: 价格数据，必须包含 $close, $open, $volume 列
                     index=datetime, columns=[close, open, volume, ...]
        """
        self.cfg = config
        self._df = price_df
        self.logger = _SimpleLogger()

        # 从 df 提取日均成交量用于 volume limit
        if '$volume' in self._df.columns:
            self._avg_daily_volume = float(self._df['$volume'].mean())
        elif 'volume' in self._df.columns:
            self._avg_daily_volume = float(self._df['volume'].mean())
        else:
            self._avg_daily_volume = 1000  # 默认值（吨）

    # ─────────────────────────────────────────────────────────────
    # 公开 API
    # ─────────────────────────────────────────────────────────────

    def deal_order(
        self,
        order: Order,
        trade_account: Optional[Account] = None,
    ) -> tuple[float, float, float]:
        """
        成交订单（参考 Qlib Exchange.deal_order）

        Returns:
            (trade_val, trade_cost, trade_price)
            - trade_val:    成交金额 (USD)
            - trade_cost:   手续费 (USD)
            - trade_price:  成交价 (cents/lb)
        """
        if not self._check_order(order):
            order.deal_amount = 0.0
            self.logger.debug(f"Order rejected: {order}")
            return 0.0, 0.0, float('nan')

        trade_price, trade_val, trade_cost = self._calc_trade_info_by_order(
            order, trade_account
        )

        if trade_val > 1e-5 and trade_account is not None:
            trade_account.update_order(order, trade_val, trade_cost, trade_price)

        return trade_val, trade_cost, trade_price

    def is_tradable(self, stock_id: str, dt: datetime, direction: OrderDir = OrderDir.BUY) -> bool:
        """检查某时刻是否可交易"""
        if stock_id not in self._df.index:
            return False
        row = self._df.loc[stock_id] if stock_id in self._df.index else self._df.iloc[self._df.index.get_loc(dt)]
        # 咖啡期货无涨跌停，永远可交易
        return True

    def get_deal_price(
        self, stock_id: str, dt: datetime, direction: OrderDir
    ) -> float:
        """获取成交价（含滑点）"""
        row = self._df.iloc[self._df.index.get_loc(dt)]
        price_type = self.cfg.deal_price_type

        if price_type == "$mid":
            # mid = (open + close) / 2
            open_key = 'open' if 'open' in row else '$open'
            close_key = 'close' if 'close' in row else '$close'
            mid = (float(row.get(open_key, 0)) + float(row.get(close_key, 0))) / 2
        else:
            key = price_type.lstrip('$')
            mid = float(row.get(key, row.get(price_type, 0)))

        # 滑点：买单略微抬高（+），卖单略微压低（-）
        slippage = self.cfg.slippage_bps / 10000.0
        deal_price = mid * (1 + slippage * direction.value)
        return deal_price

    def get_close(self, stock_id: str, dt: datetime) -> float:
        """获取收盘价（无滑点）"""
        row = self._df.iloc[self._df.index.get_loc(dt)]
        return float(row.get('close', row.get('$close', 0)))

    def get_volume(self, stock_id: str, dt: datetime) -> float:
        """获取成交量（吨）。df 索引是 datetime，不用 stock_id"""
        row = self._df.iloc[self._df.index.get_loc(dt)]
        return float(row.get('volume', 0))

    # ─────────────────────────────────────────────────────────────
    # 内部方法（参考 Qlib Exchange）
    # ─────────────────────────────────────────────────────────────

    def _check_order(self, order: Order) -> bool:
        """订单前置检查"""
        if order.amount <= 0:
            return False
        try:
            self._df.index.get_loc(order.start_time)
        except KeyError:
            return False
        return True

    def _calc_trade_info_by_order(
        self, order: Order, account: Optional[Account]
    ) -> tuple[float, float, float]:
        """
        计算订单的实际成交信息（参考 Qlib Exchange._calc_trade_info_by_order）

        核心算法:
        1. 获取成交价（含滑点）
        2. 按资金限制裁剪订单量
        3. 按成交量限制裁剪订单量
        4. 计算 trade_val
        5. 计算 trade_cost（开仓费率 + 平仓费率 + min_cost）
        """
        cfg = self.cfg

        # 1. 成交价（含滑点）
        trade_price = self.get_deal_price(
            order.stock_id, order.start_time, order.direction
        )

        # 2. 目标成交量（吨）
        target_amount = order.amount  # 吨

        # 3. 资金限制裁剪
        if cfg.cash_limit_enabled and account is not None:
            cost_ratio = (cfg.open_cost + cfg.close_cost) / 100.0
            max_by_cash = self._get_buy_amount_by_cash_limit(
                trade_price=trade_price,
                cash=account.current_equity,
                cost_ratio=cost_ratio,
                direction=order.direction,
            )
            target_amount = min(target_amount, max_by_cash)
            if target_amount <= 0:
                order.deal_amount = 0.0
                return 0.0, 0.0, trade_price

        # 4. 成交量限制裁剪（防止流动性冲击）
        daily_vol = self.get_volume(order.stock_id, order.start_time)
        if daily_vol > 0 and cfg.volume_limit_pct > 0:
            max_by_vol = daily_vol * cfg.volume_limit_pct
            target_amount = min(target_amount, max_by_vol)
            if target_amount <= 0:
                order.deal_amount = 0.0
                return 0.0, 0.0, trade_price

        # 5. 取整到合约最小单位（咖啡期货 1 contract = 17.01 t）
        #    向下取整，避免超出
        target_amount = math.floor(target_amount)
        order.deal_amount = target_amount
        order.deal_price = trade_price  # 同步成交价到 order 对象

        # 6. 计算 trade_val (USD)
        #    KC=F 价格单位是 cents/lb → 转换成 USD/lb → 乘以 lbs
        #    1 ton = 2204.62 lbs
        trade_val = target_amount * 2204.62 * trade_price / 100.0

        # 7. 计算 trade_cost
        open_fee = trade_val * (cfg.open_cost / 100.0)
        close_fee = trade_val * (cfg.close_cost / 100.0)
        trade_cost = max(open_fee + close_fee, cfg.min_cost)

        return trade_price, trade_val, trade_cost

    def _get_buy_amount_by_cash_limit(
        self,
        trade_price: float,
        cash: float,
        cost_ratio: float,
        direction: OrderDir,
    ) -> float:
        """
        根据资金限制计算最大可买入数量（参考 Qlib _get_buy_amount_by_cash_limit）

        公式:
        若 cash >= critical_price:
            max_amount = cash / (1 + cost_ratio) / trade_price
        若 cash < critical_price:
            max_amount = (cash - min_cost) / trade_price

        其中 critical_price = min_cost / cost_ratio + min_cost
        """
        cfg = self.cfg

        if cash < cfg.min_cost:
            return 0.0

        # critical_price: 手续费等于 min_cost 时的价格
        # cost_ratio * trade_val = min_cost → trade_val = min_cost / cost_ratio
        # 总占用 = trade_val + cost = trade_val * (1 + cost_ratio) = min_cost / cost_ratio * (1 + cost_ratio)
        # = min_cost / cost_ratio + min_cost
        if cost_ratio > 0:
            critical_price = cfg.min_cost / cost_ratio + cfg.min_cost
        else:
            critical_price = float('inf')

        if cash >= critical_price:
            # 费用按比例计算
            # cash = trade_val + trade_val * cost_ratio + margin
            # 简化：cash ≈ trade_val * (1 + cost_ratio)
            max_trade_val = cash / (1 + cost_ratio)
        else:
            # 费用等于 min_cost（固定）
            max_trade_val = cash - cfg.min_cost

        if trade_price <= 1e-8:
            return 0.0

        max_amount = max_trade_val * 100.0 / (trade_price * 2204.62)
        return max(max_amount, 0.0)


class _SimpleLogger:
    """最简日志"""
    def debug(self, msg): pass
    def info(self, msg): print(f"[Exchange] {msg}")
    def warning(self, msg): print(f"[Exchange WARN] {msg}")
