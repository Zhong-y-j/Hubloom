"""Prime Hubloom MCP with transport OpenAPI after both services are up."""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

HUBLOOM_BASE_URL = os.getenv("HUBLOOM_BASE_URL", "http://127.0.0.1:8003").rstrip("/")
TRANSPORT_PUBLIC_URL = os.getenv(
    "TRANSPORT_PUBLIC_URL", "http://127.0.0.1:9003"
).rstrip("/")

_PRIME_PAYLOAD = {
    "mcp_swagger_url": f"{TRANSPORT_PUBLIC_URL}/openapi.json",
    "mcp_base_url": TRANSPORT_PUBLIC_URL,
    "mcp_auth_scheme": "Bearer",
}


async def prime_hubloom() -> bool:
    """Register transport Swagger with Hubloom. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{HUBLOOM_BASE_URL}/v1/config/apply",
                json=_PRIME_PAYLOAD,
            )
        if response.status_code >= 400:
            logger.warning(
                "Hubloom 预连接失败: HTTP %s %s",
                response.status_code,
                response.text,
            )
            return False
        data = response.json()
        logger.info(
            "Hubloom 已加载交通 API：%s 个分组 · %s 个接口",
            data.get("group_count"),
            data.get("tool_count"),
        )
        return True
    except Exception as exc:
        logger.debug("Hubloom 预连接重试中: %s", exc)
        return False


async def prime_hubloom_retry(
    *,
    max_attempts: int = 30,
    interval_sec: float = 2.0,
    initial_delay_sec: float = 1.0,
) -> None:
    """Wait until this service is listening, then retry Hubloom registration."""
    await asyncio.sleep(initial_delay_sec)
    for attempt in range(1, max_attempts + 1):
        if await prime_hubloom():
            return
        if attempt < max_attempts:
            await asyncio.sleep(interval_sec)
    logger.warning(
        "Hubloom 预连接超时（%s 次），请确认 Hubloom 已启动；聊天页打开时会再次同步",
        max_attempts,
    )
