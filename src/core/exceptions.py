"""LLM 统一异常类型定义，将 SDK 异常映射为领域异常"""


class LLMException(Exception):
    """LLM 层统一异常基类"""

    pass


class ContextLengthExceeded(LLMException):
    """上下文超长异常"""

    pass


class RateLimitExceeded(LLMException):
    """速率限制异常"""

    pass


class LLMTimeout(LLMException):
    """超时异常"""

    pass


class LLMAPIError(LLMException):
    """其他 API 错误"""

    pass
