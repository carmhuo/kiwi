class ChartGenerationError(Exception):
    """图表生成专用异常"""

    def __init__(self, message="图表生成失败"):
        self.message = message
        super().__init__(self.message)


class SQLRemoveError(Exception):
    """Raise when not able to remove SQL"""

    pass


class ExecutionError(Exception):
    """Raise when not able to execute Code"""

    pass


class ValidationError(Exception):
    """Raise for validations"""

    pass


class APIError(Exception):
    """Raise for API errors"""

    pass


class UnauthorizedAccessError(Exception):
    pass


class ConversationNotFoundError(Exception):
    pass


class AgentProcessingError(Exception):
    pass
