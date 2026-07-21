# 套保比率决策引擎重构 — 无状态因子评分，单一引擎

**日期**: 2026-07-20
**状态**: 设计已确认，待实现
**影响模块**: `core/state/`, `core/regime_config.py`, `config/regimes.yaml`, `backtest/`, `reports/pipeline.py`

---

## 1. 问题

### 1.1 存在两套互不相关的套保比率逻辑

| | `DecisionEngine` | `compute_hedge_advice` |
|---|---|---|
| 位置 | `core/state/engine.py` | `reports/pipeline.py:720` |
| 输入 | 39 类事件（气候 / 持仓 / 库存 / 关税 / ML） | 主导情景方向 + RSI，仅此 |
| 消费者 | `coffee_system.py`（CLI）、paper trading、backtest、ML advisor、agent 工具 | `reports/pipeline.py:890` —— **每周发布的周报** |
| 相互引用 | 无 | 无 |

`reports/` 从未 import `DecisionEngine`。README 架构图描述的是 CLI 路径，不是周报路径。实际发给订阅者的套保建议由一个 40 行启发式产生：

```python
base_ratio = 0.75 if 下跌 else 0.45 if 上涨 else 0.65
ratio = base ± 0.10 (RSI < 35 / > 65)，clamp 到 [0.40, 0.90]
```

它完全无视关税、霜冻、ONI、COT、库存与 Polymarket。

### 1.2 `DecisionEngine` 的六个结构性缺陷

现行实现是有状态累加器：

```
ratio ← clamp(ratio + Δ(event), 0.20, 0.95)
Δ = 硬编码值 × (severity≥4 ? 1.5 : 1) × (冷却期内 ? 0.5 : 1)
```

1. **无衰减 — 棘轮效应**。事件贡献永久留在 ratio 里。霜冻过去三个月比率不会自行回落，只能等反向事件抵消。系统单调爬向 0.95 后卡死。
2. **相关信号重复计数**。一次巴西霜冻同时触发 `FROST_WARNING(+0.20)` → `FROST_CONFIRMED(+0.30)` → `BRAZIL_CROP_ALERT(+0.25)` → `PRICE_SHOCK_UP(+0.10)` → `PRICE_30D_EXTREME_UP(+0.20)`。冷却期仅对同类型事件减半，挡不住跨类型重复。
3. **路径依赖**。clamp 与冷却减半均为路径函数，同一组事件换顺序得到不同 ratio。当前比率无法从世界状态复现。
4. **`update_ml_signal` 双重施加（真 bug）**。`engine.py:433` 的 `raw_ratio = self._hedge_ratio + self._ml_bias` 把 bias 加到已含 bias 的 ratio 上，MLAdvisor 周期调用会使同一信号复利叠加。
5. **回测与实盘不同路径**。`compute_hedge_from_events`（`engine.py:726`）一次性 publish 全部事件且 `adj.timestamp` 用 `datetime.now()`，导致所有事件互处冷却期而全部减半。
6. **系数无来源**。`FROST_CONFIRMED = 0.30` 不对应价格影响、概率或方差，`reports/learning.py` 的自校准也够不到它们。

---

## 2. 方案

累加器换成**纯函数**，两套逻辑合并为一套。比率是当前活跃因子的函数，随时可从事件集重算。

### 2.1 核心公式

```python
# 单事件贡献 —— 按事件类型的信息寿命衰减
w(e)       = 0.5 ** (age_days(e) / half_life_days[e.type])
raw(e)     = adjustment[e.type] * (e.severity / 3.0)
contrib(e) = raw(e) * w(e)

# 簇内递减求和 —— 按 |contrib| 降序（同值以事件类型名为次级键），保留符号
cluster_score(c) = Σᵢ contribᵢ * rank_decay ** i        # rank_decay = 0.5

# 簇间求和 + tanh 软饱和
score = Σ_c cluster_score(c)
ratio = baseline + span * tanh(score / k)
    baseline = 0.65（固定，不自校准）
    span     = 0.30 if score > 0 else 0.45
    k        = tanh 陡度，默认 0.5
```

设计要点：

- **`clamp` 完全消失**。tanh 渐近到 0.95 / 0.20，且边界附近保留梯度——现行实现撞到 0.95 后彻底失去响应。
- **`severity / 3.0` 替代 `severity>=4 → ×1.5` 悬崖**。sev3=1.0 与现状等价，sev5=1.67，sev1=0.33，全程连续。
- **簇内递减求和**保留「多个独立观测互相印证」的加成，但收敛有上界。混合符号自然处理：更强证据主导，矛盾证据部分抵消。
- **排序须有确定性次级键**。按 `(-abs(contrib), event_type.name)` 排序，否则等值贡献的顺序会破坏顺序不变性。
- **`rank_decay` 与 `k` 是自校准对象**，二者有明确误差信号。`baseline` 不自校准——无明确误差信号，且会引入 c254082 特意防范的开环风险。

### 2.2 因子簇

39 个事件类型 + 2 个报告侧因子，归并为 13 个独立风险源：

| 簇 | 事件类型 | 半衰期 |
|---|---|---|
| `brazil_supply` | `FROST_WARNING`, `FROST_CONFIRMED`, `BRAZIL_CROP_ALERT`, `HEAT_WAVE`, `SEASONAL_WINDOW_OPEN` | 90d |
| `colombia_supply` | `COLOMBIA_WEATHER_ALERT` | 90d |
| `climate` | `EL_NINO_CONFIRMED`, `LA_NINA_CONFIRMED`, `ONI_THRESHOLD_CROSS`, `POLY_CLIMATE_HOT`, `POLY_CLIMATE_COLD` | 180d |
| `inventory` | `ICE_INVENTORY_CRITICAL`, `ICE_INVENTORY_DROP`, `ICE_INVENTORY_SPIKE` | 30d |
| `positioning` | `COT_SPECULATIVE_TOP`, `COT_SPECULATIVE_BOTTOM`, `COT_COMMERCIAL_BOTTOM` | 14d |
| `price` | `PRICE_SHOCK_UP/DOWN` (3d)、`PRICE_30D_EXTREME_UP/DOWN` (30d)、`BASIS_SPIKE` (7d) | 逐事件 |
| `fx` | `FX_USD_CNY_SHOCK`, `FX_USD_CNY_THRESHOLD`, `POLY_FX_VOLATILE` | 7d |
| `macro` | `WTI_OIL_SHOCK` | 7d |
| `supply_fundamental` | `PRODUCTION_UPDATE` | 180d |
| `policy` | `CHINA_TARIFF_CHANGE`, `EXPORT_BAN`, `TRADE_WAR_NEW_ROUND`, `TRADE_WAR_DEESCALATION`, `LDC_STATUS_GAINED/LOST`, `PESTICIDE_STANDARD_CHANGE`, `POLY_TRADE_WAR_ESCALATE/DEESCALATE`, `POLY_HORMUZ_NORMAL`, `POLY_TRUMP_VISIT_CHINA` | 365d |
| `ml` | `ML_MODEL_UPDATE` | 7d |
| `llm` | `LLM_COMMENTARY`（新增 EventType） | 7d |
| `scenario` | `SCENARIO_DOMINANT`（新增 EventType，报告侧） | 7d |
| `technical` | `RSI_EXTREME`（新增 EventType，报告侧） | 3d |

关键去重：

- Polymarket 的 El Niño 概率与 NOAA ONI 归入同一簇——二者是同一信号的两次观测，现行实现当作独立证据各加一次。
- Polymarket 贸易战概率与实际关税政策事件归入 `policy` 簇，同理。

### 2.3 ML / LLM / 情景 / 技术面均降为普通簇

`update_ml_signal` 不再修改 state，改为向 EventBus 发 `ML_MODEL_UPDATE` 事件，贡献 = `bias × confidence权重`。score 每次全量重算，**问题 4 的 double-apply bug 结构性消失**——不存在可累加的状态。

`compute_hedge_advice` 的逻辑翻译为两个贡献函数，不再自行决定 ratio：

```python
# scenario 簇：主导情景方向 × 概率（下跌→正=增套保，上涨→负）
SCENARIO_DOMINANT.adjustment = ±0.20，value = dominant.probability
# technical 簇：RSI 极值（RSI<35 → 正，RSI>65 → 负）
RSI_EXTREME.adjustment = ±0.10，severity 按偏离程度
```

四者均进入 tanh **内部**，同受软饱和约束。现行 ML bias 绕过全部约束直接改 ratio。

### 2.4 周报接入

`reports/pipeline.py` 改为调用同一纯函数。事件窗口：

```
周报事件窗口 = 出报时三域全量扫描（新鲜事件）
             ∪ DecisionDB.get_events(start=now - 365d)（衰减尾巴）
```

半衰期最长 365 天，仅靠新鲜扫描不足。无状态设计使 pipeline 无需持有跨进程 engine 实例，只需 `compute_score(events, rules, now, cfg)`。

---

## 3. 文件改动

| 文件 | 改动 |
|---|---|
| `core/state/scoring.py` | **新增**。纯函数，无 I/O 无状态：`compute_score()` / `score_to_ratio()` / `ScoreBreakdown` |
| `core/state/engine.py` | `DecisionEngine` 变薄壳：持有事件窗口，每次事件到达全量重算；`update_ml_signal` 改为发事件 |
| `core/regime_config.py` | `HedgeAdjustmentRule` 加 `cluster` / `half_life_days`；新增 `scoring:` 顶层块 |
| `config/regimes.yaml` | 各规则加两个字段 + `scoring:` 块 |
| `backtest/engine.py` | 事件驱动策略调同一纯函数，使用事件真实时间戳 |
| `core/types/enums.py` | 新增 `LLM_COMMENTARY` / `SCENARIO_DOMINANT` / `RSI_EXTREME` |
| `reports/pipeline.py` | `compute_hedge_advice` 改为产出 scenario/technical 事件；hedge 由 `compute_score` 决定 |
| `reports/` / `agent/` | LLM 点评发事件进 bus |

**附带收益**：`ScoreBreakdown` 提供逐簇归因。`reports/history.py` 的驱动因子应验率与周报多空驱动板块目前靠反查 adjustment 日志重建归因，之后可直接读取。

---

## 4. 验证点

每条均可自动检查：

| 测试 | 断言 |
|---|---|
| 顺序不变性 | 打乱事件顺序 → ratio 完全相同（property test，含等值贡献） |
| 衰减正确 | 同一事件在 `t` 与 `t + half_life` → 贡献恰好减半 |
| 簇内去重 | 5 个霜冻系事件的合计 < 5 × 单个霜冻，且 < 簇内线性和 |
| 边界 | 任意极端 score → `ratio ∈ (0.20, 0.95)`，永不越界亦永不失去梯度 |
| ML 幂等 | 同一 ML 信号连续施加 3 次 → ratio 不变（问题 4 回归测试） |
| 回测/实盘一致 | 同一事件列表走两条路径 → 同一 ratio（问题 5 回归测试） |
| 单一引擎 | 相同事件集下，周报 hedge ratio == `DecisionEngine` ratio |

---

## 5. 迁移

**无需迁移。** 核实数据现状：

```
~/.arbor/decisions.db events 表:  6 行，全部 2026-07-19，跨度 71 分钟
~/.arbor/reports/:                4 个 weekly_summary，2026-07-14 ~ 07-19
```

历史总量为 4 期周报、6 个事件、5 天。不存在值得保留的 Brier 校准序列、驱动因子应验率或凯利影子账本。

**处理方式**：4 个既有 summary 原样保留，不做任何转换；新序列从切换日起向后累积。历史 Brier 分数记的是 `scenarios` 的概率，而 scenarios 由 `compute_levels_and_scenarios(market, ...)` 从纯市场数据算出，本次改动不影响其口径。

---

## 6. 未决

无。设计已完整确认，可进入实现计划。
