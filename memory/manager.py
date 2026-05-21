from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TypeAlias

from core.models import Message

from .handlers.associative_handler import AssociativeHandler
from .handlers.base import MemoryHandler
from .handlers.conversation_handler import ConversationHandler
from .models import AssociativeRecallResult, EpisodicItem, SemanticItem
from .utils import now_local_str
from .types import (
    LONG_TERM_MEMORY_TYPES,
    LongTermMemoryType,
    MemorySource,
    MemoryType,
    RecallMode,
)

MemoryItem: TypeAlias = EpisodicItem | SemanticItem


@dataclass
class RecallResult:
    """统一 ``recall`` 返回：按记忆类型填充对应字段。"""

    memory_type: MemoryType | None
    messages: list[Message] | None = None
    items: list[MemoryItem] | None = None
    graph: AssociativeRecallResult | None = None


class MemoryManager:
    """记忆系统统一入口：通过 ``memory_type`` 分派到各 Handler。

    统一接口：
        - remember: 存储（conversation 传 ``message``，长期记忆传 ``content``）
        - recall: 获取（conversation 返回 ``messages``，长期记忆返回 ``items``）
        - forget / clear_all / run_maintenance
    """

    def __init__(
        self,
        *,
        handlers: dict[str, MemoryHandler],
    ):
        self.handlers = handlers

    def _handler(self, memory_type: MemoryType) -> MemoryHandler:
        handler = self.handlers.get(memory_type)
        if handler is None:
            raise ValueError(
                f"未知的记忆类型: {memory_type}，可用: {list(self.handlers.keys())}"
            )
        return handler

    def _conversation_handler(self) -> ConversationHandler:
        handler = self.handlers.get("conversation")
        if not isinstance(handler, ConversationHandler):
            raise ValueError("未注册 conversation Handler 或类型不匹配")
        return handler

    def _associative_handler(self) -> AssociativeHandler:
        handler = self.handlers.get("associative")
        if not isinstance(handler, AssociativeHandler):
            raise ValueError("未注册 associative Handler 或类型不匹配")
        return handler

    # ───── 统一入口：存储 ─────
    async def remember(
        self,
        *,
        memory_type: MemoryType,
        content: str | None = None,
        message: Message | None = None,
        source: MemorySource = "memory",
        metadata: Optional[dict] = None,
        token_count: int | None = None,
        turn_index: int | None = None,
    ) -> str:
        """统一存储入口。

        - ``conversation``: 必须传 ``message``（完整 Message，含 role/tool_calls）
        - ``episodic`` / ``semantic``: 必须传 ``content``
        - ``associative``: 传 ``content`` 和/或 ``metadata``（``from_name``+``to_name`` 建关系等，见 AssociativeHandler）
        - 长期记忆可在 ``metadata`` 中传 ``ref_session_id``、``importance``（0–100）
        """
        if memory_type == "conversation":
            if message is None:
                raise ValueError("conversation 存储须传 message=Message(...)")
            return await self._conversation_handler().append(
                message,
                source=source,
                metadata=metadata,
                token_count=token_count,
                turn_index=turn_index,
            )

        if memory_type == "associative":
            meta = metadata or {}
            has_triple = meta.get("from_name") and meta.get("to_name")
            has_link = (
                meta.get("entity_id")
                and meta.get("memory_type")
                and meta.get("memory_id")
            )
            if not content and not has_triple and not has_link:
                raise ValueError(
                    "associative 存储须传 content=和/或 metadata（from_name+to_name 或 entity_id+memory_*）"
                )
            return await self._associative_handler().remember(
                content=content or "",
                source=source,
                metadata=metadata,
            )

        if not content:
            raise ValueError(f"{memory_type} 存储须传 content=...")
        handler = self._handler(memory_type)
        return await handler.remember(
            content=content, source=source, metadata=metadata
        )

    # ───── 统一入口：检索 ─────
    async def recall(
        self,
        *,
        query: str = "",
        memory_type: MemoryType | None = None,
        memory_types: list[LongTermMemoryType] | None = None,
        top_k: int = 3,
        filters: Optional[dict] = None,
        mode: RecallMode = "hybrid",
    ) -> RecallResult:
        """统一检索入口。

        - ``memory_type="conversation"``: 忽略 query，按时间取最近 ``top_k`` 条 Message
        - ``memory_type="episodic"|"semantic"``: 单路检索
        - ``memory_type="associative"``: 图邻域检索，结果在 ``graph`` 字段
        - ``memory_type`` 未传: 按 ``mode`` 在 episodic/semantic 间检索（hybrid=两路合并，不含 associative）
        """
        if memory_type == "conversation":
            messages = await self._conversation_handler().recall(
                query=query, top_k=top_k, filters=filters
            )
            return RecallResult(memory_type="conversation", messages=messages)

        if memory_type in ("episodic", "semantic"):
            handler = self._handler(memory_type)
            inner_mode: RecallMode = (
                "keyword" if memory_type == "episodic" else "semantic"
            )
            items = await handler.recall(
                query=query,
                top_k=top_k,
                filters=filters,
                mode=inner_mode,
            )
            return RecallResult(memory_type=memory_type, items=list(items))

        if memory_type == "associative":
            graph = await self._associative_handler().recall_graph(
                query=query,
                top_k=top_k,
                filters=filters,
            )
            return RecallResult(memory_type="associative", graph=graph)

        # 长期记忆多路召回（默认不含 conversation / associative）
        types: list[LongTermMemoryType]
        if memory_types is not None:
            types = memory_types
        elif mode == "keyword":
            types = ["episodic"]
        elif mode == "semantic":
            types = ["semantic"]
        else:
            types = list(LONG_TERM_MEMORY_TYPES)

        per_handler_k = (
            top_k if mode != "hybrid" else max(top_k, min(top_k * 2, 20))
        )
        results: list[MemoryItem] = []
        for mt in types:
            handler = self.handlers.get(mt)
            if handler is None:
                continue
            inner_mode = "keyword" if mt == "episodic" else "semantic"
            batch = await handler.recall(
                query=query,
                top_k=per_handler_k,
                filters=filters,
                mode=inner_mode,
            )
            results.extend(batch)

        items = self._deduplicate(results, top_k=top_k)
        return RecallResult(memory_type=None, items=items)

    # ───── 统一入口：删除 / 清空 ─────
    async def forget(
        self, item_id: str, *, memory_type: MemoryType = "episodic"
    ) -> bool:
        """删除单条长期记忆；conversation 不支持单条删除。"""
        if memory_type == "conversation":
            raise ValueError("conversation 不支持 forget，请用 clear_all(memory_type='conversation')")
        handler = self.handlers.get(memory_type)
        return await handler.forget(item_id) if handler else False

    async def clear_all(self, *, memory_type: MemoryType | None = None) -> int:
        """清空记忆。不传 ``memory_type`` 时清空所有已注册类型（含 conversation）。"""
        if memory_type is not None:
            handler = self.handlers.get(memory_type)
            return await handler.clear_all() if handler else 0

        total = 0
        for h in self.handlers.values():
            total += await h.clear_all()
        return total

    async def run_maintenance(self, current_time_str: str | None = None) -> int:
        """仅对 episodic / semantic 执行 TTL/容量维护。"""
        ts = current_time_str if current_time_str is not None else now_local_str()
        total = 0
        for mt in LONG_TERM_MEMORY_TYPES:
            handler = self.handlers.get(mt)
            if handler is not None:
                total += await handler.run_maintenance(ts)
        return total

    def _deduplicate(self, items: list[MemoryItem], *, top_k: int) -> list[MemoryItem]:
        merged: list[MemoryItem] = []
        seen_ids: set[str] = set()
        seen_contents: set[str] = set()
        for item in items:
            if item.id and item.id in seen_ids:
                continue
            content = (item.content or "").strip()
            if content and content in seen_contents:
                continue
            if item.id:
                seen_ids.add(item.id)
            if content:
                seen_contents.add(content)
            merged.append(item)
            if len(merged) >= top_k:
                break
        return merged
