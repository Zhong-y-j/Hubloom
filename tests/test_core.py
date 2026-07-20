from observability import setup_log

setup_log()  # 仅写 logs/agentcortex.log，不在终端打 log

from core.models import Message, Role
from core.provider import (
    DeltaEvent,
    ReasoningDeltaEvent,
    StreamEndEvent,
    StreamErrorEvent,
    ToolCallArgsEvent,
    ToolCallStartEvent,
)
from core.factory import create_llm


async def main():
    from config import HubloomConfig

    cfg = HubloomConfig.from_file("config/env.yaml")
    llm = create_llm(
        api_key=cfg.openai_api_key,
        model=cfg.openai_model,
        base_url=cfg.openai_base_url,
    )
    messages = [
        Message(role=Role.USER, content="你好啊?"),
    ]
    print("--- 流式输出 ---")
    thinking_started = False
    content_started = False
    async for event in llm.generate_stream(messages):
        if isinstance(event, ReasoningDeltaEvent):
            if not thinking_started:
                print("\n[thinking] ", end="", flush=True)
                thinking_started = True
            print(event.delta, end="", flush=True)
        elif isinstance(event, DeltaEvent):
            if not content_started:
                print("\n[content] ", end="", flush=True)
                content_started = True
            print(event.delta, end="", flush=True)
        elif isinstance(event, ToolCallStartEvent):
            print(f"\n[tool_start] id={event.call_id} name={event.name}")
        elif isinstance(event, ToolCallArgsEvent):
            print(f"[tool_args] id={event.call_id} {event.args_delta}", end="")
        elif isinstance(event, StreamEndEvent):
            out = event.output
            print("\n--- 流结束 ---")
            if out.thinking:
                print(f"thinking: {out.thinking!r}")
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


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
