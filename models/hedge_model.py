"""
models/hedge_model.py
咖啡价格预测 & 套保比率推荐模型

两个目标:
1. 价格方向分类: 未来5日涨跌 (分类)
2. 套保比率推荐: 基于风险预算的动态比率 (回归)

模型选择:
- Random Forest (分类 + 回归)
- Logistic Regression (基线分类)
- Ridge Regression (基线回归)

无 sklearn: 使用 numpy 实现简化版本
"""

from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path

_proj_root = _Path(__file__).parent.parent
if str(_proj_root) not in _sys.path:
    _sys.path.insert(0, str(_proj_root))

import numpy as np
import pandas as pd
from typing import Optional, Literal
from dataclasses import dataclass

from models.features import FeatureEngine, ManualScaler


# ─── 数据类型 ────────────────────────────────────────────────

@dataclass
class ModelOutput:
    """模型输出"""
    prediction: float       # 预测值 (方向概率 或 收益率)
    confidence: float      # 置信度
    model_name: str         # 模型名
    feature_importance: dict  # 特征重要性


@dataclass
class HedgeRecommendation:
    """套保推荐"""
    hedge_ratio: float          # 推荐套保比率 [0, 1]
    target_tons: float          # 目标套保量 (吨)
    confidence: float           # 信号置信度
    rationale: list[str]        # 理由
    model_signals: dict         # 各模型输出
    risk_factors: list[str]     # 风险因素


# ─── 简化模型实现 (无 sklearn) ─────────────────────────────

class SimpleLogisticRegression:
    """简化的逻辑回归 (梯度下降)"""

    def __init__(self, lr: float = 0.01, epochs: int = 100, l2_reg: float = 0.01):
        self.lr = lr
        self.epochs = epochs
        self.l2_reg = l2_reg
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0

    def _sigmoid(self, z: np.ndarray) -> np.ndarray:
        # 防止溢出
        z = np.clip(z, -500, 500)
        return 1 / (1 + np.exp(-z))

    def fit(self, X: np.ndarray, y: np.ndarray, verbose: bool = False):
        n, d = X.shape
        self.weights = np.zeros(d)
        self.bias = 0.0

        y_binary = (y > 0).astype(float)  # 0/1 标签

        for epoch in range(self.epochs):
            z = X @ self.weights + self.bias
            pred = self._sigmoid(z)

            # 梯度
            grad_w = (X.T @ (pred - y_binary)) / n + self.l2_reg * self.weights
            grad_b = np.mean(pred - y_binary)

            self.weights -= self.lr * grad_w
            self.bias -= self.lr * grad_b

            if verbose and epoch % 20 == 0:
                loss = -np.mean(y_binary * np.log(pred + 1e-10) + (1 - y_binary) * np.log(1 - pred + 1e-10))
                acc = np.mean((pred > 0.5) == y_binary)
                print(f'  Epoch {epoch:3d}: loss={loss:.4f} acc={acc:.3f}')

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        z = X @ self.weights + self.bias
        prob = self._sigmoid(z)
        return np.column_stack([1 - prob, prob])

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] > 0.5).astype(int)


class SimpleRidgeRegression:
    """岭回归 (闭式解)"""

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.weights: Optional[np.ndarray] = None
        self.intercept: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray):
        n, d = X.shape
        # 闭式解: (X'X + alpha*I)^-1 X'y
        XtX = X.T @ X
        Xty = X.T @ y
        I = np.eye(d)
        self.weights = np.linalg.solve(XtX + self.alpha * I, Xty)
        self.intercept = np.mean(y - X @ self.weights)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return X @ self.weights + self.intercept


class SimpleDecisionTree:
    """简化决策树 (用于特征重要性)"""

    def __init__(self, max_depth: int = 5, min_samples_leaf: int = 20):
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.tree: dict = {}

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: list[str]):
        self.feature_names = feature_names
        self.feature_importance = np.zeros(X.shape[1])
        self.tree = self._build_tree(X, y, depth=0)

    def _best_split(self, X: np.ndarray, y: np.ndarray) -> tuple[int, float]:
        best_gain = -1
        best_feat = 0
        best_thresh = 0.0
        current_var = np.var(y)

        for j in range(X.shape[1]):
            thresholds = np.percentile(X[:, j], [25, 50, 75])
            for t in thresholds:
                left = y[X[:, j] <= t]
                right = y[X[:, j] > t]
                if len(left) < self.min_samples_leaf or len(right) < self.min_samples_leaf:
                    continue
                gain = current_var - (len(left)/len(y))*np.var(left) - (len(right)/len(y))*np.var(right)
                if gain > best_gain:
                    best_gain = gain
                    best_feat = j
                    best_thresh = t

        return best_feat, best_thresh

    def _build_tree(self, X: np.ndarray, y: np.ndarray, depth: int) -> dict:
        if depth >= self.max_depth or len(y) < self.min_samples_leaf * 2:
            return {'leaf': float(np.mean(y))}

        feat, thresh = self._best_split(X, y)
        if feat < 0:
            return {'leaf': float(np.mean(y))}

        left_idx = X[:, feat] <= thresh
        right_idx = X[:, feat] > thresh

        self.feature_importance[feat] += np.var(y) * len(y)

        return {
            'feature': feat,
            'threshold': thresh,
            'left': self._build_tree(X[left_idx], y[left_idx], depth + 1),
            'right': self._build_tree(X[right_idx], y[right_idx], depth + 1),
        }

    def _predict_sample(self, x: np.ndarray, node: dict) -> float:
        if 'leaf' in node:
            return node['leaf']
        if x[node['feature']] <= node['threshold']:
            return self._predict_sample(x, node['left'])
        return self._predict_sample(x, node['right'])

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.array([self._predict_sample(x, self.tree) for x in X])


# ─── 主模型类 ───────────────────────────────────────────────

class HedgeModel:
    """
    咖啡套保预测模型

    功能:
    1. 价格方向分类 (5日涨跌)
    2. 收益率回归 (5日收益)
    3. 套保比率推荐

    用法:
        model = HedgeModel()
        model.fit(train_df, oni_df)
        rec = model.recommend(current_features, price=285, total_tons=100)
        print(f'Hedge ratio: {rec.hedge_ratio:.0%}')
    """

    def __init__(self):
        self.feature_engine = FeatureEngine()
        self.scaler = ManualScaler()
        self._clf: Optional[SimpleLogisticRegression] = None
        self._reg: Optional[SimpleRidgeRegression] = None
        self._tree: Optional[SimpleDecisionTree] = None
        self._fitted = False
        self._feature_names: list[str] = []

    def fit(
        self,
        price_df: pd.DataFrame,
        oni_df: pd.DataFrame,
        test_size: float = 0.2,
        verbose: bool = True,
    ) -> dict:
        """
        训练模型

        Args:
            price_df: 历史价格数据
            oni_df: ONI 数据
            test_size: 测试集比例

        Returns:
            训练报告 dict
        """
        if verbose:
            print('Building features...')

        # 构建特征
        df = self.feature_engine.build_features(price_df, oni_df)
        df = df.dropna()

        # 移除没有足够历史的行 (滚动指标需要预热期)
        min_idx = 120  # 至少需要 120 天历史
        df = df.iloc[min_idx:].copy()

        if verbose:
            print(f'Training data: {len(df)} samples')

        # 目标变量
        y_direction = (df['return_5d'] > 0).astype(int).values
        y_return = df['return_5d'].values

        # 特征
        X, self._feature_names = self.feature_engine.get_X(df, scaler=None, fit=True)

        # 训练/测试分割 (时序，不要 shuffle)
        split = int(len(df) * (1 - test_size))
        X_train, X_test = X[:split], X[split:]
        y_dir_train, y_dir_test = y_direction[:split], y_direction[split:]
        y_ret_train, y_ret_test = y_return[:split], y_return[split:]

        # 训练分类器
        if verbose:
            print('Training Logistic Regression (direction classifier)...')

        self._clf = SimpleLogisticRegression(lr=0.1, epochs=100, l2_reg=0.1)
        self._clf.fit(X_train, y_dir_train, verbose=verbose)

        # 训练回归器
        if verbose:
            print('Training Ridge Regression (return regressor)...')

        self._reg = SimpleRidgeRegression(alpha=1.0)
        self._reg.fit(X_train, y_ret_train)

        # 训练决策树 (用于特征重要性)
        self._tree = SimpleDecisionTree(max_depth=4, min_samples_leaf=30)
        self._tree.fit(X_train, y_ret_train, self._feature_names)

        # 评估
        report = self._evaluate(X_test, y_dir_test, y_ret_test)
        self._fitted = True

        if verbose:
            print()
            print('=== Training Complete ===')
            print(f'  Direction Accuracy: {report["clf_accuracy"]:.1%}')
            print(f'  Return MAE:         {report["reg_mae"]:.4f}')
            print(f'  Return RMSE:        {report["reg_rmse"]:.4f}')

        return report

    def _evaluate(self, X_test, y_dir_test, y_ret_test) -> dict:
        # 分类
        clf_pred = self._clf.predict(X_test)
        clf_proba = self._clf.predict_proba(X_test)[:, 1]

        clf_acc = np.mean(clf_pred == y_dir_test)

        # 回归
        reg_pred = self._reg.predict(X_test)
        reg_mae = np.mean(np.abs(reg_pred - y_ret_test))
        reg_rmse = np.sqrt(np.mean((reg_pred - y_ret_test) ** 2))

        # 方向准确率
        direction_correct = np.mean((reg_pred > 0) == (y_ret_test > 0))

        return {
            'clf_accuracy': clf_acc,
            'clf_direction_acc': direction_correct,
            'reg_mae': reg_mae,
            'reg_rmse': reg_rmse,
        }

    def predict_direction(self, df: pd.DataFrame) -> ModelOutput:
        """预测价格方向"""
        if not self._fitted:
            raise RuntimeError('Model not fitted. Call fit() first.')

        X, _ = self.feature_engine.get_X(df, scaler=self.feature_engine._scaler, fit=False)
        proba = self._clf.predict_proba(X)[-1, 1]  # 取最新

        return ModelOutput(
            prediction=float(proba > 0.5),
            confidence=float(max(proba, 1 - proba)),
            model_name='LogisticRegression',
            feature_importance=dict(zip(self._feature_names, self._tree.feature_importance.tolist())),
        )

    def predict_return(self, df: pd.DataFrame) -> ModelOutput:
        """预测 5 日收益率"""
        if not self._fitted:
            raise RuntimeError('Model not fitted. Call fit() first.')

        X, _ = self.feature_engine.get_X(df, scaler=self.feature_engine._scaler, fit=False)
        pred = self._reg.predict(X)[-1]

        # 置信度: 预测值与均值的标准化距离
        conf = 1.0 / (1.0 + abs(pred) * 10)
        conf = float(np.clip(conf, 0.5, 0.99))

        return ModelOutput(
            prediction=float(pred),
            confidence=conf,
            model_name='RidgeRegression',
            feature_importance=dict(zip(self._feature_names, self._tree.feature_importance.tolist())),
        )

    def recommend_hedge(
        self,
        df: pd.DataFrame,
        current_price: float,
        total_tons: float,
        risk_budget_usd: float = 100_000,
    ) -> HedgeRecommendation:
        """
        推荐套保策略

        Args:
            df: 特征 DataFrame
            current_price: 当前 KC=F 价格 (cents/lb)
            total_tons: 总进口量 (吨)
            risk_budget_usd: 最大容忍损失 (USD)

        Returns:
            HedgeRecommendation
        """
        # 预测
        dir_output = self.predict_direction(df)
        ret_output = self.predict_return(df)

        # 提取关键特征
        latest = df.iloc[-1]
        oni = latest.get('oni', 0)
        oni_phase = latest.get('oni_phase', 'NEUTRAL')
        frost_season = latest.get('frost_season', 0)
        rsi = latest.get('rsi_14', 50)
        vol = latest.get('volatility_20d', 0.02)
        price_rank = latest.get('price_rank_60d', 0.5)

        signals = {
            'direction': dir_output,
            'return': ret_output,
        }

        # ─── 套保比率逻辑 ────────────────────────────────
        base_ratio = 0.65  # 基准 65%

        # 气候调整
        climate_adj = 0.0
        rationale = []
        risk_factors = []

        if frost_season and oni <= -0.5:
            # La Nina + 霜冻季 → 大幅增加套保
            climate_adj = +0.20
            rationale.append('La Nina + Frost Season: HIGH RISK (+20%)')
            risk_factors.append('Frost damage to Brazil crop')
        elif frost_season and oni >= 0.5:
            climate_adj = +0.10
            rationale.append('El Nino + Frost Season: ELEVATED RISK (+10%)')
            risk_factors.append('Drought stress before frost')
        elif oni <= -0.5:
            climate_adj = +0.10
            rationale.append('La Nina active: elevated risk (+10%)')
        elif oni >= 0.5:
            climate_adj = -0.05
            rationale.append('El Nino active: supply pressure (-5%)')

        # 价格位置调整
        if price_rank > 0.9:
            # 价格历史高位 → 减少套保（已锁定高价）
            rank_adj = -0.15
            rationale.append(f'Price at {price_rank:.0%} percentile: already high, reduce hedge (-15%)')
        elif price_rank < 0.2:
            # 价格低位 → 增加套保（锁定低价）
            rank_adj = +0.10
            rationale.append(f'Price at {price_rank:.0%} percentile: low, increase hedge (+10%)')
        else:
            rank_adj = 0.0

        # 趋势调整
        momentum = latest.get('momentum_20d', 0)
        if momentum < -0.1:
            trend_adj = +0.05
            rationale.append('Strong downtrend: increase hedge (+5%)')
        elif momentum > 0.1:
            trend_adj = -0.05
            rationale.append('Strong uptrend: reduce hedge (-5%)')
        else:
            trend_adj = 0.0

        # RSI 极端调整
        if rsi < 30:
            rsi_adj = +0.10
            rationale.append(f'RSI oversold ({rsi:.0f}): expect bounce, increase hedge (+10%)')
        elif rsi > 70:
            rsi_adj = -0.10
            rationale.append(f'RSI overbought ({rsi:.0f}): expect correction, reduce hedge (-10%)')
        else:
            rsi_adj = 0.0

        # 波动率调整
        vol_pct = vol * np.sqrt(252) if vol < 1 else vol  # 年化
        vol_adj = 0.0
        if vol_pct > 0.5:
            vol_adj = +0.05
            rationale.append(f'High volatility ({vol_pct:.0%}): cautious (+5%)')
            risk_factors.append('High market volatility')

        # 预测方向调整
        predicted_return = ret_output.prediction
        if dir_output.prediction == 1 and predicted_return < -0.05:
            # 预测下跌且幅度大 → 增套保
            dir_adj = +0.10
            rationale.append(f'Predicted drop {predicted_return:.1%}: add hedge (+10%)')
        elif dir_output.prediction == 0 and predicted_return > 0.05:
            # 预测上涨且幅度大 → 减套保
            dir_adj = -0.10
            rationale.append(f'Predicted rise {predicted_return:.1%}: reduce hedge (-10%)')
        else:
            dir_adj = 0.0

        # 汇总
        total_adj = climate_adj + rank_adj + trend_adj + rsi_adj + vol_adj + dir_adj
        target_ratio = np.clip(base_ratio + total_adj, 0.20, 0.95)
        target_tons = total_tons * target_ratio

        # 置信度
        confidence = (
            dir_output.confidence * 0.3 +
            ret_output.confidence * 0.3 +
            (1.0 - abs(total_adj) / 0.65) * 0.4
        )
        confidence = float(np.clip(confidence, 0.3, 0.95))

        return HedgeRecommendation(
            hedge_ratio=round(float(target_ratio), 2),
            target_tons=round(float(target_tons), 1),
            confidence=round(confidence, 2),
            rationale=rationale if rationale else ['Baseline recommendation'],
            model_signals={
                'direction_model': f'{"UP" if dir_output.prediction else "DOWN"} (conf={dir_output.confidence:.0%})',
                'return_model': f'{ret_output.prediction:+.2%} (conf={ret_output.confidence:.0%})',
                'oni_phase': str(oni_phase),
                'rsi': round(rsi, 1),
                'volatility_annual': round(vol_pct, 2) if vol < 1 else round(vol, 2),
                'price_rank_60d': round(price_rank, 3),
            },
            risk_factors=risk_factors if risk_factors else ['Standard market risk'],
        )


# ─── CLI ──────────────────────────────────────────────────────

if __name__ == '__main__':
    from backtest.loader import HistoryLoader
    from sources.climate.noaa_oni import ONIScraper

    print('='*60)
    print('COFFEE HEDGE PREDICTION MODEL')
    print('='*60)
    print()

    # 加载数据
    print('Loading data...')
    loader = HistoryLoader()
    price_df = loader.load_kc_futures('2019-01-01', '2025-12-31')

    scraper = ONIScraper()
    oni_df = scraper.fetch()

    print(f'Price: {len(price_df)} rows  ONI: {len(oni_df)} rows')
    print()

    # 训练
    model = HedgeModel()
    report = model.fit(price_df, oni_df, test_size=0.2, verbose=True)

    # 当前推荐
    print()
    print('='*60)
    print('CURRENT RECOMMENDATION')
    print('='*60)

    # 用最新数据生成推荐
    engine = FeatureEngine()
    df = engine.build_features(price_df, oni_df)
    df = df.dropna().iloc[120:]

    latest_price = df['price'].iloc[-1]
    rec = model.recommend_hedge(df, current_price=latest_price, total_tons=100)

    print(f'Current Price: {latest_price:.2f} cents/lb')
    print(f'Recommended Hedge Ratio: {rec.hedge_ratio:.0%}')
    print(f'Target Hedge Tons: {rec.target_tons:.1f} tons')
    print(f'Confidence: {rec.confidence:.0%}')
    print()
    print('Rationale:')
    for r in rec.rationale:
        print(f'  {r}')
    print()
    print('Model Signals:')
    for k, v in rec.model_signals.items():
        print(f'  {k}: {v}')
    print()
    print('Risk Factors:')
    for r in rec.risk_factors:
        print(f'  ! {r}')

    # 特征重要性
    print()
    print('Top Feature Importance:')
    dir_output = model.predict_direction(df)
    fi = dir_output.feature_importance
    sorted_fi = sorted(fi.items(), key=lambda x: abs(x[1]), reverse=True)
    for name, imp in sorted_fi[:10]:
        print(f'  {name:25s}: {imp:,.0f}')
