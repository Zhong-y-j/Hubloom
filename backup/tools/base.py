from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """工具基类：定义工具的名称/描述/JSON-Schema，并提供异步执行入口。

    约定：
    - `name`：工具名称
    - `description`：工具描述
    - `parameters`：工具参数
    - `execute()`：执行工具，返回文本结果。
    """

    name: str
    description: str
    parameters: dict[str, Any]

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """执行工具，返回文本结果（必要时可以返回 JSON 字符串）。"""
        raise NotImplementedError
