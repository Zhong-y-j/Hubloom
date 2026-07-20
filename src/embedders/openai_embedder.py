from __future__ import annotations

from typing import Sequence

from openai import AsyncOpenAI

from .base import Embedder

_DEFAULT_EMBEDDING_MODEL = "text-embedding-v3"


class OpenAIEmbedder(Embedder):
    """OpenAI Embeddings：调用方显式传参，不读 OPENAI_* 环境变量。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise ValueError(
                "OpenAIEmbedder requires api_key=... "
                "(pass HubloomConfig.openai_api_key)"
            )
        resolved_model = (model or "").strip() or _DEFAULT_EMBEDDING_MODEL
        resolved_base = (base_url or "").strip() or None

        self._model = resolved_model
        self._client = AsyncOpenAI(api_key=key, base_url=resolved_base)

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # OpenAI embedding API 支持 batch；保持输入顺序输出
        cleaned: Sequence[str] = [str(t or "").strip() for t in texts]
        resp = await self._client.embeddings.create(model=self._model, input=cleaned)
        # resp.data[i].embedding 与 input 顺序一致
        return [list(item.embedding) for item in resp.data]
