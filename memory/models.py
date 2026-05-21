from dataclasses import dataclass, field
from typing import Any

from .types import MemorySource

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
    # id 允许为空：推荐由 store/manager 生成（例如 UUID）。
    id: str | None = None


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
