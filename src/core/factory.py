"""根据配置创建具体 LLM 实例（调用方显式传参，不读 OPENAI_* 环境变量）。"""

from observability import log
from .llm import LLM
from .provider import LLMProvider


def _with_thinking_params(params: dict | None, *, enable_thinking: bool) -> dict:
    merged = dict(params or {})
    if not enable_thinking:
        return merged
    extra = dict(merged.get("extra_body") or {})
    extra.setdefault("enable_thinking", True)
    merged["extra_body"] = extra
    return merged


def create_llm(
    provider: str = "openai",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    params: dict | None = None,
    *,
    enable_thinking: bool = False,
) -> LLMProvider:

    provider = provider.lower()
    key = (api_key or "").strip()
    if not key:
        log("create_llm failed", provider=provider, reason="api_key not provided")
        raise ValueError(
            "create_llm requires api_key=... "
            "(pass HubloomConfig.openai_api_key or request context)"
        )
    api_key = key
    merged_params = _with_thinking_params(params, enable_thinking=enable_thinking)
    if provider == "openai":
        llm = LLM(
            api_key=api_key,
            base_url=base_url,
            model=model,
            params=merged_params,
        )
        log(
            "create_llm ok",
            provider=provider,
            model=model,
            base_url=base_url or "(default)",
            enable_thinking=enable_thinking,
        )
        return llm
    # 未来可在此扩展其他 provider
    log("create_llm failed", provider=provider, reason="unsupported provider")
    raise ValueError(f"Unsupported LLM provider: {provider}")
