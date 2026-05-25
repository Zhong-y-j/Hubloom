"""Reflection 阶段输入输出协议（PlanExecute → Hub）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReflectionIssue:
    """单条审查问题（供 Hub 决定是否重跑 PlanExecute 某步）。"""

    severity: str  # "error" | "warning"
    category: str  # consistency | completeness | intent_mismatch | execution_failure | ...
    message: str
    related_step_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "related_step_ids": list(self.related_step_ids),
        }


@dataclass
class ReflectionVerdict:
    """Reflection 的最终输出（Hub 消费）。

    核心字段：
    - ``passed``：是否建议将当前 deliverable 视为可交付（True = 通过审查）
    - ``summary``：一两句总评（可展示给用户或日志）
    - ``issues``：结构化问题列表；``passed=false`` 时通常非空
    - ``recommendation``：给 Hub / PlanExecute 的下一步建议（如重跑 step 2）
    """

    passed: bool
    summary: str
    issues: list[ReflectionIssue] = field(default_factory=list)
    recommendation: str = ""
    review_report: str = ""  # LLM 审查正文（流式拼接后的全文，可选展示）

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "issues": [i.to_dict() for i in self.issues],
            "recommendation": self.recommendation,
            "review_report": self.review_report,
        }

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")
