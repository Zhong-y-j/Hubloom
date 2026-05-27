"""记忆提炼 smoke test：用一轮真实对话格式，调用 LLM 提取并写入长期记忆。

运行（需 .env：OPENAI_API_KEY、Qdrant、Neo4j）::

    PYTHONPATH=. uv run python -m memory.test_consolidator
"""

from __future__ import annotations

import asyncio

from core.factory import create_llm
from memory.consolidator import MemoryConsolidator
from memory.factory import create_memory_manager
from observability import setup_log

# 模拟 ReAct 澄清/闲聊后一轮结束：信息多、实体多，便于观察提炼效果
USER_MESSAGE = """\
我叫陈艳，是法务部的，现在在上海总部办公。
我们团队在跟「合同项目A」和「供应商B公司」谈采购框架协议，下周三（3月15日）前要出一版审查意见。
我比较在意付款节点和违约责任，希望你之后帮我：回复尽量简洁、列要点时用编号。
另外不要把我司内部的报价金额写进对外邮件草稿里。"""

ASSISTANT_MESSAGE = """ """
# ASSISTANT_MESSAGE = """\
# 好的陈艳，已了解你的角色与场景，我按你的偏好来配合：

# 1. 你在上海总部、法务部，当前主线是「合同项目A」与供应商B公司的采购框架协议，截止日期是 3月15日（下周三）。
# 2. 你重点关注付款节点与违约责任；后续我会用简洁表述，并用编号列要点。
# 3. 涉及内部报价金额的内容，我不会写进对外邮件草稿。

# 接下来你可以把合同条款或草稿发我，我们从付款与违约章节开始审查。"""

# 抽查 recall 用的查询（可与对话主题不同，用于测向量/图检索）
RECALL_QUERY_HYBRID = "陈艳 合同项目A 付款 违约"
RECALL_QUERY_SEMANTIC = "回复风格 简洁 要点"
RECALL_QUERY_GRAPH = "陈艳"

NAMESPACE = "mem:tester_id:default"


async def main() -> None:
    setup_log()

    mem = create_memory_manager(namespace=NAMESPACE)
    llm = create_llm()
    consolidator = MemoryConsolidator(mem, llm)
    await mem.clear_all()
    print("--- 输入（一轮对话）---")
    print("用户:", USER_MESSAGE)
    print("助手:", ASSISTANT_MESSAGE)
    print()

    result = await consolidator.consolidate(
        user_message=USER_MESSAGE,
        assistant_message=ASSISTANT_MESSAGE,
        session_id=NAMESPACE,
    )

    print("--- 提炼结果 ---")
    print("skipped:", result.skipped)
    if result.error:
        print("error:", result.error)
    print("episodic:", result.episodic_written)
    print("semantic:", result.semantic_written)
    print("relations:", result.relations_written)
    print("links:", result.links_written)
    print()

    if result.total_written == 0:
        print("（未写入长期记忆，可能模型返回空 JSON）")
        return

    print("--- recall 抽查 ---")
    hybrid = await mem.recall(query=RECALL_QUERY_HYBRID, mode="hybrid", top_k=5)
    print(f"hybrid ({RECALL_QUERY_HYBRID!r}):")
    for item in hybrid.items or []:
        kind = "episodic" if item.__class__.__name__ == "EpisodicItem" else "semantic"
        print(f"  - [{kind}] {item.content}")

    sem = await mem.recall(memory_type="semantic", query=RECALL_QUERY_SEMANTIC, top_k=5)
    print(f"semantic ({RECALL_QUERY_SEMANTIC!r}):")
    for item in sem.items or []:
        print(f"  - {item.content}")

    graph = await mem.recall(
        memory_type="associative", query=RECALL_QUERY_GRAPH, top_k=10
    )
    g = graph.graph
    if g and g.seed:
        print("图种子:", g.seed.name)
        print("邻域:", [e.name for e in g.entities])
        print(
            "关系:",
            [f"{r.from_name}-[{r.relation_label}]->{r.to_name}" for r in g.relations],
        )


if __name__ == "__main__":
    asyncio.run(main())
