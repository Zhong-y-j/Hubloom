"""ContextAssembler 装配 smoke test（本地假数据，不联网）。

运行::

    PYTHONPATH=. uv run python -m memory.test_context
"""

from __future__ import annotations

from core.models import Message, Role
from memory.context import ContextAssembler
from observability import setup_log

SYSTEM = "你是 Agent Cortex 助手，请结合记忆与文档回答。"

MEMORIES = [
    {"content": "用户在上海负责合同项目A", "score": 0.88, "memory_type": "episodic"},
    {"content": "用户偏好简洁、列要点用编号", "score": 0.82, "memory_type": "semantic"},
]

DOCUMENTS = [
    {
        "text": "付款节点应在验收后 30 日内支付。",
        "metadata": {"doc_name": "合同模板", "section_path": "付款"},
        "score": 0.85,
    },
]

GRAPH_SUMMARY = """种子实体: 陈艳 (person)
- 陈艳 --[负责]--> 合同项目A
- 实体 合同项目A (project)"""

HISTORIES = [
    Message(role=Role.USER, content="你好"),
    Message(role=Role.ASSISTANT, content="你好，有什么可以帮你？"),
]

CURRENT = "帮我看看付款条款有没有风险？"


def main() -> None:
    setup_log()

    asm = ContextAssembler(max_tokens=2000, min_relevance=0.3)
    messages = asm.assemble(
        system_prompt=SYSTEM,
        memories=MEMORIES,
        documents=DOCUMENTS,
        histories=HISTORIES,
        current_task=CURRENT,
        graph_summary=GRAPH_SUMMARY,
    )

    print("--- 装配结果 ---")
    print(f"消息数: {len(messages)}  预算: {asm.max_tokens}")
    for i, msg in enumerate(messages):
        preview = str(msg.content or "").replace("\n", " ")[:100]
        print(f"[{i}] {msg.role.value:10s} | {preview}...")

    tags = [
        t
        for m in messages
        for t in ("[MEMORY]", "[GRAPH]", "[DOCUMENTS]")
        if t in str(m.content)
    ]
    print("\n块标签:", ", ".join(dict.fromkeys(tags)) or "(无)")


if __name__ == "__main__":
    main()
