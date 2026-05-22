import re
from typing import List, Literal
from core.provider import LLMProvider
from core.models import Message, Role


class QueryOptimizer:
    """查询优化器，通过 LLM 改写查询来提升 RAG 检索质量。

    支持两种策略：
        - MQE（多查询扩展）：将单个查询改写为多个语义变体，并行检索合并
        - HyDE（假设文档嵌入）：先生成假设答案，用答案去检索文档
    """

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def optimize(
        self, query: str, strategy: Literal["mqe", "hyde"] = "hyde"
    ) -> str | List[str]:
        """优化查询入口。

        Args:
            query: 原始用户查询
            strategy: 优化策略

        Returns:
            - HyDE: 返回假设文档文本（str）
            - MQE: 返回多个查询变体（List[str]）
        """
        if strategy == "mqe":
            return await self._mqe(query)
        elif strategy == "hyde":
            return await self._hyde(query)
        else:
            # 不优化，直接返回原查询
            return query

    async def _mqe(self, query: str, num_variants: int = 3) -> List[str]:
        """多查询扩展：生成多个语义等价但表述不同的查询。

        Args:
            query: 原始查询
            num_variants: 生成的变体数量

        Returns:
            查询变体列表（包含原始查询）
        """
        prompt = (
            f"请为以下查询生成 {num_variants} 个语义相同但表述不同的变体，"
            f"每个变体用换行分隔，不要编号，不要解释。\n"
            f"查询：{query}\n"
            f"变体："
        )

        try:
            response = await self.llm.generate(
                messages=[Message(role=Role.USER, content=prompt)]
            )
            raw_text = (response.content or "").strip()

            # 按换行分割，去除空行和首尾空白
            variants = [line.strip() for line in raw_text.split("\n") if line.strip()]

            # 如果生成失败或数量不足，回退到原始查询
            if not variants:
                return [query]

            # 限制数量并保证包含原始查询
            variants = variants[:num_variants]
            if query not in variants:
                variants.insert(0, query)

            return variants

        except Exception:
            # LLM 调用失败时，只返回原始查询
            return [query]

    async def _hyde(self, query: str) -> str:
        """假设文档嵌入：生成一个可能回答问题的假设文档片段。

        Args:
            query: 原始查询

        Returns:
            假设文档文本
        """
        prompt = (
            "请根据以下问题，撰写一个可能出现在文档中的段落，用来代表该问题的答案。"
            "段落应包含相关的细节和术语，风格类似于百科全书或技术文档。"
            "直接返回段落内容，不要加任何前缀或解释。\n"
            f"问题：{query}\n"
            f"段落："
        )

        try:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}]
            )
            hyde_text = (response.content or "").strip()

            # 如果生成失败，回退到原查询
            if not hyde_text:
                return query

            return hyde_text

        except Exception:
            # LLM 调用失败时，返回原查询
            return query


if __name__ == "__main__":
    import asyncio
    from agents.core import create_llm

    async def main():
        optimizer = QueryOptimizer(create_llm())
        result = await optimizer.optimize("当前电商行业趋势怎么样", strategy="mqe")
        print(result)

    asyncio.run(main())
