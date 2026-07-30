"""会话历史 Postgres 连通性联调（读 config/env.yaml）。

用法（仓库根目录）::

    PYTHONPATH=src .venv/bin/python tests/test_conversation_postgres_connect.py

可选环境变量::

    HUBLOOM_CONFIG=config/env.yaml   # 配置路径（默认 config/env.yaml）
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from config import HubloomConfig
from core.models import Message, Role
from memory.store import ConversationPostgresStore, create_conversation_store


def _config_path() -> Path:
    env = (os.environ.get("HUBLOOM_CONFIG") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path("config/env.yaml").resolve()


def main() -> int:
    path = _config_path()
    if not path.is_file():
        print(f"找不到配置文件: {path}")
        return 1

    cfg = HubloomConfig.from_file(path)
    backend = (cfg.conversation_store or "sqlite").strip().lower() or "sqlite"
    dsn = (cfg.conversation_postgres_dsn or "").strip()

    print("=" * 56)
    print(" 会话历史 Postgres 连通性测试")
    print("=" * 56)
    print(f"config              : {path}")
    print(f"conversation_store  : {backend}")
    print(
        f"postgres_dsn        : "
        f"{'(空)' if not dsn else dsn.split('@')[-1] if '@' in dsn else dsn}"
    )
    # DSN 打印时隐藏 user:pass，只留 host/db 段，避免把密码打到终端

    if backend != "postgres":
        print(
            "\n当前不是 postgres。请在配置里设置:\n"
            "  memory:\n"
            "    conversation_store: postgres\n"
            "    postgres_dsn: postgresql://user:pass@host:5432/dbname\n"
        )
        return 1

    if not dsn:
        print("\n缺少 memory.postgres_dsn，无法连接。")
        return 1

    print("\n① 连接并建表（若不存在）…")
    try:
        store = create_conversation_store(backend="postgres", postgres_dsn=dsn)
    except Exception as exc:
        print(f"连接失败: {type(exc).__name__}: {exc}")
        print(
            "\n排查建议:\n"
            "  - Postgres 是否已启动\n"
            "  - 用户名/密码/库名是否正确\n"
            "  - 库是否已创建（CREATE DATABASE hubloom;）\n"
            "  - 本机端口是否为 5432\n"
        )
        return 1

    if not isinstance(store, ConversationPostgresStore):
        print(f"意外类型: {type(store)!r}")
        store.close()
        return 1

    session_id = f"pg-connect-{uuid.uuid4().hex[:8]}"
    try:
        print(f"② 写入一条测试消息 session_id={session_id} …")
        msg_id = store.add_message(
            session_id,
            Message(role=Role.USER, content="postgres connect probe"),
        )
        print(f"   message_id={msg_id}")

        print("③ 读回最近消息 …")
        recent = store.get_recent(session_id, limit=5)
        if not recent or recent[-1].content != "postgres connect probe":
            print(f"读回内容不符合预期: {recent!r}")
            return 1
        print(f"   ok: role={recent[-1].role.value} content={recent[-1].content!r}")

        print("④ 清理测试会话 …")
        deleted = store.clear_session(session_id)
        print(f"   deleted={deleted}")

        print("\n" + "=" * 56)
        print(" 连通成功：可读写 conversation_memory")
        print("=" * 56)
        return 0
    except Exception as exc:
        print(f"读写失败: {type(exc).__name__}: {exc}")
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
