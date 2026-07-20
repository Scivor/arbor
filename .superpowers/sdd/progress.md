# 套保比率无状态因子评分 — 执行进度

Plan: docs/superpowers/plans/2026-07-20-hedge-ratio-scoring.md
Branch: feat/hedge-ratio-scoring
Base: 7c5d0ed

预检决议: DecisionEngine 构造函数去掉 use_yaml 布尔参数，改为显式注入
rules/cfg（None → 从 YAML 加载）。原因：删除 _FALLBACK_EVENT_CONFIG 后
use_yaml=False 会导致规则表为空；而 loader 在 local_only=False 时会联网，
不能简单全改 True。计划已相应更新。

## 任务

- [ ] Task 1: scoring.py 纯函数核心
- [ ] Task 2: regime_config 扩展
- [ ] Task 3: regimes.yaml 填充
- [ ] Task 4: DecisionEngine 薄壳
- [ ] Task 5: 回测同路径
- [ ] Task 6: 三个新 EventType + LLM 接线
- [ ] Task 7: 周报接入
- [ ] Task 8: 文档同步

## Minor findings (供最终 review 分诊)

（暂无）
