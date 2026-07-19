# 公众号发布 SOP

每周一篇，全流程约 5 分钟手工。

## 1. 自动出报（周六 03:00 CST）

launchd / systemd 调度的 `scripts/scheduler.py` 每周六 03:00 自动生成周报，
产物写入 `web/static/reports/<YYYY-MM-DD>/`：

| 文件 | 用途 |
|---|---|
| `report.html` / `report_en.html` | 在线版（中英双语） |
| `report.pdf` | PDF 归档 |
| `report.md` | **公众号用 markdown 源稿** |

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
   - **AI 分析师点评**小节是否存在（无 LLM key 时该节缺席，属正常降级）。
4. 发布到小报童 / 知识星球。

## 4. 邮件订阅渠道

订阅者管理（数据存 `~/.arbor/subscribers.json`，用户数据不进 git）：

```bash
python scripts/subscribers.py add user@example.com    # 订阅（幂等）
python scripts/subscribers.py remove user@example.com # 退订（保留记录）
python scripts/subscribers.py list                    # 查看 active 订阅者
```

`scripts/weekly_report_daemon.py` 每周一 09:00 生成报告并通过 SMTP 发送给
active 订阅者；订阅表为空时回退 `COFFEE_SMTP_TO` 环境变量。
SMTP 通过 `COFFEE_SMTP_HOST/PORT/USER/PASS` 配置。

## 故障排查

- **没收到 📰 提醒**：看 `output/logs/scheduler.err.log`（launchd stderr），
  确认出报是否成功；再用 `python scripts/scheduler.py --alert-test` 验证 Telegram 链路。
- **提醒收到但没有 report.md**：markdown 只在 `--format html|both` 下产出，
  确认调度命令的 `--format` 为 both。
- **AI 点评缺席**：`DEEPSEEK_API_KEY` 未配置或调用失败（静默降级），
  检查 `~/.arbor/.env`。
