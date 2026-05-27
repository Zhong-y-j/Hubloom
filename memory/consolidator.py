"""回合结束后从对话提炼并写入长期记忆（episodic / semantic / associative）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from core.models import Message, Role
from core.provider import LLMProvider
from memory.handlers.associative_handler import AssociativeHandler
from memory.manager import MemoryManager
from memory.types import EntityType, LongTermMemoryType

_VALID_ENTITY_TYPES = frozenset(
    {
        "person",
        "organization",
        "project",
        "concept",
        "tool",
        "document",
        "event",
        "location",
        "other",
    }
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)

CONSOLIDATION_SYSTEM = """你是记忆提炼助手。从本轮对话中提取值得长期保存的信息。

规则：
- episodic：一次性事实/事件，短句，每条不超过 80 字
- semantic：稳定偏好/规则/抽象知识；勿把一次性事件写入 semantic
- relations：实体间关系；实体名规范简短
- from_entity_type / to_entity_type 取值：person, organization, project, concept, tool, document, event, location, other
- 若无值得保存的内容，对应字段返回空数组
- 不要保存敏感信息（密码、密钥等）

只输出 JSON，格式如下：
```json
{
  "episodic": ["用户正在做神灯AR合作项目"],
  "semantic": ["用户偏好简洁回复"],
  "relations": [
    {
      "from_name": "用户",
      "to_name": "神灯AR项目",
      "relation_label": "参与",
      "from_entity_type": "person",
      "to_entity_type": "project"
    }
  ]
}
```"""


@dataclass
class MemoryConsolidationResult:
    """一轮记忆提炼写入结果。"""

    episodic_written: list[str] = field(default_factory=list)
    semantic_written: list[str] = field(default_factory=list)
    relations_written: list[str] = field(default_factory=list)
    links_written: list[str] = field(default_factory=list)
    skipped: bool = False
    error: str | None = None

    @property
    def total_written(self) -> int:
        return (
            len(self.episodic_written)
            + len(self.semantic_written)
            + len(self.relations_written)
            + len(self.links_written)
        )


@dataclass
class _WrittenVectorMemory:
    memory_type: LongTermMemoryType
    memory_id: str
    content: str


def parse_consolidation_json(text: str) -> dict[str, Any]:
    """从模型输出解析提炼 JSON。"""
    raw = (text or "").strip()
    if not raw:
        return {}

    match = _JSON_BLOCK_RE.search(raw)
    payload = match.group(1).strip() if match else raw
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}

    return data if isinstance(data, dict) else {}


def _norm_entity_type(value: Any) -> EntityType:
    t = str(value or "other").strip().lower()
    return t if t in _VALID_ENTITY_TYPES else "other"  # type: ignore[return-value]


class MemoryConsolidator:
    """Hub 侧记忆提炼：LLM 抽取 → MemoryManager.remember。

    Args:
        memory_manager: MemoryManager 实例
        llm: LLMProvider 实例
        min_user_chars: 用户消息最小字符数

    Actions:
        consolidate: 提炼记忆
        apply_extraction: 应用提炼结果 
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        llm: LLMProvider,
        *,
        min_user_chars: int = 4,
    ) -> None:
        self._memory = memory_manager
        self._llm = llm
        self._min_user_chars = min_user_chars

    async def consolidate(
        self,
        *,
        user_message: str,
        assistant_message: str = "",
        session_id: str | None = None,
    ) -> MemoryConsolidationResult:
        """提炼记忆

        Args:
            user_message: 用户消息
            assistant_message: 助手消息
            session_id: 会话 ID
        Returns:
            MemoryConsolidationResult: 提炼结果
        """

        user_message = (user_message or "").strip()
        assistant_message = (assistant_message or "").strip()

        if len(user_message) < self._min_user_chars:
            return MemoryConsolidationResult(skipped=True)

        prompt = (
            f"用户：{user_message}\n"
            f"助手：{assistant_message or '（无回复）'}\n\n"
            "请提炼 episodic / semantic / relations。"
        )
        try:
            out = await self._llm.generate(
                messages=[
                    Message(role=Role.SYSTEM, content=CONSOLIDATION_SYSTEM),
                    Message(role=Role.USER, content=prompt),
                ],
                tools=None,
            )
            data = parse_consolidation_json(out.content or "")
        except Exception as exc:
            return MemoryConsolidationResult(skipped=True, error=str(exc))

        return await self.apply_extraction(data, session_id=session_id)

    async def apply_extraction(
        self,
        data: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> MemoryConsolidationResult:
        """将已解析的提炼结果写入 MemoryManager（关系先于向量，再 link_memory）。

        Args:
            data: 提炼结果
            session_id: 会话 ID
        Returns:
            MemoryConsolidationResult: 提炼结果
        """
        result = MemoryConsolidationResult()
        meta_base: dict[str, Any] = {}
        if session_id:
            meta_base["ref_session_id"] = session_id

        relation_entity_names: set[str] = set()
        written_vectors: list[_WrittenVectorMemory] = []

        for rel in data.get("relations") or []:
            if not isinstance(rel, dict):
                continue
            from_name = str(rel.get("from_name") or "").strip()
            to_name = str(rel.get("to_name") or "").strip()
            if not from_name or not to_name:
                continue
            label = str(rel.get("relation_label") or "关联").strip()
            try:
                await self._memory.remember(
                    memory_type="associative",
                    content=label,
                    metadata={
                        "from_name": from_name,
                        "to_name": to_name,
                        "relation_label": label,
                        "from_entity_type": _norm_entity_type(
                            rel.get("from_entity_type")
                        ),
                        "to_entity_type": _norm_entity_type(rel.get("to_entity_type")),
                        **meta_base,
                    },
                )
            except Exception:
                continue
            relation_entity_names.add(from_name)
            relation_entity_names.add(to_name)
            result.relations_written.append(f"{from_name} --[{label}]--> {to_name}")

        for item in data.get("episodic") or []:
            content = str(item).strip()
            if not content:
                continue
            memory_id = await self._memory.remember(
                memory_type="episodic",
                content=content,
                metadata=dict(meta_base),
            )
            result.episodic_written.append(content)
            written_vectors.append(_WrittenVectorMemory("episodic", memory_id, content))

        for item in data.get("semantic") or []:
            content = str(item).strip()
            if not content:
                continue
            memory_id = await self._memory.remember(
                memory_type="semantic",
                content=content,
                metadata=dict(meta_base),
            )
            result.semantic_written.append(content)
            written_vectors.append(_WrittenVectorMemory("semantic", memory_id, content))

        if written_vectors and relation_entity_names:
            result.links_written = await self._link_vectors_to_entities(
                written_vectors,
                relation_entity_names,
            )

        if not result.total_written:
            result.skipped = True
        return result

    def _associative_handler(self) -> AssociativeHandler | None:
        handler = self._memory.handlers.get("associative")
        return handler if isinstance(handler, AssociativeHandler) else None

    async def _resolve_entity_id(self, entity_name: str) -> str | None:
        handler = self._associative_handler()
        if handler is None:
            return None
        entity = await handler.store.get_entity_by_name(handler.namespace, entity_name)
        return entity.id if entity else None

    def _entity_matches_content(self, entity_name: str, content: str) -> bool:
        """实体名出现在正文中，或正文过短时由批次关系兜底。"""
        if entity_name in content:
            return True
        short = entity_name.strip()
        if len(short) >= 2 and short in content.replace(" ", ""):
            return True
        return False

    async def _link_vectors_to_entities(
        self,
        vectors: list[_WrittenVectorMemory],
        entity_names: set[str],
    ) -> list[str]:
        """将本轮向量记忆挂到图实体（HAS_MEMORY → MemoryRef）。"""
        handler = self._associative_handler()
        if handler is None:
            return []

        links: list[str] = []
        for vec in vectors:
            preview = vec.content[:120] if len(vec.content) > 120 else vec.content
            targets = [
                name
                for name in entity_names
                if self._entity_matches_content(name, vec.content)
            ]
            if not targets:
                targets = list(entity_names)

            for name in targets:
                entity_id = await self._resolve_entity_id(name)
                if not entity_id:
                    continue
                try:
                    await handler.link_memory(
                        entity_id=entity_id,
                        memory_type=vec.memory_type,
                        memory_id=vec.memory_id,
                        content_preview=preview,
                    )
                    links.append(
                        f"{name} <-[{vec.memory_type}] {preview[:40]}"
                        + ("..." if len(vec.content) > 40 else "")
                    )
                except Exception:
                    continue
        return links
