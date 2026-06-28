"""长期记忆开关与 MemoryManager 工厂单元测试。"""

from __future__ import annotations

import unittest

from memory.factory import create_memory_manager


class LongTermMemoryEnvTests(unittest.TestCase):
    def test_conversation_only_when_backends_none(self) -> None:
        mem = create_memory_manager(
            namespace="mem:test:default",
            vector_backend="none",
            graph_backend="none",
        )
        self.assertEqual(set(mem.handlers.keys()), {"conversation"})


if __name__ == "__main__":
    unittest.main()
