# 景区门票 Mock 系统

SQLite 存储的独立景区门票预约 API，用于 Hubloom 差旅演示案例（计划由 A2 景点 Agent 承接）。

## 启动

```bash
# 在 Hubloom 项目根目录
PYTHONPATH=. uv run python -m examples.travel.mocks.attraction
```

- 服务地址：http://127.0.0.1:8103
- OpenAPI 文档：http://127.0.0.1:8103/docs
- 数据库：`data/attraction.db`（首次启动自动建表并种子化）

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
curl http://127.0.0.1:8103/health

curl http://127.0.0.1:8103/tickets/by-trip/TRIP-5566 \
  -H "Authorization: Bearer demo-attraction-token"

curl http://127.0.0.1:8103/attractions/ATTR-BJ-GUGONG/policies
```
