# 差旅出行演示案例

Hubloom 跨系统编排演示：交通通行、酒店预定、旅行景点三个独立业务系统，经 MCP 与 A2A 协同完成「行程延误后的冲突诊断」。

本目录仅包含演示用的 mock 系统与联调配置，**不修改** Hubloom 核心代码（`agents/`、`mcp_adapter/` 等）。

---

## 业务场景

**主演示话术：**

> 旅客张三的行程 `TRIP-5566` 原计划明天到故宫，但高铁 `G1234` 延误了 3 小时。帮我看看交通、酒店入住和故宫门票预约现在分别什么状态，明天还能按计划游玩吗？

**预期链路：**

1. Hubloom A1（行程协调）→ Assessor 路由到 Thought
2. MCP `transport` → 查高铁延误与预计到达时间
3. MCP `hotel` → 查酒店预订与入住冲突
4. A2A `delegate_task` → Hubloom A2（景点服务 Agent）
5. MCP `attraction` → 查故宫门票预约是否仍有效
6. A1 汇总：能否按计划游玩 + 原因 + 建议

**备用单系统话术（证明各系统可独立查询）：**

- 「张三有哪些进行中的行程？」→ 仅交通系统
- 「行程 TRIP-5566 关联的酒店预订状态？」→ 仅酒店系统

---

## 系统分工

| 系统 | 目录 | 职责 | Hubloom 接入方式 |
|------|------|------|------------------|
| 交通通行 | `mocks/transport/` | 行程、高铁/航班状态 | A1 MCP（tag: `transport`） |
| 酒店预定 | `mocks/hotel/` | 预订、入住政策 | A1 MCP（tag: `hotel`） |
| 旅行景点 | `mocks/attraction/` | 门票预约、改期政策 | A2 MCP（tag: `attraction`）+ A1 A2A 委托 |

三个系统**逻辑与代码分治**；联调时经 `gateway/` 聚合为统一 MCP 入口（贴近企业 API 网关）。

---

## 端口规划

| 进程 | 端口 | 说明 |
|------|------|------|
| travel-gateway | 8100 | MCP 聚合入口 |
| transport-api（可选独立调试） | 8101 | 仅开发单测 |
| hotel-api（可选独立调试） | 9001 | 仅开发单测 |
| attraction-api（可选独立调试） | 8103 | 仅开发单测 |
| Hubloom A1 | 8001 | 主 Web UI + 交通/酒店 MCP + A2A 出站 |
| Hubloom A2 | 8002 | 景点 Agent，承接 `delegate_task` |

---

## 目录结构

```
examples/travel/
  README.md           # 本文件
  seeds/              # 共享种子数据（如 trip-5566.json）
  specs/              # OpenAPI 规范（a1 / a2 两份）
  mocks/
    transport/        # 交通通行 mock
    hotel/            # 酒店预定 mock
    attraction/       # 旅行景点 mock
  gateway/            # 聚合入口（联调 MCP 用）
  env/                # A1 / A2 Hubloom 环境变量
  scripts/            # 启动 / 停止脚本
```

---

## 实施步骤（当前进度）

- [x] **Step 1**：创建目录骨架与本 README
- [ ] **Step 2**：编写种子数据 `seeds/trip-5566.json`（跨系统共享，待交通/景点完成后统一）
- [x] **Step 3a**：酒店 mock 系统（SQLite + 18 业务接口 + 登录）→ 见 [`mocks/hotel/README.md`](./mocks/hotel/README.md)
- [x] **Step 3b**：交通 mock 系统（高铁/动车，SQLite + 18 业务接口 + 登录）→ 见 [`mocks/transport/README.md`](./mocks/transport/README.md)
- [x] **Step 3c**：景区 mock 系统（SQLite + 18 业务接口 + 登录）→ 见 [`mocks/attraction/README.md`](./mocks/attraction/README.md)
- [ ] **Step 4**：gateway 聚合 + OpenAPI spec
- [ ] **Step 5**：`env/` 与 `scripts/` 联调脚本
- [ ] **Step 6**：双 Hubloom 实例端到端演示

---

## 关联文档

- [Hubloom 总体架构图](../../docs/Hubloom总体架构图.md)
- [A2A 互联](../../docs/Hubloom-A2A互联.md)
- [MCP 适配层](../../docs/Hubloom-MCP适配.md)
