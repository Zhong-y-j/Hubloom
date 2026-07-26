"""事件调度：模板渲染 → HubloomRuntime.run_stream（trigger_source=event）。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from agent.run import RunResult
from context import clear_request_context
from core.models import Message, Role
from events.callback import post_result_callback
from events.catalog import EventCatalog, render_event_trigger
from events.idempotency import EventDispatchResult, IdempotencyStore
from events.models import HubloomEvent

if TYPE_CHECKING:
    from runtime import HubloomRuntime


class EventDispatcher:
    """把规范化事件交给 Runtime；同 event_id 幂等。"""

    def __init__(
        self,
        *,
        catalog: EventCatalog,
        idempotency: IdempotencyStore | None = None,
        result_callback_url: str | None = None,
        default_bearer_token: str | None = None,
        present_mode: str = "markdown",
    ) -> None:
        self.catalog = catalog
        self.idempotency = idempotency or IdempotencyStore()
        self.result_callback_url = (result_callback_url or "").strip() or None
        self.default_bearer_token = (default_bearer_token or "").strip() or None
        self.present_mode = present_mode  # type: ignore[assignment]
        self._runtime: HubloomRuntime | None = None
        self._claim_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Event] = {}

    def bind_runtime(self, runtime: HubloomRuntime) -> None:
        self._runtime = runtime

    def _validate_payload(self, event: HubloomEvent) -> None:
        entry = self.catalog.get(event.type)
        missing = [
            f for f in entry.payload_fields if event.payload.get(f) in (None, "")
        ]
        if missing:
            raise ValueError(
                f"事件 {event.type!r} 缺少 payload 字段: {', '.join(missing)}"
            )

    async def _claim_or_wait(
        self, event_id: str
    ) -> EventDispatchResult | None:
        """返回已有结果；``None`` 表示本协程应执行；否则等待并返回 duplicate。"""
        while True:
            async with self._claim_lock:
                existing = self.idempotency.get(event_id)
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

    async def _finish_claim(
        self, event_id: str, result: EventDispatchResult
    ) -> None:
        async with self._claim_lock:
            self.idempotency.put(result)
            ev = self._inflight.pop(event_id, None)
            if ev is not None:
                ev.set()

    async def dispatch(self, event: HubloomEvent) -> EventDispatchResult:
        if self._runtime is None:
            raise RuntimeError("EventDispatcher 尚未绑定 HubloomRuntime")

        try:
            entry = self.catalog.get(event.type)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc

        self._validate_payload(event)

        claimed = await self._claim_or_wait(event.event_id)
        if claimed is not None:
            return claimed

        trigger_text = render_event_trigger(event, entry)
        bearer = event.bearer_token or self.default_bearer_token
        final: RunResult | None = None
        error: str | None = None
        ok = False
        summary = ""
        turn_count = 0

        try:
            async for item in self._runtime.run_stream(
                Message(role=Role.USER, content=trigger_text),
                session_id=event.session_id,
                present_mode=self.present_mode,  # type: ignore[arg-type]
                bearer_token=bearer,
                trigger_source="event",
            ):
                if isinstance(item, RunResult):
                    final = item
            if final is None:
                error = "未收到编排结果"
            elif not final.ok:
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

        result = EventDispatchResult(
            event_id=event.event_id,
            session_id=event.session_id,
            type=event.type,
            ok=ok,
            duplicate=False,
            summary=summary,
            error=error,
            turn_count=turn_count,
        )
        await self._finish_claim(event.event_id, result)

        if self.result_callback_url:
            await post_result_callback(
                self.result_callback_url,
                result,
                extra={"payload": dict(event.payload)},
            )
        return result

    def known_types(self) -> list[str]:
        return self.catalog.types()
