"""应用组装：依赖注入与默认配置。"""

from .bootstrap import DEFAULT_QUERY, build_hub

__all__ = ["build_hub", "DEFAULT_QUERY"]
