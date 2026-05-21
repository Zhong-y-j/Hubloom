from __future__ import annotations

from typing import Literal, TypeAlias

# 记忆类型（当前仅两种；未来可扩展）
MemoryType: TypeAlias = Literal["episodic", "semantic", "conversation"]

# 检索模式
RecallMode: TypeAlias = Literal["keyword", "semantic", "hybrid"]

# 记忆来源
MemorySource: TypeAlias = Literal["memory", "document", "knowledge"]
