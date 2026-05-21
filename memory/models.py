from dataclasses import dataclass, field
from typing import Any

from .types import EntityType, LongTermMemoryType, MemorySource

from .utils import now_local_str


@dataclass
class EpisodicItem:
    """情景记忆的最小存储单元

    Args:
        id: 记忆条目的唯一标识
        content: 记忆条目的内容
        namespace: 逻辑分区键，用于存储/检索时强制隔离（如 SQL ``WHERE namespace = ?``）。

            **推荐格式** ``{kind}:{owner}:{scope}``：

            - ``kind``：大类，如 ``mem``（用户情景记忆）、``doc``（某份文档的片段）等。
            - ``owner``：**必须稳定且全局唯一**。生产环境应使用账号体系的
              ``user_id``（UUID/雪花 ID 等），不要用昵称、姓名或拼音——同名/改名都会冲突。
              本地开发可读占位符（如 ``alice``）仅便于自测。
            - ``scope``：该 owner 下的子域，如 ``default``、``session_<id>``、``proj_<id>``。

            **示例**：开发自测 ``mem:dev_alice:default``；生产建议
            ``mem:usr_8f3a2b1c:default``、``mem:usr_8f3a2b1c:sess_abc123``。

        ref_session_id: 来源会话 ID（与 conversation.session_id 对齐，可选）
        content_hash: 正文哈希，用于去重（可由 store 自动计算）
        importance: 重要度 0–100，越大越不易被 LRU/TTL 淘汰（策略层使用）
        metadata: 记忆条目的元数据
        created_at: 记忆条目的创建时间
        last_accessed_at: 记忆条目的最后一次访问时间
        access_count: 记忆条目的访问次数
        source: 记忆条目的来源
            - memory: 情景记忆
            - document: 文档记忆
            - knowledge: 知识记忆
    """

    content: str
    namespace: str  # 见类 docstring：kind:owner:scope；owner 在生产环境须为稳定 user_id
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_local_str)
    last_accessed_at: str = field(default_factory=now_local_str)
    access_count: int = 0
    source: MemorySource = "memory"
    id: str | None = None
    ref_session_id: str | None = None
    content_hash: str | None = None
    importance: int = 0


@dataclass
class SemanticItem:
    """语义记忆（Semantic Memory）的最小存储单元。

    与 EpisodicItem 的区别（工程分工）：
    - Episodic：存“发生过的事实片段/事件”，通常可衰减、可淘汰，关键词检索也能工作。
    - Semantic：存“抽象后的稳定知识/偏好/规则”，用于跨表述的语义相似度检索，生命周期更长。
    """

    content: str
    namespace: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_local_str)
    last_accessed_at: str = field(default_factory=now_local_str)
    access_count: int = 0
    source: MemorySource = "memory"
    id: str | None = None
    ref_session_id: str | None = None
    content_hash: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    importance: int = 0


@dataclass
class GraphEntity:
    """联想记忆 · 图实体节点（Neo4j ``:Entity``）。"""

    id: str
    namespace: str
    name: str
    entity_type: EntityType = "other"
    aliases: list[str] = field(default_factory=list)
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_local_str)
    updated_at: str | None = None
    source: MemorySource = "memory"
    ref_session_id: str | None = None
    importance: int = 0


@dataclass
class GraphRelation:
    """联想记忆 · 实体间关系边。"""

    namespace: str
    from_entity_id: str
    to_entity_id: str
    from_name: str
    to_name: str
    relation_type: str = "RELATES_TO"
    relation_label: str | None = None
    weight: float = 1.0
    created_at: str | None = None
    id: str | None = None


@dataclass
class GraphMemoryRef:
    """联想记忆 · 指向 episodic/semantic 向量记忆的引用节点。"""

    id: str
    namespace: str
    memory_type: LongTermMemoryType
    memory_id: str
    entity_id: str | None = None
    content_preview: str | None = None
    created_at: str | None = None


@dataclass
class AssociativeRecallResult:
    """联想记忆检索结果：种子实体 + 邻域 + 关联记忆引用。"""

    seed: GraphEntity | None = None
    entities: list[GraphEntity] = field(default_factory=list)
    relations: list[GraphRelation] = field(default_factory=list)
    memory_refs: list[GraphMemoryRef] = field(default_factory=list)
