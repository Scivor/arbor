"""
agent/runtime.py
AgentRuntime — Agent Swarm 的运行时入口

处理:
- 单命令模式: python coffee.py --agent "咖啡价格展望"
- 交互模式:   python coffee.py --agent
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.agents import CoffeeAnalyst  # noqa: F401 — 仅注解用，运行时惰性导入

class AgentRuntime:
    """
    Agent 运行时。

    Usage:
        runtime = AgentRuntime()
        runtime.run_once("咖啡价格展望")
        runtime.run_interactive()
    """

    def __init__(self):
        self.analyst: Optional["CoffeeAnalyst"] = None
        self._chat_history: list = []

    def _ensure_analyst(self) -> "CoffeeAnalyst":
        if self.analyst is None:
            from agent.agents import CoffeeAnalyst
            print("[Agent] 初始化 CoffeeAnalyst...")
            self.analyst = CoffeeAnalyst()
        return self.analyst

    def run_once(self, query: str) -> str:
        """执行单次查询并打印结果。"""
        analyst = self._ensure_analyst()
        print(f"\n[Agent] 查询: {query}\n")
        try:
            result = analyst.invoke(query)
            output = result.get("output", "")
            print(output)
            return output
        except Exception as e:
            msg = f"[Agent] 执行错误: {e}"
            print(msg)
            return msg

    def run_interactive(self):
        """启动交互式对话。"""
        analyst = self._ensure_analyst()

        print("\n" + "=" * 65)
        print("  COFFEE V3.0 — Agent Swarm 交互模式")
        print("=" * 65)
        print("命令:")
        print("  <任意问题>  — 向 Agent 提问")
        print("  scan        — 触发全域扫描后分析")
        print("  status      — 查询系统状态")
        print("  quit / q    — 退出")
        print("=" * 65 + "\n")

        while True:
            try:
                line = input("agent> ").strip()
                if not line:
                    continue

                if line in ("quit", "q", "exit"):
                    print("[Agent] 退出")
                    break

                if line == "scan":
                    line = "触发全域扫描，然后基于最新数据给出咖啡市场综合分析"
                elif line == "status":
                    line = "查询当前系统状态并解读"

                result = analyst.invoke(line, chat_history=self._chat_history)
                output = result.get("output", "")
                print(f"\n{output}\n")

                # 保留对话历史（简单方式，最多 10 轮）
                self._chat_history.append(("human", line))
                self._chat_history.append(("ai", output))
                if len(self._chat_history) > 20:
                    self._chat_history = self._chat_history[-20:]

            except KeyboardInterrupt:
                print("\n[Agent] 使用 'quit' 退出")
            except Exception as e:
                print(f"[Agent] 错误: {e}")


def main(args: Optional[list] = None):
    """
    Agent 模式入口。

    Args:
        args: sys.argv[2:] (去掉 --agent)
    """
    runtime = AgentRuntime()

    if args:
        # 单命令模式
        query = " ".join(args)
        runtime.run_once(query)
    else:
        # 交互模式
        runtime.run_interactive()
