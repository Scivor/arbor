# 套保比率无状态因子评分 — 执行进度

Plan: docs/superpowers/plans/2026-07-20-hedge-ratio-scoring.md
Branch: feat/hedge-ratio-scoring
Base: 7c5d0ed

预检决议: DecisionEngine 构造函数去掉 use_yaml 布尔参数，改为显式注入
rules/cfg（None → 从 YAML 加载）。原因：删除 _FALLBACK_EVENT_CONFIG 后
use_yaml=False 会导致规则表为空；而 loader 在 local_only=False 时会联网，
不能简单全改 True。计划已相应更新。

## 任务

- [x] Task 1: scoring.py 纯函数核心 — complete (commits 2cc0de1..9532edd, review clean)
- [x] Task 2: regime_config 扩展 — complete (commits 9040d96..2035cf7, review clean)
      含 Step 0 解环：core/state/__init__.py 惰性导出 engine (PEP 562 __getattr__)
- [x] Task 3: regimes.yaml 填充 — complete (commit 5f2cc5b, review clean)
      40 条规则，控制方独立验证：无重复 key / 无缺字段 / 原字段完好
- [x] Task 4: DecisionEngine 薄壳 — complete (commits 5f46bf3..182915b, review clean)
      修了 review 的 I2/I3/I4/I5 + M6-M9。ML bias 双重施加 bug 已结构性消失。
      ⚠ 遗留 Critical C1：backtest 事件驱动策略按 datetime.now() 给历史事件计龄
         → 贡献归零 → 比率恒为 0.65（等同静态套保）。**Task 5 必须关闭**。
- [ ] Task 5: 回测同路径
- [ ] Task 6: 三个新 EventType + LLM 接线
- [ ] Task 7: 周报接入
- [ ] Task 8: 文档同步

## 环境备注

- `python` 不在 PATH，测试命令一律用 `.venv/bin/python -m pytest`

## Minor findings (供最终 review 分诊)

- `tests/test_llm_commentary.py::test_html_none_hides_section` 在 **main 上即失败**，
  非本分支引入。Task 6 会触碰该文件，注意不要与之混淆。按铁律三未顺手修。
- Task 1 review FYI：第二个 commit 除了删 epsilon，还把
  `test_ratio_keeps_gradient_at_extremes` 的采样点从 5.0/6.0 改为 3.0/4.0 并
  多加了两条边界断言。无害且更强，但比"只修那一条过严断言"的最小改动略宽。
- `core/regime_config.py:527` `loader.scoring` property 未先调 `self.load()`，
  与同级 property（`adjustment_rules` / `settings`）不一致。若成为 loader 上的
  首个调用会静默返回 ScoringConfig() 默认值而非 YAML 实际值 —— 静默错而非报错。
  当前及计划中的所有调用点都先调了 load()，暂无实际影响。一行可修。
- spec 与计划的文字瑕疵：多处写「13 个因子簇」，实际簇集合是 14 个
  （brazil_supply, colombia_supply, climate, inventory, positioning, price,
  fx, macro, supply_fundamental, policy, ml, llm, scenario, technical）。
  Task 8 文档同步时一并订正。
- 计划 Task 3 Step 4 原文有误（称 PRICE_30D_EXTREME_UP/DOWN 缺失，实际已存在）。
  实现者已正确规避，未产生重复 key。
