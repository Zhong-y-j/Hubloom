from typing import Any, Dict

from mcp_adapter import MCPToolClient
from tools.base import BaseTool


def _filter_args(parameters: Dict[str, Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """只转发 JSON Schema ``properties`` 里声明的字段，减少无关参数触发的校验错误。"""
    props = parameters.get("properties") if isinstance(parameters, dict) else None
    if not isinstance(props, dict) or not props:
        return dict(kwargs)
    allowed = set(props.keys())
    return {k: v for k, v in kwargs.items() if k in allowed}


class MCPTool(BaseTool):
    """一个代理工具，代表远程 MCP Server 上的一个具体工具。

    对 Agent 而言，它和本地工具完全一样。
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        client: MCPToolClient,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        """执行远程工具调用，将参数传递给 MCP Server。"""
        payload = _filter_args(self.parameters, kwargs)
        return await self._client.execute_tool(self.name, payload)
