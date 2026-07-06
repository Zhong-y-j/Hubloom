"""OpenAPI spec 准备管线：加载、规范化、解析 base URL。"""

from __future__ import annotations
from .base_url import infer_base_url, infer_base_url_from_source
from .loader import load_spec
from .normalize import normalize_openapi_spec
