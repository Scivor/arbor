# 公众号发布 SOP

每周一篇，全流程约 5 分钟手工。

## 出报真相源（必读）

| 角色 | 脚本 | 时刻 | 产物去向 | 是否生产真相源 |
|------|------|------|----------|----------------|
| **主出报** | `scripts/scheduler.py` | 每周六 **03:00 Asia/Shanghai** | `web/static/reports/<date>/`（站内周报 / PDF / MD / briefing.json） | **是** |
| 邮件旁路 | `scripts/weekly_report_daemon.py` | 每周一 **09:00 Asia/Shanghai** | 本地 HTML + SMTP | **否**（只服务订阅邮件，不覆盖站内周报） |

运维与排障以周六 `scheduler` 为准。不要把周一 daemon 的输出当成「最新一期周报」。
手动补发也请用：

```bash
python scripts/scheduler.py --now --format both
```

---

## 1. 自动出报（周六 03:00 Asia/Shanghai）

launchd / systemd 调度的 `scripts/scheduler.py` 每周六 **03:00 Asia/Shanghai** 自动生成周报
（Cron 显式绑定时区，避免主机落在 UTC 时跑成 03:00 UTC = 11:00 北京时间）。
预测周默认 `forecast_offset=0`：即将到来的 Mon–Fri（勿用 1，否则会跳过一周）。
产物写入 `web/static/reports/<YYYY-MM-DD>/`：

| 文件 | 用途 |
|---|---|
| `report.html` / `report_en.html` | 在线版（中英双语） |
| `report.pdf` | PDF 归档 |
| `report.md` | **公众号用 markdown 源稿** |
| `briefing.json` | 采购简报 sidecar（聊天页 / Agent 优先读取） |

## 2. 接收发布提醒（Telegram）

出报成功后会收到一条 📰 发布提醒（含现价 / 套保建议 / AI 点评首句 / markdown 路径）。
未收到先看故障排查节。

> 区分: 🔴/🟡 是生成失败或降级的告警；📰 是常态发布提醒，收到它才进入第 3 步。

## 3. 复制排版发布

1. 打开 `web/static/reports/<date>/report.md`，全文复制。
2. 粘贴进 mdnice（或同类 markdown 排版工具），选一个简洁主题。
3. 重点检查三块：
   - **表格**（市场快照 / 关键价位 / 情景分析）是否渲染正常；
   - **情景分析**的概率与区间数字；
   - **采购下一步建议**小节（无 LLM key 时为规则五段简报，属正常降级；有 `DEEPSEEK_API_KEY` 时会 LLM 润色）。
4. 发布到小报童 / 知识星球。

## 4. 邮件订阅渠道（旁路，非真相源）

订阅者管理（数据存 `~/.arbor/subscribers.json`，用户数据不进 git）：

```bash
python scripts/subscribers.py add user@example.com    # 订阅（幂等）
python scripts/subscribers.py remove user@example.com # 退订（保留记录）
python scripts/subscribers.py list                    # 查看 active 订阅者
```

`scripts/weekly_report_daemon.py` 每周一 **09:00 Asia/Shanghai** 另生成一份 HTML 并通过 SMTP 发给
active 订阅者。**该路径不写入 `web/static/reports/`，不能替代周六主出报。**
订阅表为空时回退 `COFFEE_SMTP_TO`。SMTP 通过 `COFFEE_SMTP_HOST/PORT/USER/PASS` 配置。

## 故障排查

- **没收到 📰 提醒**：看 `output/logs/scheduler.err.log`（launchd stderr），
  确认出报是否成功；再用 `python scripts/scheduler.py --alert-test` 验证 Telegram 链路。
- **提醒收到但没有 report.md**：markdown 只在 `--format html|both` 下产出，
  确认调度命令的 `--format` 为 both。
- **采购建议只有规则版、文风偏模板**：`DEEPSEEK_API_KEY` 未配置或调用失败时
  会回退规则拼装（仍有五段行动建议）；要 LLM 润色请检查 `~/.arbor/.env`。
- **站内周报与邮件内容不一致**：以 `web/static/reports/<date>/`（周六 scheduler）为准。
