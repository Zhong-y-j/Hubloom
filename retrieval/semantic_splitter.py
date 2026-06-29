import re
import math
from typing import List, Tuple, Optional, Dict


class SemanticSplitter:
    """增强版语义分块器，基于 Markdown 结构、Token 控制和重叠策略。

    核心能力：
    - Markdown 标题层级解析（含中文编号：一、（一）等），生成语义完整的块
    - 中英文混合 Token 数量估算，精准控制块大小
    - 相邻块重叠机制，保证上下文连贯
    - 无标题文档的降级处理（基于语义段落边界）
    - 丰富的元数据输出（标题路径、上下文关联等）
    """

    # 中文编号标题模式：一、 二、 （一） （二） 第一章 等
    _CHINESE_HEADING_PATTERNS = [
        (r"^(第[一二三四五六七八九十百千]+[章节篇部])\s*(.*)", 1),
        (r"^([一二三四五六七八九十]+[、.．])\s*(.*)", 1),
        (r"^([（\(][一二三四五六七八九十]+[）\)])\s*(.*)", 2),
        (r"^(\d+[、.．])\s*(.*)", 3),
    ]

    def __init__(
        self,
        chunk_token_size: int = 384,
        overlap_token_size: int = 64,
        min_chunk_token_size: int = 100,
        max_heading_chars: int = 40,
    ):
        self.chunk_token_size = chunk_token_size
        self.overlap_token_size = overlap_token_size
        self.min_chunk_token_size = min_chunk_token_size
        self.max_heading_chars = max_heading_chars
        self._md_heading_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        self._chinese_heading_res = [
            (re.compile(pat, re.MULTILINE), level)
            for pat, level in self._CHINESE_HEADING_PATTERNS
        ]

    def split(self, text: str) -> List[Dict]:
        """主入口：将文本分割为语义块，返回元数据丰富的块列表。

        Returns:
            分块列表，每个块为 dict: { content, metadata }
        """
        if not text or not text.strip():
            return []

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)

        sections = self._parse_sections(text)

        if not sections:
            chunks = self._split_flat_text(text)
        else:
            chunks = self._split_sections_into_chunks(sections)

        if not chunks:
            chunks = self._split_flat_text(text)

        return self._finalize_chunks(chunks)

    # ──── 标题识别 ────
    def _detect_heading(self, line: str) -> Optional[Tuple[int, str]]:
        """检测一行是否为标题，返回 (level, heading_text) 或 None。

        优先 Markdown #，其次中文编号。
        """
        md_match = self._md_heading_re.match(line)
        if md_match:
            return len(md_match.group(1)), md_match.group(2).strip()

        stripped = line.strip()
        for pattern, level in self._chinese_heading_res:
            m = pattern.match(stripped)
            if m:
                prefix = m.group(1)
                rest = m.group(2).strip() if m.lastindex >= 2 else ""
                heading_text = f"{prefix}{rest}" if rest else prefix
                if len(stripped) > self.max_heading_chars:
                    continue
                return level, heading_text

        return None

    # ──── 结构解析 ────
    def _parse_sections(self, text: str) -> List[Dict]:
        """解析标题树，返回扁平化的 section 列表（每个 section 只含自身直属内容）。"""
        lines = text.split("\n")

        headings: List[Tuple[int, int, str]] = []
        for i, line in enumerate(lines):
            result = self._detect_heading(line)
            if result:
                level, heading_text = result
                headings.append((i, level, heading_text))

        if not headings:
            return []

        sections = []

        if headings[0][0] > 0:
            preamble = "\n".join(lines[: headings[0][0]]).strip()
            if preamble:
                sections.append(
                    {"level": 0, "heading": "", "path": [], "content": preamble}
                )

        path_stack: List[Tuple[int, str]] = []

        for idx, (line_no, level, heading_text) in enumerate(headings):
            # 维护标题路径栈
            while path_stack and path_stack[-1][0] >= level:
                path_stack.pop()
            path_stack.append((level, heading_text))
            current_path = [h for _, h in path_stack]

            # 自身直属内容：从标题下一行到下一个标题行之前
            content_start = line_no + 1
            if idx + 1 < len(headings):
                content_end = headings[idx + 1][0]
            else:
                content_end = len(lines)

            content = "\n".join(lines[content_start:content_end]).strip()

            sections.append(
                {
                    "level": level,
                    "heading": heading_text,
                    "path": current_path,
                    "content": content,
                }
            )

        return sections

    # ──── 分块逻辑 ────
    def _split_sections_into_chunks(self, sections: List[Dict]) -> List[Dict]:
        """将每个 section 的内容按 Token 大小切分为块。"""
        chunks = []
        for section in sections:
            content = section["content"]
            path = section["path"]
            heading = section["heading"]

            if not content:
                continue

            path_prefix = " > ".join(path) if path else ""
            path_token_cost = (
                self._estimate_tokens(path_prefix + "\n\n") if path_prefix else 0
            )
            effective_token_size = max(
                self.chunk_token_size - path_token_cost, self.min_chunk_token_size
            )

            sub_chunks = self._token_split(content, effective_token_size)

            for i, sub_content in enumerate(sub_chunks):
                if path_prefix:
                    chunk_content = f"{path_prefix}\n\n{sub_content}"
                else:
                    chunk_content = sub_content

                chunks.append(
                    {
                        "content": chunk_content,
                        "path": path,
                        "heading": heading,
                        "chunk_index_in_section": i,
                        "total_chunks_in_section": len(sub_chunks),
                    }
                )

        return chunks

    def _token_split(self, text: str, max_tokens: int) -> List[str]:
        """按 Token 限制分割文本，优先在段落 / 句子边界切割。"""
        if not text:
            return []
        if self._estimate_tokens(text) <= max_tokens:
            return [text]

        chunks = []
        paragraphs = text.split("\n\n")
        current_chunk = ""
        current_tokens = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            para_tokens = self._estimate_tokens(para)

            if current_tokens + para_tokens <= max_tokens:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
                current_tokens += para_tokens
            else:
                if current_chunk:
                    chunks.append(current_chunk)

                if para_tokens > max_tokens:
                    sent_chunks = self._split_long_paragraph(para, max_tokens)
                    chunks.extend(sent_chunks[:-1])
                    current_chunk = sent_chunks[-1] if sent_chunks else ""
                    current_tokens = self._estimate_tokens(current_chunk)
                else:
                    current_chunk = para
                    current_tokens = para_tokens

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _split_long_paragraph(self, text: str, max_tokens: int) -> List[str]:
        """超长段落按句子边界强制切割。"""
        sentences = re.split(r"(?<=[。！？\.!\?；;])\s*", text)
        chunks = []
        current = ""
        for sent in sentences:
            if not sent:
                continue
            if self._estimate_tokens(current + sent) <= max_tokens:
                current += sent
            else:
                if current:
                    chunks.append(current.strip())
                current = sent
        if current:
            chunks.append(current.strip())
        return chunks if chunks else [text]

    # ──── 降级处理（无标题文档） ────
    def _split_flat_text(self, text: str) -> List[Dict]:
        """无标题纯文本，按段落边界聚合到 Token 限制内。"""
        if not text:
            return []
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current_chunk = ""
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self._estimate_tokens(para)

            if para_tokens > self.chunk_token_size:
                if current_chunk:
                    chunks.append(self._make_flat_chunk(current_chunk))
                    current_chunk = ""
                    current_tokens = 0
                for sub in self._split_long_paragraph(para, self.chunk_token_size):
                    chunks.append(self._make_flat_chunk(sub))
                continue

            if current_tokens + para_tokens <= self.chunk_token_size:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
                current_tokens += para_tokens
            else:
                if current_chunk:
                    chunks.append(self._make_flat_chunk(current_chunk))
                current_chunk = para
                current_tokens = para_tokens

        if current_chunk:
            chunks.append(self._make_flat_chunk(current_chunk))
        return chunks

    @staticmethod
    def _make_flat_chunk(content: str) -> Dict:
        return {
            "content": content,
            "path": [],
            "heading": "",
            "chunk_index_in_section": 0,
            "total_chunks_in_section": 1,
        }

    # ──── 重叠与最终化 ────
    def _finalize_chunks(self, raw_chunks: List[Dict]) -> List[Dict]:
        """合并过短块、添加重叠窗口、生成最终元数据。"""
        if not raw_chunks:
            return []

        filtered = []
        for chunk in raw_chunks:
            if (
                filtered
                and self._estimate_tokens(chunk["content"]) < self.min_chunk_token_size
            ):
                filtered[-1]["content"] += "\n\n" + chunk["content"]
            else:
                filtered.append(chunk)

        final_chunks = []
        total = len(filtered)
        for i, chunk in enumerate(filtered):
            content = chunk["content"]

            if i > 0 and self.overlap_token_size > 0:
                prev_content = filtered[i - 1]["content"]
                if self._estimate_tokens(prev_content) > self.overlap_token_size:
                    overlap_text = self._get_tail_by_sentence(
                        prev_content, self.overlap_token_size
                    )
                    if overlap_text:
                        content = overlap_text + "\n\n" + content

            chunk_id = f"chunk_{i}"
            metadata = {
                "chunk_id": chunk_id,
                "chunk_index": i,
                "total_chunks": total,
                "section_path": " > ".join(chunk.get("path", [])),
                "heading": chunk.get("heading", ""),
                "prev_chunk_id": f"chunk_{i-1}" if i > 0 else None,
                "next_chunk_id": f"chunk_{i+1}" if i + 1 < total else None,
            }

            final_chunks.append({"content": content, "metadata": metadata})

        return final_chunks

    @staticmethod
    def _get_tail_by_sentence(text: str, target_tokens: int) -> str:
        """从文本尾部按句子边界截取约 target_tokens 大小的片段。"""
        if not text:
            return ""
        sentences = re.split(r"(?<=[。！？\.!\?；;])\s*", text)
        sentences = [s for s in sentences if s.strip()]
        if not sentences:
            char_count = int(target_tokens * 2.5)
            return text[-char_count:]

        result_parts: list[str] = []
        accumulated = 0
        for sent in reversed(sentences):
            sent_tokens = SemanticSplitter._estimate_tokens(sent)
            if accumulated + sent_tokens > target_tokens and result_parts:
                break
            result_parts.append(sent)
            accumulated += sent_tokens
        result_parts.reverse()
        return "".join(result_parts)

    # ──── Token 估算 ────
    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """中英文混合 Token 数估算。

        中文字符 ~0.7 token/字，英文单词 ~1.3 token/词，数字 ~1 token/组。
        """
        if not text:
            return 0
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
        english_words = len(re.findall(r"[a-zA-Z]+", text))
        others = len(re.findall(r"[0-9]+", text))
        tokens = chinese_chars * 0.7 + english_words * 1.3 + others * 1.0
        return math.ceil(tokens)


if __name__ == "__main__":
    from loader import DocumentLoader

    loader = DocumentLoader()
    # text = loader.load()
    # splitter = SemanticSplitter()
    # chunks = splitter.split(text)
    # print(len(chunks))
    # for chunk in chunks:
    #     print(chunk["content"])
    #     print(chunk["metadata"])
    #     print("-" * 100)
