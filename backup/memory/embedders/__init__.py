from .base import Embedder

__all__ = ["Embedder"]

# OpenAIEmbedder 依赖 openai 包；允许在未安装 openai 时仍可使用本地/自定义 embedder。
try:
    from .openai_embedder import OpenAIEmbedder  # type: ignore

    __all__.append("OpenAIEmbedder")
except Exception:
    OpenAIEmbedder = None  # type: ignore

