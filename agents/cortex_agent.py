"""ADP 编排入口：Assessor 路由 → Chat（快答）或 Thought（慢思考）。

编排层职责：会话 recall、长期记忆 recall（只读）、ContextAssembler 装配、落库 conversation。
长期记忆写入由离线 ``MemoryBatchConsolidator`` 负责，不在此模块执行。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from core.models import Message, Role

from agents.assessor import AssessResult, Assessor
from agents.chat import Chat, build_chat_system_prompt
from agents.events import AgentEvent, FinalAnswerEvent
from agents.agent_log import clip, cortex_log, memory_log, clear_turn_id, set_turn_id
from memory.memory_context import MemoryContextProvider, MemoryRecallContext

if TYPE_CHECKING:
    from core.provider import LLMProvider
    from tools.registry import ToolRegistry

    from agents.thought import Thought


from memory import create_memory_manager, ContextAssembler
from memory.factory import GraphBackend, VectorBackend

from agents.prompts import ASSESSOR_SYSTEM, THOUGHT_CONTEXT_SYSTEM


async def load_knowledge_base_from_env():
    """按环境变量初始化 RAG 知识库（可选入库）。"""
    import os
    from pathlib import Path

    from retrieval.rag_bootstrap import (
        create_knowledge_base,
        ingest_rag_sources,
        is_rag_enabled,
        parse_rag_doc_paths,
    )

    project_root = Path(__file__).resolve().parent.parent
    rag_docs_raw = os.getenv("CORTEX_RAG_DOCS", "").strip()
    if not is_rag_enabled(rag_docs_raw):
        return None

    kb_dir = os.getenv("CORTEX_KB_DIR", "data/knowledge_db")
    kb = create_knowledge_base(persist_dir=kb_dir)
    doc_paths = parse_rag_doc_paths(rag_docs_raw, project_root=project_root)
    try:
        indexed = await ingest_rag_sources(kb, doc_paths)
        memory_log(
            "cortex rag ready",
            indexed=indexed,
            doc_paths=len(doc_paths),
            kb_dir=kb_dir,
        )
    except Exception as exc:
        memory_log(
            "cortex rag ingest failed",
            error=type(exc).__name__,
            detail=clip(str(exc), 120),
        )
    return kb


class Route(str, Enum):
    """本轮走路径。"""

    CHAT = "chat"
    THOUGHT = "thought"


@dataclass(frozen=True)
class TurnOutcome:
    """上一轮编排结果。"""

    route: Route
    assess: AssessResult
    final_answer: str = ""


class CortexAgent:
    """Agent Cortex 统一入口（编排层）。"""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry | None = None,
        *,
        assessor: Assessor | None = None,
        chat: Chat | None = None,
        thought: Thought | None = None,
        session_id: str = "tester_id",
        history_limit: int = 20,
        router_history_limit: int = 5,
        enable_long_term_memory: bool = True,
        long_term_top_k: int = 5,
        include_graph_memory: bool = False,
        vector_backend: VectorBackend = "qdrant",
        graph_backend: GraphBackend | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.assessor = assessor
        self.chat = chat
        self.thought = thought
        self.session_id = session_id
        self.history_limit = history_limit
        self.router_history_limit = router_history_limit
        self._enable_long_term_memory = enable_long_term_memory
        self._long_term_top_k = long_term_top_k
        self._include_graph_memory = include_graph_memory
        self._last_outcome: TurnOutcome | None = None

        self.namespace = f"mem:{session_id}:default"

        resolved_graph: GraphBackend = (
            graph_backend if graph_backend is not None
            else ("neo4j" if include_graph_memory else "none")
        )
        resolved_vector: VectorBackend = (
            vector_backend if enable_long_term_memory else "none"
        )

        self._memory_manager = create_memory_manager(
            namespace=self.namespace,
            vector_backend=resolved_vector,
            graph_backend=resolved_graph,
        )
        self._memory_context = MemoryContextProvider(
            self._memory_manager,
            hybrid_top_k=long_term_top_k,
            include_associative=include_graph_memory and resolved_graph == "neo4j",
        )
        self._context_assembler = ContextAssembler(max_tokens=5000, min_relevance=0.3)

    def attach_readonly_tools(self, *, knowledge_base=None) -> None:
        """注册只读内置工具：长期记忆检索、文档 RAG（供 Thought 执行阶段调用）。"""
        from tools.builtin import SearchDocumentsTool, SearchMemoryTool
        from tools.registry import ToolRegistry

        if self.tools is None:
            self.tools = ToolRegistry()

        if self._enable_long_term_memory:
            self.tools.register(
                SearchMemoryTool(
                    self._memory_manager,
                    top_k=self._long_term_top_k,
                    include_graph=self._include_graph_memory,
                )
            )

        if knowledge_base is not None:
            self.tools.register(SearchDocumentsTool(knowledge_base))

        memory_log(
            "cortex readonly tools attached",
            search_memory=self._enable_long_term_memory,
            search_documents=knowledge_base is not None,
            total=len(self.tools.list_definitions()),
        )
        cortex_log(
            "readonly tools attached",
            search_memory=self._enable_long_term_memory,
            search_documents=knowledge_base is not None,
            tool_count=len(self.tools.list_definitions()),
        )

    def get_last_outcome(self) -> TurnOutcome | None:
        """返回上一轮编排结果。"""
        return self._last_outcome

    async def _recall_conversation(self) -> list[Message]:
        """读取本会话近期对话（不含本轮尚未落库的 USER）。"""
        conv = await self._memory_manager.recall(
            memory_type="conversation", top_k=self.history_limit
        )
        messages = conv.messages or []
        cortex_log(
            "conversation recall",
            session_id=self.namespace,
            count=len(messages),
            top_k=self.history_limit,
        )
        return messages

    async def _recall_long_term_context(self, task: str) -> MemoryRecallContext:
        """只读：hybrid 召回 episodic + semantic，可选图摘要 → 供 Assembler 消费。"""
        if not self._enable_long_term_memory:
            return MemoryRecallContext()
        ctx = await self._memory_context.recall_for_context(task)
        memory_log(
            "cortex long_term recall",
            task=clip(task, 80),
            hits=len(ctx.memories or []),
            has_graph=bool((ctx.graph_summary or "").strip()),
        )
        return ctx

    def _assemble_agent_messages(
        self,
        route: Route,
        task: str,
        histories: list[Message],
        memory_ctx: MemoryRecallContext,
    ) -> list[Message]:
        """按路由装配 Chat / Thought 可直接消费的 messages。"""
        if route == Route.CHAT:
            return self._assemble_chat_messages(
                task, histories, memory_ctx=memory_ctx
            )
        return self._assemble_thought_messages(
            task, histories, memory_ctx=memory_ctx
        )

    def _router_histories(
        self, task: str, system_prompt: str, conv_messages: list[Message]
    ) -> list[Message]:
        """供 Assessor 使用的短窗口历史。"""

        dialogue = [m for m in conv_messages if m.role in (Role.USER, Role.ASSISTANT)]
        dialogue = dialogue[-self.router_history_limit :]
        return [
            Message(role=Role.SYSTEM, content=system_prompt),
            *dialogue,
            Message(role=Role.USER, content=task),
        ]

    async def _persist_user(self, task: str) -> None:
        """落库本轮 USER。"""
        text = (task or "").strip()
        if not text:
            return
        await self._memory_manager.remember(
            memory_type="conversation",
            message=Message(role=Role.USER, content=text),
        )
        cortex_log("persist user", session_id=self.namespace, content_len=len(text))

    async def _persist_assistant(self, content: str) -> None:
        """落库本轮 ASSISTANT（最终回复）。"""
        text = (content or "").strip()
        if not text:
            return
        await self._memory_manager.remember(
            memory_type="conversation",
            message=Message(role=Role.ASSISTANT, content=text),
        )
        cortex_log(
            "persist assistant",
            session_id=self.namespace,
            content_len=len(text),
        )

    async def _persist_conversation_message(self, message: Message) -> None:
        """供 Thought 落库执行期消息（ASSISTANT+tool_calls / TOOL）。"""
        if message.role not in (Role.ASSISTANT, Role.TOOL):
            return
        await self._memory_manager.remember(
            memory_type="conversation",
            message=message,
        )

    async def _assess(self, task: str, conv_messages: list[Message]) -> AssessResult:
        """静默路由评估。"""
        if self.assessor is None:
            self.assessor = Assessor(self.llm)
        messages = self._router_histories(task, ASSESSOR_SYSTEM, conv_messages)
        return await self.assessor.evaluate(messages, task)

    def _dialogue_from_histories(
        self, histories: list[Message], task: str
    ) -> list[Message]:
        """会话历史：仅 USER/ASSISTANT；若末条已是本轮 USER 则去掉，避免重复。"""
        dialogue = [m for m in histories if m.role in (Role.USER, Role.ASSISTANT)]
        current = (task or "").strip()
        if (
            current
            and dialogue
            and dialogue[-1].role == Role.USER
            and (dialogue[-1].content or "").strip() == current
        ):
            dialogue = dialogue[:-1]
        return dialogue

    def _assemble_chat_messages(
        self,
        task: str,
        histories: list[Message],
        *,
        memory_ctx: MemoryRecallContext | None = None,
    ) -> list[Message]:
        """快答路径：ContextAssembler + Chat system（可选长期记忆）。"""
        ctx = memory_ctx or MemoryRecallContext()
        return self._context_assembler.assemble(
            system_prompt=build_chat_system_prompt(self.tools),
            memories=ctx.memories or None,
            documents=None,
            histories=self._dialogue_from_histories(histories, task),
            current_task=(task or "").strip(),
            graph_summary=ctx.graph_summary,
        )

    def _assemble_thought_messages(
        self,
        task: str,
        histories: list[Message],
        *,
        memory_ctx: MemoryRecallContext | None = None,
    ) -> list[Message]:
        """慢思考路径：会话 + 长期记忆背景（各阶段 SYSTEM 由 Thought 注入）。"""
        ctx = memory_ctx or MemoryRecallContext()
        return self._context_assembler.assemble(
            system_prompt=THOUGHT_CONTEXT_SYSTEM,
            memories=ctx.memories or None,
            documents=None,
            histories=self._dialogue_from_histories(histories, task),
            current_task=(task or "").strip(),
            graph_summary=ctx.graph_summary,
        )

    async def _run_chat(
        self,
        messages: list[Message],
    ) -> AsyncIterator[AgentEvent]:
        """快答路径执行：透传 Chat 流式事件。"""
        if self.chat is None:
            self.chat = Chat(self.llm)
        async for ev in self.chat.run_stream(messages):
            yield ev

    async def _run_thought(
        self,
        messages: list[Message],
    ) -> AsyncIterator[AgentEvent]:
        """慢思考路径执行：透传 Thought 流式事件。"""
        from agents.thought import Thought

        if self.thought is None:
            self.thought = Thought(
                self.llm,
                tools=self.tools,
                persist_message=self._persist_conversation_message,
            )
        async for ev in self.thought.run_stream(messages):
            yield ev

    async def run_stream(self, task: str) -> AsyncIterator[AgentEvent]:
        """单轮编排入口：评估 → 快答 / 慢思考 → 落库。"""
        import uuid

        text = (task or "").strip()
        if not text:
            yield FinalAnswerEvent(content="请输入有效内容。")
            return

        turn_id = uuid.uuid4().hex[:8]
        set_turn_id(turn_id)
        cortex_log(
            "turn start",
            session_id=self.namespace,
            task=clip(text, 80),
            turn_id=turn_id,
        )

        try:
            conv_messages = await self._recall_conversation()
            histories = conv_messages

            assess_result = await self._assess(text, histories)
            route = Route.THOUGHT if assess_result.need_deep_think else Route.CHAT
            cortex_log(
                "route selected",
                route=route.value,
                reason=clip(assess_result.reason, 40),
            )

            await self._persist_user(text)

            memory_ctx = await self._recall_long_term_context(text)
            messages = self._assemble_agent_messages(
                route, text, histories, memory_ctx
            )
            cortex_log(
                "messages assembled",
                route=route.value,
                message_count=len(messages),
                memory_hits=len(memory_ctx.memories or []),
                has_graph=bool((memory_ctx.graph_summary or "").strip()),
            )
            final_answer = ""

            if route == Route.CHAT:
                async for ev in self._run_chat(messages):
                    if isinstance(ev, FinalAnswerEvent) and ev.content:
                        final_answer = ev.content
                    yield ev
            else:
                async for ev in self._run_thought(messages):
                    if isinstance(ev, FinalAnswerEvent) and ev.content:
                        final_answer = ev.content
                    yield ev

            if final_answer:
                await self._persist_assistant(final_answer)

            self._last_outcome = TurnOutcome(
                route=route,
                assess=assess_result,
                final_answer=final_answer,
            )
            cortex_log(
                "turn done",
                route=route.value,
                answer_len=len(final_answer),
                turn_id=turn_id,
            )
        finally:
            clear_turn_id()


async def main():
    from pathlib import Path

    from core.factory import create_llm
    from mcp_adapter import load_mcp_tools
    from tools.registry import ToolRegistry

    from agents.events import (
        ErrorEvent,
        FinalAnswerDeltaEvent,
        FinalAnswerEvent,
        ThoughtDeltaEvent,
        ToolCallEvent,
        ToolResultEvent,
    )

    root = Path(__file__).resolve().parent.parent
    kb = await load_knowledge_base_from_env()
    bindings = await load_mcp_tools(
        command="uv",
        args=["run", "python", "mcp_adapter/server.py"],
        cwd=str(root),
    )
    try:
        tools = ToolRegistry.from_tools(bindings.tools)
        cortex_agent = CortexAgent(
            create_llm(), tools=tools, assessor=Assessor(create_llm())
        )
        cortex_agent.attach_readonly_tools(knowledge_base=kb)
        query = "查询下我当前库存"
        print(f"已加载 {len(cortex_agent.tools.list_definitions())} 个工具\n")
        print(f"--- 用户：{query} ---\n")
        printed_thinking = False
        printed_final = False
        async for ev in cortex_agent.run_stream(query):
            if isinstance(ev, ThoughtDeltaEvent):
                if not printed_thinking:
                    printed_thinking = True
                    print("【思考过程】")
                print(ev.delta, end="", flush=True)
            elif isinstance(ev, ToolCallEvent):
                if not printed_thinking:
                    printed_thinking = True
                    print("【思考过程】")
                print(f"\n[调用工具] {ev.tool_name} {ev.args}", flush=True)
            elif isinstance(ev, ToolResultEvent):
                if not printed_thinking:
                    printed_thinking = True
                    print("【思考过程】")
                status = "错误" if ev.is_error else "结果"
                print(f"\n[工具{status}] {ev.tool_name}: {ev.result}", flush=True)
            elif isinstance(ev, FinalAnswerDeltaEvent):
                if not printed_final:
                    printed_final = True
                    prefix = "\n\n" if printed_thinking else ""
                    print(f"{prefix}【最终回复】")
                print(ev.delta, end="", flush=True)
            elif isinstance(ev, FinalAnswerEvent):
                if ev.content:
                    if not printed_final:
                        printed_final = True
                        prefix = "\n\n" if printed_thinking else ""
                        print(f"{prefix}【最终回复】")
                        print(ev.content, end="", flush=True)
                    print()
            elif isinstance(ev, ErrorEvent):
                print(f"\n[错误] {ev.error}")
        print()
    finally:
        await bindings.client.close()


if __name__ == "__main__":
    import asyncio
    from observability import setup_log

    setup_log()
    asyncio.run(main())
