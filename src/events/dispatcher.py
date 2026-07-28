"""事件调度：幂等 → 会话串行 → EventAgentRunner（Agent 一轮）。

不依赖 ``HubloomRuntime`` 类型；通过 ``EventAgentRunner`` / ``bind_agent`` 注入。
"""

from __future__ import annotations

import asyncio

from loguru import logger

from context import clear_request_context
from core.models import Message, Role
from events.agent_runner import EventAgentRunner
from events.callback import post_result_callback
from events.catalog import EventCatalog, render_event_trigger
from events.idempotency import (
    EventDispatchResult,
    IdempotencyStore,
)
from events.models import HubloomEvent
from events.session_gate import SessionGate


class EventDispatcher:
    """把规范化事件交给 Agent；同 event_id 幂等；同 session_id 串行。"""

    def __init__(
        self,
        *,
        catalog: EventCatalog,
        idempotency: IdempotencyStore,
        session_gate: SessionGate,
        result_callback_url: str | None = None,
        default_bearer_token: str | None = None,
        present_mode: str = "markdown",
    ) -> None:
        self.catalog = catalog
        self.idempotency = idempotency
        self.session_gate = session_gate
        self.result_callback_url = (result_callback_url or "").strip() or None
        self.default_bearer_token = (default_bearer_token or "").strip() or None
        self.present_mode = present_mode
        self._agent: EventAgentRunner | None = None
        # 同 event_id 并发：进程内等待首个完成（跨实例靠 Redis 幂等键）
        self._claim_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Event] = {}

    def bind_agent(self, agent: EventAgentRunner) -> None:
        """注入跑一轮 Agent 的实现（推荐）。"""
        self._agent = agent

    def bind_runtime(self, runtime: object) -> None:
        """兼容旧调用：把带 ``run_stream`` 的宿主包成 AgentRunner。

        不 import runtime 模块；新代码请用 ``bind_agent``。
        """
        from events.agent_runner import StreamHostAgentRunner

        self.bind_agent(StreamHostAgentRunner(runtime))

    def _validate_payload(self, event: HubloomEvent) -> None:
        entry = self.catalog.get(event.type)
        missing = [
            f for f in entry.payload_fields if event.payload.get(f) in (None, "")
        ]
        if missing:
            raise ValueError(
                f"事件 {event.type!r} 缺少 payload 字段: {', '.join(missing)}"
            )

    async def _wait_inflight_or_claim(self, event_id: str) -> EventDispatchResult | None:
        """返回已有/等待后的 duplicate 结果；``None`` 表示本协程应执行。"""
        while True:
            async with self._claim_lock:
                existing = await self.idempotency.get(event_id)
                if existing is not None:
                    return EventDispatchResult(
                        event_id=existing.event_id,
                        session_id=existing.session_id,
                        type=existing.type,
                        ok=existing.ok,
                        duplicate=True,
                        summary=existing.summary,
                        error=existing.error,
                        turn_count=existing.turn_count,
                    )
                if event_id not in self._inflight:
                    self._inflight[event_id] = asyncio.Event()
                    return None
                waiter = self._inflight[event_id]
            await waiter.wait()

    async def _finish_inflight(self, event_id: str) -> None:
        async with self._claim_lock:
            ev = self._inflight.pop(event_id, None)
            if ev is not None:
                ev.set()

    async def _execute(self, event: HubloomEvent) -> EventDispatchResult:
        assert self._agent is not None
        entry = self.catalog.get(event.type)
        trigger_text = render_event_trigger(event, entry)
        bearer = event.bearer_token or self.default_bearer_token
        error: str | None = None
        ok = False
        summary = ""
        turn_count = 0

        try:
            final = await self._agent.run_event_turn(
                Message(role=Role.USER, content=trigger_text),
                session_id=event.session_id,
                present_mode=self.present_mode,
                bearer_token=bearer,
                trigger_source="event",
            )
            if not final.ok:
                error = final.error or "运行失败"
            else:
                ok = True
                summary = (final.content or "").strip()
                turn_count = int(final.think_rounds or 0)
        except Exception as exc:
            error = str(exc)
            logger.exception(
                "event dispatch failed | event_id={} | type={}",
                event.event_id,
                event.type,
            )
        finally:
            clear_request_context()

        return EventDispatchResult(
            event_id=event.event_id,
            session_id=event.session_id,
            type=event.type,
            ok=ok,
            duplicate=False,
            summary=summary,
            error=error,
            turn_count=turn_count,
        )

    async def dispatch(self, event: HubloomEvent) -> EventDispatchResult:
        if self._agent is None:
            raise RuntimeError("EventDispatcher 尚未绑定 Agent（bind_agent）")

        try:
            self.catalog.get(event.type)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc

        self._validate_payload(event)

        # 1) 幂等：已完成则直接返回
        existing = await self.idempotency.get(event.event_id)
        if existing is not None:
            return EventDispatchResult(
                event_id=existing.event_id,
                session_id=existing.session_id,
                type=existing.type,
                ok=existing.ok,
                duplicate=True,
                summary=existing.summary,
                error=existing.error,
                turn_count=existing.turn_count,
            )

        # 2) 同 event_id 并发占坑（进程内）
        claimed = await self._wait_inflight_or_claim(event.event_id)
        if claimed is not None:
            return claimed

        result: EventDispatchResult | None = None
        try:
            # 再查一次（等待期间可能已被 put）
            existing = await self.idempotency.get(event.event_id)
            if existing is not None:
                result = EventDispatchResult(
                    event_id=existing.event_id,
                    session_id=existing.session_id,
                    type=existing.type,
                    ok=existing.ok,
                    duplicate=True,
                    summary=existing.summary,
                    error=existing.error,
                    turn_count=existing.turn_count,
                )
            else:
                # 3) 同 session 串行跑 Agent
                async def _run() -> EventDispatchResult:
                    return await self._execute(event)

                result = await self.session_gate.run(event.session_id, _run)
                if not result.duplicate:
                    await self.idempotency.put(result)
        finally:
            await self._finish_inflight(event.event_id)

        assert result is not None
        if self.result_callback_url and not result.duplicate:
            await post_result_callback(
                self.result_callback_url,
                result,
                extra={"payload": dict(event.payload)},
            )
        return result

    def known_types(self) -> list[str]:
        return self.catalog.types()
