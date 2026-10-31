# Arbor / 阿尔博 — 咖啡进口商套期保值智能体

[![tests](https://github.com/Scivor/arbor/actions/workflows/tests.yml/badge.svg)](https://github.com/Scivor/arbor/actions/workflows/tests.yml)

事件驱动的咖啡进口商套期保值决策系统，支持回测、LLM 智能体、实时数据源与自动化周报。

**运行边界（采购风险改造第一阶段）**：ML、LLM、情景与 RSI 默认仅用于观察，不改变套保比率。`scoring.prediction_adjustments_enabled: true` 仅供显式研究对照；尚未完成样本外验证，不代表获准实盘。评分排除评分时刻之后的事件。现有 65% 基准仍是历史配置，不代表企业风险政策，建议比率不能直接当成订单。详见 `docs/procurement-risk-roadmap.md`。

**架构**: 事件驱动 (Event-Driven) + 三域并行 (Supply / Finance / Policy) + LLM Agent

---

## 核心功能

```
事件驱动套保决策
    供给域: 产区天气 / ONI / COT / ICE库存
    金融域: KC=F价格 / USD/CNY / Polymarket概率
    政策域: 关税 / 贸易战 / LDC地位 / 政策新闻
         ↓
  评分引擎 (arbor/domain/scoring.py) → 动态套保比率 (20%~95%)
    事件按类型半衰期衰减 → 14 个因子簇内递减求和 → tanh 软饱和
    CLI / 周报 / 回测共用同一个纯函数

周报流水线 (reports/)
    市场快照 / 情景分析 / ML预测 / 套保建议
    + 中国进口商视角 (汇率·到库成本·政策事件)
    + 参考类基础概率 / 凯利仓位影子（只读）
    + 采购下一步建议（规则五段简报；有 LLM key 时润色）
    → HTML (双语) / PDF / Markdown / briefing.json
    主出报: scripts/scheduler.py（周六 03:00 Asia/Shanghai → web/static/reports/）

战绩复盘 (reports/history + web/track_record)
    Brier 概率校准 / 驱动因子应验率 / 系数自校准 / 凯利影子账本

LLM 智能体 (agent/)
    CoffeeAnalyst（采购顾问人设）+ 13 个查询工具；追问页 /chat/

回测引擎 (backtest/)
    事件驱动回测: 无套保 / 静态65% / 事件驱动 三策略对比
```

---

## 快速开始

```bash
pip install -e .        # 安装（pyproject.toml 为依赖单一事实源）

# 实时扫描 + 完整报告
python coffee.py --demo

# 交互模式 (scan / status / report / events / inventory / policy / start / stop)
python coffee.py

# Paper Trading 模拟盘
python coffee.py --paper

# LLM Agent 模式 (需要 API key)
python coffee.py --agent "分析当前套保策略"

# 手动生成一期周报 (HTML + PDF，写入 web/static/reports/<日期>/)
python scripts/scheduler.py --now --format both

# 启动周报站 (http://127.0.0.1:8000)
python -m uvicorn web.app:app --host 127.0.0.1 --port 8000
```

---

## 项目结构

Clean Architecture 分层（详见 `ARCHITECTURE.md`）：

```
arbor/                     # 规范包（依赖只向内）
├── domain/                # 纯领域：types / scoring / cost / trading
├── application/           # 用例：DecisionEngine / ports / CoffeeSystem
├── infrastructure/        # 驱动：EventBus / SQLite / YAML / notify / secrets
└── adapters/              # 适配器归属说明（实体仍在仓库根目录）

# 根目录适配器 + 兼容 shim（旧 from core… 仍可用）
coffee.py / coffee_system.py
cli/  web/  agent/  reports/  domains/  sources/  models/  backtest/
core/                      # → re-export arbor.*
config/  scripts/  deploy/  tests/
```

---

## 数据源

| 数据源 | 模块 | 说明 |
|--------|------|------|
| KC=F 价格 | `sources/coffee` | Yahoo Finance chart API |
| KC=F 日线历史 | `sources/coffee/kc_history.py` | yfinance 5 年日线，本地缓存 7 天 |
| USD/CNY | `sources/fx` | Yahoo Finance |
| NOAA ONI | `sources/climate/noaa_oni.py` | www.cpc.ncep.noaa.gov |
| 产区天气 | `sources/climate/open_meteo.py` | Open-Meteo (巴西/哥伦比亚) |
| CFTC COT | `sources/cot` | 自动抓取 + `--inject` 手动输入 |
| ICE 库存 | `sources/inventory` | 手动输入 |
| Polymarket | `sources/markets` | gamma-api.polymarket.com |
| CME 结算价 | `sources/finance` | Nasdaq Data Link |
| USDA / World Bank | `sources/supply` | 供需与产区指标 |
| 政策新闻 | `sources/policy` | Google News RSS |

---

## 回测

`backtest/` 目录（无 strategies.py，勿引用旧文档）：

- `engines/base.py` — BaseEngine：信号对齐 + bar 循环
- `engines/coffee.py` — CoffeeFuturesEngine：期货保证金记账
- `engine.py` — 事件驱动回测：无套保 / 静态 65% 每月滚动 / 事件驱动（DecisionEngine）三策略对比
- `loader.py` / `metrics.py` / `models.py` — 数据加载 / 绩效指标 / 记录模型

---

## Agent 工具 (13 个)

`agent/tools/system.py`: `query_system_status` / `get_recent_events` / `scan_all_domains`

`agent/tools/market.py`: `fetch_market_price` / `get_ml_advice` / `get_landed_cost` / `get_procurement_briefing`

`agent/tools/analysis.py`: `get_track_record` / `get_driver_stats` / `get_learning_status` / `get_kelly_shadow` / `get_reference_class` / `get_policy_events`

---

## 周报与战绩页

- **生产真相源**: `scripts/scheduler.py` 每周六 **03:00 Asia/Shanghai** 写入 `web/static/reports/<日期>/`（HTML 中英 + PDF + Markdown + `briefing.json`；预测即将到来的 Mon–Fri）。站内 `/`、公众号稿、采购顾问都以这里为准。
- **邮件旁路**（非真相源）: `scripts/weekly_report_daemon.py` 每周一 09:00 Asia/Shanghai 仅用于 SMTP 订阅投递，**不覆盖**站内周报。详见 `docs/publishing.md`。
- **周报站** (`web/`): FastAPI；`/` 最新周报，`/reports/` 归档，`/track-record/` 战绩，`/chat/` 采购顾问追问。
- **战绩页** (`/track-record/`): 区间命中/方向/套保三率、平均 Brier 与概率校准桶、驱动因子应验率、系数自校准状态、凯利影子账本。
- **无人值守**: macOS launchd（`deploy/com.arbor.weekly-report.plist`）或 Linux systemd（`deploy/coffee-*.service`）拉起 **scheduler**；数据源降级/生成失败时 Telegram 告警（验证：`python scripts/scheduler.py --alert-test`）。详见 DEPLOY.md。

---

## 安装依赖

```bash
pip install -e .
# 或
uv pip install -e . --python .venv/bin/python
```

主要依赖: `yfinance`, `pandas`, `numpy`, `matplotlib` + `mplfinance`, `apscheduler`, `fastapi` + `uvicorn`, `langchain` + `langgraph`, `scikit-learn`。
PDF 导出另需 `playwright`（`python -m playwright install chromium`）。

---

## 测试

```bash
python -m pytest tests/ -q    # 364 个测试（无网络依赖，合成数据）
```

---

## License

MIT.

## 采购风险与模拟账务边界

模拟盘按剩余未定价采购量和整数手数建仓，KC一手约17.0097吨。需先输入每手保证金预算；未配置时不自动开仓。例如交互命令 `margin <USD>`、`tons <采购吨数>`、`priced <已定价吨数>`、`ratio <比例>`。保证金由用户提供，系统不会猜测当前交易所要求。

回测已修正累计盈亏、费用隔离和实际采购月份口径；仍是同价格序列的月度采购模拟。旧价格方向统计不再被展示为套保有效率。详情及未完成的实盘要求见 [改造记录](docs/procurement-risk-roadmap.md)。

## 按采购批次预览

```bash
python -m cli.procurement_plan docs/examples/purchase-batch.json --as-of 2026-10-30
```

示例中的行情、保证金、政策编号与退出日期都是演示输入，不是市场报价或经纪商通知。此命令只读取JSON并输出预览，不下单。必须按实际采购填写批次、已定价量、KC合约月份、定价日、经纪商确认的退出截止日、政策参考编号与汇率。输出区分剩余KC价格风险、浮动基差和未付款采购的汇率风险；税费、运费、融资与汇率对冲未包含。

模拟盘可通过 `PaperTradingEngine.sync_batch(...)` 按批次同步；需要与批次匹配的明确合约行情，不能使用未指定月份的 `KC=F` 代替。当前只维护一个批次持仓，切换批次须先显式平仓。

## 多批次持久化模拟账户

```bash
python -m cli.paper_portfolio docs/examples/paper-portfolio.json \
  --db ~/.arbor/portfolio-demo.db --account demo \
  --operation-id demo-001 --as-of 2026-10-30
```

仅写入本地模拟账本，不连接经纪商或发送订单。相同操作编号和相同输入可安全重试；输入变化必须使用新编号。示例全部为合成参数。

多个批次共享一个账户权益及保证金预算。先执行明确要求的平仓/减仓，再按 `batches` 的输入顺序分配新增仓位；未提及的批次保留持仓并继续占用预算。所有未平仓合约都必须有评估日的报价和每手保证金输入。`close_batch_ids` 用于明确关闭旧批次，换月需先显式平旧合约。

关闭程序后重新打开同一个数据库和账户，会恢复持仓、现金、费用、最后报价快照及操作历史；恢复的报价不是实时行情。旧单批次模拟账户不自动迁移至新组合账户。预算不足会阻止新增，保证金缺口或退出期限到期会提示复核，不擅自强平。

多批次模拟账户支持执行前预览：在 `cli.paper_portfolio` 命令中加入 `--dry-run`，可省略 `--operation-id`。仅支持已有账户，以只读方式返回拟成交、预计资金状态和风控拦截原因；不保存交易或预留资金。详见 `docs/procurement-risk-roadmap.md`。

完整的工程检查、离线评分与模拟账户验收步骤见 [整改验收操作手册](docs/acceptance-runbook.md)。该手册明确区分合成示例通过与真实业务验证。
