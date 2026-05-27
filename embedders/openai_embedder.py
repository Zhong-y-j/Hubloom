from __future__ import annotations

import os
from typing import Sequence

from openai import AsyncOpenAI

from .base import Embedder
from dotenv import load_dotenv

load_dotenv()


class OpenAIEmbedder(Embedder):
    """OpenAI Embeddings 实现（方案 A）。

    依赖环境变量：
    - OPENAI_API_KEY（必需）
    - OPENAI_BASE_URL（可选，兼容自建网关/代理）
    - OPENAI_EMBEDDING_MODEL（可选，默认 text-embedding-3-small）
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIEmbedder")
        base_url = base_url or os.getenv("OPENAI_BASE_URL")
        model = model or os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-v3"

        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # OpenAI embedding API 支持 batch；保持输入顺序输出
        cleaned: Sequence[str] = [str(t or "").strip() for t in texts]
        resp = await self._client.embeddings.create(model=self._model, input=cleaned)
        # resp.data[i].embedding 与 input 顺序一致
        return [list(item.embedding) for item in resp.data]
