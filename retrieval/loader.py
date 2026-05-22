import os
from typing import Callable, Optional


class DocumentLoader:
    """通用文档加载器，使用 MarkItDown 将多格式文档转换为 Markdown。

    所有文档格式（PDF、Word、Excel、PPT、HTML、CSV、JSON 等）统一通过 MarkItDown 转换。
    代码文件单独处理，以 Markdown 代码块形式输出。
    图片和音频待定，未来可通过 MarkItDown 插件或自定义转换器扩展。

    Args:
        code_extensions: 自定义的代码文件扩展名映射（扩展名 -> 语言标识），
                         不传则使用默认映射。
    """

    def __init__(self, code_extensions: Optional[dict] = None):
        # 代码文件扩展名 -> 语言标识
        self.code_extensions = code_extensions or {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".java": "java",
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".sh": "bash",
            ".bash": "bash",
            ".zsh": "bash",
            ".sql": "sql",
            ".r": "r",
            ".lua": "lua",
            ".toml": "toml",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".ini": "ini",
        }
        # 额外的自定义格式转换器（注册后优先级高于 MarkItDown）
        self._custom_converters: dict[str, Callable[[str], str]] = {}

    def load(self, file_path: str) -> str:
        """加载文档，返回 Markdown 文本。"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()

        # 1) 用户注册的自定义转换器优先
        if ext in self._custom_converters:
            return self._custom_converters[ext](file_path)

        # 2) 代码文件 → Markdown 代码块
        if ext in self.code_extensions:
            return self._load_code(file_path, ext)

        # 3) 其余所有文档格式，统一走 MarkItDown
        return self._convert_with_markitdown(file_path)

    # ──── MarkItDown 核心转换 ────
    @staticmethod
    def _convert_with_markitdown(file_path: str) -> str:
        """使用 MarkItDown 将任意文档转换为 Markdown。"""
        try:
            from markitdown import MarkItDown
        except ImportError:
            raise ImportError(
                "markitdown is required for document conversion. "
                "Install with: pip install markitdown"
            )
        converter = MarkItDown()
        result = converter.convert(file_path)
        return result.text_content

    # ──── 代码文件处理 ────
    def _load_code(self, file_path: str, ext: str) -> str:
        """将代码文件包装为 Markdown 代码块。"""
        lang = self.code_extensions[ext]
        file_name = os.path.basename(file_path)
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return f"# {file_name}\n\n```{lang}\n{content}\n```"


if __name__ == "__main__":
    loader = DocumentLoader()
    text = loader.load(
        "/Users/zhong/Desktop/Git-store/CODE/面试/AI项目个人工作内容及实现思路.docx"
    )
    print(text)
