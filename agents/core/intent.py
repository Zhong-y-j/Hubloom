"""ReAct 阶段结构化意图：供 PlanExecute 消费。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# 澄清完成且无需进入 PlanExecute 的 intent 类型
_NO_PLAN_INTENTS = frozenset({"general_chat"})

_USER_REPLY_PREFIX_RE = re.compile(
    r"^user_reply\s*[:：]\s*",
    re.IGNORECASE,
)

_JSON_BLOCK_RE = re.compile(
    r"```(?:intent|json)\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)

_INTENT_FENCE_MARKERS = ("```intent", "```json")


@dataclass
class StructuredIntent:
    """意图澄清结果（ReAct → PlanExecute handoff）。"""

    is_clear: bool
    intent: str
    summary: str
    slots: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    user_reply: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_clear": self.is_clear,
            "intent": self.intent,
            "summary": self.summary,
            "slots": self.slots,
            "missing": self.missing,
            "user_reply": self.user_reply,
        }

    def should_invoke_plan(self) -> bool:
        """中枢是否应进入 PlanExecute（闲聊等直接结束）。"""
        if not self.is_clear:
            return False
        return self.intent not in _NO_PLAN_INTENTS


INTENT_OUTPUT_INSTRUCTION = """
## 输出格式（必须遵守）
本轮回复须包含两部分：
1. **user_reply**：给用户看的自然语言。
   - 对外口径：你是 **Agent Cortex（灵枢）智能助手**，禁止自称「意图澄清专家」或描述内部阶段名（ReAct / PlanExecute 等）。
   - 闲聊、问候、问「你是谁/能做什么」：`general_chat` + `is_clear=true`；user_reply **必须基于系统提示中「当前可调用工具」与「系统执行能力」（MCP 动态目录）的真实 description** 来介绍能力，可略长，**禁止**编造目录中不存在的能力。
   - 澄清追问：简洁，只问 1～3 个关键问题。
   - 任务已清晰、将交执行层：user_reply 只做简要确认，**不要**代写完整合同/长方案/长清单。
   - **正文里不要写「user_reply:」这类字段名前缀。**
2. **intent JSON**：用 ```intent 代码块包裹，供系统路由与执行，格式如下：

```intent
{
  "is_clear": true,
  "intent": "意图类型英文蛇形名，如 document_qa / general_task / general_chat",
  "summary": "一句结构化任务描述，供规划阶段使用",
  "slots": { "键": "已澄清的关键信息" },
  "missing": [],
  "user_reply": "与上文一致的用户可见短回复"
}
```

意图未澄清时：
- `is_clear` 必须为 false
- `missing` 列出仍缺的信息项
- `user_reply` 只问 1～3 个关键问题，不要执行任务
- 若已从 [DOCUMENTS] 或工具结果得知主题/项目名称，写入 `slots`（如 subject、project_name），仅对仍缺项列入 `missing`

意图已澄清时：
- `is_clear` 为 true
- `slots` 填入已确认字段；**不要在 user_reply 里写完整交付物**（如完整合同正文、项目长清单），留给 PlanExecute。

若任务需由「系统执行能力」（MCP 工具）完成，在 slots 中填写：
- "suggested_tools": ["<工具名>"]   // 必须来自系统提示里「系统执行能力」列表的 name，供 Plan 参考
- "action_params": {}               // 已从用户或对话中明确的参数（键名须符合该工具 parameters）
"""

INTENT_TYPE_HINTS = """
### intent 类型参考（与具体 MCP 工具无关，仅作路由标签）
- `document_qa`：主要从文档/知识库查事实
- `general_task`：需调用 MCP 执行能力完成的多步/查询类任务（具体调哪些工具由 Plan 读目录决定）
- `general_chat`：问候、自我介绍、问产品能力、闲聊（`is_clear=true` 时直接 user_reply，不进 PlanExecute）
- 其他蛇形名可自拟，但不要绑定某一固定 API 或 Swagger 名称
"""

INTENT_REFORMAT_NUDGE = (
    "你上一段回复缺少合法的 ```intent``` JSON，或格式不规范。"
    "请仅重新输出：简短 user_reply 正文（不要写 user_reply: 前缀）+ ```intent``` 代码块，不要调用工具。"
)


class IntentStreamFilter:
    """流式输出时隐藏 ```intent / ```json 代码块，避免用户看到 JSON。"""

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._hold = ""
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def push(self, chunk: str) -> str:
        if not self._enabled or self._closed or not chunk:
            return ""
        self._hold += chunk
        lowered = self._hold.lower()
        for marker in _INTENT_FENCE_MARKERS:
            idx = lowered.find(marker)
            if idx >= 0:
                out = self._hold[:idx]
                self._hold = ""
                self._closed = True
                return out
        if len(self._hold) <= 12:
            return ""
        out = self._hold[:-12]
        self._hold = self._hold[-12:]
        return out

    def flush(self) -> str:
        if not self._enabled or self._closed:
            return ""
        out = self._hold
        self._hold = ""
        return out


def clean_user_display(text: str) -> str:
    """去掉展示用文本中的字段名前缀等噪音。"""
    t = (text or "").strip()
    t = _USER_REPLY_PREFIX_RE.sub("", t)
    return t.strip()


def resolve_display_text(
    parsed_display: str,
    intent: StructuredIntent | None,
    *,
    raw_fallback: str = "",
) -> str:
    """确定最终给用户看的文本。"""
    if intent and intent.user_reply:
        base = intent.user_reply
    elif parsed_display:
        base = parsed_display
    else:
        base = raw_fallback
    return clean_user_display(base)


def parse_intent_from_answer(text: str) -> tuple[str, StructuredIntent | None]:
    """从模型回复中解析 intent 块，返回 (展示文本, StructuredIntent)。"""
    raw = (text or "").strip()
    if not raw:
        return "", None

    match = _JSON_BLOCK_RE.search(raw)
    if not match:
        return clean_user_display(raw), None

    display = clean_user_display(raw[: match.start()])
    try:
        data = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return clean_user_display(raw), None

    if not isinstance(data, dict):
        return clean_user_display(raw), None

    user_reply = clean_user_display(str(data.get("user_reply") or ""))
    if not display and user_reply:
        display = user_reply

    intent = StructuredIntent(
        is_clear=bool(data.get("is_clear", False)),
        intent=str(data.get("intent") or "unknown"),
        summary=str(data.get("summary") or ""),
        slots=dict(data.get("slots") or {}),
        missing=[str(x) for x in (data.get("missing") or [])],
        user_reply=user_reply,
    )
    display = resolve_display_text(display, intent, raw_fallback=raw)
    return display, intent


def intent_from_dict(data: dict[str, Any]) -> StructuredIntent:
    return StructuredIntent(
        is_clear=bool(data.get("is_clear", False)),
        intent=str(data.get("intent") or "unknown"),
        summary=str(data.get("summary") or ""),
        slots=dict(data.get("slots") or {}),
        missing=[str(x) for x in (data.get("missing") or [])],
        user_reply=clean_user_display(str(data.get("user_reply") or "")),
    )
