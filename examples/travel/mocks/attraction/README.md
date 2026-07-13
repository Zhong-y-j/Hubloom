# 景区门票 Mock 系统

SQLite 存储的独立景区门票预约 API，用于 Hubloom 差旅演示案例（计划由 A2 景点 Agent 承接）。

## 启动

### 方式一：一键脚本（推荐）

在 **Hubloom 项目根目录** 执行：

```bash
./examples/travel/scripts/start-attraction-demo.sh
```

停止：

```bash
./examples/travel/scripts/stop-attraction-demo.sh
```

脚本会依次启动：
1. 景点 mock（`9004`，先提供 `/openapi.json`）
2. Hubloom A2（`8004`，会话库 `data/memory-attraction.db`）
3. 向 Hubloom 注册景点 OpenAPI

打开：**http://127.0.0.1:9004/login**

### 方式二：仅 API（无聊天 UI）

```bash
# 在 Hubloom 项目根目录
PYTHONPATH=. uv run python -m examples.travel.mocks.attraction
```

### 方式三：两个终端手动联调

**终端 1 — 景点（先启动）：**
```bash
HUBLOOM_BASE_URL=http://127.0.0.1:8004 ATTRACTION_PUBLIC_URL=http://127.0.0.1:9004 PYTHONPATH=. uv run python -m examples.travel.mocks.attraction
```

**终端 2 — Hubloom：**
```bash
CORTEX_API_PORT=8004 CORTEX_MEMORY_DB=data/memory-attraction.db PYTHONPATH=. uv run python -m agents.api.app
```

- 服务地址：http://127.0.0.1:9004
- 登录页：http://127.0.0.1:9004/ 或 http://127.0.0.1:9004/login
- 聊天页：http://127.0.0.1:9004/chat（需先登录）
- OpenAPI 文档：http://127.0.0.1:9004/docs
- 数据库：`data/attraction.db`（首次启动自动建表并种子化）

联调 Hubloom 助手时，**先启景点、再启 Hubloom**（默认 `http://127.0.0.1:8004`）。

可选环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `HUBLOOM_BASE_URL` | `http://127.0.0.1:8004` | Hubloom 基址 |
| `ATTRACTION_PUBLIC_URL` | `http://127.0.0.1:9004` | 景点对外基址（写入 Swagger） |

## Hubloom 代理（BFF）

前端通过景点同源接口转发到 Hubloom：

| 景点接口 | 转发到 |
|----------|--------|
| `POST /hubloom/config/apply` | `POST {HUBLOOM}/v1/config/apply` |
| `POST /hubloom/chat` | `POST {HUBLOOM}/v1/chat`（SSE 透传） |
| `GET /hubloom/chat/history` | `GET {HUBLOOM}/v1/chat/history` |

## 演示账号

| 项 | 值 |
|----|-----|
| 用户名 | `HubloomAttraction` |
| 密码 | `HubloomAttraction@2026` |
| Token | `demo-attraction-token` |

除 `POST /auth/login` 外，业务接口需在 Header 携带：

```http
Authorization: Bearer demo-attraction-token
```

## 种子门票

- 门票：`TKT-778`
- 景区：`ATTR-BJ-GUGONG` 故宫博物院
- 行程：`TRIP-5566`
- 游客：`张三`
- 参观日：`2026-07-14`
- 入园时段：`08:30-12:00`（上午场）
- 状态：`confirmed`

## 接口一览（18 个业务 + 登录）

### auth

| 方法 | 路径 |
|------|------|
| POST | `/auth/login` |

### attraction

| 方法 | 路径 |
|------|------|
| GET | `/attractions` |
| GET | `/attractions/search` |
| GET | `/attractions/{attraction_id}` |
| GET | `/attractions/{attraction_id}/policies` |

### ticket_type

| 方法 | 路径 |
|------|------|
| GET | `/attractions/{attraction_id}/ticket-types` |
| GET | `/ticket-types/{ticket_type_id}` |
| GET | `/attractions/{attraction_id}/availability` |

### ticket

| 方法 | 路径 |
|------|------|
| POST | `/tickets/quote` |
| POST | `/tickets` |
| GET | `/tickets` |
| GET | `/tickets/by-trip/{trip_id}` |
| GET | `/tickets/{ticket_id}` |
| GET | `/tickets/{ticket_id}/price-breakdown` |
| PATCH | `/tickets/{ticket_id}/visitor-info` |
| POST | `/tickets/{ticket_id}/cancel` |
| GET | `/tickets/{ticket_id}/timeline` |

### user

| 方法 | 路径 |
|------|------|
| GET | `/users/me` |
| GET | `/users/me/ticket-summary` |

## 快速验证

```bash
curl http://127.0.0.1:9004/health

curl http://127.0.0.1:9004/tickets/by-trip/TRIP-5566 \
  -H "Authorization: Bearer demo-attraction-token"

curl http://127.0.0.1:9004/attractions/ATTR-BJ-GUGONG/policies
```
