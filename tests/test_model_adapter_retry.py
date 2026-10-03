import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from shulian_backend.services.model_adapter_service import (
    OpenAICompatibleModelAdapter,
    RetryPolicy,
    upstream_error_context,
)


class _UpstreamError(RuntimeError):
    def __init__(self, status_code, request_id=""):
        super().__init__("provider detail must not be logged by the adapter")
        self.status_code = status_code
        self.request_id = request_id


class ModelAdapterRetryTests(unittest.TestCase):
    def _adapter(self, create, retries=2, delay=0.8):
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        return OpenAICompatibleModelAdapter(
            provider="deepseek",
            model="deepseek-flash",
            client_factory=lambda: client,
            retry_policy=RetryPolicy(retries=retries, base_delay_seconds=delay),
        )

    @patch("shulian_backend.services.model_adapter_service.log_event")
    @patch("shulian_backend.services.model_adapter_service.time.sleep")
    def test_transient_502_uses_three_bounded_attempts(self, sleep, log_event):
        response = SimpleNamespace(choices=[])
        create = MagicMock(
            side_effect=[_UpstreamError(502, "first"), _UpstreamError(503, "second"), response]
        )
        adapter = self._adapter(create)

        self.assertIs(adapter.complete([], temperature=0.5), response)
        self.assertEqual(create.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.8, 1.6])
        self.assertEqual(log_event.call_count, 2)

    @patch("shulian_backend.services.model_adapter_service.log_event")
    @patch("shulian_backend.services.model_adapter_service.time.sleep")
    def test_non_retryable_400_fails_immediately(self, sleep, log_event):
        create = MagicMock(side_effect=_UpstreamError(400, "bad-request"))
        adapter = self._adapter(create)

        with self.assertRaises(_UpstreamError):
            adapter.complete([], temperature=0.5)
        self.assertEqual(create.call_count, 1)
        sleep.assert_not_called()
        self.assertEqual(log_event.call_count, 1)

    def test_error_context_follows_wrapped_cause_without_message_body(self):
        upstream = _UpstreamError(502, "provider-request-id")
        try:
            raise RuntimeError("safe wrapper") from upstream
        except RuntimeError as wrapped:
            context = upstream_error_context(wrapped)

        self.assertEqual(context["upstream_error_type"], "_UpstreamError")
        self.assertEqual(context["upstream_status"], 502)
        self.assertEqual(context["upstream_request_id"], "provider-request-id")
        self.assertNotIn("message", context)

    def test_environment_defaults_are_deliberate(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MODEL_ADAPTER_RETRIES", None)
            os.environ.pop("MODEL_ADAPTER_RETRY_DELAY_SECONDS", None)
            policy = RetryPolicy.from_environment()
        self.assertEqual(policy, RetryPolicy(retries=2, base_delay_seconds=0.8))


if __name__ == "__main__":
    unittest.main()
