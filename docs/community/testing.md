# 测试计划

目标：用分层测试证明「换 Swagger 能办事、多入口行为一致、并发与幂等正确」。本地演示前端仅联调；生产路径以 **BFF → Serve** 为准。

## A. 冒烟（CI / 无真 LLM）

| 场景 | 命令 / 入口 | 期望 |
|------|-------------|------|
| Serve 路由与 SSE | `pytest tests/test_hubloom_serve.py` | chat / resume / health |
| Events + 企微挂载 | `pytest tests/test_hubloom_serve_events_wecom.py` | 幂等、503 开关、回调 ACK |
| 会话存储工厂 | `pytest tests/test_conversation_store_factory.py` | sqlite / postgres 配置选择 |
| Agent 内核步进 | `pytest tests/test_agent_v2_*.py` | Decide / Gate / Wait / Journal |
| Runtime 装配任务 | `python tests/test_runtime_agent_assembly.py` | 完整加宠故事（ScriptedLLM） |

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_hubloom_serve.py \
  tests/test_hubloom_serve_events_wecom.py \
  tests/test_conversation_store_factory.py \
  tests/test_agent_v2_step1.py \
  tests/test_agent_v2_step2.py \
  tests/test_agent_v2_step3.py \
  tests/test_agent_v2_step4.py \
  tests/test_agent_v2_flow.py -q
```

## B. 不同业务 Swagger（真 MCP）

换 `mcp.swagger_url` / `base_url`（及按需 Bearer），验证「契约即能力」：

| 场景 | 做法 | 关注点 |
|------|------|--------|
| Petstore 等公开样例 | 默认 / 示例 swagger | `list_api` / `call_api`、SSE 工具事件 |
| 企业内部 OpenAPI | 换真实 swagger + Token | 鉴权透传、错误码、分页/过滤 |
| 多分组大规格 | 复杂 tag / 路径 | catalog 加载、工具选择、超时 |
| 规格变更回归 | 同一 Skill，换版本 swagger | Playbook 是否仍拦得住违规动作 |

辅助脚本：`tests/test_mcp_list_tools.py`、`tests/test_mcp_serve_swagger.py`；端到端对话：`tests/test_hubloom_serve_chat_task.py`（需已启动 Serve + 真 LLM）。

## C. 事件（Events）

| 场景 | 命令 / 入口 | 期望 |
|------|-------------|------|
| 调度层幂等 / 串行 | `python tests/test_events.py`（需 Redis） | 同 `event_id` 不双跑；同 session 串行 |
| HTTP 真链路 | Serve + `POST /v1/events` | 返回 `ok` / `summary`；历史可查 |
| 类型覆盖 | `locker.created` / `locker.offline` / `order.refund` 等 | 分册字段校验、触发文正确 |
| 无人值守 | `no_wait` | 误 `ask` 不挂死会话 |
| 密钥 | 配 / 不配 `shared_secret` | 401 vs 放行 |

## D. 企业微信（IM）

| 场景 | 命令 / 入口 | 期望 |
|------|-------------|------|
| 出站推送 | `python tests/test_im_wecom.py send --to <UserId>` | 手机收到 text |
| 回调管道 | `python tests/test_im_wecom.py echo` + 公网隧道 | GET 验 URL；POST 收信并回声 |
| Redis 队列 | `python tests/test_im_wecom.py queue` | 同 session FIFO、MsgId 去重 |
| 正式 Serve | 后台 URL → Serve 回调 | ACK 快、异步 Agent、短回复截断 |
| Web 一致 | 同一 `wecom:{UserId}` 查 history | 企微短、网页可看全文 |

## E. 并发与稳定性

| 场景 | 做法 | 期望 |
|------|------|------|
| 同 session 多入口 | chat + events（同 `session_id`）交错 | Redis session 锁，历史不乱序撕裂 |
| 同 session 多事件 | 并发 `POST /v1/events` | 串行执行、结果可复现 |
| 多 session 并行 | 多 `session_id` 同时 chat | 吞吐上来、互不堵死 |
| 挂起续跑 | interactive ask → resume | await_token 校验、无串台 |
| 存储后端 | sqlite ↔ postgres 切换 | 历史读写一致；Postgres 自动建库/表 |
| 故障注入 | Redis 短暂不可用、错误 Bearer、工具 4xx/5xx | 可恢复错误有提示；幂等键不丢 |

## F. 记忆 / RAG / Skill（按需）

| 场景 | 入口 | 期望 |
|------|------|------|
| 会话 remember/recall | `tests/test_memory_conversation.py` | 工具消息可回放 |
| Postgres 连通 | `tests/test_conversation_postgres_connect.py` | 读写 `conversation_memory` |
| 长期记忆 | `tests/test_memory_longterm.py` | Qdrant / Neo4j（需 enable） |
| RAG | `tests/test_retrieval.py` | 文档检索 |
| Skill 加载 | `tests/test_skill.py` | 卡片进提示、`read_skill` |

## G. 高强度复杂问题（建议清单）

人工 / 脚本构造，优先覆盖：

- [ ] 多轮追问 + 确认 + 真实写操作（含 Gate 打回）
- [ ] 工具失败重试、部分成功、空结果
- [ ] 长对话历史裁剪后仍能办完事
- [ ] Events 重放与并发同 session
- [ ] 企微短回复 vs Web 长历史一致性
- [ ] `thought_delta` 与最终答案是否冗余刷屏
- [ ] 换业务域 swagger 后旧 Skill/Playbook 是否仍成立
