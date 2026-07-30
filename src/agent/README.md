# Agent（Step 2 · Typed ReAct + Evidence Journal）

目标架构见 `docs/modules/agent-architecture.md`。

当前目录是 **新环**实现；旧 Think/Present/A2UI 备份在 `src/agent copy/`。  
**不在本步改 Runtime / 示例站**（宿主切换见 Step 5）。

## 包结构

| 路径 | 作用 |
| --- | --- |
| `actions.py` | Typed 动作互斥解析 + 控制 tools |
| `evidence.py` | Evidence Journal（观察入账、摘要、cite id） |
| `loop/decide.py` | 一轮 LLM → TypedAction |
| `loop/exec_act.py` | 执行业务 tool_calls |
| `run.py` | Decide↔Exec↔Journal 主循环 `run_stream` |
| `assemble.py` / `prompts.py` | 历史 + Journal 摘要 + system |
| `events.py` | `step` / tool / `run_complete` 等（无 A2UI） |

未做（后续）：Wait Profile 挂起、Playbook Gate、Runtime/示例拆 A2UI。

## 验证（不经 Runtime）

```bash
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step1.py
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step2.py
```
