from __future__ import annotations

from typing import Literal, TypeAlias

# 记忆类型
MemoryType: TypeAlias = Literal["episodic", "semantic", "conversation"]

# 可检索的长期记忆（不含 conversation）
LongTermMemoryType: TypeAlias = Literal["episodic", "semantic"]

LONG_TERM_MEMORY_TYPES: tuple[LongTermMemoryType, ...] = ("episodic", "semantic")

# 检索模式（仅 episodic / semantic）
RecallMode: TypeAlias = Literal["keyword", "semantic", "hybrid"]

# 记忆来源
MemorySource: TypeAlias = Literal["memory", "document", "knowledge"]
