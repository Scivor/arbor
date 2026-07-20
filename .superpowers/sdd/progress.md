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
      (已由 Task 5 关闭) 遗留 Critical C1：backtest 事件驱动策略按 datetime.now() 给历史事件计龄
         → 贡献归零 → 比率恒为 0.65（等同静态套保）。**Task 5 必须关闭**。
- [x] Task 5: 回测同路径 — complete (commit 3bb43fa, review clean)
      Critical C1 已关闭：回测比率区间 0.65→0.92（修复前恒为 0.65）
- [x] Task 6: 三个新 EventType + LLM 接线 — complete (commit 191822d, review clean)
- [x] Task 7: 周报接入 — complete (commits b41523b..78d9484, review clean)
      修了 review 的 3 个 Important + 修复轮自身引入的 china_import 上下文回归
- [x] Task 8: 文档同步 — complete (commit 349b08f)

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
- 「回测零网络」是**偶然**而非结构性保证：`get_regime_loader()` 仅在
  `config/regimes.yaml` 存在时才 pin `local_only=True`，文件缺失会回落到
  `requests.get(MANIFEST_URL)`。属既有代码、非本分支引入，实盘路径同样如此。
  若要硬保证，需在回测/测试上下文显式构造 `RegimeConfigLoader(local_only=True)`。
- Task 7 review Minor（未修，留待分诊）：
  * `gather_report_events(now=...)` 未传递给 scenario/rsi/llm 三个构造函数，
    它们各自调 `datetime.now()`。生产无影响（run() 从不传 now），但违背
    scoring.py 的「时间由调用方传入」约束，回测报告路径时会踩到。
  * DB 载入的事件一律硬编码 `domain=Domain.SUPPLY`（如 CHINA_TARIFF_CHANGE
    被重建成 SUPPLY）。compute_score 不看 domain 所以当前无评分影响。
- 端到端验证副作用：Task 7 期间真实联网出过一期报告，在
  `~/.arbor/reports/weekly_summary_2026-07-20.json` 留下记录（hedge_ratio 0.81），
  并调用了 2 次 DeepSeek API。**待用户决定是否删除。**

## 最终全分支 review 后的修复（已完成）

- 三域全量扫描接入 gather_report_events（spec §2.4 的缺失前半截），每域独立降级
- 去重窗口按事件类型取 cooldown_seconds（此前是死的 1 小时，会吃掉合法重复）
- 规则表为空 → compute_hedge_advice 抛错（此前静默退化成恰好 0.65）
- loader.scoring 补 self.load()
- 溯源表方法学说明订正为「14 个因子簇加权评分」
- 补 DB 行解析测试（真实 SQLite 行 / 未知类型跳过 / 坏行不连累后续 / 去重生效）
- tests/conftest.py 阻断 socket：全量测试 233s → 3.7s，揪出 4 个偷偷联网的测试

## 合并前状态：可合并

全量 294 passed / 1 failed（既有失败，main 上即红）；ruff 全绿。
