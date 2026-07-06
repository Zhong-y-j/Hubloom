"""从 OpenAPI spec 自动生成网关分组目录（tag → 工具列表）。

不手写分组；数据来自 Swagger 里每个 operation 的 tags / operationId。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from mcp_adapter.spec.filter import summarize_by_tag
from mcp_adapter.spec.loader import load_spec
from mcp_adapter.spec.normalize import normalize_openapi_spec


@dataclass(frozen=True)
class ToolRef:
    """组内一个工具（MCP tool name = operationId）。"""

    name: str
    method: str
    path: str
    description: str


@dataclass
class GroupCatalog:
    """一个 tag 分组 = 一个后端 worker（tag 即 worker 参数）。"""

    tag: str
    description: str
    tools: list[ToolRef] = field(default_factory=list)

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]


@dataclass
class GatewayCatalog:
    """全部分组目录。"""

    groups: dict[str, GroupCatalog]

    def list_tags(self) -> list[str]:
        return sorted(self.groups.keys())

    def get_group(self, tag: str) -> GroupCatalog | None:
        return self.groups.get(tag)

    def print_summary(self) -> None:
        print(f"=== 网关目录：共 {len(self.groups)} 个分组 ===")
        for tag in self.list_tags():
            g = self.groups[tag]
            print(f"  {tag}: {g.tool_count} 个工具 — {g.description[:40]}")


def _tag_descriptions(spec: dict) -> dict[str, str]:
    """OpenAPI 顶层 tags 里的 description（若有）。"""
    out: dict[str, str] = {}
    for item in spec.get("tags") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        desc = str(item.get("description") or "").strip()
        out[name] = desc or name
    return out


def _operation_description(operation: dict) -> str:
    for key in ("summary", "description", "operationId"):
        text = str(operation.get(key) or "").strip()
        if text:
            return text.split("\n")[0]
    return ""


def build_catalog_from_openapi(spec: dict) -> GatewayCatalog:
    """从已规范化的 OpenAPI 3.x spec 构建目录。"""
    tag_desc = _tag_descriptions(spec)
    groups: dict[str, GroupCatalog] = {}

    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method == "parameters" or not isinstance(operation, dict):
                continue

            name = str(operation.get("operationId") or "").strip()
            if not name:
                continue

            raw_tags = operation.get("tags") or []
            tags = [str(t).strip() for t in raw_tags if str(t).strip()]
            if not tags:
                tags = ["_untagged"]

            ref = ToolRef(
                name=name,
                method=method.upper(),
                path=str(path),
                description=_operation_description(operation),
            )

            for tag in tags:
                if tag not in groups:
                    groups[tag] = GroupCatalog(
                        tag=tag,
                        description=tag_desc.get(tag, tag),
                    )
                groups[tag].tools.append(ref)

    for g in groups.values():
        g.tools.sort(key=lambda t: t.name)

    return GatewayCatalog(groups=groups)


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


async def load_catalog() -> GatewayCatalog:
    """从 .env 的 MCP_SWAGGER_URL 加载 spec 并生成目录。"""
    load_dotenv()
    swagger_url = _env(
        "MCP_SWAGGER_URL",
        "https://petstore.swagger.io/v2/swagger.json",
    )
    raw = await load_spec(swagger_url)
    openapi = normalize_openapi_spec(raw)
    return build_catalog_from_openapi(openapi)


async def main() -> None:
    catalog = await load_catalog()
    catalog.print_summary()

    # 与 filter.summarize_by_tag 交叉验证数量
    raw = await load_spec(
        _env("MCP_SWAGGER_URL", "https://petstore.swagger.io/v2/swagger.json")
    )
    openapi = normalize_openapi_spec(raw)
    counts = summarize_by_tag(openapi)

    print()
    print("=== 与 summarize_by_tag 对照 ===")
    for tag in catalog.list_tags():
        g = catalog.get_group(tag)
        expected = counts.get(tag, 0)
        ok = "✓" if g and g.tool_count == expected else "✗"
        print(f"  {ok} {tag}: catalog={g.tool_count if g else 0}, filter={expected}")

    print()
    print("=== 示例 ===")
    dic = catalog.get_group(catalog.list_tags()[0])
    if dic:
        for t in dic.tools[:5]:
            print(f"  - {t.name} ({t.method} {t.path})")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
