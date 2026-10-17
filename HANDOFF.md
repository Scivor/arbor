# Arbor — Handoff（已归档）

> **请先读**: [`ARCHITECTURE.md`](ARCHITECTURE.md)（依赖规则与规范包）· [`README.md`](README.md)（功能与入口）· [`docs/publishing.md`](docs/publishing.md)（周报出报真相源）。
>
> 本文保留 2026-07 前后的交接快照，**数字与目录结构已过时**，勿再当现行说明。

| 项 | 现行真相（2026-10） | 本文旧值（勿用） |
|----|---------------------|------------------|
| 架构入口 | `arbor/` + `ARCHITECTURE.md` | 根目录 `core/` 当规范包 |
| 评分 | `arbor/domain/scoring.py` | `core/state/scoring.py` |
| Agent 工具 | **13** | 6 |
| 测试 | **364** | 16 / 150 |
| 周报主出报 | `scripts/scheduler.py` 周六 03:00 Asia/Shanghai → `web/static/reports/` | 未区分主/旁路 |
| 邮件旁路 | `scripts/weekly_report_daemon.py`（不覆盖站内周报） | — |
| 采购顾问 | `/chat/` + `briefing.json` + 规则五段简报 | — |

---

## 历史快照（2026-07-20，只读）

**状态（当时）**: Paper Trading 已完成，Agent Swarm MVP 已补，CLI 已拆分；套保比率统一为无状态因子评分。

当时目录与待办见 git 历史；新工作请以 `ARCHITECTURE.md` / `README.md` 为准。

### 当时快速验证（命令仍大致可用）

```bash
pip install -e .
python coffee.py --demo
python coffee.py --paper ratio 0.80 mtm 215.50 status
python coffee.py --agent "分析当前套保策略"
python -m pytest tests/ -q
python scripts/scheduler.py --now --format both
```
