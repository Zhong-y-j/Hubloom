# 酒店预定 Mock 系统

SQLite 存储的独立酒店预订 API，用于 Hubloom 差旅演示案例。

## 启动

### 方式一：一键脚本（推荐）

在 **Hubloom 项目根目录** 执行：

```bash
./examples/travel/scripts/start-hotel-demo.sh
```

停止：

```bash
./examples/travel/scripts/stop-hotel-demo.sh
```

脚本会依次启动：
1. 酒店 mock（`9001`，先提供 `/openapi.json`）
2. Hubloom（`8001`，会话库 `data/memory-hotel.db`）
3. 向 Hubloom 注册酒店 OpenAPI

打开：**http://127.0.0.1:9001/login**

### 方式二：两个终端手动启动

**终端 1 — 酒店（先启动）：**
```bash
HUBLOOM_BASE_URL=http://127.0.0.1:8001 HOTEL_PUBLIC_URL=http://127.0.0.1:9001 PYTHONPATH=. uv run python -m examples.travel.mocks.hotel
```

**终端 2 — Hubloom：**
```bash
CORTEX_API_PORT=8001 CORTEX_MEMORY_DB=data/memory-hotel.db PYTHONPATH=. uv run python -m examples.chat.app
```

- 服务地址：http://127.0.0.1:9001
- 登录页：http://127.0.0.1:9001/ 或 http://127.0.0.1:9001/login
- 聊天页：http://127.0.0.1:9001/chat（需先登录）
- OpenAPI 文档：http://127.0.0.1:9001/docs
- 数据库：`data/hotel.db`（首次启动自动建表并种子化）

联调 Hubloom 助手时，**先启酒店、再启 Hubloom**（默认 `http://127.0.0.1:8001`）。Hubloom 就绪后酒店会在后台重试注册 OpenAPI；聊天页进入后也会自动同步配置。

可选环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `HUBLOOM_BASE_URL` | `http://127.0.0.1:8001` | Hubloom 基址 |
| `HOTEL_PUBLIC_URL` | `http://127.0.0.1:9001` | 酒店对外基址（写入 Swagger） |

## Hubloom 代理（BFF）

前端通过酒店同源接口转发到 Hubloom，避免跨域：

| 酒店接口 | 转发到 |
|----------|--------|
| `POST /hubloom/config/apply` | `POST {HUBLOOM}/v1/config/apply` |
| `POST /hubloom/chat` | `POST {HUBLOOM}/v1/chat`（SSE 透传） |
| `GET /hubloom/chat/history` | `GET {HUBLOOM}/v1/chat/history` |

请求头会透传：`X-OpenAI-*`、`X-MCP-*`、`X-Session-Id`、`Authorization` 等。

## 演示账号

| 项     | 值                  |
| ------ | ------------------- |
| 用户名 | `HubloomHotel`      |
| 密码   | `HubloomHotel@2026` |
| Token  | `demo-hotel-token`  |

除 `POST /auth/login` 外，业务接口需在 Header 携带：

```http
Authorization: Bearer demo-hotel-token
```

## 种子订单

- 订单：`HTL-889`
- 行程：`TRIP-5566`
- 入住人：`张三`（非登录账号名，是订单旅客）
- 酒店：`HOTEL-BJ-01` 北京王府井商务酒店

## 接口一览（18 个业务 + 登录）

### auth

| 方法 | 路径          |
| ---- | ------------- |
| POST | `/auth/login` |

### hotel

| 方法 | 路径                            |
| ---- | ------------------------------- |
| GET  | `/hotels`                       |
| GET  | `/hotels/search`                |
| GET  | `/hotels/{hotel_id}`            |
| GET  | `/hotels/{hotel_id}/facilities` |
| GET  | `/hotels/{hotel_id}/policies`   |
| GET  | `/hotels/{hotel_id}/reviews`    |

### room

| 方法 | 路径                              |
| ---- | --------------------------------- |
| GET  | `/hotels/{hotel_id}/room-types`   |
| GET  | `/room-types/{room_type_id}`      |
| GET  | `/hotels/{hotel_id}/availability` |

### booking

| 方法  | 路径                                     |
| ----- | ---------------------------------------- |
| POST  | `/bookings/quote`                        |
| POST  | `/bookings`                              |
| GET   | `/bookings`                              |
| GET   | `/bookings/by-trip/{trip_id}`            |
| GET   | `/bookings/{booking_id}`                 |
| GET   | `/bookings/{booking_id}/price-breakdown` |
| PATCH | `/bookings/{booking_id}/guest-info`      |
| POST  | `/bookings/{booking_id}/cancel`          |

### user

| 方法 | 路径                        |
| ---- | --------------------------- |
| GET  | `/users/me`                 |
| GET  | `/users/me/booking-summary` |

## 快速验证

```bash
curl http://127.0.0.1:9001/health

curl -X POST http://127.0.0.1:9001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"HubloomHotel","password":"HubloomHotel@2026"}'

curl http://127.0.0.1:9001/bookings/by-trip/TRIP-5566 \
  -H "Authorization: Bearer demo-hotel-token"
```
