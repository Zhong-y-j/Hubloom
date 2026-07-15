"""最简 A2A Server：名片 + 执行器 + HTTP 路由。

运行：
  uv run python -m a2a_adapter.simple_server

另开终端测 Client：
  uv run python -m a2a_adapter.simple_client
"""

from __future__ import annotations

import uvicorn
from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    TaskState,
)
from starlette.applications import Starlette

HOST = "127.0.0.1"
PORT = 9000
BASE_URL = f"http://{HOST}:{PORT}"


class HelloExecutor(AgentExecutor):
    """真正干活的地方：收到 Message → 回一句 Hello。"""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # 1. 拿到 / 创建 Task
        task = context.current_task or new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task.id,
            context_id=task.context_id,
        )

        # 2. 标记进行中
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Processing…"),
        )

        # 3. 读用户文本，生成回复（这里故意极简，不接 LLM）
        query = get_message_text(context.message) or "(empty)"
        reply = f"Hello, World! I received: {query}"

        # 4. 写入产物，标记完成
        await updater.add_artifact(
            parts=[new_text_part(text=reply, media_type="text/plain")]
        )
        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("Done."),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel not supported")


def build_app() -> Starlette:
    # ① Agent Card：对外名片（Client 会先拉这个）
    skill = AgentSkill(
        id="hello",
        name="Hello",
        description="Returns a hello reply.",
        input_modes=["text/plain"],
        output_modes=["text/plain"],
        tags=["demo"],
        examples=["Say hello."],
    )
    card = AgentCard(
        name="Hubloom Simple Hello Agent",
        description="Minimal A2A server for learning.",
        version="0.0.1",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=BASE_URL,
                protocol_version="1.0",
            )
        ],
        skills=[skill],
    )

    # ② RequestHandler：把协议请求转到 Executor，并管理 Task 状态
    handler = DefaultRequestHandler(
        agent_executor=HelloExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    # ③ 路由：Card 发现 + JSON-RPC 协议端点
    routes = [
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, "/"),
    ]
    return Starlette(routes=routes)


if __name__ == "__main__":
    print(f"A2A Server listening on {BASE_URL}")
    print(f"Agent Card: {BASE_URL}/.well-known/agent-card.json")
    uvicorn.run(build_app(), host=HOST, port=PORT)
