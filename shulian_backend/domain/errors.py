"""不依赖 FastAPI 的应用层错误。"""


class StateServiceError(RuntimeError):
    """SQLite 状态服务无法完成请求。"""


class InvalidStateDataError(StateServiceError):
    """传入的状态数据不符合数恋存储约束。"""


class StateUnavailableError(StateServiceError):
    """本地状态仓库暂时不可用。"""


class AIConfigServiceError(RuntimeError):
    """可安全返回给 API 层的 AI 凭据错误。"""

    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class TTSConfigurationError(RuntimeError):
    """TTS 配置无效。"""


class TTSServiceError(RuntimeError):
    """TTS 上游服务调用失败。"""
