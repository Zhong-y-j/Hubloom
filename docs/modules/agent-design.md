# Agent 重构设计备忘（暂定）

> 状态：**过程备忘**（走向 ReAct、去掉 A2UI 的共识）。  
> **最终落地架构以 [Agent 最终架构：Policy-Bounded Typed ReAct](agent-architecture.md) 为准。**

---

## 1. 产品定位（业务）

Hubloom 的 Agent 不是陪聊，也不是 UI 引擎，而是：

> **在给定会话与鉴权下，分析用户（或事件）要办的事 → 通过工具真正执行 → 基于思考与工具结果给出可读总结。**

业务上永远是这三步；实现上**不再**拆成多套「对用户说话」的模型角色。

入口（网页 / 企微 / Events）可换，**同一条 Agent**；业务真相在企业 API（及可选 A2A 对端），不在 Hubloom 核心里重写业务。

---

## 2. 架构选择：从碎相位收到 ReAct 主轴

### 共识

- 去掉 A2UI / Present / 默认双通道 Respond。  
- A2A 也是 Tool（行动）。  
- 终稿「够用」：环内根据思考与工具结果总结即可。  
- 对外好讲、好嵌：触发 → 事件流 → 最终文本。

### 已收敛

在「ReAct 主轴」之上，最终规格定为 **Policy-Bounded Typed ReAct**（类型化动作 + 规程硬拦 + 证据账本 + `ask` 跨 run 交班）。详见 [agent-architecture.md](agent-architecture.md)。

---

## 3. 相关文档

- 最终架构：[agent-architecture.md](agent-architecture.md)  
- 模块导读大纲：[agent.md](agent.md)
