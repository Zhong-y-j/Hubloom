# 差旅出行演示案例

Hubloom 跨系统编排演示：交通通行、酒店预定、旅行景点三个独立业务系统，经 MCP 与 A2A 协同完成「行程延误后的冲突诊断」。

本目录仅包含演示用的 mock 系统与联调配置，**不修改** Hubloom 核心代码（`agents/`、`mcp_adapter/` 等）。

---

## 业务场景

**主演示话术：**

> 旅客张三的行程 `TRIP-5566` 原计划明天到故宫，但高铁 `G1234` 延误了 3 小时。帮我看看交通、酒店入住和故宫门票预约现在分别什么状态，明天还能按计划游玩吗？

**预期链路：**

1. 用户在任一系统聊天页提问 → 本系统 Hubloom 路由到 Thought
2. 本地 MCP → 查本系统 API（交通 / 酒店 / 景点）
3. A2A `delegate_task` → 委托另外两个 Hubloom Agent
4. 对方 Agent 经各自 MCP 查询后返回
5. 入口 Agent 汇总：能否按计划游玩 + 原因 + 建议

**备用单系统话术（证明各系统可独立查询）：**

- 「张三有哪些进行中的行程？」→ 仅交通系统
- 「行程 TRIP-5566 关联的酒店预订状态？」→ 仅酒店系统

---

## 系统分工

| 系统 | 目录 | 职责 | Hubloom 接入方式 |
|------|------|------|------------------|
| 交通通行 | `mocks/transport/` | 行程、高铁/航班状态 | 独立 Hubloom（8003）+ 本地 MCP |
| 酒店预定 | `mocks/hotel/` | 预订、入住政策 | 独立 Hubloom（8001）+ 本地 MCP |
| 旅行景点 | `mocks/attraction/` | 门票预约、改期政策 | 独立 Hubloom（8004）+ 本地 MCP |

三个系统**逻辑与代码分治**；各 Hubloom 经 **A2A 三向互连**（每个实例出站指向另外两个），可从任一聊天页发起跨系统编排。联调时还可经 `gateway/` 聚合为统一 MCP 入口（贴近企业 API 网关）。

### 一键启动（跨系统 + A2A）

在 **Hubloom 项目根目录** 执行：

```bash
./examples/travel/scripts/start-travel-demo.sh
```

停止：

```bash
./examples/travel/scripts/stop-travel-demo.sh
```

按 **交通 → 景点 → 酒店** 顺序启动；三个 Hubloom（8001 / 8003 / 8004）**A2A 互连**，可从任一聊天页做跨系统演示：

- 交通 http://127.0.0.1:9003/chat
- 景点 http://127.0.0.1:9004/chat
- 酒店 http://127.0.0.1:9001/chat

### 单系统演示

| 系统 | 启动脚本 | 登录页 | Hubloom 端口 |
|------|----------|--------|--------------|
| 酒店 | `./examples/travel/scripts/start-hotel-demo.sh` | http://127.0.0.1:9001/login | 8001 |
| 交通 | `./examples/travel/scripts/start-transport-demo.sh` | http://127.0.0.1:9003/login | 8003 |
| 景点 | `./examples/travel/scripts/start-attraction-demo.sh` | http://127.0.0.1:9004/login | 8004 |

三个演示可独立运行；**跨系统编排**需另外两个 Hubloom 也已启动。停止脚本分别为 `stop-hotel-demo.sh`、`stop-transport-demo.sh`、`stop-attraction-demo.sh`。

---

## 端口规划

| 进程 | 端口 | 说明 |
|------|------|------|
| travel-gateway | 8100 | MCP 聚合入口 |
| transport-api（可选独立调试） | 9003 | 仅开发单测 |
| hotel-api（可选独立调试） | 9001 | 仅开发单测 |
| attraction-api（可选独立调试） | 9004 | 仅开发单测 |
| Hubloom 酒店 | 8001 | 酒店演示专用 Hubloom |
| Hubloom 交通 | 8003 | 交通演示专用 Hubloom |
| Hubloom 景点 | 8004 | 景点演示专用 Hubloom |

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
- [x] **Step 3a**：酒店 mock 系统（SQLite + 18 业务接口 + 登录 + UI/联调）→ 见 [`mocks/hotel/README.md`](./mocks/hotel/README.md)
- [x] **Step 3b**：交通 mock 系统（高铁/动车，SQLite + 18 业务接口 + 登录 + UI/联调）→ 见 [`mocks/transport/README.md`](./mocks/transport/README.md)
- [x] **Step 3c**：景区 mock 系统（SQLite + 18 业务接口 + 登录 + UI/联调）→ 见 [`mocks/attraction/README.md`](./mocks/attraction/README.md)
- [ ] **Step 4**：gateway 聚合 + OpenAPI spec
- [ ] **Step 5**：`env/` 与三系统联调脚本（单系统演示脚本已完成）
- [ ] **Step 6**：双 Hubloom 实例端到端演示

---

## 关联文档

- [Hubloom 总体架构图](../../docs/Hubloom总体架构图.md)
- [A2A 互联](../../docs/Hubloom-A2A互联.md)
- [MCP 适配层](../../docs/Hubloom-MCP适配.md)
