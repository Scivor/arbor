# 整改分支验收操作手册

本手册用于验证程序行为，不作为策略有效性或实盘授权证明。全部 examples 数据为合成数据，包括日期、交易日历、概率、价格、保证金及政策编号。示例未来日期仅用于离线测试，不代表已取得未来行情。

## 1. 工程检查

在仓库根目录、独立 Python 3.11 或 3.12 环境运行：

```sh
python -m pip install -e '.[dev]'
ruff check .
python -m pytest tests/ -q
```

需分别保存环境版本、提交 SHA、测试结果。远端 Actions 必须针对 PR 当前提交实际运行通过；本地成功或无合并冲突不能替代远端结果。工作流未出现时，检查 Actions 中 tests 工作流是否可手动运行，并选择整改分支。没有运行记录不等于通过。

## 2. 离线标签与概率诊断

```sh
python -m cli.forecast_labels docs/examples/forecast-labels.json \
  --evaluated-at 2026-11-09T20:00:00+00:00 \
  --probabilities docs/examples/forecast-probabilities.json
```

示例预期：1 条 labeled、方向 up、模型 Brier 0.26；一个分组、一个非重叠窗口。浮点表示允许舍入差异。archive_sha256 与 probabilities_sha256 分别追溯输入文件；provenance_verified、calibration_validated、has_skill 均不得因此变成 true。

将评估时刻改为 2026-11-05T20:00:00+00:00，应输出 pending、target_session_not_closed，已评分数为0。不得将缺失标签当作预测失败或成功。

## 3. 多批次模拟账户

使用独立演示数据库，不能指向正式账本。首次以下命令会创建账户并执行模拟交易：

```sh
python -m cli.paper_portfolio docs/examples/paper-portfolio.json \
  --db /tmp/arbor-acceptance-demo.db --account acceptance-demo \
  --operation-id acceptance-initial --as-of 2026-10-30
```

预期两个批次分别持有2手、1手，现金19955美元、保证金15000美元。原样重试应返回同一操作结果且不重复成交。若该路径已有其他测试账户，请换新路径，不覆盖或清空已有数据库。

对同一账户运行预览：

```sh
python -m cli.paper_portfolio docs/examples/paper-portfolio.json \
  --db /tmp/arbor-acceptance-demo.db --account acceptance-demo \
  --as-of 2026-10-30 --dry-run
```

预期 PREVIEW_NO_ORDER、无新增成交，原账本与操作历史不变。执行前将预览 base_version 写入请求顶层 expected_version；账户若已变化应拒绝，重新预览后再核对。该检查只保护账户版本，不冻结价格、保证金或审批。

## 4. 真实数据接入清单

| 输入 | 必须确认的内容 | 当前能力边界 |
|---|---|---|
| 预测档案 | 原始发布时间、数据截止时间、参考价、合约、冻结阈值及模型版本 | 可导入，发布时冻结证据未验证 |
| 概率文件 | 预测ID对应的原始三类概率，不能事后重写 | 可评分，哈希不是可信时间证明 |
| 交易日历 | 目标市场完整日历、带时区收盘时间和版本 | 由输入提供，不验证日历来源 |
| 合约行情 | 同合约收盘价、首次可用时间和来源 | 不允许后续日期或其他合约替代 |
| 采购与账户 | 真实未定价量、期限、合约、保证金和费用 | 支持模拟；未接入真实结算和对账 |
| 企业政策 | 已批准的比例、额度、权限及有效版本 | 审批校验尚未实现 |

## 5. 尚未达到的验收条件

- 正式数据来源核验、线上报告接入、滚动样本外校准与稳定增益证明。
- 逐日结算、出入金、真实采购成本回测和经纪商对账。
- 业务页面、旧账户迁移、部署与实盘接口。

PR 保持草稿直至对应工程和业务验收完成；不因合成示例通过而启用预测调仓。

## 自动回归入口

上述随仓库提供的 JSON 示例由 `tests/test_acceptance_examples.py` 直接通过命令行执行，包含标签及待补齐状态、分组评分、账户重复提交、只读预览和过期版本执行拒绝。测试使用临时数据库，运行结束自动清理。可单独运行：

```sh
python -m pytest tests/test_acceptance_examples.py -q
```

该文件已纳入现有全量 pytest 命令；不需要另加 CI 工作流。自动回归依然只验证合成样例行为。

评分 API 的 report 必须包含带时区的 evaluated_at。对所有已标记结果，评分层独立验证：发布时间 < 目标收盘时间 ≤ 结果可用时间 ≤ 评估时间。无时区、顺序错误或尚不可用的结果会被拒绝，即使调用方绕过离线导入入口也不能计分。此校验只验证输入的一致性，不证明时间戳来源真实。
