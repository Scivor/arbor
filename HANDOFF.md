# Arbor — Handoff（已归档）

> **请先读**: [`ARCHITECTURE.md`](ARCHITECTURE.md)（依赖规则与规范包）· [`README.md`](README.md)（功能与入口）。
>
> 本文保留 2026-07 前后的交接快照，**数字与目录结构已过时**，勿再当现行说明。

| 项 | 现行 | 本文旧值（勿用） |
|----|------|------------------|
| 架构入口 | `arbor/` + `ARCHITECTURE.md` | 根目录 `core/` 当规范包 |
| 评分 | `arbor/domain/scoring.py` | `core/state/scoring.py` |
| 预测与套保 | `coffee.py --demo`、`python -m reports.cli`、`coffee.py --paper` | Agent、网站、周报调度、采购顾问 |

---

## 历史快照（2026-07-20，只读）

**状态（当时）**: Paper Trading 已完成，Agent Swarm MVP 已补，CLI 已拆分；套保比率统一为无状态因子评分。

当时目录与待办见 git 历史；新工作请以 `ARCHITECTURE.md` / `README.md` 为准。

### 当时快速验证

下面两条仍可用。`--agent` 和 `scripts/scheduler.py` 已随采购顾问、网站和周报调度一起删除。

```bash
pip install -e .
python coffee.py --demo
python coffee.py --paper ratio 0.80 mtm 215.50 status
python -m pytest tests/ -q
```
