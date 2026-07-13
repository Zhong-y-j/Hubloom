# 交通通行 Mock 系统（高铁/动车）

SQLite 存储的独立高铁出行 API，用于 Hubloom 差旅演示案例。

## 启动

### 方式一：一键脚本（推荐）

在 **Hubloom 项目根目录** 执行：

```bash
./examples/travel/scripts/start-transport-demo.sh
```

停止：

```bash
./examples/travel/scripts/stop-transport-demo.sh
```

脚本会依次启动：
1. 交通 mock（`9003`，先提供 `/openapi.json`）
2. Hubloom（`8003`，会话库 `data/memory-transport.db`）
3. 向 Hubloom 注册交通 OpenAPI

打开：**http://127.0.0.1:9003/login**

### 方式二：仅 API（无聊天 UI）

```bash
# 在 Hubloom 项目根目录
PYTHONPATH=. uv run python -m examples.travel.mocks.transport
```

### 方式三：两个终端手动联调

**终端 1 — 交通（先启动）：**
```bash
HUBLOOM_BASE_URL=http://127.0.0.1:8003 TRANSPORT_PUBLIC_URL=http://127.0.0.1:9003 PYTHONPATH=. uv run python -m examples.travel.mocks.transport
```

**终端 2 — Hubloom：**
```bash
CORTEX_API_PORT=8003 CORTEX_MEMORY_DB=data/memory-transport.db PYTHONPATH=. uv run python -m agents.api.app
```

- 服务地址：http://127.0.0.1:9003
- 登录页：http://127.0.0.1:9003/ 或 http://127.0.0.1:9003/login
- 聊天页：http://127.0.0.1:9003/chat（需先登录）
- OpenAPI 文档：http://127.0.0.1:9003/docs
- 数据库：`data/transport.db`（首次启动自动建表并种子化）

联调 Hubloom 助手时，**先启交通、再启 Hubloom**（默认 `http://127.0.0.1:8003`）。

可选环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `HUBLOOM_BASE_URL` | `http://127.0.0.1:8003` | Hubloom 基址 |
| `TRANSPORT_PUBLIC_URL` | `http://127.0.0.1:9003` | 交通对外基址（写入 Swagger） |

## Hubloom 代理（BFF）

前端通过交通同源接口转发到 Hubloom：

| 交通接口 | 转发到 |
|----------|--------|
| `POST /hubloom/config/apply` | `POST {HUBLOOM}/v1/config/apply` |
| `POST /hubloom/chat` | `POST {HUBLOOM}/v1/chat`（SSE 透传） |
| `GET /hubloom/chat/history` | `GET {HUBLOOM}/v1/chat/history` |

## 演示账号

| 项 | 值 |
|----|-----|
| 用户名 | `HubloomTransport` |
| 密码 | `HubloomTransport@2026` |
| Token | `demo-transport-token` |

除 `POST /auth/login` 外，业务接口需在 Header 携带：

```http
Authorization: Bearer demo-transport-token
```

## 种子行程

- 行程：`TRIP-5566`
- 车次：`G1234`（上海虹桥 → 北京南）
- 旅客：`张三`
- 运行日：`2026-07-13`
- 状态：`delayed`（延误 180 分钟，预计 22:00 到达北京南）

## 接口一览（18 个业务 + 登录）

### auth

| 方法 | 路径 |
|------|------|
| POST | `/auth/login` |

### station

| 方法 | 路径 |
|------|------|
| GET | `/stations` |
| GET | `/stations/search` |

### train

| 方法 | 路径 |
|------|------|
| GET | `/trains` |
| GET | `/trains/search` |
| GET | `/trains/{train_no}` |
| GET | `/trains/{train_no}/status` |
| GET | `/trains/{train_no}/seat-types` |
| GET | `/trains/{train_no}/availability` |

### trip

| 方法 | 路径 |
|------|------|
| POST | `/trips/quote` |
| POST | `/trips` |
| GET | `/trips` |
| GET | `/trips/{trip_id}` |
| GET | `/trips/{trip_id}/price-breakdown` |
| PATCH | `/trips/{trip_id}/passenger-info` |
| POST | `/trips/{trip_id}/cancel` |
| GET | `/trips/{trip_id}/timeline` |

### user

| 方法 | 路径 |
|------|------|
| GET | `/users/me` |
| GET | `/users/me/trip-summary` |

## 快速验证

```bash
curl http://127.0.0.1:9003/health

curl "http://127.0.0.1:9003/trains/G1234/status?date=2026-07-13"

curl http://127.0.0.1:9003/trips/TRIP-5566 \
  -H "Authorization: Bearer demo-transport-token"
```
