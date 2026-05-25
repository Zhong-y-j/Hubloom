# `agents/` 目录结构

灵枢业务 Agent 层，按阶段分子包；**项目主入口**为仓库根目录 [`main.py`](../main.py)。

```
agents/
├── __init__.py          # 对外统一导出（from agents import CortexHub, …）
├── README.md
├── core/                # 共享协议
│   ├── base.py          # Agent 基类
│   ├── events.py        # 流式事件（含 HubPhase / HubTurnComplete）
│   └── intent.py        # StructuredIntent 与解析
├── react/               # 阶段 1：意图澄清
│   └── agent.py         # ReActAgent
├── plan/                # 阶段 2：规划与执行
│   ├── execute.py       # PlanExecuteAgent、LLMPlanGenerator
│   └── models.py        # ExecutionPlan / ExecutionResult
├── reflection/          # 阶段 3：质量审查
│   ├── agent.py         # ReflectionAgent
│   └── models.py        # ReflectionVerdict
├── hub/                 # 中枢编排
│   ├── hub.py           # CortexHub
│   ├── models.py        # 路由常量、HubTurnOutcome
│   └── registry.py      # build_default_registry()
├── specialists/         # Plan 步级专业 Agent（legal / programming）
├── app/                 # 运行时组装
│   └── bootstrap.py     # build_hub() 依赖注入
└── scripts/             # 开发与阶段冒烟
    ├── hub_io.py        # Hub 终端打印与 run_turn / run_repl
    ├── hub_demo.py      # 兼容模块（指向 hub_io）
    ├── react_demo.py    # 仅 ReAct
    ├── plan_demo.py     # 仅 PlanExecute
    └── reflection_demo.py
```

## 运行方式

```bash
# 推荐：完整 Hub
PYTHONPATH=. python main.py
PYTHONPATH=. python main.py --repl

# 环境变量
# RUN_REFLECTION=0          跳过审查
# HUB_MAX_REVISION_ROUNDS=1  审查不通过时修订次数

# 单阶段调试
PYTHONPATH=. python -m agents.scripts.react_demo
PYTHONPATH=. python -m agents.scripts.plan_demo
PYTHONPATH=. python -m agents.scripts.reflection_demo
```

## 导入约定

- 应用代码：`from agents import CortexHub, ReActAgent, StructuredIntent`
- 子包：`from agents.hub import CortexHub`、`from agents.plan import PlanExecuteAgent`

设计说明见项目根目录 [`设计思路.md`](../设计思路.md) 第五～八篇。
