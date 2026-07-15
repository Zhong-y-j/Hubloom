"""RAG 环境配置与启动入库。"""

from __future__ import annotations

import os
from pathlib import Path

from embedders.openai_embedder import OpenAIEmbedder
from retrieval.knowledge_base import KnowledgeBase
from observability import log

_SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", ".venv", "venv"}
# retrieval → src → 仓库根
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_rag_doc_paths(
    raw: str | None,
    *,
    project_root: Path | None = None,
) -> list[Path]:
    """解析 ``CORTEX_RAG_DOCS``（逗号分隔的文件或目录路径）。"""
    root = project_root or _PROJECT_ROOT
    paths: list[Path] = []
    for part in (raw or "").split(","):
        text = part.strip()
        if not text:
            continue
        path = Path(text)
        if not path.is_absolute():
            path = root / path
        paths.append(path)
    return paths


def is_rag_enabled(rag_docs_raw: str | None = None) -> bool:
    """配置了 ``CORTEX_RAG_DOCS`` 则启用；``CORTEX_ENABLE_RAG=0`` 可强制关闭。"""
    explicit = os.getenv("CORTEX_ENABLE_RAG", "").strip().lower()
    if explicit in ("0", "false", "no", "off"):
        return False
    if explicit in ("1", "true", "yes", "on"):
        return True
    raw = rag_docs_raw if rag_docs_raw is not None else os.getenv("CORTEX_RAG_DOCS", "")
    return bool(raw and raw.strip())


def collect_document_files(paths: list[Path]) -> list[Path]:
    """展开目录，收集待入库文件（去重、跳过隐藏项）。"""
    found: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path.is_file():
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
            continue
        if not path.is_dir():
            log("rag path skip", path=str(path), reason="not_found")
            continue
        for root, dirnames, filenames in os.walk(path):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _SKIP_DIR_NAMES and not d.startswith(".")
            ]
            for name in filenames:
                if name.startswith("."):
                    continue
                fp = (Path(root) / name).resolve()
                if fp not in seen:
                    seen.add(fp)
                    found.append(fp)
    return found


async def ingest_rag_sources(kb: KnowledgeBase, paths: list[Path]) -> int:
    """将源文档写入 Chroma；已存在同名 ``doc_name`` 的跳过。"""
    files = collect_document_files(paths)
    if not files:
        log("rag ingest skip", reason="no_files", paths=len(paths))
        return 0

    existing = {item.get("doc_name") for item in kb.get_document_list()}
    indexed = 0
    for file_path in files:
        doc_name = file_path.name
        if doc_name in existing:
            log("rag ingest skip file", file=str(file_path), reason="already_indexed")
            continue
        await kb.add_document(str(file_path))
        existing.add(doc_name)
        indexed += 1
    log("rag ingest done", indexed=indexed, total_files=len(files))
    return indexed


def create_knowledge_base(*, persist_dir: str) -> KnowledgeBase:
    return KnowledgeBase(embedder=OpenAIEmbedder(), persist_dir=persist_dir)
