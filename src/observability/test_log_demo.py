#!/usr/bin/env python3
"""日志演示。运行: PYTHONPATH=. uv run python -m observability.test_log_demo"""

from __future__ import annotations

from observability import log, logger, setup_log


def main() -> None:
    path = setup_log(capture_print=True)

    print("这条 print 会进日志文件")

    log("Hub 开始", phase="react", session="mem:tester_id:default", turn=1)
    log("预取记忆", query="我叫张三", hits=0, namespace="mem:tester_id:default")
    log("LLM 流式", content="很高兴认识你，张三！")
    log("写入 Qdrant", episodic='["用户姓名：张三"]', skipped=False)
    logger.opt(depth=1).warning(
        "图记忆失败 error=Unable to retrieve routing information"
    )
    # 故意触发未捕获异常，验证会写入 logs/agentcortex.log（含完整 traceback）
    # print(a)  # noqa: F821 — NameError 测试


if __name__ == "__main__":
    main()
