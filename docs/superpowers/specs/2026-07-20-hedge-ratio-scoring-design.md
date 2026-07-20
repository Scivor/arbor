# 套保比率决策引擎重构 — 无状态因子评分

**日期**: 2026-07-20
**状态**: 设计已确认，待实现
**影响模块**: `core/state/`, `core/regime_config.py`, `config/regimes.yaml`, `backtest/`, `reports/`

---

## 1. 问题

现行 `DecisionEngine` 是一个有状态累加器：

```
ratio ← clamp(ratio + Δ(event), 0.20, 0.95)
Δ = 硬编码值 × (severity≥4 ? 1.5 : 1) × (冷却期内 ? 0.5 : 1)
```

六个结构性缺陷：

1. **无衰减 — 棘轮效应**。事件贡献永久留在 ratio 里。霜冻过去三个月，比率不会自行回落，只能等反向事件抵消。系统单调爬向 0.95 后卡死。
2. **相关信号重复计数**。一次巴西霜冻同时触发 `FROST_WARNING(+0.20)` → `FROST_CONFIRMED(+0.30)` → `BRAZIL_CROP_ALERT(+0.25)` → `PRICE_SHOCK_UP(+0.10)` → `PRICE_30D_EXTREME_UP(+0.20)`，同一现实事件被记 5 次。冷却期仅对同类型事件减半，挡不住跨类型重复。
3. **路径依赖**。clamp 与冷却减半都是路径函数，同一组事件换顺序得到不同 ratio。当前比率无法从世界状态复现，只能重放事件流。
4. **`update_ml_signal` 双重施加（真 bug）**。`engine.py:433` 的 `raw_ratio = self._hedge_ratio + self._ml_bias` 把 bias 加到已含 bias 的 ratio 上。MLAdvisor 周期性调用会使同一信号复利叠加。
5. **回测与实盘不同路径**。`compute_hedge_from_events`（`engine.py:726`）一次性 publish 全部事件，`adj.timestamp` 用 `datetime.now()` 而非事件时间，导致所有事件互相处于冷却期而全部减半。
6. **系数无来源**。`FROST_CONFIRMED = 0.30` 不对应价格影响、概率或方差。`reports/learning.py` 的自校准也够不到这批系数。

---

## 2. 方案

把累加器换成**纯函数**：比率是当前活跃因子的函数，随时可从事件集重算。

### 2.1 核心公式

```python
# 单事件贡献 —— 按事件类型的信息寿命衰减
w(e)       = 0.5 ** (age_days(e) / half_life_days[e.type])
raw(e)     = adjustment[e.type] * (e.severity / 3.0)
contrib(e) = raw(e) * w(e)

# 簇内递减求和 —— 按 |contrib| 降序，保留符号
cluster_score(c) = Σᵢ contribᵢ * rank_decay ** i        # rank_decay = 0.5

# 簇间求和 + tanh 软饱和
score = Σ_c cluster_score(c)
ratio = baseline + span * tanh(score / k)
    baseline = 0.65（固定）
    span     = 0.30 if score > 0 else 0.45
    k        = tanh 陡度，默认 0.5
```

设计要点：

- **`clamp` 完全消失**。tanh 渐近到 0.95 / 0.20，且边界附近保留梯度——现行实现撞到 0.95 后彻底失去响应。
- **`severity / 3.0` 替代 `severity>=4 → ×1.5` 悬崖**。sev3=1.0 与现状等价，sev5=1.67，sev1=0.33，全程连续。
- **簇内递减求和**保留「多个独立观测互相印证」的加成，但收敛有上界。混合符号自然处理：更强的证据主导，矛盾证据部分抵消。
- **`rank_decay` 与 `k` 是自校准对象**。二者都有明确误差信号，交给 `reports/learning.py`。`baseline` 不自校准——无明确误差信号，且会引入开环风险（见 c254082）。

### 2.2 因子簇

39 个事件类型归并为 11 个独立风险源：

| 簇 | 事件类型 | 半衰期 |
|---|---|---|
| `brazil_supply` | `FROST_WARNING`, `FROST_CONFIRMED`, `BRAZIL_CROP_ALERT`, `HEAT_WAVE`, `SEASONAL_WINDOW_OPEN` | 90d |
| `colombia_supply` | `COLOMBIA_WEATHER_ALERT` | 90d |
| `climate` | `EL_NINO_CONFIRMED`, `LA_NINA_CONFIRMED`, `ONI_THRESHOLD_CROSS`, `POLY_CLIMATE_HOT`, `POLY_CLIMATE_COLD` | 180d |
| `inventory` | `ICE_INVENTORY_CRITICAL`, `ICE_INVENTORY_DROP`, `ICE_INVENTORY_SPIKE` | 30d |
| `positioning` | `COT_SPECULATIVE_TOP`, `COT_SPECULATIVE_BOTTOM`, `COT_COMMERCIAL_BOTTOM` | 14d |
| `price` | `PRICE_SHOCK_UP/DOWN` (3d), `PRICE_30D_EXTREME_UP/DOWN` (30d), `BASIS_SPIKE` (7d) | 见括号 |
| `fx` | `FX_USD_CNY_SHOCK`, `FX_USD_CNY_THRESHOLD`, `POLY_FX_VOLATILE` | 7d |
| `macro` | `WTI_OIL_SHOCK` | 7d |
| `policy` | `CHINA_TARIFF_CHANGE`, `EXPORT_BAN`, `TRADE_WAR_NEW_ROUND`, `TRADE_WAR_DEESCALATION`, `LDC_STATUS_GAINED/LOST`, `PESTICIDE_STANDARD_CHANGE`, `POLY_TRADE_WAR_ESCALATE/DEESCALATE`, `POLY_HORMUZ_NORMAL`, `POLY_TRUMP_VISIT_CHINA` | 365d |
| `ml` | `ML_MODEL_UPDATE` | 7d |
| `llm` | `LLM_COMMENTARY`（新增） | 7d |

关键去重：

- Polymarket 的 El Niño 概率与 NOAA ONI 归入同一簇——二者是同一信号的两次观测，现行实现当作独立证据各加一次。
- Polymarket 贸易战概率与实际关税政策事件归入 `policy` 簇，同理。

### 2.3 ML 与 LLM 作为普通簇

`update_ml_signal` 不再直接修改 state，改为向 EventBus 发一个 `ML_MODEL_UPDATE` 事件，贡献 = `bias × confidence权重`。由于 score 每次全量重算，**问题 4 的 double-apply bug 结构性消失**——不存在可累加的状态。

`LLM_COMMENTARY` 为新增 EventType。当前 LLM 点评在 `reports/` 层记分（commit f7bc0e7），未进 EventBus；本次需补接线。

两者进入 tanh **内部**，因此同样受软饱和约束。现行实现中 ML bias 绕过所有约束直接改 ratio。

---

## 3. 文件改动

| 文件 | 改动 |
|---|---|
| `core/state/scoring.py` | **新增**。纯函数，无 I/O 无状态：`compute_score(events, now, cfg) -> ScoreBreakdown`、`score_to_ratio(score, cfg) -> float` |
| `core/state/engine.py` | `DecisionEngine` 变薄壳：持有事件窗口，每次事件到达全量重算；`update_ml_signal` 改为发事件 |
| `core/regime_config.py` | `AdjustmentRule` 加 `cluster` / `half_life_days`；新增 `scoring:` 顶层块（`rank_decay` / `tanh_k` / `baseline` / `span_up` / `span_down`） |
| `config/regimes.yaml` | 39 条规则各加两个字段 + `scoring:` 块 |
| `backtest/engine.py` | `compute_hedge_from_events` 调同一纯函数，使用事件真实时间戳 |
| `core/types/enums.py` | 新增 `LLM_COMMENTARY` |
| `reports/` / `agent/` | LLM 点评发事件进 bus |

**附带收益**：`ScoreBreakdown` 提供逐簇归因。`reports/history.py` 的驱动因子应验率与周报多空驱动板块目前靠反查 adjustment 日志重建归因，之后可直接读取。

**事件来源**：实盘从 `EventBus`（deque maxlen=2000）读取窗口；重启恢复与回测从 `DecisionDB.get_events()` 读取（`core/persistence/database.py:352`）。

---

## 4. 验证点

每条均可自动检查：

| 测试 | 断言 |
|---|---|
| 顺序不变性 | 打乱事件顺序 → ratio 完全相同（property test） |
| 衰减正确 | 同一事件在 `t` 与 `t + half_life` → 贡献恰好减半 |
| 簇内去重 | 5 个霜冻系事件的合计 < 5 × 单个霜冻，且 < 簇内线性和 |
| 边界 | 任意极端 score → `ratio ∈ (0.20, 0.95)`，永不越界亦永不失去梯度 |
| ML 幂等 | 同一 ML 信号连续施加 3 次 → ratio 不变（问题 4 回归测试） |
| 回测/实盘一致 | 同一事件列表走两条路径 → 同一 ratio（问题 5 回归测试） |

---

## 5. 迁移

引擎变更会改变所有历史比率。**已决定：全量重算（单序列）**——用新引擎重放历史事件，重算全部 Brier 分数、驱动因子应验率与凯利影子账本。战绩页呈现单一连续序列。

### 5.1 已知风险（已接受）

> 以下为设计讨论中提出的保留意见，用户已知情并选择全量重算方案。记录于此以备后续复盘。

**校准数据污染**。Brier 分数衡量的是「声称 70% 的场合是否约 70% 兑现」。用新引擎重放历史得到的并非当时的预测，而是「以今日选定的簇划分与半衰期回溯会说什么」——而这些参数是在已知历史结果的前提下选定的。重算后的校准曲线会更好看，但衡量的是拟合度而非预测能力。

**自校准开环**。`reports/learning.py` 若读取重算序列，系数将拟合一条由自身参数生成的曲线，构成开环反馈——即 commit c254082 特意通过单向降级所防范的失效模式。实现计划须包含一个决策点：`learning.py` 的输入是全量重算序列，还是仅切换日之后的前瞻部分。

---

## 6. 未决

无。设计已完整确认，可进入实现计划。
