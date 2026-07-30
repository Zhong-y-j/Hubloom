# Agent（Step 4 · Gate + Playbook）

目标架构见 `docs/modules/agent-architecture.md`。

**不在本步改 Runtime / 示例站**（宿主切换见 Step 5）。

## 包结构

| 路径 | 作用 |
| --- | --- |
| `actions.py` | Typed 动作互斥 |
| `evidence.py` | Evidence Journal |
| `wait.py` / `session.py` | Wait Profile + pending/awaiting |
| `policy.py` | Playbook 模型 + Skill frontmatter 编译 |
| `gate.py` | Exec 前硬拦；reject 回环；同因熔断 |
| `run.py` | Decide → Gate → Exec/Wait/Finish |
| `assemble.py` | 历史 + Playbook/Journal/Pending 摘要 |

## Skill `playbook` frontmatter（最小）

```yaml
playbook:
  forbid_tools: [echo_bad]
  require_steps:
    - id: register_pet
      tools: [echo_pet]
  confirm_tools: [echo_pet]
```

无 Playbook = 纯能力环。

## 验证

分步单测 + **整流程集成**（推荐先跑 flow）：

```bash
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_flow.py
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step1.py
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step2.py
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step3.py
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step4.py
```
