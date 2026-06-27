"""Hub 用户可见回复：LLM 摘要交付物 + 组合 ReAct / Reflection 输出。"""

from __future__ import annotations

from core.models import Message, Role
from core.provider import LLMProvider

from agents.core.agent_log import hub_log
from agents.core.intent import StructuredIntent

_DELIVERABLE_SUMMARY_SYSTEM = """你是灵枢的用户回复助手。将 PlanExecute 的原始交付物改写为**面向终端用户的自然语言摘要**。

规则：
- 使用清晰、友好的中文，直接回答用户问题
- 若交付物是 JSON / API 数据：提取关键数字与结论，忽略明显测试噪音（如 PreConditionStatus XXXX、invalid-status 等）
- 若交付物是长文档：给出结构化要点摘要，不要全文复述
- 不要提及 PlanExecute、MCP、工具名、JSON、API 等内部实现细节
- 不要重复用户已经看到的确认语或寒暄
- 只输出摘要正文，不要 markdown 代码块、不要字段名前缀"""


class ReplyComposer:
    """将原始 deliverable 转为自然语言，并组合最终用户可见回复。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def summarize_deliverable(
        self,
        deliverable: str,
        intent: StructuredIntent | None = None,
    ) -> str:
        """用 LLM 将原始交付物转为自然语言摘要。"""
        raw = (deliverable or "").strip()
        if not raw:
            return ""

        intent_blurb = ""
        if intent is not None:
            intent_blurb = (
                f"\n\n用户意图：{intent.summary or intent.user_reply}\n"
                f"intent 类型：{intent.intent}"
            )

        messages = [
            Message(role=Role.SYSTEM, content=_DELIVERABLE_SUMMARY_SYSTEM),
            Message(
                role=Role.USER,
                content=(
                    f"请将以下交付物改写为用户可读的自然语言摘要。{intent_blurb}\n\n"
                    f"原始交付物：\n{raw}"
                ),
            ),
        ]
        try:
            out = await self._llm.generate(messages=messages, tools=None)
            summary = (out.content or "").strip()
            hub_log(
                "deliverable summarized",
                raw_len=len(raw),
                summary_len=len(summary),
            )
            return summary
        except Exception as exc:
            hub_log("deliverable summarize failed", error=str(exc))
            return raw

    @staticmethod
    def compose(
        *,
        user_reply: str,
        deliverable_summary: str = "",
        reflection_summary: str | None = None,
    ) -> str:
        """组合 ReAct 确认语、Reflection 总评、交付物自然语言摘要。"""
        parts: list[str] = []
        if (user_reply or "").strip():
            parts.append(user_reply.strip())
        if (reflection_summary or "").strip():
            parts.append(reflection_summary.strip())
        if (deliverable_summary or "").strip():
            parts.append(deliverable_summary.strip())
        return "\n\n".join(parts)

    async def build_final_message(
        self,
        *,
        user_reply: str,
        deliverable: str | None,
        intent: StructuredIntent | None = None,
        reflection_summary: str | None = None,
    ) -> tuple[str, str]:
        """返回 (delivery_summary, final_user_message)。"""
        raw = (deliverable or "").strip()
        if not raw:
            return "", (user_reply or "").strip()

        delivery_summary = await self.summarize_deliverable(raw, intent)
        final = self.compose(
            user_reply=user_reply,
            deliverable_summary=delivery_summary,
            reflection_summary=reflection_summary,
        )
        return delivery_summary, final
