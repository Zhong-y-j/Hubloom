"""MemoryManager.bind_namespace 单元测试。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from memory.handlers.conversation_handler import ConversationHandler
from memory.handlers.episodic_qdrant_handler import EpisodicQdrantHandler
from memory.manager import MemoryManager


class MemoryBindNamespaceTests(unittest.TestCase):
    def test_bind_namespace_updates_handlers(self) -> None:
        conv_store = MagicMock()
        qdrant_store = MagicMock()
        embedder = MagicMock()

        conversation = ConversationHandler(store=conv_store, session_id="mem:a:default")
        episodic = EpisodicQdrantHandler(
            store=qdrant_store,
            embedder=embedder,
            namespace="mem:a:default",
        )
        mem = MemoryManager(handlers={"conversation": conversation, "episodic": episodic})

        mem.bind_namespace("mem:web-user:default")

        self.assertEqual(conversation.session_id, "mem:web-user:default")
        self.assertEqual(episodic.namespace, "mem:web-user:default")

    def test_bind_namespace_rejects_empty(self) -> None:
        mem = MemoryManager(handlers={})
        with self.assertRaises(ValueError):
            mem.bind_namespace("  ")


if __name__ == "__main__":
    unittest.main()
