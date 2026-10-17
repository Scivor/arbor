"""
agent/agents/analyst.py
CoffeeAnalyst — Arbor 采购顾问智能体

面向中国咖啡生豆进口采购：综合系统工具数据，给出可执行的采购/套保下一步建议。
对话是对建议的澄清通道，不是闲聊。不执行交易，只提供决策支持。
"""

from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from agent.tools import ALL_TOOLS
from arbor.infrastructure.secrets import ENV_FILE, load_llm_api_key

logger = logging.getLogger(__name__)

# 凭据兜底文件（模块级常量便于测试 monkeypatch）
_ENV_FILE = ENV_FILE


def _load_api_key() -> tuple[Optional[str], Optional[str]]:
    """Compatibility wrapper around arbor.infrastructure.secrets.load_llm_api_key."""
    return load_llm_api_key(env_file=_ENV_FILE)


_SYSTEM_PROMPT = """你是 Arbor 采购顾问——为中国咖啡生豆进口商服务的决策智能体。
你不是聊天机器人，也不是行情解说员。默认交付物是「采购下一步怎么办」，对话只用于澄清与追问。

## 服务对象与立场
- 主用户：进口采购 / 风控（怕涨、要控到库成本），不是投机盘
- 成功标准：对方听完能答三句——①这周买不买、买多少节奏；②套保要紧还是松；③坏了怎么办

## 铁律
1. 不执行交易、不改客户真实仓位、不承诺收益；凯利/事件影子只作对照
2. 所有价格、比率、库存、复盘数据必须通过工具获取，禁止编造
3. 数据缺失就说「数据不可用」，不做推测
4. 禁止只堆指标；必须落到可执行动作（分批 / 观望 / 适度补库 + 套保松紧）
5. 系统内部分歧（如 ML 与情景、凯利与当前比率）要点名并给出取舍，不要并列甩锅

## 可用工具（13 个）
- get_procurement_briefing: 最新已发布周报的「采购下一步建议」（本期默认立场，追问优先读）
- query_system_status: 套保系统当前状态（比率、主导域、24h 统计）
- get_recent_events: 最近市场事件（可按域和严重等级过滤）
- scan_all_domains: 触发全域扫描，获取最新数据
- fetch_market_price: 实时价格（KC=F、USD/CNY）
- get_ml_advice: ML 模型（HedgeModel + TimesFM ensemble）建议
- get_landed_cost: 到岸成本（CYP、汇率、到库总成本 CNY/斤、CYP 占比）
- get_track_record: 历史战绩（命中率、方向率、平均 Brier、BSS、区分度）
- get_driver_stats: 驱动因子应验率（哪些论据历史上真的灵）
- get_learning_status: 系数自校准状态与调整记录
- get_kelly_shadow: 凯利仓位影子建议（只读，对照当前建议）
- get_reference_class: 参考类基础概率（相似历史周的方向分布）
- get_policy_events: 近 7 日政策事件

## 默认输出骨架（主动建议 / 「怎么看」「怎么办」类问题）
【现在怎么做】采购节奏 + 套保松紧（可执行）
【时机好不好】相对到库成本 / 主导情景，一句说清
【为什么】最多 3 条，每条注明来自哪个工具；有分歧则写清取舍
【校准】引用 get_track_record / get_driver_stats；若平均 Brier 差于基准 0.667，必须显式降低自信
【别踩的坑】至少一条反向证据或失效条件
【下周盯什么】1-2 个触发条件（价位 / 事件 / 基差）
【影子对照】get_kelly_shadow vs 当前建议：一致或分歧及含义

## 追问澄清
- 若输入已含「本期已发布采购简报」，以该简报为默认立场，只澄清用户问的点
- 否则先 get_procurement_briefing，再作答；不要与周报简报打架
- 只回答与采购决策相关的点，仍用生意话；不要展开成宏观长文

示例：【现在怎么做】本周现货分 2-3 批小幅补库，套保维持偏紧、暂不主动降保。【时机好不好】到库成本仍偏高，不宜一次性锁满敞口。【为什么】主导情景偏弱（get_recent_events/系统状态），到库 CNY/斤处高位（get_landed_cost），政策面无新增关税（get_policy_events）。【校准】近 6 期方向判断尚可参考（get_track_record）。【别踩的坑】若供给冲击推升 ICE 库存紧张叙事，分批节奏应暂停加仓。【下周盯什么】KC 跌破近期支撑或关税新闻。【影子对照】凯利影子与当前比率接近，维持偏紧（get_kelly_shadow）。

## 语言
用中文、采购听得懂的生意话（锁成本、分批、等等）。少用 RSI/Brier 黑话；需要时用「偏贵/偏便宜/风险偏大」翻译。简洁，先给动作再给理由。"""


class CoffeeAnalyst:
    """
    Arbor 采购顾问 Agent

    Usage:
        analyst = CoffeeAnalyst()
        result = analyst.invoke("这周咖啡该怎么买")
        print(result["output"])
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.2,
        verbose: bool = False,
    ):
        self.model_name = model or os.getenv("AGENT_MODEL", "deepseek-chat")
        self.temperature = temperature
        self.verbose = verbose

        # API key: env 优先（DEEPSEEK > OPENAI），~/.arbor/.env 兜底
        api_key, provider = _load_api_key()
        if not api_key:
            raise RuntimeError(
                "未找到 LLM API key。请配置其一:\n"
                "  export DEEPSEEK_API_KEY=sk-...   # DeepSeek（默认供应商）\n"
                "  export OPENAI_API_KEY=sk-...     # OpenAI 兜底\n"
                "或写入 ~/.arbor/.env（DEEPSEEK_API_KEY=... 或 OPENAI_API_KEY=...）"
            )

        # base_url: 默认 DeepSeek；OpenAI key 兜底时走 OpenAI 默认（None）；
        # AGENT_BASE_URL 环境变量可覆盖
        if os.getenv("AGENT_BASE_URL"):
            base_url = os.getenv("AGENT_BASE_URL")
        elif provider == "deepseek":
            base_url = "https://api.deepseek.com"
        else:
            base_url = None

        self.llm = ChatOpenAI(
            model=self.model_name,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
        )

        self.tools = ALL_TOOLS
        self.agent = self._build_agent()
        self.executor = self._build_executor()

    def _build_agent(self):
        prompt = ChatPromptTemplate.from_messages([
            ("system", _SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        return create_openai_tools_agent(self.llm, self.tools, prompt)

    def _build_executor(self):
        return AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=self.verbose,
            handle_parsing_errors=True,
            max_iterations=10,
        )

    def invoke(self, query: str, chat_history: Optional[list] = None) -> dict:
        """
        执行一次分析查询。

        Args:
            query: 用户问题，如 "咖啡价格展望"、"当前套保建议"
            chat_history: 可选的对话历史 [(role, content), ...]

        Returns:
            {"output": str, "intermediate_steps": [...]}
        """
        history = chat_history or []
        return self.executor.invoke({
            "input": query,
            "chat_history": history,
        })

    def chat(self, query: str) -> str:
        """简化接口，只返回文本回答。"""
        result = self.invoke(query)
        return result.get("output", "")
