from __future__ import annotations

import asyncio
from typing import Optional

from core.models import Message, Role
from memory.handlers.base import MemoryHandler
from memory.store.conversation_sqlite_store import ConversationSQLitesStore


class ConversationHandler(MemoryHandler):
    """对话记忆专员：负责当前会话 Message 的追加与按条数召回。

    与 Episodic/Semantic 的区别：
    - 隔离键为 ``session_id``（一次对话线程），不是 ``namespace``。
    - 存完整 ``Message``（含 role、tool_calls），不做向量/关键词检索。
    - 推荐用 ``append(message=...)``；``remember`` 仅作统一接口的简化入口（默认 user 角色）。
    """

    def __init__(
        self,
        *,
        store: ConversationSQLitesStore,
        session_id: str,
    ):
        self.store = store
        self.session_id = session_id

    async def append(
        self,
        message: Message,
        *,
        source: str = "memory",
        metadata: Optional[dict] = None,
        token_count: int | None = None,
        turn_index: int | None = None,
    ) -> str:
        """追加一条对话消息（推荐入口）。"""
        return await asyncio.to_thread(
            self.store.add_message,
            self.session_id,
            message,
            source=source,
            metadata=metadata,
            token_count=token_count,
            turn_index=turn_index,
        )

    async def remember(
        self,
        *,
        content: str,
        source: str = "memory",
        metadata: Optional[dict] = None,
    ) -> str:
        # source/metadata 对话表未单独存列；metadata 可编码进 content 或后续扩展列
        _ = source, metadata
        return await self.append(Message(role=Role.USER, content=content))

    async def recall(
        self,
        *,
        query: str,
        top_k: int = 20,
        filters: Optional[dict] = None,
        mode: str = "recent",
    ) -> list[Message]:
        # 对话记忆按时间取最近 N 条；query/mode 预留给后续摘要检索
        _ = query, filters, mode
        limit = top_k if top_k > 0 else 20
        return await asyncio.to_thread(
            self.store.get_recent, self.session_id, limit
        )

    async def get_all(self) -> list[Message]:
        """获取本会话完整历史（正序）。"""
        return await asyncio.to_thread(self.store.get_all, self.session_id)

    async def forget(self, item_id: str) -> bool:
        # 对话层不做单条删除；请用 clear_all 清空本会话
        _ = item_id
        return False

    async def clear_all(self) -> int:
        """清空当前 session 的全部对话记录。"""
        return await asyncio.to_thread(self.store.clear_session, self.session_id)

    async def run_maintenance(self, current_time_str: str) -> int:
        # 对话裁剪由 ContextAssembler 在组装时控制条数，不做存储层淘汰
        _ = current_time_str
        return 0

    async def count(self) -> int:
        return await asyncio.to_thread(self.store.count, self.session_id)
