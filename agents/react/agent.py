from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from core.models import Message, Role, StopReason, TokenUsage
from core.provider import (
    DeltaEvent,
    StreamEndEvent,
    StreamErrorEvent,
    LLMProvider,
)
from agents.core.events import (
    AgentEvent,
    TextDeltaEvent,
    FinalAnswerEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolResultEvent,
    RunStatsEvent,
    IntentOutcomeEvent,
    MemoryConsolidatedEvent,
)
from agents.core.base import Agent
from agents.core.intent import (
    INTENT_OUTPUT_INSTRUCTION,
    INTENT_REFORMAT_NUDGE,
    INTENT_TYPE_HINTS,
    IntentStreamFilter,
    StructuredIntent,
    parse_intent_from_answer,
    resolve_display_text,
)
from tools import ToolRegistry, ToolRunner
from observability import log as _log

if TYPE_CHECKING:
    from memory.context import ContextAssembler
    from memory.memory_context import MemoryContextProvider
    from memory.store.conversation_sqlite_store import ConversationSQLitesStore
    from memory.manager import MemoryManager
    from retrieval.knowledge_base import KnowledgeBase

_DEFAULT_PREMATURE_STOP_NUDGE = (
    "你尚未按意图澄清专家格式结束本轮。"
    "若仍需追问，请输出 user_reply + ```intent```（is_clear=false）；"
    "若意图已清晰，请输出简要 user_reply + ```intent```（is_clear=true），"
    "不要代用户完成长文交付。"
)

_DEFAULT_FORCED_FINALIZE_NUDGE = (
    "请立即结束本轮：不要再调用工具。"
    "只输出简短 user_reply，并附上符合规范的 ```intent``` JSON 块。"
)


# 澄清阶段允许的只读工具（执行型工具留给 PlanExecute）
_READONLY_TOOL_NAMES = frozenset({"search_documents", "search_memory"})

# ReAct agent 日志开关：默认关闭，避免刷屏；需要时设 CORTEX_REACT_LOG=1
_REACT_LOG_ENABLED = "1"


def _react_log(message: str, /, **fields) -> None:
    if not _REACT_LOG_ENABLED:
        return
    _log(message, **fields)


def _clip(text: str | None, n: int = 160) -> str:
    s = (text or "").strip().replace("\n", "\\n")
    if len(s) <= n:
        return s
    return s[:n] + f"…(+{len(s) - n})"


_SYSTEM_INTRO = """你是 **Agent Cortex（灵枢）** 面向用户的智能助手：先弄清需求，再在任务明确后由系统完成起草、检索与多步执行。

## 对用户说话（user_reply）——必须遵守
- 语气自然、专业、可执行，像正式产品助手，**不要**暴露内部架构或岗位名称。
- **禁止**在 user_reply 中出现：意图澄清专家、ReAct、PlanExecute、Reflection、中枢、后续流程/模块、结构化 intent、交给下一阶段 等表述。
- **自我介绍**（如「你是谁」）：可说「我是 Agent Cortex（灵枢），你的智能助手」，简要说明能帮你做什么；**不要**说「我是意图澄清专家」「我只负责澄清、不负责交付」。
- **能力介绍**（如「你能帮我做什么」）：用 2～5 句 + 少量 bullet 列举用户可发起的任务（起草/修改合同、查公司文档与政策、梳理并执行多步骤任务等），语气积极；复杂任务说明你会先确认关键信息再动手，但**不要**强调内部流水线。
- 用户只是闲聊、问候、问产品能力时：intent 用 `general_chat`，`is_clear=true`，user_reply 直接给出完整友好答复。

## 内部职责（仅指导你的判断，勿写入 user_reply）
1. 理解用户真实需求；信息不足时**追问**，不要猜测。
2. 结合对话、[MEMORY]、[DOCUMENTS] 与**只读检索工具**补全背景。
3. 本阶段不写完整合同、不长篇罗列文档细节；执行型工作通过结构化 intent 交给系统执行层。
4. 任务需求已足够清晰时，输出结构化 `intent` JSON（用户看不到该块）。

## 工具（仅辅助理解）
- 仅可使用只读检索类工具（如 search_documents、search_memory）。
- 检索是为了弄清用户所指，不是为了替用户写完整答案。
"""


def _build_default_system(tools: ToolRegistry) -> str:
    """根据已注册工具生成默认 system prompt。"""
    parts = [_SYSTEM_INTRO, INTENT_TYPE_HINTS, INTENT_OUTPUT_INSTRUCTION]
    readonly = [
        d for d in tools.list_definitions() if d["name"] in _READONLY_TOOL_NAMES
    ]
    if readonly:
        parts.extend(["", "## 当前可用只读工具"])
        for d in readonly:
            parts.append(f"- **{d['name']}**：{d.get('description', '').strip()}")
        parts.append("")
        parts.append("禁止调用未列出的工具；禁止执行写入、派发、生成完整交付物。")
    return "\n".join(parts)


def _default_allowed_tools(tools: ToolRegistry) -> set[str]:
    registered = {d["name"] for d in tools.list_definitions()}
    return registered & set(_READONLY_TOOL_NAMES)


class ReActAgent(Agent):
    """
    ReActAgent（意图澄清）：流式 LLM + 可选只读工具 + 结构化 intent 输出。

    输出 ``IntentOutcomeEvent`` + ``FinalAnswerEvent``（含 ``intent`` 字段），
    供后续 PlanExecute 消费。
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        system_prompt: str | None = None,
        max_steps: int = 8,
        allowed_tools: set[str] | None = None,
        tool_max_attempts: int = 2,
        *,
        memory_manager: MemoryManager | None = None,
        conversation_store: ConversationSQLitesStore | None = None,
        session_id: str | None = None,
        context_assembler: ContextAssembler | None = None,
        knowledge_base: KnowledgeBase | None = None,
        history_limit: int = 20,
        prefetch_memory_top_k: int = 5,
        prefetch_docs_top_k: int = 3,
        prefetch_associative: bool = True,
        consolidate_memory: bool = True,
        emit_structured_intent: bool = True,
        accept_stop: Callable[[str, int, int], bool] | None = None,
        premature_stop_nudge: str | None = None,
        forced_finalize_nudge: str | None = None,
        max_premature_stop_retries: int = 3,
    ):
        if system_prompt is not None:
            base = system_prompt.strip()
        else:
            base = _build_default_system(tools)
        super().__init__(llm, system_prompt=base, memory_manager=memory_manager)

        self._system_prompt_str = base
        self.tools = tools
        self.max_steps = max_steps
        if allowed_tools is None:
            allowed_tools = _default_allowed_tools(tools)
        self.allowed_tools = allowed_tools
        self.tool_max_attempts = max(1, tool_max_attempts)
        self._conversation_store = conversation_store
        self._session_id = session_id
        self._context_assembler = context_assembler
        self._knowledge_base: Any = knowledge_base
        self._history_limit = history_limit
        self._prefetch_memory_top_k = prefetch_memory_top_k
        self._prefetch_docs_top_k = prefetch_docs_top_k
        self._prefetch_associative = prefetch_associative
        self._consolidate_memory = consolidate_memory
        self._last_user_task = ""
        self._memory_context: MemoryContextProvider | None = None
        if memory_manager is not None:
            from memory.memory_context import MemoryContextProvider

            self._memory_context = MemoryContextProvider(
                memory_manager,
                hybrid_top_k=prefetch_memory_top_k,
                include_associative=prefetch_associative,
            )
        self._memory_consolidator = None
        if memory_manager is not None and consolidate_memory:
            from memory.consolidator import MemoryConsolidator

            self._memory_consolidator = MemoryConsolidator(memory_manager, llm)
        self._emit_structured_intent = emit_structured_intent
        self._accept_stop = accept_stop
        self._premature_stop_nudge = premature_stop_nudge
        self._forced_finalize_nudge = forced_finalize_nudge
        self._max_premature_stop_retries = max(0, max_premature_stop_retries)
        self.tools_invoked_this_run: list[str] = []
        self.last_intent: StructuredIntent | None = None
        self.tool_runner = ToolRunner(
            tools,
            allowed_tools=allowed_tools,
            tool_max_attempts=self.tool_max_attempts,
        )

    @property
    def _should_persist(self) -> bool:
        return self._conversation_store is not None and self._session_id is not None

    def add_message(self, message: Message) -> None:
        super().add_message(message)
        if not self._should_persist:
            return
        self._conversation_store.add_message(self._session_id, message)  # type: ignore[union-attr]

    async def _prefetch_long_term_memory(
        self, task: str
    ) -> tuple[list[dict[str, Any]], str | None]:
        if self._memory_context is None:
            return [], None
        ctx = await self._memory_context.recall_for_context(task)
        return ctx.memories, ctx.graph_summary

    async def _prefetch_documents(self, task: str) -> list[dict[str, Any]] | None:
        if self._knowledge_base is None:
            return None
        hits = await self._knowledge_base.search(
            task,
            top_k=self._prefetch_docs_top_k,
            optimize="none",
        )
        return hits or None

    def _load_conversation_histories(self) -> list[Message] | None:
        if not self._should_persist:
            return None
        histories = self._conversation_store.get_recent(  # type: ignore[union-attr]
            self._session_id,
            self._history_limit,
        )
        return histories or None

    async def _bootstrap_context(self, task: str) -> None:
        """为当前用户任务准备 history：GSSC 装配 + 预取记忆/RAG + 会话历史。

        无 ``context_assembler`` 时：重置为 [SYSTEM] 并追加本轮 USER（避免多轮 run 堆叠旧 history）。
        """
        task = (task or "").strip()
        if not task:
            raise ValueError("task must not be empty")

        self._last_user_task = task
        _react_log(
            "react bootstrap start",
            task=_clip(task, 120),
            has_assembler=bool(self._context_assembler),
            has_memory=bool(self.memory),
            has_kb=bool(self._knowledge_base),
            persist=bool(self._should_persist),
            session_id=self._session_id,
        )

        if self._context_assembler is None:
            self._history = [
                Message(role=Role.SYSTEM, content=self._system_prompt_str),
                Message(role=Role.USER, content=task),
            ]
            if self._should_persist:
                self._conversation_store.add_message(  # type: ignore[union-attr]
                    self._session_id,
                    Message(role=Role.USER, content=task),
                )
            _react_log(
                "react bootstrap done (no assembler)", history=len(self._history)
            )
            return

        memory_items, graph_summary = await self._prefetch_long_term_memory(task)
        documents = await self._prefetch_documents(task)
        histories = self._load_conversation_histories()
        _react_log(
            "react bootstrap prefetched",
            memories=len(memory_items or []),
            graph_summary=bool((graph_summary or "").strip()),
            documents=len(documents or []) if documents is not None else None,
            histories=len(histories or []) if histories is not None else None,
        )

        self._history = self._context_assembler.assemble(
            system_prompt=self._system_prompt_str,
            memories=memory_items or None,
            documents=documents,
            histories=histories,
            current_task=task,
            graph_summary=graph_summary,
        )
        _react_log("react bootstrap done", history=len(self._history))

        if self._should_persist:
            self._conversation_store.add_message(  # type: ignore[union-attr]
                self._session_id,
                Message(role=Role.USER, content=task),
            )

    async def _final_summarize(self) -> str:
        """截断/超步数时：非流式总结（不传 tools），须带 intent 块。"""
        self.add_message(
            Message(
                role=Role.SYSTEM,
                content="请给出简短 user_reply，并附上 ```intent``` JSON（不要再调用工具）。",
            )
        )
        out = await self.llm.generate(
            messages=self.get_history(),
            tools=None,
        )
        return (out.content or "").strip()

    async def _resolve_intent_output(
        self, answer: str
    ) -> tuple[str, StructuredIntent | None]:
        """解析展示文本与结构化意图；必要时额外请求一次补全 intent 块。"""
        if not self._emit_structured_intent:
            return (answer or "").strip(), None

        display, intent = parse_intent_from_answer(answer)
        if intent is not None:
            self.last_intent = intent
            _react_log(
                "react intent parsed",
                ok=True,
                intent=intent.intent,
                is_clear=intent.is_clear,
            )
            return resolve_display_text(display, intent, raw_fallback=answer), intent

        _react_log(
            "react intent parse failed; reformatting",
            ok=False,
            answer_len=len(answer or ""),
        )
        extra = await self.llm.generate(
            messages=self.get_history()
            + [
                Message(role=Role.ASSISTANT, content=answer),
                Message(role=Role.SYSTEM, content=INTENT_REFORMAT_NUDGE),
            ],
            tools=None,
        )
        reformatted = (extra.content or "").strip()
        display2, intent2 = parse_intent_from_answer(reformatted)
        if intent2 is not None:
            self.last_intent = intent2
            _react_log(
                "react intent parsed (reformatted)",
                ok=True,
                intent=intent2.intent,
                is_clear=intent2.is_clear,
            )
            return (
                resolve_display_text(display2, intent2, raw_fallback=reformatted),
                intent2,
            )

        _react_log(
            "react intent parse failed (reformatted); fallback",
            ok=False,
            reformatted_len=len(reformatted),
        )
        fallback = StructuredIntent(
            is_clear=False,
            intent="unknown",
            summary=(answer or "")[:300],
            user_reply=resolve_display_text("", None, raw_fallback=answer),
            missing=["structured_intent_parse_failed"],
        )
        self.last_intent = fallback
        return fallback.user_reply, fallback

    async def _finish_turn(
        self,
        raw_answer: str,
        usage: Optional[TokenUsage],
        *,
        steps: int,
        tool_calls_count: int,
        tool_errors_count: int,
        start: float,
    ) -> AsyncIterator[AgentEvent]:
        """结束一轮：解析 intent → 统计 → IntentOutcome → FinalAnswer。"""
        _react_log(
            "react finish_turn",
            steps=steps,
            tool_calls=tool_calls_count,
            tool_errors=tool_errors_count,
            answer_len=len(raw_answer or ""),
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )
        if raw_answer:
            self.add_message(Message(role=Role.ASSISTANT, content=raw_answer))

        parsed_display, intent = await self._resolve_intent_output(raw_answer)
        display = resolve_display_text(parsed_display, intent, raw_fallback=raw_answer)
        if intent is not None and intent.user_reply != display:
            intent.user_reply = display

        yield RunStatsEvent(
            steps=steps,
            tool_calls=tool_calls_count,
            tool_errors=tool_errors_count,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )
        if intent is not None:
            yield IntentOutcomeEvent(
                intent=intent,
                is_clear=intent.is_clear,
            )
        yield FinalAnswerEvent(content=display, usage=usage, intent=intent)

        if self._memory_consolidator is not None and self._last_user_task:
            from memory.consolidator import MemoryConsolidationResult

            consolidation = MemoryConsolidationResult(skipped=True)
            try:
                consolidation = await self._memory_consolidator.consolidate(
                    user_message=self._last_user_task,
                    assistant_message=display,
                    session_id=self._session_id,
                )
            except Exception as exc:
                consolidation = MemoryConsolidationResult(skipped=True, error=str(exc))
            _react_log(
                "react memory consolidated",
                skipped=consolidation.skipped,
                episodic=consolidation.episodic_written,
                semantic=consolidation.semantic_written,
                relations=consolidation.relations_written,
                links=consolidation.links_written,
                error=consolidation.error,
            )
            yield MemoryConsolidatedEvent(
                episodic=consolidation.episodic_written,
                semantic=consolidation.semantic_written,
                relations=consolidation.relations_written,
                links=consolidation.links_written,
                skipped=consolidation.skipped,
                error=consolidation.error,
            )

    async def run(self, task: str) -> AgentEvent:
        last_final: FinalAnswerEvent | None = None
        async for ev in self.run_stream(task):
            if isinstance(ev, FinalAnswerEvent):
                last_final = ev
            if isinstance(ev, ErrorEvent):
                return ev
        return last_final or ErrorEvent(error="No final answer produced")

    def get_last_intent(self) -> StructuredIntent | None:
        """上一轮 run 解析出的结构化意图（供 PlanExecute 读取）。"""
        return self.last_intent

    async def run_stream(self, task: str) -> AsyncIterator[AgentEvent]:
        start = time.monotonic()
        steps = 0
        tool_calls_count = 0
        tool_errors_count = 0
        self.tools_invoked_this_run = []

        _react_log(
            "react run_stream start",
            task=_clip(task, 120),
            max_steps=self.max_steps,
            allowed_tools=(
                ",".join(sorted(self.allowed_tools)) if self.allowed_tools else ""
            ),
            emit_structured_intent=self._emit_structured_intent,
        )
        await self._bootstrap_context(task)

        premature_stop_retries = 0

        for _ in range(self.max_steps):
            steps += 1
            full_text = ""
            final_usage: Optional[TokenUsage] = None
            final_stop: StopReason | None = None
            tool_calls = []

            stream_filter = IntentStreamFilter(enabled=self._emit_structured_intent)

            async for ev in self.llm.generate_stream(
                messages=self.get_history(),
                tools=self.tools.list_definitions(),
            ):
                if isinstance(ev, DeltaEvent):
                    full_text += ev.delta
                    visible = stream_filter.push(ev.delta)
                    if visible:
                        yield TextDeltaEvent(delta=visible)

                elif isinstance(ev, StreamEndEvent):
                    out = ev.output
                    final_usage = out.usage
                    final_stop = out.stop_reason
                    tool_calls = out.tool_calls
                    break

                elif isinstance(ev, StreamErrorEvent):
                    _react_log(
                        "react llm stream error",
                        step=steps,
                        error=str(ev.error),
                    )
                    yield ErrorEvent(error=str(ev.error))
                    return

            if final_stop is None:
                _react_log("react error: stream ended without end event", step=steps)
                yield ErrorEvent(error="LLM stream ended without StreamEndEvent")
                return

            if not stream_filter.closed:
                tail = stream_filter.flush()
                if tail:
                    yield TextDeltaEvent(delta=tail)

            _react_log(
                "react step done",
                step=steps,
                stop_reason=str(final_stop),
                content_len=len(full_text),
                tool_calls=len(tool_calls or []),
                tool_calls_total=tool_calls_count,
            )

            if final_stop == StopReason.STOP:
                answer = full_text.strip()
                reject_stop = (
                    self._accept_stop is not None
                    and bool(answer)
                    and not self._accept_stop(answer, tool_calls_count, steps)
                )
                if (
                    reject_stop
                    and premature_stop_retries < self._max_premature_stop_retries
                ):
                    premature_stop_retries += 1
                    _react_log(
                        "react premature_stop retry",
                        step=steps,
                        retries=premature_stop_retries,
                        max_retries=self._max_premature_stop_retries,
                    )
                    self.add_message(Message(role=Role.ASSISTANT, content=answer))
                    nudge = self._premature_stop_nudge or _DEFAULT_PREMATURE_STOP_NUDGE
                    self.add_message(Message(role=Role.SYSTEM, content=nudge))
                    continue

                if reject_stop and self._accept_stop is not None:
                    _react_log(
                        "react forced_finalize",
                        step=steps,
                        tool_calls=tool_calls_count,
                    )
                    if answer:
                        self.add_message(Message(role=Role.ASSISTANT, content=answer))
                    finalize = (
                        self._forced_finalize_nudge or _DEFAULT_FORCED_FINALIZE_NUDGE
                    )
                    self.add_message(Message(role=Role.SYSTEM, content=finalize))
                    answer = await self._final_summarize()
                    async for ev in self._finish_turn(
                        answer,
                        None,
                        steps=steps,
                        tool_calls_count=tool_calls_count,
                        tool_errors_count=tool_errors_count,
                        start=start,
                    ):
                        yield ev
                    return

                async for ev in self._finish_turn(
                    answer,
                    final_usage,
                    steps=steps,
                    tool_calls_count=tool_calls_count,
                    tool_errors_count=tool_errors_count,
                    start=start,
                ):
                    yield ev
                return

            if final_stop == StopReason.TOOL_CALLS and tool_calls:
                self.add_message(
                    Message(
                        role=Role.ASSISTANT,
                        content=full_text.strip(),
                        tool_calls=tool_calls,
                    )
                )

                for tc in tool_calls:
                    tool_calls_count += 1
                    self.tools_invoked_this_run.append(tc.name)
                    _react_log(
                        "react tool_call",
                        step=steps,
                        tool=tc.name,
                        call_id=tc.id,
                        arg_keys=",".join(sorted(tc.arguments.keys())),
                    )
                    yield ToolCallEvent(
                        call_id=tc.id, tool_name=tc.name, args=tc.arguments
                    )

                tool_start = time.monotonic()
                results = await asyncio.gather(
                    *[self.tool_runner.run(tc.name, tc.arguments) for tc in tool_calls],
                    return_exceptions=False,
                )
                tool_elapsed_ms = int((time.monotonic() - tool_start) * 1000)

                for tc, (result, is_error) in zip(tool_calls, results):
                    if is_error:
                        tool_errors_count += 1
                    _react_log(
                        "react tool_result",
                        step=steps,
                        tool=tc.name,
                        call_id=tc.id,
                        is_error=is_error,
                        elapsed_ms=tool_elapsed_ms,
                        result_len=len(result or ""),
                    )
                    yield ToolResultEvent(
                        call_id=tc.id,
                        tool_name=tc.name,
                        result=result,
                        is_error=is_error,
                    )
                    self.add_message(
                        Message(
                            role=Role.TOOL,
                            content=result,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )

                continue

            if final_stop == StopReason.LENGTH:
                _react_log("react length_truncated; summarize", step=steps)
                self.add_message(
                    Message(
                        role=Role.SYSTEM,
                        content="刚才的输出可能被截断。请给出简短 user_reply + ```intent```（不要再调用工具）。",
                    )
                )
                answer = await self._final_summarize()
                async for ev in self._finish_turn(
                    answer,
                    None,
                    steps=steps,
                    tool_calls_count=tool_calls_count,
                    tool_errors_count=tool_errors_count,
                    start=start,
                ):
                    yield ev
                return

            _react_log(
                "react unexpected stop_reason", step=steps, stop_reason=str(final_stop)
            )
            yield ErrorEvent(error=f"Unexpected stop_reason: {final_stop}")
            return

        self.add_message(
            Message(
                role=Role.SYSTEM,
                content="已达到最大步数。请给出简短 user_reply + ```intent```（不要再调用工具）。",
            )
        )
        _react_log(
            "react max_steps reached; summarize", steps=steps, max_steps=self.max_steps
        )
        answer = await self._final_summarize()
        async for ev in self._finish_turn(
            answer,
            None,
            steps=steps,
            tool_calls_count=tool_calls_count,
            tool_errors_count=tool_errors_count,
            start=start,
        ):
            yield ev
