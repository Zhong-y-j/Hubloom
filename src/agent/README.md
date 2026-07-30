# Agent（Step 3 · Wait Profile）

目标架构见 `docs/modules/agent-architecture.md`。

当前目录是 **新环**实现；旧 Think/Present/A2UI 备份在 `src/agent copy/`。  
**不在本步改 Runtime / 示例站**（宿主切换见 Step 5）。

## 包结构

| 路径 | 作用 |
| --- | --- |
| `actions.py` | Typed 动作互斥解析 + 控制 tools |
| `evidence.py` | Evidence Journal |
| `wait.py` | `interactive` / `turn_based` / `no_wait` |
| `session.py` | pending / awaiting + `InMemorySessionStore` |
| `loop/decide.py` / `loop/exec_act.py` | Decide / Exec |
| `run.py` | `run_stream` + `resume_stream` |
| `assemble.py` | 历史 + Journal + Pending 摘要 |
| `events.py` | step / tool / `awaiting_user` / `run_complete` |

未做（后续）：Playbook Gate、Runtime/示例拆 A2UI、Session 外置 Redis。

## Wait Profile（Agent 层）

| Profile | ask / await_confirm |
| --- | --- |
| `turn_based`（默认） | 结束 Run → `waiting_user` + `pending`；下轮新 Run 续办 |
| `interactive` | 同一 Run 挂起 → `awaiting_user`；`resume_stream` 继续 |
| `no_wait` | 降级 `failed`，不挂死 |

## 验证（不经 Runtime）

```bash
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step1.py
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step2.py
PYTHONPATH=src .venv/bin/python tests/test_agent_v2_step3.py
```
