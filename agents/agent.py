from __future__ import annotations


from .base import BaseAgent

from core.provider import (
    DeltaEvent,
    StreamEndEvent,
    StreamErrorEvent,
    LLMProvider,
)
from .prompts import (
    DEFAULT_SYSTEM,
    DEFAULT_PREMATURE_STOP_NUDGE,
    DEFAULT_FORCED_FINALIZE_NUDGE,
)


class CortexAgent(BaseAgent):
    """
    ReActAgent（意图澄清）：流式 LLM + MCP 工具 + 结构化 intent 输出。

    Args:
        llm:
        tools: 工具注册表
        system_prompt: 系统提示词
    """

    def __init__(self, llm: LLMProvider, *, system_prompt: str | None = None):
        base = system_prompt.strip() if system_prompt is not None else DEFAULT_SYSTEM
        super().__init__(llm, system_prompt=base)

        self._system_prompt_str = base
