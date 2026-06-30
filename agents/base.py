from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from core.models import Message, Role
from core.provider import LLMProvider

from .events import AgentEvent
from memory.manager import MemoryManager


class BaseAgent(ABC):
    """所有 Agent 范式必须实现的抽象基类。

    约定：
    - `run()`：非流式，一次拿到最终结果
    - `run_stream()`：流式产出事件（适合 WebSocket/SSE）
    - `add_message()` / `get_history()`：对话历史的通用能力
    """

    def __init__(
        self,
        llm: LLMProvider,
        *,
        system_prompt: str,
        memory_manager: MemoryManager | None = None,
    ):
        self.llm = llm
        self._history: list[Message] = [
            Message(role=Role.SYSTEM, content=system_prompt)
        ]
        self.memory = memory_manager

    def add_message(self, message: Message) -> None:
        """追加一条消息到历史。"""
        self._history.append(message)

    def get_history(self) -> list[Message]:
        """获取当前历史（返回同一 list 引用，调用方可只读使用）。"""
        return self._history

    @abstractmethod
    async def run(self, task: str) -> AgentEvent:
        """非流式执行，返回最终事件（通常是 FinalAnswerEvent 或 ErrorEvent）。"""

    @abstractmethod
    async def run_stream(self, task: str) -> AsyncIterator[AgentEvent]:
        """流式执行，返回事件异步迭代器。"""
