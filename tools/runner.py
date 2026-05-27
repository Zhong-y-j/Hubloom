import asyncio
from .registry import ToolRegistry


class ToolRunner:
    """工具运行器：执行工具，并返回结果。

    Args:
        tools: 工具注册表
        allowed_tools: 允许调用的工具列表
        tool_max_attempts: 工具调用的最大重试次数
    """

    def __init__(
        self,
        tools: ToolRegistry,
        *,
        allowed_tools: set[str] | None = None,
        tool_max_attempts: int = 2,
    ):
        self.tools = tools
        self.allowed_tools = allowed_tools
        self.tool_max_attempts = max(1, tool_max_attempts)

    async def run(self, name: str, args: dict) -> tuple[str, bool]:
        if self.allowed_tools is not None and name not in self.allowed_tools:
            return f"Tool not allowed: {name}", True

        tool = self.tools.get(name)
        if tool is None:
            return f"Tool not found: {name}", True

        last_err: Exception | None = None
        for attempt in range(1, self.tool_max_attempts + 1):
            try:
                return await tool.execute(**args), False
            except Exception as e:
                last_err = e
                if attempt < self.tool_max_attempts:
                    await asyncio.sleep(0.3 * attempt)
        return f"Tool execution error: {last_err}", True
