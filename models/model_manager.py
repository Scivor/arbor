"""
models/model_manager.py
模型管理 — 训练/保存/加载/回测

功能:
1. 训练并保存模型
2. 加载已有模型
3. 回测模型建议 vs 静态套保
4. 定期自动重训练
"""

from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path

_proj_root = _Path(__file__).parent.parent
if str(_proj_root) not in _sys.path:
    _sys.path.insert(0, str(_proj_root))

import numpy as np
import pandas as pd
import json
import pickle
from datetime import datetime, date
from typing import Optional

from models.hedge_model import HedgeModel, HedgeRecommendation
from models.features import FeatureEngine
from backtest.loader import HistoryLoader
from sources.climate.noaa_oni import ONIScraper
from core.persistence import DecisionDB


MODEL_DIR = _Path('~/.coffee_v3/models').expanduser()
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MODEL_FILE = MODEL_DIR / 'hedge_model.pkl'
META_FILE = MODEL_DIR / 'model_meta.json'


class ModelManager:
    """
    模型生命周期管理

    用法:
        mgr = ModelManager()
        mgr.fit()              # 训练
        mgr.save()             # 保存
        mgr.load()             # 加载
        rec = mgr.recommend(price=285, tons=100)  # 推荐
        report = mgr.backtest()  # 回测
    """

    def __init__(self):
        self.model: Optional[HedgeModel] = None
        self.feature_engine: Optional[FeatureEngine] = None
        self.meta: dict = {}
        self._loaded = False

    def fit(
        self,
        start: str = '2015-01-01',
        end: str = '2024-12-31',
        test_size: float = 0.2,
        verbose: bool = True,
    ) -> dict:
        """训练新模型"""
        if verbose:
            print(f'Training model: {start} → {end}')

        loader = HistoryLoader()
        price_df = loader.load_kc_futures(start, end)

        scraper = ONIScraper()
        oni_df = scraper.fetch()

        self.model = HedgeModel()
        self.feature_engine = self.model.feature_engine

        report = self.model.fit(price_df, oni_df, test_size=test_size, verbose=verbose)

        self.meta = {
            'trained_at': datetime.now().isoformat(),
            'train_start': start,
            'train_end': end,
            'test_size': test_size,
            'report': {k: float(v) if isinstance(v, (np.floating, np.integer)) else v
                       for k, v in report.items()},
            'n_samples': len(price_df),
        }

        self._loaded = True
        return report

    def save(self, path: Optional[_Path] = None) -> str:
        """保存模型到磁盘"""
        if self.model is None:
            raise RuntimeError('No model to save. Call fit() or load() first.')

        model_path = path or MODEL_FILE
        model_path.parent.mkdir(parents=True, exist_ok=True)

        # 保存模型
        with open(model_path, 'wb') as f:
            pickle.dump({
                'clf_weights': self.model._clf.weights,
                'clf_bias': self.model._clf.bias,
                'reg_weights': self.model._reg.weights,
                'reg_intercept': self.model._reg.intercept,
                'scaler_mean': self.model.feature_engine._scaler.mean,
                'scaler_std': self.model.feature_engine._scaler.std,
                'feature_names': self.model._feature_names,
                'fitted': self.model._fitted,
            }, f)

        # 保存元数据
        meta_path = model_path.with_suffix('.meta.json')
        with open(meta_path, 'w') as f:
            json.dump(self.meta, f, indent=2)

        return str(model_path)

    def load(self, path: Optional[_Path] = None) -> bool:
        """从磁盘加载模型"""
        model_path = path or MODEL_FILE
        meta_path = model_path.with_suffix('.meta.json')

        if not model_path.exists():
            if not MODEL_FILE.exists():
                return False
            model_path = MODEL_FILE
            meta_path = MODEL_FILE.with_suffix('.meta.json')

        # 加载权重
        with open(model_path, 'rb') as f:
            state = pickle.load(f)

        # 重建模型
        from models.hedge_model import SimpleLogisticRegression, SimpleRidgeRegression
        from models.features import ManualScaler

        self.model = HedgeModel()
        self.feature_engine = self.model.feature_engine

        self.model._clf = SimpleLogisticRegression()
        self.model._clf.weights = state['clf_weights']
        self.model._clf.bias = state['clf_bias']

        self.model._reg = SimpleRidgeRegression()
        self.model._reg.weights = state['reg_weights']
        self.model._reg.intercept = state['reg_intercept']

        scaler = ManualScaler()
        scaler.mean = state['scaler_mean']
        scaler.std = state['scaler_std']
        self.model.feature_engine._scaler = scaler
        self.model.feature_engine._fitted = True

        self.model._feature_names = state['feature_names']
        self.model._fitted = state['fitted']

        # 加载元数据
        if meta_path.exists():
            with open(meta_path) as f:
                self.meta = json.load(f)

        self._loaded = True
        return True

    def recommend(
        self,
        current_price: float,
        total_tons: float,
        as_of: Optional[datetime] = None,
    ) -> HedgeRecommendation:
        """
        获取当前套保推荐

        Args:
            current_price: 当前 KC=F 价格 (cents/lb)
            total_tons: 总进口量 (吨)
            as_of: 可选，指定时间（用于历史回测）

        Returns:
            HedgeRecommendation
        """
        if not self._loaded:
            loaded = self.load()
            if not loaded:
                raise RuntimeError('No model loaded. Call fit() or load() first.')

        # 获取最新特征
        as_of = as_of or datetime.now()
        end = as_of.strftime('%Y-%m-%d')
        start_date = (as_of - pd.Timedelta(days=400)).strftime('%Y-%m-%d')

        loader = HistoryLoader()
        price_df = loader.load_kc_futures(start_date, end)

        scraper = ONIScraper()
        oni_df = scraper.fetch()

        engine = FeatureEngine()
        df = engine.build_features(price_df, oni_df)
        df = df.dropna().iloc[120:]

        # 用已有模型的 scaler 重新构建
        # 重新 fit 以获取正确的 scaler（临时方案）
        # 更好的方案是保存 scaler
        rec = self._recommend_from_df(df, current_price, total_tons)
        return rec

    def _recommend_from_df(
        self,
        df: pd.DataFrame,
        current_price: float,
        total_tons: float,
    ) -> HedgeRecommendation:
        """从特征 DataFrame 生成推荐（复用已训练的 scaler）"""
        if not self._loaded or self.model is None:
            raise RuntimeError('Model not loaded')

        # 用模型自带的 scaler
        X, _ = self.model.feature_engine.get_X(
            df, scaler=self.model.feature_engine._scaler, fit=False
        )

        # 预测
        proba = self.model._clf.predict_proba(X)[-1, 1]
        pred_return = self.model._reg.predict(X)[-1]

        latest = df.iloc[-1]
        oni = latest.get('oni', 0)
        oni_phase = latest.get('oni_phase', 'NEUTRAL')
        frost_season = latest.get('frost_season', 0)
        rsi = latest.get('rsi_14', 50)
        vol = latest.get('volatility_20d', 0.02)
        price_rank = latest.get('price_rank_60d', 0.5)
        momentum = latest.get('momentum_20d', 0)

        # 套保逻辑
        base = 0.65
        adj = 0.0
        rationale = []

        if frost_season and oni <= -0.5:
            adj += 0.20; rationale.append('La Nina + Frost Season: +20%')
        elif frost_season and oni >= 0.5:
            adj += 0.10; rationale.append('El Nino + Frost Season: +10%')
        elif oni <= -0.5:
            adj += 0.10; rationale.append('La Nina active: +10%')
        elif oni >= 0.5:
            adj -= 0.05; rationale.append('El Nino active: -5%')

        if price_rank > 0.9:
            adj -= 0.15; rationale.append(f'Price {price_rank:.0%} percentile (high): -15%')
        elif price_rank < 0.2:
            adj += 0.10; rationale.append(f'Price {price_rank:.0%} percentile (low): +10%')

        if momentum < -0.1:
            adj += 0.05; rationale.append('Downtrend: +5%')
        elif momentum > 0.1:
            adj -= 0.05; rationale.append('Uptrend: -5%')

        if rsi < 30:
            adj += 0.10; rationale.append(f'RSI oversold {rsi:.0f}: +10%')
        elif rsi > 70:
            adj -= 0.10; rationale.append(f'RSI overbought {rsi:.0f}: -10%')

        target_ratio = np.clip(base + adj, 0.20, 0.95)

        confidence = np.clip(
            0.5 + 0.3 * (1 - abs(adj) / 0.3),
            0.4, 0.90
        )

        return HedgeRecommendation(
            hedge_ratio=round(float(target_ratio), 2),
            target_tons=round(float(target_ratio * total_tons), 1),
            confidence=round(float(confidence), 2),
            rationale=rationale or ['Baseline'],
            model_signals={
                'direction': 'DOWN' if proba < 0.5 else 'UP',
                'confidence': f'{max(proba, 1-proba):.0%}',
                'predicted_return': f'{pred_return:+.2%}',
                'oni_phase': oni_phase,
                'rsi': round(float(rsi), 1),
                'price_rank': round(float(price_rank), 3),
            },
            risk_factors=['Frost' if frost_season else ''],
        )

    def backtest(
        self,
        start: str = '2023-01-01',
        end: str = '2025-12-31',
        total_tons: float = 100.0,
        initial_equity: float = 500_000,
        commission_per_contract: float = 75.0,
    ) -> dict:
        """
        回测模型推荐的套保策略表现

        对比:
        - 无套保
        - 静态 65% 套保
        - 模型动态套保

        Returns:
            回测报告 dict
        """
        print(f'Backtesting: {start} → {end}')
        print(f'Initial equity: ${initial_equity:,.0f}')
        print()

        # 加载历史数据
        loader = HistoryLoader()
        price_df = loader.load_kc_futures(start, end)

        scraper = ONIScraper()
        oni_df = scraper.fetch()

        # 构建特征
        engine = FeatureEngine()
        df = engine.build_features(price_df, oni_df)
        df = df.dropna().iloc[120:].copy()

        prices = df['price'].values
        n = len(df)

        # 仓位设置
        # 每吨 = ~37.5 袋 (60kg/袋) = ~37.5 contracts (每手25000 lbs)
        contracts_per_ton = 1.0  # 简化：每吨1手

        # 权益曲线
        equity_unhedged = np.full(n, initial_equity)
        equity_static = np.full(n, initial_equity)
        equity_model = np.full(n, initial_equity)

        hedge_ratio_static = 0.65
        prev_model_ratio = None

        # 逐日模拟
        for i in range(1, n):
            ret = (prices[i] - prices[i-1]) / prices[i-1]

            # 无套保：完全暴露
            equity_unhedged[i] = equity_unhedged[i-1] * (1 + ret)

            # 静态套保
            hedge_pnl_static = -ret * hedge_ratio_static  # 期货盈利对冲现货亏损
            equity_static[i] = equity_static[i-1] * (1 + ret * (1 - hedge_ratio_static))
            # 简化：直接乘
            equity_static[i] = equity_static[i-1] + ret * initial_equity * (1 - hedge_ratio_static)

            # 模型动态套保
            if i % 5 == 0 and i >= 5:  # 每5天调整一次
                window = df.iloc[max(0, i-120):i]
                rec = self._recommend_from_df(window, prices[i], total_tons)
                target_ratio = rec.hedge_ratio
            else:
                target_ratio = prev_model_ratio or 0.65

            # 调整成本
            if prev_model_ratio is not None and target_ratio != prev_model_ratio:
                # 调整仓位的交易成本
                change = abs(target_ratio - prev_model_ratio)
                equity_model[i] = equity_model[i-1] - change * total_tons * contracts_per_ton * commission_per_contract / initial_equity
            else:
                equity_model[i] = equity_model[i-1]

            # 模型收益
            equity_model[i] += ret * initial_equity * (1 - target_ratio)

            prev_model_ratio = target_ratio

        # 计算指标
        def metrics(equity_series, name):
            total_return = (equity_series[-1] / equity_series[0]) - 1
            # 年化
            years = n / 252
            ann_return = (1 + total_return) ** (1/years) - 1
            # 波动率
            rets = np.diff(equity_series) / equity_series[:-1]
            ann_vol = np.std(rets) * np.sqrt(252)
            # 最大回撤
            peak = np.maximum.accumulate(equity_series)
            drawdown = (equity_series - peak) / peak
            max_dd = drawdown.min()
            # Sharpe
            sharpe = ann_return / (ann_vol + 1e-10)

            return {
                'name': name,
                'final_equity': equity_series[-1],
                'total_return': total_return,
                'ann_return': ann_return,
                'ann_vol': ann_vol,
                'max_drawdown': max_dd,
                'sharpe': sharpe,
            }

        results = {
            'unhedged': metrics(equity_unhedged, 'No Hedge'),
            'static_65': metrics(equity_static, 'Static 65%'),
            'model': metrics(equity_model, 'Model'),
        }

        # 打印
        print(f"{'Strategy':<15} {'Final Equity':>15} {'Total Ret':>12} {'Ann Ret':>10} {'Ann Vol':>10} {'Max DD':>10} {'Sharpe':>8}")
        print('-' * 80)
        for r in results.values():
            print(f"{r['name']:<15} ${r['final_equity']:>13,.0f} {r['total_return']:>11.1%} "
                  f"{r['ann_return']:>9.1%} {r['ann_vol']:>9.1%} {r['max_drawdown']:>9.1%} {r['sharpe']:>7.2f}")

        # 改善
        model_vs_static = results['model']['total_return'] - results['static_65']['total_return']
        model_vs_none = results['model']['total_return'] - results['unhedged']['total_return']
        print()
        print(f'Model vs Static 65%: {model_vs_static:+.1%}')
        print(f'Model vs No Hedge:   {model_vs_none:+.1%}')

        # 保存权益曲线
        dates = df.index
        eq_df = pd.DataFrame({
            'date': dates,
            'unhedged': equity_unhedged,
            'static_65': equity_static,
            'model': equity_model,
        })
        eq_df.to_csv(MODEL_DIR / 'backtest_equity.csv', index=False)
        print(f'\nEquity curve saved to {MODEL_DIR / "backtest_equity.csv"}')

        return results


# ─── CLI ──────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Coffee Hedge Model Manager')
    parser.add_argument('--fit', action='store_true', help='Train new model')
    parser.add_argument('--save', action='store_true', help='Save model after training')
    parser.add_argument('--load', action='store_true', help='Load existing model')
    parser.add_argument('--backtest', action='store_true', help='Run backtest')
    parser.add_argument('--recommend', action='store_true', help='Get current recommendation')
    args = parser.parse_args()

    mgr = ModelManager()

    if args.fit:
        report = mgr.fit(verbose=True)
        print()
        print('=== Training Report ===')
        for k, v in report.items():
            print(f'  {k}: {v}')

        if args.save:
            path = mgr.save()
            print(f'Model saved: {path}')

    elif args.load:
        ok = mgr.load()
        print(f'Loaded: {ok}')
        if ok:
            print(f'Trained: {mgr.meta.get("trained_at","unknown")}')
            print(f'Data: {mgr.meta.get("train_start","?")} → {mgr.meta.get("train_end","?")}')

    elif args.backtest:
        ok = mgr.load()
        if not ok:
            print('No model found. Training first...')
            mgr.fit(verbose=False)
        results = mgr.backtest()

    elif args.recommend:
        ok = mgr.load()
        if not ok:
            print('No model found. Training first...')
            mgr.fit(verbose=True)
        rec = mgr.recommend(current_price=350.0, total_tons=100)
        print()
        print('=== Current Recommendation ===')
        print(f'Hedge Ratio: {rec.hedge_ratio:.0%}')
        print(f'Target Tons: {rec.target_tons:.1f}')
        print(f'Confidence:  {rec.confidence:.0%}')
        print()
        print('Rationale:')
        for r in rec.rationale:
            print(f'  {r}')
        print()
        print('Model Signals:')
        for k, v in rec.model_signals.items():
            print(f'  {k}: {v}')

    else:
        # 默认: 检查并显示状态
        ok = mgr.load()
        if ok:
            print(f'Model loaded: trained {mgr.meta.get("trained_at","?")}')
        else:
            print('No model found. Run --fit to train.')
