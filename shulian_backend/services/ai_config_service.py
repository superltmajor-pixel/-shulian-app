"""AI 凭据的读取、校验、切换与移除。"""

import threading

from ai_credentials import (
    CredentialError,
    credentials_exist,
    delete_api_key as delete_stored_api_key,
    load_api_key as load_stored_api_key,
    save_api_key as save_stored_api_key,
)
from chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatModelUnavailableError,
    ChatServiceError,
    activate_validated_api_key,
    clear_api_client,
    get_model_options,
    is_api_key_active,
    mask_api_key,
    get_active_model,
    set_active_model,
    runtime_ai_status,
    validate_api_key,
)

from ..domain.errors import AIConfigServiceError


_AI_CONFIG_LOCK = threading.RLock()
_SESSION_LOGGED_OUT = False

_MODEL_PRESENTATION = {
    "deepseek-flash": (
        "DeepSeek V4.1 Flash",
        "最新版 Flash 多模态模型",
    ),
    "doubao-seed-character-260628": (
        "豆包 Seed Character",
        "面向角色扮演与虚拟陪伴的 Character 模型",
    ),
}


def _model_options_payload() -> list[dict]:
    options = []
    for index, model in enumerate(get_model_options()):
        label, description = _MODEL_PRESENTATION.get(
            model,
            (model, "当前产品配置的可用模型"),
        )
        options.append(
            {
                "id": model,
                "label": label,
                "description": description,
                "recommended": index == 0,
            }
        )
    return options


def ai_config_payload(
    *,
    configured: bool,
    ready: bool,
    remembered: bool = False,
    masked_key: str | None = None,
    error: str | None = None,
) -> dict:
    runtime = runtime_ai_status()
    return {
        "configured": configured,
        "ready": ready,
        "remembered": remembered,
        "provider": runtime["provider"],
        "provider_label": runtime["provider_label"],
        "masked_key": masked_key,
        "model": runtime["model"],
        "model_options": _model_options_payload(),
        "base_url": runtime["base_url"],
        "auto_detect": runtime.get("auto_detect", False),
        "error": error,
    }


def resolve_ai_config() -> dict:
    """读取并验证已保存的凭据，不允许环境变量绕过登录页。"""
    with _AI_CONFIG_LOCK:
        if _SESSION_LOGGED_OUT:
            # Logout is scoped to the current process. Keep the encrypted key
            # for the next launch, but do not let health checks silently log
            # the user back in during this run.
            return ai_config_payload(
                configured=False,
                ready=False,
                remembered=credentials_exist(),
            )
        try:
            api_key = load_stored_api_key()
        except CredentialError:
            clear_api_client()
            return ai_config_payload(
                configured=credentials_exist(),
                ready=False,
                remembered=credentials_exist(),
                error="credential_error",
            )

        if api_key is None:
            # “Do not remember” is a valid session login. Status polling must
            # not log it out; explicit DELETE still clears storage and runtime.
            runtime = runtime_ai_status()
            return ai_config_payload(configured=False, ready=bool(runtime["ready"]),
                                     remembered=False,
                                     masked_key=runtime["masked_key"] if runtime["ready"] else None)

        masked_key = mask_api_key(api_key)
        if is_api_key_active(api_key):
            runtime = runtime_ai_status()
            return ai_config_payload(
                configured=True,
                ready=bool(runtime["ready"]),
                remembered=True,
                masked_key=runtime["masked_key"] or masked_key,
            )

        try:
            candidate = validate_api_key(api_key)
        except ChatAuthenticationError:
            clear_api_client()
            return ai_config_payload(
                configured=True,
                ready=False,
                remembered=True,
                masked_key=masked_key,
                error="invalid_key",
            )
        except ChatModelUnavailableError:
            clear_api_client()
            return ai_config_payload(
                configured=True,
                ready=False,
                remembered=True,
                masked_key=masked_key,
                error="model_unavailable",
            )
        except (ChatConnectionError, ChatServiceError):
            clear_api_client()
            return ai_config_payload(
                configured=True,
                ready=False,
                remembered=True,
                masked_key=masked_key,
                error="network_error",
            )

        activate_validated_api_key(candidate)
        return ai_config_payload(
            configured=True,
            ready=True,
            remembered=True,
            masked_key=candidate.masked_key,
        )


def update_ai_config(api_key: str, remember: bool) -> dict:
    global _SESSION_LOGGED_OUT
    api_key = api_key.strip()
    if not 8 <= len(api_key) <= 512 or any(char.isspace() for char in api_key):
        raise AIConfigServiceError("invalid_request", "API Key 格式不正确", 422)

    with _AI_CONFIG_LOCK:
        try:
            candidate = validate_api_key(api_key)
        except ChatAuthenticationError as exc:
            raise AIConfigServiceError("invalid_key", "API Key 无效或已失效", 401) from exc
        except ChatModelUnavailableError as exc:
            raise AIConfigServiceError(
                "model_unavailable",
                "当前配置的 AI 模型不可用",
                503,
            ) from exc
        except (ChatConnectionError, ChatServiceError) as exc:
            raise AIConfigServiceError(
                "network_error",
                "暂时无法连接 AI 服务，请检查网络后重试",
                503,
            ) from exc

        try:
            if remember:
                save_stored_api_key(api_key)
            else:
                delete_stored_api_key()
        except (CredentialError, OSError) as exc:
            raise AIConfigServiceError(
                "credential_error",
                "无法安全更新 API Key",
                500,
            ) from exc

        activate_validated_api_key(candidate)
        _SESSION_LOGGED_OUT = False
        return ai_config_payload(
            configured=remember,
            ready=True,
            remembered=remember,
            masked_key=candidate.masked_key,
        )


def update_ai_model(model: str) -> dict:
    if model not in get_model_options():
        raise AIConfigServiceError("invalid_model", "不支持的模型档位", 422)

    with _AI_CONFIG_LOCK:
        runtime = runtime_ai_status()
        if not runtime["ready"]:
            raise AIConfigServiceError(
                "not_ready",
                f"请先连接 {runtime['provider_label']} API",
                409,
            )
        try:
            set_active_model(model)
        except (OSError, ValueError) as exc:
            raise AIConfigServiceError(
                "preference_error",
                "无法保存模型档位",
                500,
            ) from exc
        remembered = credentials_exist()
        return ai_config_payload(
            configured=remembered,
            ready=True,
            remembered=remembered,
            masked_key=runtime.get("masked_key"),
        )


def remove_ai_config() -> dict:
    global _SESSION_LOGGED_OUT
    with _AI_CONFIG_LOCK:
        try:
            delete_stored_api_key()
        except CredentialError as exc:
            raise AIConfigServiceError(
                "credential_error",
                "无法清除已保存的 API Key",
                500,
            ) from exc
        clear_api_client()
        _SESSION_LOGGED_OUT = False
        return ai_config_payload(configured=False, ready=False, remembered=False)


def logout_ai_config() -> dict:
    """Disconnect the current session while preserving a remembered API key."""
    global _SESSION_LOGGED_OUT
    with _AI_CONFIG_LOCK:
        clear_api_client()
        _SESSION_LOGGED_OUT = True
        remembered = credentials_exist()
        return ai_config_payload(
            configured=False,
            ready=False,
            remembered=remembered,
        )
