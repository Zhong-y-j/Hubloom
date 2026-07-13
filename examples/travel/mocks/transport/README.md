# 交通通行 Mock 系统（高铁/动车）

SQLite 存储的独立高铁出行 API，用于 Hubloom 差旅演示案例。

## 启动

```bash
# 在 Hubloom 项目根目录
PYTHONPATH=. uv run python -m examples.travel.mocks.transport
```

- 服务地址：http://127.0.0.1:8101
- OpenAPI 文档：http://127.0.0.1:8101/docs
- 数据库：`data/transport.db`（首次启动自动建表并种子化）

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
curl http://127.0.0.1:8101/health

curl "http://127.0.0.1:8101/trains/G1234/status?date=2026-07-13"

curl http://127.0.0.1:8101/trips/TRIP-5566 \
  -H "Authorization: Bearer demo-transport-token"
```
