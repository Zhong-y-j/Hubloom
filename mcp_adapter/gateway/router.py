"""网关路由层：校验 tag / tool，转发到 BackendPool。"""

from __future__ import annotations

from typing import Any

from mcp_adapter.gateway.catalog import GatewayCatalog
from mcp_adapter.gateway.pool import BackendPool, DEFAULT_TIMEOUT


class BackendRouter:
    """只做路由校验，生命周期交给 BackendPool。"""

    def __init__(
        self,
        catalog: GatewayCatalog,
        pool: BackendPool | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._catalog = catalog
        self._pool = pool or BackendPool(catalog, timeout=timeout)
        self._owns_pool = pool is None

    def _ensure_tag(self, tag: str) -> None:
        if tag not in self._catalog.groups:
            raise ValueError(f"未知分组 tag: {tag!r}")

    def _ensure_tool(self, tag: str, tool_name: str) -> None:
        group = self._catalog.get_group(tag)
        if group and tool_name not in group.tool_names:
            preview = ", ".join(group.tool_names[:5])
            raise ValueError(
                f"工具 {tool_name!r} 不属于分组 {tag!r}；示例: {preview}..."
            )

    @property
    def pool(self) -> BackendPool:
        return self._pool

    async def list_tools(self, tag: str) -> list[dict[str, Any]]:
        self._ensure_tag(tag)
        return await self._pool.list_tools(tag)

    async def call_tool(
        self,
        tag: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        self._ensure_tag(tag)
        self._ensure_tool(tag, tool_name)
        return await self._pool.call_tool(tag, tool_name, arguments)

    async def close(self) -> None:
        if self._owns_pool:
            await self._pool.close()

    async def __aenter__(self) -> BackendRouter:
        await self._pool.prewarm()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


async def main() -> None:
    from mcp_adapter.gateway.catalog import load_catalog

    catalog = await load_catalog()
    catalog.print_summary()

    sample_tag = "pet" if catalog.get_group("pet") else catalog.list_tags()[0]

    async with BackendRouter(catalog) as router:
        print(f"\n=== 已预热 / 已运行 tag: {router.pool.running_tags()} ===")
        print(f"\n=== 访问 [{sample_tag}] ===")
        tools = await router.list_tools(sample_tag)
        print(f"工具数: {len(tools)}")
        for t in tools[:5]:
            print(f"  - {t['name']}: {t['description'][:50]}")
        print(f"\n运行中后端: {router.pool.running_tags()}")

    print("\n=== 后端已关闭 ===")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
