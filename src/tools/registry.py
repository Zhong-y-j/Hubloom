from __future__ import annotations

from typing import Any

from .base import BaseTool


class ToolRegistry:
    """工具注册表：name -> tool 实例，并生成给 LLM 的 tools 定义。
    未来扩展：支持 tags 参数，用于工具分组与按需注入。
        register(tool, tags=["file", "system"])
        list_definitions(active_tags=["memory", "web"])
    约定：
    - `register(tool: BaseTool)`：注册工具
    - `get(name: str)`：获取工具
    - `list_definitions()`：生成给 LLM 的工具定义（function 部分）
    - `from_tools(tools: list[BaseTool])`：从工具列表创建注册表
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_definitions(self) -> list[dict[str, Any]]:
        """生成给 LLM 的工具定义（function 部分）每个工具定义是一个字典，包含名称、描述和参数定义。

        Returns:
           [
            {
                "name": 工具名称,
                "description": 工具描述,
                "parameters": 工具参数定义,
            }
           ]
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]

    @classmethod
    def from_tools(cls, tools: list[BaseTool]) -> "ToolRegistry":
        reg = cls()
        for t in tools:
            reg.register(t)
        return reg
