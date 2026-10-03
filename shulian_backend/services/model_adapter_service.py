"""统一的大模型调用适配层。

业务代码只负责准备消息；供应商 SDK、重试和流关闭等运行细节集中在这里。
纯净版默认使用 DeepSeek，也支持通过环境变量切换到其他 OpenAI 兼容服务。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, Iterator, Protocol

from diagnostics import log_event


class ModelRequestCancelled(RuntimeError):
    """调用方主动取消了一次模型请求。"""


class CancellationToken:
    """可跨同步生成器传递的轻量取消令牌。"""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ModelRequestCancelled("model request cancelled")


class ModelAdapter(Protocol):
    """模型供应商对数恋暴露的最小能力集合。"""

    provider: str
    model: str

    def complete(
        self,
        messages: list[dict],
        *,
        temperature: float,
        max_tokens: int | None = None,
        cancellation: CancellationToken | None = None,
    ) -> Any: ...

    def stream(
        self,
        messages: list[dict],
        *,
        temperature: float,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[Any]: ...


@dataclass(frozen=True)
class RetryPolicy:
    retries: int = 2
    base_delay_seconds: float = 0.8

    @classmethod
    def from_environment(cls) -> "RetryPolicy":
        try:
            retries = int(os.getenv("MODEL_ADAPTER_RETRIES", "2"))
        except ValueError:
            retries = 2
        try:
            delay = float(os.getenv("MODEL_ADAPTER_RETRY_DELAY_SECONDS", "0.8"))
        except ValueError:
            delay = 0.8
        return cls(
            retries=max(0, min(retries, 3)),
            base_delay_seconds=max(0.0, min(delay, 2.0)),
        )


def _status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _is_retryable(exc: Exception) -> bool:
    status_code = _status_code(exc)
    if status_code is None:
        return True
    return status_code in {408, 409, 425, 429} or status_code >= 500


def upstream_error_context(exc: BaseException) -> dict[str, Any]:
    """Return safe provider metadata without prompts, replies or credentials."""
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, Exception):
            status_code = _status_code(current)
            request_id = str(getattr(current, "request_id", "") or "").strip()
            if status_code is not None or request_id:
                return {
                    "upstream_error_type": type(current).__name__[:80],
                    "upstream_status": status_code,
                    "upstream_request_id": request_id[:160],
                }
        current = current.__cause__ or current.__context__
    return {
        "upstream_error_type": type(exc).__name__[:80],
        "upstream_status": None,
        "upstream_request_id": "",
    }


class OpenAICompatibleModelAdapter:
    """适配 OpenAI Chat Completions 协议的供应商。"""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        client_factory: Callable[[], Any],
        extra_body_factory: Callable[[], dict] | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._client_factory = client_factory
        self._extra_body_factory = extra_body_factory
        self._retry_policy = retry_policy or RetryPolicy.from_environment()

    def _request_kwargs(
        self,
        messages: list[dict],
        *,
        temperature: float,
        stream: bool = False,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": messages,
        }
        if stream:
            kwargs["stream"] = True
            if self.provider == "deepseek":
                kwargs["stream_options"] = {"include_usage": True}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if self._extra_body_factory is not None:
            kwargs["extra_body"] = self._extra_body_factory()
        return kwargs

    def _create_with_retry(
        self,
        kwargs: dict[str, Any],
        cancellation: CancellationToken | None,
    ) -> Any:
        for attempt in range(self._retry_policy.retries + 1):
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            try:
                return self._client_factory().chat.completions.create(**kwargs)
            except ModelRequestCancelled:
                raise
            except Exception as exc:
                if attempt >= self._retry_policy.retries or not _is_retryable(exc):
                    log_event(
                        "error",
                        "model_request_failed",
                        "Model provider request failed after bounded retries",
                        provider=self.provider,
                        model=self.model,
                        attempt=attempt + 1,
                        max_attempts=self._retry_policy.retries + 1,
                        retryable=_is_retryable(exc),
                        **upstream_error_context(exc),
                    )
                    raise
                delay = self._retry_policy.base_delay_seconds * (2**attempt)
                log_event(
                    "warning",
                    "model_request_retry",
                    "Retrying a transient model provider failure",
                    provider=self.provider,
                    model=self.model,
                    attempt=attempt + 1,
                    max_attempts=self._retry_policy.retries + 1,
                    retry_delay_ms=round(delay * 1000),
                    **upstream_error_context(exc),
                )
                if delay:
                    time.sleep(delay)
        raise RuntimeError("unreachable model retry state")

    def _record_usage(self, response: Any, started: float, first_token_ms: float | None = None) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        def count(name: str) -> int | None:
            value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
            return value if type(value) is int and value >= 0 else None
        hit = count("prompt_cache_hit_tokens")
        miss = count("prompt_cache_miss_tokens")
        total = hit + miss if hit is not None and miss is not None else None
        log_event(
            "info", "model_usage", "Model input cache and token usage",
            provider=self.provider, model=self.model,
            prompt_tokens=count("prompt_tokens"), completion_tokens=count("completion_tokens"),
            cache_hit_tokens=hit, cache_miss_tokens=miss,
            cache_hit_ratio=hit / total if total else None,
            first_token_ms=first_token_ms,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def complete(
        self,
        messages: list[dict],
        *,
        temperature: float,
        max_tokens: int | None = None,
        cancellation: CancellationToken | None = None,
    ) -> Any:
        started = time.perf_counter()
        response = self._create_with_retry(
            self._request_kwargs(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            cancellation,
        )
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        self._record_usage(response, started)
        return response

    def stream(
        self,
        messages: list[dict],
        *,
        temperature: float,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[Any]:
        started = time.perf_counter()
        first_token_ms = None
        usage_response = None
        upstream = self._create_with_retry(
            self._request_kwargs(
                messages,
                temperature=temperature,
                stream=True,
            ),
            cancellation,
        )
        try:
            for chunk in upstream:
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                for choice in getattr(chunk, "choices", []) or []:
                    delta = getattr(choice, "delta", None)
                    if first_token_ms is None and getattr(delta, "content", None):
                        first_token_ms = round((time.perf_counter() - started) * 1000, 2)
                if getattr(chunk, "usage", None) is not None:
                    usage_response = chunk
                yield chunk
        finally:
            if usage_response is not None:
                self._record_usage(usage_response, started, first_token_ms)
            close = getattr(upstream, "close", None)
            if callable(close):
                close()


class ModelAdapterRegistry:
    """按供应商名解析适配器，避免业务层出现供应商分支。"""

    def __init__(self) -> None:
        self._adapters: dict[str, ModelAdapter] = {}

    def register(self, adapter: ModelAdapter) -> None:
        self._adapters[adapter.provider] = adapter

    def resolve(self, provider: str) -> ModelAdapter:
        try:
            return self._adapters[provider]
        except KeyError as exc:
            raise LookupError(f"Unsupported model provider: {provider}") from exc


def model_adapter_status() -> dict:
    """返回可安全写入自检/诊断包的适配层能力。"""
    retry_policy = RetryPolicy.from_environment()
    return {
        "adapter": "openai_compatible",
        "retries": retry_policy.retries,
        "streaming": True,
        "cancellation": True,
    }
