# AI 在金融领域开源项目调查报告

**调研日期**: 2026-04-09
**调研范围**: GitHub 全球范围 AI/LLM 驱动的金融交易与量化投资开源项目
**数据来源**: GitHub API, 项目官方 README / arXiv

---

## 一、调研背景与目的

随着大语言模型（LLM）技术的成熟，AI Agent 正在加速渗透金融领域——从市场数据分析、策略生成、多 Agent 协作决策，到实盘交易执行，形成了一套全新的技术范式。本调查旨在系统梳理全球范围内具有代表性的开源 AI 金融项目，明确各项目 的定位、技术架构、功能边界与生态成熟度，为技术选型、行业研究和创业创新提供参考。

---

## 二、项目全景图（按 Star 数量排序）

| 排名 | 项目名称 | Stars | Forks | 主要语言 | 创建时间 | 最近更新 |
|:---:|----------|------:|------:|----------|----------|----------|
| 1 | **TradingAgents** (TauricResearch) | 48,887 | 8,860 | Python | 2024-12 | 2026-04 |
| 2 | **FinRL** (AI4Finance-Foundation) | 14,713 | 3,261 | Jupyter | 2020-07 | 活跃 |
| 3 | **AI-Trader** (HKUDS) | 12,724 | 2,138 | Python | 2025-10 | 2026-04 |
| 4 | **EliteQuant** | 3,787 | 659 | 多语言 | — | 活跃 |
| 5 | **OpenAlice** (TraderAlice) | 3,498 | 511 | TypeScript | 2026-02 | 2026-04 |
| 6 | **Polymarket/agents** | 2,795 | 637 | Python | 2024-07 | 2024-11 |
| 7 | **Lumibot** (Lumiwealth) | 1,328 | 268 | Python | 2020-09 | 2026-04 |
| 8 | **AutoHedge** (The-Swarm-Corporation) | 1,151 | 219 | Python | 2024-12 | 2026-03 |
| 9 | **Introduction-to-Quantitative-Finance** (Barca0412) | 1,318 | 153 | Python | 2023-08 | 活跃 |
| 10 | **Vibe-Trading** (HKUDS) | 427 | 87 | Python | 2026-04 | 2026-04 |
| 11 | **MAHORAGA** | 798 | — | TypeScript | — | — |
| 12 | **TradingAgents-MCPmode** | 282 | — | Python | — | — |
| 13 | **nof1.ai** | 645 | — | TypeScript | — | — |
| 14 | **CryptoTradingAgents** (Tomortec) | 249 | — | Python | — | — |
| 15 | **ai-trading-agent** (Gajesh2007) | 485 | — | Python | — | — |

> 数据截至 2026-04-09，Star 数量动态变化中。

---

## 三、重点项目深度分析

### 3.1 TradingAgents ⭐ 48,887 — 多智能体 LLM 金融交易框架

**链接**: https://github.com/TauricResearch/TradingAgents
**机构**: TauricResearch（学术团队，有对应论文 arXiv:2412.20138）

#### 核心定位
多 Agent 辩论框架，模拟真实交易公司的组织架构，通过不同专业角色的 Agent 协作完成市场分析、策略生成与交易决策。

#### 技术架构
使用 **LangGraph** 构建，模块化程度高。支持多 LLM Provider：OpenAI GPT 系列、Google Gemini、Anthropic Claude、xAI Grok、OpenRouter，以及本地 Ollama。

#### Agent 角色分工

```
┌─────────────────────────────────────────────────────┐
│                   Analyst Team                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐│
│  │Fundamental│ │ Sentiment │ │   News   │ │Technical││
│  │ Analyst  │ │ Analyst  │ │ Analyst  │ │Analyst ││
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘│
│       └────────────┴─────┬──────┴────────────┘       │
│                          ▼                           │
│                  Researcher Team                      │
│            (Bullish & Bearish Debate)                │
│                          ▼                           │
│                  Trader Agent                        │
│                          ▼                           │
│     ┌──────────────────────────────┐                │
│     │  Risk Management + Portfolio │                │
│     │         Manager              │                │
│     └──────────────────────────────┘                │
└─────────────────────────────────────────────────────┘
```

| Agent | 职责 |
|-------|------|
| Fundamentals Analyst | 评估公司财务、绩效指标，识别内在价值 |
| Sentiment Analyst | 分析社交媒体情绪，量化短期市场情绪评分 |
| News Analyst | 监测全球新闻与宏观经济指标，解读事件影响 |
| Technical Analyst | 运用 MACD、RSI 等技术指标识别价格模式 |
| Researcher Team | 多空双方辩论，平衡收益与风险 |
| Trader Agent | 综合分析报告，决定交易时机与仓位 |
| Risk Management | 持续评估组合风险，调整策略 |
| Portfolio Manager | 最终批准/否决交易提案 |

#### 主要特性
- **多 Provider 支持**: GPT-5.x / Gemini 3.x / Claude 4.x / Grok 4.x
- **辩论机制**: 研究员团队进行结构化多空辩论
- **Docker 支持**: 一键容器化部署（含 Ollama 本地模型配置）
- **CLI 交互**: TUI 界面选择股票、分析日期、LLM Provider、研究深度
- **Python API**: `TradingAgentsGraph().propagate("NVDA", "2026-01-15")`
- **最新版本**: v0.2.3（2026-03），支持多语言、backtesting date fidelity、代理支持

#### 不足
- 无内置回测系统
- 无 Skill 生态体系
- 无 MCP 插件
- 无 Pine Script 导出能力
- 主要面向研究，CLI 为主，Web UI 薄弱

---

### 3.2 FinRL ⭐ 14,713 — 金融强化学习框架

**链接**: https://github.com/AI4Finance-Foundation/FinRL
**机构**: AI4Finance-Foundation（较为成熟的学术开源组织）

#### 核心定位
面向金融的深度强化学习框架，专注使用 DRL（深度强化学习）算法进行股票、加密资产的投资组合管理。提供端到端训练-验证-测试流程。

#### 支持的 DRL 算法
- DDPG (Deep Deterministic Policy Gradient)
- TD3 (Twin Delayed DDPG)
- PPO (Proximal Policy Optimization)
- SAC (Soft Actor-Critic)
- A2C / A3C
- DRQN (Deep Recurrent Q-Network)

#### 特色模块
- **ElegantRL**: 轻量级 DRL 库，底层支持 GPU 加速
- **多市场覆盖**: NYSE, NASDAQ, 加密货币, Forex
- **经纪商集成**: Alpaca, Interactive Brokers, Binance
- **Backtesting**: 支持 VectorBT, FinRL-Meta（数据管理）

#### 定位
偏学术和算法研究，适合用强化学习做量化策略的研究者，不适合直接作为交易 Agent 使用。

---

### 3.3 AI-Trader ⭐ 12,724 — 全自动 Agent-Native 交易系统

**链接**: https://github.com/HKUDS/AI-Trader
**机构**: HKUDS（香港大学数据科学实验室）

#### 核心定位
100% 全自动 Agent-Native 交易系统，强调"一句话生成交易策略→自动执行"。

#### 特点
- 与 Vibe-Trading 同属 HKUDS 生态
- 定位更激进，强调无需人工干预的"全自动"
- 同样使用 OpenAI-compatible API
- 支持多市场（A股、港股、美股、加密）

---

### 3.4 Vibe-Trading ⭐ 427 — 技能生态 + Swarm 多团队 + 跨市场回测

**链接**: https://github.com/HKUDS/Vibe-Trading
**机构**: HKUDS
**详细分析在前次调研中已产出，此处补充定位对比**

#### 差异化定位
Vibe-Trading 是本次调研中**技能化程度最高**的项目，核心创新在于：

1. **68 个 Finance Skills**: 每个 Skill 为独立的功能模块（SKILL.md），覆盖策略、分析、资产类别、加密货币、资金流、工具 7 大类
2. **29 个 Swarm 团队预设**: DAG 编排的多 Agent 协作模板，可一键部署专业交易团队
3. **5 数据源自适应降级**: tushare / yfinance / OKX / AKShare / CCXT，零 API Key 也能运行
4. **Pine Script v6 导出**: 策略可直接转换为 TradingView 指标
5. **MCP Server**: 16 个工具暴露为标准 MCP 协议，可接入任何 MCP 兼容的 AI 客户端

#### 与 TradingAgents 的关键差异

| 维度 | Vibe-Trading | TradingAgents |
|------|-------------|---------------|
| 架构范式 | ReAct 单 Agent + Skills | 多 Agent 辩论（平等角色） |
| 技能系统 | **68 个 Skills** | 无 |
| Swarm 预设 | **29 个预设团队** | 无 |
| 回测引擎 | **5 数据源跨市场** | 无 |
| Pine Script | **支持** | 无 |
| MCP 插件 | **16 tools** | 无 |
| 数据源 | 免费数据源优先 | 仅 Alpha Vantage |
| 前端 | **React 19 Web UI** | CLI 为主 |
| 目标用户 | 个人交易者，开箱即用 | 研究人员，框架定制 |

---

### 3.5 Lumibot ⭐ 1,328 — 量化回测与交易框架

**链接**: https://github.com/Lumiwealth/lumibot
**机构**: Lumiwealth

#### 核心定位
专注于**回测和交易Bot开发**的框架，支持 Crypto、股票、期权、期货、外汇市场。强调与 AI Agent 策略的深度整合。

#### 特色
- 专为 AI 交易策略设计 Safer 回测和运行方式
- 支持多个交易所和数据源
- 相对成熟的框架，有商业化背景

---

### 3.6 AutoHedge ⭐ 1,151 — 自主对冲基金框架

**链接**: https://github.com/The-Swarm-Corporation/AutoHedge
**机构**: The Swarm Corporation

#### 核心定位
企业级自主对冲基金框架，专注 Solana 链上交易。

#### Agent 角色
| Agent | 职责 |
|-------|------|
| Director Agent | 策略生成与论点评审 |
| Quant Agent | 技术分析 + 统计分析 |
| Risk Management Agent | 仓位管理与风险评估 |
| Execution Agent | 订单生成与执行 |

#### 当前状态
- 仅支持 Solana 全自主交易
- Coinbase 集成开发中
- 风险优先架构，强调仓位管理

---

### 3.7 OpenAlice ⭐ 3,498 — 文件驱动的 AI 交易引擎

**链接**: https://openalice.ai
**机构**: TraderAlice

#### 核心定位
文件驱动的 AI 交易 Agent 引擎，支持加密货币和证券市场。**已有商业化产品**，定位偏向产品级应用。

#### 技术栈
- TypeScript（区别于大多数 Python 主导的量化项目）
- 有独立商业化网站和服务

---

### 3.8 Polymarket/agents ⭐ 2,795 — 预测市场 AI Agent

**链接**: https://github.com/Polymarket/agents

#### 核心定位
在 Polymarket 预测市场进行自主交易的 AI Agent。

#### 特点
- 针对二元预测市场优化
- 相对垂直的场景，不是通用交易框架
- 更新频率较低（2024-11 后无更新）

---

## 四、技术范式分类

### 4.1 多 Agent 协作架构（主流范式）

代表项目：**TradingAgents**, **AutoHedge**, **Vibe-Trading (Swarm)**

```
[User Input]
      │
      ▼
┌─────────────┐     ┌─────────────┐
│  Analyst    │────▶│  Researcher  │
│  (多角色)   │     │  (多空辩论)  │
└─────────────┘     └──────┬──────┘
                            │
                            ▼
                    ┌─────────────┐
                    │   Trader    │
                    │   Agent     │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │Risk Manager │
                    │+ Portfolio  │
                    └─────────────┘
```

### 4.2 强化学习驱动架构

代表项目：**FinRL**, **ucaiado/rl_trading**

- 使用 DDPG, PPO, SAC 等 DRL 算法
- 端到端从数据到交易决策
- 适合学术研究和算法挖掘

### 4.3 Skill / Tool 生态架构

代表项目：**Vibe-Trading**（最典型）

- 以 Skill 为原子能力单元
- 68 个专业化 Finance Skills
- 支持 MCP 协议接入外部 Agent

### 4.4 文件驱动执行架构

代表项目：**OpenAlice**, **nof1-tracker**

- 以文件系统或配置文件为输入
- 外部 Agent/LLM 解析后驱动交易

---

## 五、数据源与市场覆盖对比

| 项目 | A股 | 港股 | 美股 | 加密 | 期货 | 外汇 | 预测市场 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| TradingAgents | — | — | ✅ | — | — | — | — |
| Vibe-Trading | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| FinRL | ✅ | — | ✅ | ✅ | — | ✅ | — |
| AutoHedge | — | — | — | — | — | — | — |
| Lumibot | — | — | ✅ | ✅ | ✅ | ✅ | — |
| Polymarket agents | — | — | — | — | — | — | ✅ |
| OpenAlice | — | — | ✅ | ✅ | — | — | — |

---

## 六、LLM Provider 支持矩阵

| 项目 | OpenAI | Gemini | Claude | Grok | Local(Ollama) | OpenRouter |
|------|:------:|:------:|:------:|:----:|:-------------:|:----------:|
| TradingAgents | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Vibe-Trading | ✅ | — | — | — | — | ✅ |
| AutoHedge | ✅ | — | — | — | — | — |
| FinRL | — | — | — | — | — | — |

---

## 七、应用场景映射

| 场景 | 推荐项目 |
|------|---------|
| 学术研究 / 论文发表 | **FinRL**（强化学习）, **TradingAgents**（多 Agent 框架） |
| 个人投资者 / 开箱即用 | **Vibe-Trading**（Skill + 回测 + MCP） |
| 企业级交易系统 | **AutoHedge**（风险优先架构） |
| 预测市场套利 | **Polymarket/agents** |
| 策略到 TradingView 落地 | **Vibe-Trading**（Pine Script 导出） |
| 加密货币 Solana 生态 | **AutoHedge** |
| 多市场量化研究 | **Lumibot**, **FinRL** |
| 接入现有 AI Agent | **Vibe-Trading**（MCP Server） |

---

## 八、关键发现与结论

### 8.1 市场格局总结

1. **TradingAgents (48.9k ⭐)** 是当前最热门的开源 AI 金融框架，以多 Agent 辩论架构为核心，适合学术研究，但缺乏回测、Skill 生态和 MCP 集成

2. **Vibe-Trading (427 ⭐)** 定位独特，以 **Skill 生态 + Swarm 团队预设 + 跨市场回测** 为差异化，是目前最接近"个人 AI 交易助手"这一定位的开源方案，与 TradingAgents 是互补关系而非直接竞争

3. **FinRL (14.7k ⭐)** 是强化学习量化交易的标杆，偏学术；**AI-Trader (12.7k ⭐)** 和 Vibe-Trading 同属 HKUDS，组合使用效果更佳

4. **AutoHedge** 是真正在做实盘执行的项目，但目前只支持 Solana，生态尚早期

5. 大多数项目仍处于研究阶段，明确声明"不构成投资建议"

### 8.2 技术趋势

- **多 Agent 协作**是主流架构范式
- **Skill/Tool 生态**正在成为新一代 AI 交易框架的标配
- **MCP 协议**开始被用于将交易能力接入通用 AI Agent
- **跨市场覆盖 + 零配置数据获取**是重要发展方向
- **Pine Script 导出**是策略落地的重要出口

### 8.3 风险提示

> ⚠️ 所有开源 AI 交易项目均明确声明：仅用于研究、模拟和回测，不构成投资建议，不执行真实交易（除 AutoHedge 等少数项目）。AI 生成的投资决策存在极高风险，历史表现不预示未来收益。

---

## 九、参考链接

| 项目 | 地址 |
|------|------|
| TradingAgents | https://github.com/TauricResearch/TradingAgents |
| Vibe-Trading | https://github.com/HKUDS/Vibe-Trading |
| FinRL | https://github.com/AI4Finance-Foundation/FinRL |
| AI-Trader | https://github.com/HKUDS/AI-Trader |
| OpenAlice | https://github.com/TraderAlice/OpenAlice |
| AutoHedge | https://github.com/The-Swarm-Corporation/AutoHedge |
| Lumibot | https://github.com/Lumiwealth/lumibot |
| Polymarket/agents | https://github.com/Polymarket/agents |
| Barca0412/Quant-Finance | https://github.com/Barca0412/Introduction-to-Quantitative-Finance |
| CryptoTradingAgents | https://github.com/Tomortec/CryptoTradingAgents |
| MAHORAGA | https://github.com/ygwyg/MAHORAGA |

---

*报告生成时间: 2026-04-09*
*调研工具: GitHub API, curl, Python json parsing*
