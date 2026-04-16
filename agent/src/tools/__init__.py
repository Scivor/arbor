"""Agent tools — Vibe-Trading tool registry + coffee_v3 extensions.

Vibe-Trading convention: tools are BaseTool ABC subclasses.
coffee_v3 extends with HedgeExecuteTool (dataclass-based).
"""

from agent.src.tools.backtest_tool import BacktestTool
from agent.src.tools.background_tools import BackgroundManager, BackgroundRunTool, CheckBackgroundTool
from agent.src.tools.bash_tool import BashTool
from agent.src.tools.compact_tool import CompactTool
from agent.src.tools.debate_tool import DebateTool
from agent.src.tools.doc_reader_tool import DocReaderTool
from agent.src.tools.edit_file_tool import EditFileTool
from agent.src.tools.factor_analysis_tool import FactorAnalysisTool
from agent.src.tools.hedge_execute_tool import HedgeExecuteTool
from agent.src.tools.load_skill_tool import LoadSkillTool
from agent.src.tools.options_pricing_tool import OptionsPricingTool
from agent.src.tools.pattern_tool import PatternTool
from agent.src.tools.read_file_tool import ReadFileTool
from agent.src.tools.subagent_tool import SubagentTool
from agent.src.tools.swarm_tool import SwarmRunTool, SwarmListTool, SwarmStatusTool
from agent.src.tools.task_tools import TaskManager, TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool
from agent.src.tools.web_reader_tool import WebReaderTool
from agent.src.tools.web_search_tool import WebSearchTool
from agent.src.tools.write_file_tool import WriteFileTool

# Vibe-Trading registry — uses BaseTool ABC from agent.src.agent.tools
from agent.src.agent.tools import ToolRegistry as BaseToolRegistry


def build_registry(skills_loader=None) -> BaseToolRegistry:
    """Build the full tool registry (Vibe-Trading convention).

    Args:
        skills_loader: SkillsLoader instance (required for LoadSkillTool).
    """
    registry = BaseToolRegistry()
    for tool in [
        BashTool(),
        CompactTool(),
        DocReaderTool(),
        EditFileTool(),
        FactorAnalysisTool(),
        LoadSkillTool(skills_loader=skills_loader),
        OptionsPricingTool(),
        PatternTool(),
        ReadFileTool(),
        SubagentTool(),
        TaskCreateTool(),
        TaskUpdateTool(),
        TaskListTool(),
        TaskGetTool(),
        BackgroundRunTool(),
        CheckBackgroundTool(),
        WebReaderTool(),
        WebSearchTool(),
        WriteFileTool(),
        # coffee_v3 native tools
        BacktestTool(),
        DebateTool(),
        HedgeExecuteTool(),
        SwarmRunTool(),
        SwarmListTool(),
        SwarmStatusTool(),
    ]:
        registry.register(tool)
    return registry


def build_filtered_registry(tool_names: list[str]) -> BaseToolRegistry:
    """Build a registry with only specified tool names."""
    full = build_registry()
    filtered = BaseToolRegistry()
    for name in tool_names:
        tool = full.get(name)
        if tool:
            filtered.register(tool)
    return filtered


__all__ = [
    # Vibe-Trading registry functions
    "build_registry",
    "build_filtered_registry",
    # tools
    "BacktestTool",
    "BackgroundManager",
    "DebateTool",
    "BackgroundRunTool",
    "CheckBackgroundTool",
    "BashTool",
    "CompactTool",
    "DocReaderTool",
    "EditFileTool",
    "FactorAnalysisTool",
    "HedgeExecuteTool",
    "LoadSkillTool",
    "OptionsPricingTool",
    "PatternTool",
    "ReadFileTool",
    "SubagentTool",
    "SwarmRunTool",
    "SwarmListTool",
    "SwarmStatusTool",
    "TaskManager",
    "TaskCreateTool",
    "TaskUpdateTool",
    "TaskListTool",
    "TaskGetTool",
    "WebReaderTool",
    "WebSearchTool",
    "WriteFileTool",
]
