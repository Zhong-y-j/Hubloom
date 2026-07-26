"""可选：事件跑完后回调业务系统。"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from events.idempotency import EventDispatchResult


async def post_result_callback(
    url: str,
    result: EventDispatchResult,
    *,
    timeout_s: float = 10.0,
    extra: dict[str, Any] | None = None,
) -> None:
    if not url or not url.strip():
        return
    body: dict[str, Any] = result.to_dict()
    if extra:
        body.update(extra)
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url.strip(), json=body)
            if resp.status_code >= 400:
                logger.warning(
                    "event result callback HTTP {} | url={} | body={}",
                    resp.status_code,
                    url[:120],
                    (resp.text or "")[:200],
                )
    except Exception as e:
        logger.warning(
            "event result callback failed | url={} | detail={}",
            url[:120],
            str(e)[:200],
        )
