import os
from dotenv import load_dotenv
from .llm import LLM
from .provider import LLMProvider

load_dotenv()


def create_llm(
    provider: str = "openai",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    params: dict | None = None,
) -> LLMProvider:

    provider = provider.lower()
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set")
    base_url = base_url or os.getenv("OPENAI_BASE_URL")
    model = model or os.getenv("OPENAI_MODEL")
    params = params or {}
    if provider == "openai":
        return LLM(
            api_key=api_key,
            base_url=base_url,
            model=model,
            params=params,
        )
    # 未来可在此扩展其他 provider
    raise ValueError(f"Unsupported LLM provider: {provider}")


if __name__ == "__main__":
    from .models import Message, Role
    from .provider import (
        DeltaEvent,
        StreamEndEvent,
        StreamErrorEvent,
        ToolCallArgsEvent,
        ToolCallStartEvent,
    )
    import asyncio

    async def main():
        llm = create_llm()
        messages = [
            Message(role=Role.USER, content="你好啊?"),
        ]
        print("--- 流式输出 ---")
        async for event in llm.generate_stream(messages):
            if isinstance(event, DeltaEvent):
                print(event.delta, end="", flush=True)
            elif isinstance(event, ToolCallStartEvent):
                print(f"\n[tool_start] id={event.call_id} name={event.name}")
            elif isinstance(event, ToolCallArgsEvent):
                print(f"[tool_args] id={event.call_id} {event.args_delta}", end="")
            elif isinstance(event, StreamEndEvent):
                out = event.output
                print("\n--- 流结束 ---")
                print(f"content: {out.content!r}")
                print(f"stop_reason: {out.stop_reason}")
                if out.tool_calls:
                    print(f"tool_calls: {out.tool_calls}")
                if out.usage:
                    print(
                        f"usage: prompt={out.usage.prompt_tokens} "
                        f"completion={out.usage.completion_tokens} "
                        f"total={out.usage.total_tokens}"
                    )
            elif isinstance(event, StreamErrorEvent):
                print(f"\n[error] {type(event.error).__name__}: {event.error}")
            else:
                print(f"\n[unknown] {event!r}")

    asyncio.run(main())
