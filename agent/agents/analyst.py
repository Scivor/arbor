"""
agent/agents/analyst.py
CoffeeAnalyst — LLM 驱动的咖啡套保分析 Agent

基于 LangChain OpenAI Tools Agent，调用系统工具获取实时数据，
输出专业分析报告。不执行交易，只提供决策支持。
"""

from __future__ import annotations
import os
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from agent.tools import ALL_TOOLS


_SYSTEM_PROMPT = """你是一个资深咖啡大宗商品分析师，专注于阿拉比卡咖啡期货（KC=F）的进口套保策略分析。

## 铁律
1. 你不执行交易，只提供分析建议
2. 所有价格、比率、库存、复盘数据必须通过工具获取，禁止编造
3. 如果数据缺失，明确说明"数据不可用"，不做推测

## 可用工具（12 个）
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

## 输出结构（每次分析必须按此骨架）
【核心判断】方向 + 概率 %（必须给数字，禁止 0%/100%）
【依据】供给 / 金融 / 政策三面展开，每个论点标注来自哪个工具
【校准】引用 get_track_record / get_driver_stats：系统近期 Brier 与应验率如何修正本次置信度；若 Brier 差于基准 0.667，必须显式降低自信表述
【风险】至少一条反向证据
【套保视角】引用 get_kelly_shadow：凯利建议 vs 当前建议，一致或分歧及含义

示例：【核心判断】未来一周 KC=F 横盘偏弱，概率 55%。【依据】供给面 ICE 库存低位（get_recent_events），金融面价格跌破 MA20（fetch_market_price），政策面无新增关税事件（get_policy_events）。【校准】近 6 期平均 Brier 0.61 优于基准，方向判断可参考（get_track_record）。【风险】RSI 接近超卖，技术反弹概率上升。【套保视角】凯利影子建议 70% 与当前 65% 接近，维持中性偏紧（get_kelly_shadow）。

## 语言
用中文回答，专业、简洁。"""


class CoffeeAnalyst:
    """
    Coffee 分析 Agent

    Usage:
        analyst = CoffeeAnalyst()
        result = analyst.invoke("咖啡价格展望")
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

        # API key: DEEPSEEK_API_KEY 优先，OPENAI_API_KEY 兜底
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "未找到 LLM API key。请配置其一:\n"
                "  export DEEPSEEK_API_KEY=sk-...   # DeepSeek（默认供应商）\n"
                "  export OPENAI_API_KEY=sk-...     # OpenAI 兜底"
            )

        # base_url: 默认 DeepSeek；OPENAI_API_KEY 兜底时走 OpenAI 默认（None）；
        # AGENT_BASE_URL 环境变量可覆盖
        if os.getenv("AGENT_BASE_URL"):
            base_url = os.getenv("AGENT_BASE_URL")
        elif os.getenv("DEEPSEEK_API_KEY"):
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
