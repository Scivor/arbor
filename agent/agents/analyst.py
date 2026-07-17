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

## 职责
1. 通过工具查询系统状态、市场数据和 ML 模型建议
2. 基于真实数据给出专业分析，绝不编造数据
3. 如果工具不可用，如实说明，不做推测
4. 用中文回答，保持专业、简洁

## 可用工具
- query_system_status: 查询套保系统当前状态（套保比率、主导域、24h 统计）
- get_recent_events: 获取最近市场事件（可按域和严重等级过滤）
- scan_all_domains: 触发全域扫描，获取最新数据
- fetch_market_price: 获取实时价格（KC=F、USD/CNY）
- get_ml_advice: 获取 ML 模型（HedgeModel + TimesFM）建议
- get_landed_cost: 计算基于当前价格的到岸成本

## 分析框架
- 供给端：天气（ONI、霜冻）、ICE 库存、COT 持仓结构
- 金融端：KC=F 价格趋势、USD/CNY 汇率、基差
- 政策端：关税、贸易战、LDC 地位变化
- ML 信号：统计模型和时序模型的 ensemble 方向建议

## 约束
- 你不执行交易，只提供分析建议
- 所有价格、比率、库存数据必须通过工具获取，禁止编造
- 如果数据缺失，明确说明 "数据不可用"
- 分析结论必须标注依据（如 "基于 ML 信号偏空..."）
"""


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
        self.model_name = model or os.getenv("AGENT_MODEL", "gpt-4o-mini")
        self.temperature = temperature
        self.verbose = verbose

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY 未设置。请设置环境变量:\n"
                "  export OPENAI_API_KEY=sk-..."
            )

        self.llm = ChatOpenAI(
            model=self.model_name,
            temperature=temperature,
            api_key=api_key,
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
