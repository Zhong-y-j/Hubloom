"""Experience Case：长期记忆批量提炼的核心数据结构。

一条案例 = 用户问题 + 处理办法 + 工具使用 + 结果评价 + 教训。
编排层只读 Qdrant；写入由离线 worker 调用本模块的序列化/解析与后续 consolidator 完成。

与现有存储的映射：
- ``ExperienceCase`` → ``episodic``（``content`` = 检索文本，``metadata`` = 完整案例 JSON）
- ``SemanticRule``   → ``semantic``（从多案例归纳的稳定规则）
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .types import (
    AgentRoute,
    CaseOutcome,
    CaseSatisfaction,
    RuleConfidence,
)

_VALID_OUTCOMES = frozenset({"success", "partial", "failed", "unknown"})
_VALID_SATISFACTION = frozenset({"yes", "no", "unknown"})
_VALID_RULE_CONFIDENCE = frozenset({"low", "medium", "high"})
_VALID_ROUTES = frozenset({"chat", "thought"})


def _norm_outcome(value: Any) -> CaseOutcome:
    v = str(value or "unknown").strip().lower()
    return v if v in _VALID_OUTCOMES else "unknown"  # type: ignore[return-value]


def _norm_satisfaction(value: Any) -> CaseSatisfaction:
    v = str(value or "unknown").strip().lower()
    return v if v in _VALID_SATISFACTION else "unknown"  # type: ignore[return-value]


def _norm_rule_confidence(value: Any) -> RuleConfidence:
    v = str(value or "medium").strip().lower()
    return v if v in _VALID_RULE_CONFIDENCE else "medium"  # type: ignore[return-value]


def _norm_route(value: Any) -> AgentRoute | None:
    if value is None:
        return None
    v = str(value).strip().lower()
    return v if v in _VALID_ROUTES else None  # type: ignore[return-value]


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


@dataclass
class ToolUsageRecord:
    """案例中一次工具调用摘要（不存完整参数，避免噪音与敏感信息）。"""

    name: str
    args_summary: str = ""
    success: bool = True
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolUsageRecord | None:
        name = str(data.get("name") or "").strip()
        if not name:
            return None
        err = data.get("error")
        return cls(
            name=name,
            args_summary=_clip(str(data.get("args_summary") or ""), 200),
            success=bool(data.get("success", True)),
            error=_clip(str(err), 120) if err else None,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "args_summary": self.args_summary,
            "success": self.success,
        }
        if self.error:
            out["error"] = self.error
        return out


@dataclass
class ExperienceCase:
    """情景记忆案例：问题 → 办法 → 工具 → 结果 → 教训。"""

    user_intent: str
    approach: str
    lesson: str
    outcome: CaseOutcome = "unknown"
    user_satisfied: CaseSatisfaction = "unknown"
    tools_used: list[ToolUsageRecord] = field(default_factory=list)

    ref_session_id: str = ""
    turn_start_id: str | None = None
    turn_end_id: str | None = None
    route: AgentRoute | None = None

    user_message_preview: str = ""
    assistant_message_preview: str = ""
    confidence: float = 0.5

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperienceCase | None:
        intent = str(data.get("user_intent") or "").strip()
        approach = str(data.get("approach") or "").strip()
        lesson = str(data.get("lesson") or "").strip()
        if not intent and not lesson:
            return None

        tools: list[ToolUsageRecord] = []
        for raw in data.get("tools_used") or []:
            if isinstance(raw, dict):
                rec = ToolUsageRecord.from_dict(raw)
                if rec is not None:
                    tools.append(rec)

        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        return cls(
            user_intent=_clip(intent, 300),
            approach=_clip(approach, 500),
            lesson=_clip(lesson, 300),
            outcome=_norm_outcome(data.get("outcome")),
            user_satisfied=_norm_satisfaction(data.get("user_satisfied")),
            tools_used=tools,
            ref_session_id=str(data.get("ref_session_id") or "").strip(),
            turn_start_id=(str(data["turn_start_id"]).strip() if data.get("turn_start_id") else None),
            turn_end_id=(str(data["turn_end_id"]).strip() if data.get("turn_end_id") else None),
            route=_norm_route(data.get("route")),
            user_message_preview=_clip(str(data.get("user_message_preview") or ""), 200),
            assistant_message_preview=_clip(
                str(data.get("assistant_message_preview") or ""), 200
            ),
            confidence=confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["tools_used"] = [t.to_dict() for t in self.tools_used]
        return out

    def to_episodic_content(self) -> str:
        """写入 Qdrant ``content`` 的检索文本（用于 embedding）。"""
        tool_part = ""
        if self.tools_used:
            parts = []
            for t in self.tools_used:
                status = "成功" if t.success else "失败"
                parts.append(f"{t.name}（{status}）")
            tool_part = f"\n工具：{', '.join(parts)}"

        outcome_labels = {
            "success": "成功",
            "partial": "部分完成",
            "failed": "失败",
            "unknown": "待确认",
        }
        sat_labels = {"yes": "满意", "no": "不满意", "unknown": "待确认"}

        return (
            f"【案例】{self.user_intent}\n"
            f"做法：{self.approach}{tool_part}\n"
            f"结果：{outcome_labels.get(self.outcome, self.outcome)}；"
            f"用户反馈：{sat_labels.get(self.user_satisfied, self.user_satisfied)}\n"
            f"教训：{self.lesson}"
        ).strip()

    def to_episodic_metadata(self) -> dict[str, Any]:
        """写入 Qdrant ``metadata`` 的结构化字段。"""
        meta = self.to_dict()
        meta["memory_kind"] = "experience_case"
        if self.ref_session_id:
            meta["ref_session_id"] = self.ref_session_id
        importance = 30
        if self.user_satisfied == "no" or self.outcome == "failed":
            importance = 70
        elif self.lesson and self.outcome == "success":
            importance = 50
        meta["importance"] = importance
        return meta


@dataclass
class SemanticRule:
    """从多条案例归纳的语义规则（写入 semantic 向量库）。"""

    rule: str
    confidence: RuleConfidence = "medium"
    domain: str | None = None
    source_case_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SemanticRule | None:
        rule = str(data.get("rule") or "").strip()
        if not rule:
            return None
        domain = data.get("domain")
        try:
            count = int(data.get("source_case_count") or 0)
        except (TypeError, ValueError):
            count = 0
        return cls(
            rule=_clip(rule, 300),
            confidence=_norm_rule_confidence(data.get("confidence")),
            domain=_clip(str(domain), 80) if domain else None,
            source_case_count=max(0, count),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "confidence": self.confidence,
            "source_case_count": self.source_case_count,
        }
        if self.domain:
            out["domain"] = self.domain
        return out

    def to_semantic_content(self) -> str:
        prefix = f"[{self.domain}] " if self.domain else ""
        return f"{prefix}{self.rule}".strip()

    def to_semantic_metadata(self) -> dict[str, Any]:
        meta = self.to_dict()
        meta["memory_kind"] = "semantic_rule"
        importance = {"low": 40, "medium": 55, "high": 75}.get(self.confidence, 55)
        meta["importance"] = importance
        return meta


@dataclass
class BatchExtractionResult:
    """批量提炼 LLM 输出解析结果。"""

    cases: list[ExperienceCase] = field(default_factory=list)
    semantic_rules: list[SemanticRule] = field(default_factory=list)
    skipped: bool = False
    error: str | None = None

    @property
    def total_written(self) -> int:
        return len(self.cases) + len(self.semantic_rules)


def parse_batch_extraction_json(text: str) -> dict[str, Any]:
    """从模型输出解析 JSON 对象。"""
    raw = (text or "").strip()
    if not raw:
        return {}

    import re

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)

    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_batch_extraction(text: str) -> BatchExtractionResult:
    """解析批量提炼 JSON → 案例 + 规则。"""
    data = parse_batch_extraction_json(text)
    if not data:
        return BatchExtractionResult(skipped=True)

    cases: list[ExperienceCase] = []
    for item in data.get("cases") or []:
        if isinstance(item, dict):
            case = ExperienceCase.from_dict(item)
            if case is not None:
                cases.append(case)

    rules: list[SemanticRule] = []
    for item in data.get("semantic_rules") or []:
        if isinstance(item, dict):
            rule = SemanticRule.from_dict(item)
            if rule is not None:
                rules.append(rule)

    if not cases and not rules:
        return BatchExtractionResult(skipped=True)
    return BatchExtractionResult(cases=cases, semantic_rules=rules)


# LLM 批量提炼期望的输出格式（供 step 2 consolidator prompt 使用）
BATCH_EXTRACTION_JSON_EXAMPLE = """```json
{
  "cases": [
    {
      "user_intent": "查询当前库存",
      "approach": "直接调用 list_inventory 获取全量库存，未追问仓点",
      "tools_used": [
        {"name": "list_inventory", "args_summary": "{}", "success": true}
      ],
      "outcome": "success",
      "user_satisfied": "unknown",
      "lesson": "查库存可先 list_inventory，无需先问仓点",
      "confidence": 0.75
    }
  ],
  "semantic_rules": [
    {
      "rule": "库存类问题优先使用 list_inventory，不要编造 SKU",
      "confidence": "medium",
      "domain": "inventory"
    }
  ]
}
```"""
