"""RAG 启用判定与路径解析单元测试。"""

from __future__ import annotations

import unittest
from pathlib import Path

from retrieval.rag_bootstrap import collect_document_files, is_rag_enabled, parse_rag_doc_paths


class RagEnvTests(unittest.TestCase):
    def test_parse_comma_separated_paths(self) -> None:
        root = Path("/project")
        paths = parse_rag_doc_paths("docs/a.md, data/b", project_root=root)
        self.assertEqual(paths, [root / "docs/a.md", root / "data/b"])

    def test_auto_enable_when_docs_configured(self) -> None:
        self.assertTrue(is_rag_enabled("docs/knowledge"))
        self.assertFalse(is_rag_enabled(""))

    def test_force_disable(self) -> None:
        self.assertFalse(is_rag_enabled("docs/knowledge", enabled=False))

    def test_explicit_enable_requires_docs(self) -> None:
        self.assertFalse(is_rag_enabled("", enabled=True))
        self.assertTrue(is_rag_enabled("docs/a", enabled=True))

    def test_collect_files_from_directory(self) -> None:
        root = Path(__file__).resolve().parent
        files = collect_document_files([root])
        names = {f.name for f in files}
        self.assertIn("test_rag_env.py", names)


if __name__ == "__main__":
    unittest.main()
