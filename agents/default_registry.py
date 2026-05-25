"""默认专业 Agent 注册表（PlanExecute / Hub 测试共用）。"""

from agents.plan_execute import InMemoryAgentRegistry


def build_default_registry() -> InMemoryAgentRegistry:
    reg = InMemoryAgentRegistry()
    reg.register(
        {
            "agent_id": "prog-001",
            "agent_type": "programming",
            "capabilities": ["programming"],
            "description": "编程与技术规格 Agent",
        }
    )
    reg.register(
        {
            "agent_id": "legal-001",
            "agent_type": "legal",
            "capabilities": ["legal"],
            "description": "法律条款 Agent",
        }
    )
    return reg
