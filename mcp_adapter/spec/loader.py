"""从 URL 或本地文件加载原始 OpenAPI / Swagger spec。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


async def load_spec(source: str) -> dict[str, Any]:
    """加载原始 spec，原样返回 JSON 对象。

    参数:
        source: 源文件路径或 URL, 例如: https://petstore.swagger.io/v2/swagger.json
    返回:
        dict: 原始 spec 对象
    """
    source = (source or "").strip()
    if not source:
        raise ValueError("swagger source 不能为空")

    path = Path(source)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))

    if not source.startswith(("http://", "https://")):
        raise ValueError(f"须为 http(s) URL 或本地文件路径: {source!r}")

    async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
        response = await client.get(source)
        response.raise_for_status()
        return response.json()


async def main():
    spec = await load_spec("https://petstore.swagger.io/v2/swagger.json")
    print(spec)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
