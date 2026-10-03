import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import ai_credentials
import chat
import main
from ai_credentials import CredentialCorruptError, CredentialError
from chat import (
    ChatAuthenticationError,
    ChatConnectionError,
    ChatConfigurationError,
    ChatModelUnavailableError,
    ValidatedAIClient,
)


KEY_A = "sk-unit-test-alpha-1234"
KEY_B = "sk-unit-test-bravo-5678"
ROOT = Path(__file__).resolve().parents[1]


class CredentialStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "credentials.bin"

    def tearDown(self):
        self.temp_dir.cleanup()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is required")
    def test_dpapi_round_trip_never_writes_plaintext(self):
        ai_credentials.save_api_key(KEY_A, self.path)

        raw = self.path.read_bytes()
        self.assertTrue(raw.startswith(ai_credentials._MAGIC_V2))
        self.assertNotIn(KEY_A.encode("utf-8"), raw)
        self.assertEqual(ai_credentials.load_api_key(self.path), KEY_A)

        ai_credentials.delete_api_key(self.path)
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is required")
    def test_machine_scoped_credential_survives_a_new_process(self):
        ai_credentials.save_api_key(KEY_A, self.path)
        environment = os.environ.copy()
        environment["SHULIAN_CREDENTIALS_FILE"] = str(self.path)
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import ai_credentials as a; print('ok' if a.load_api_key() else 'missing')",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), "ok")

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is required")
    def test_legacy_user_scoped_credential_remains_readable(self):
        encrypted = ai_credentials._protect_data(KEY_A.encode("utf-8"))
        self.path.write_bytes(ai_credentials._MAGIC_V1 + encrypted)
        self.assertEqual(ai_credentials.load_api_key(self.path), KEY_A)

    def test_missing_and_corrupt_credentials_are_distinct(self):
        self.assertIsNone(ai_credentials.load_api_key(self.path))

        self.path.write_bytes(b"not-a-shulian-credential")
        with self.assertRaises(CredentialCorruptError):
            ai_credentials.load_api_key(self.path)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is required")
    def test_failed_atomic_replace_preserves_previous_key(self):
        ai_credentials.save_api_key(KEY_A, self.path)

        with patch("ai_credentials.os.replace", side_effect=OSError("locked")):
            with self.assertRaises(CredentialError):
                ai_credentials.save_api_key(KEY_B, self.path)

        self.assertEqual(ai_credentials.load_api_key(self.path), KEY_A)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_test_path_can_be_overridden_without_touching_default(self):
        with patch.dict(
            os.environ,
            {"SHULIAN_CREDENTIALS_FILE": str(self.path)},
            clear=False,
        ):
            self.assertEqual(ai_credentials.credential_path(), self.path)


class ChatCredentialRuntimeTests(unittest.TestCase):
    def setUp(self):
        chat.clear_api_client()

    def tearDown(self):
        chat.clear_api_client()

    @staticmethod
    def _provider_client(*model_ids: str):
        provider_client = MagicMock()
        provider_client.models.list.return_value = SimpleNamespace(
            data=[SimpleNamespace(id=model_id) for model_id in model_ids]
        )
        return provider_client

    def test_candidate_is_verified_with_model_list_before_activation(self):
        provider_client = self._provider_client(chat.MODEL, "another-model")

        with patch("chat._new_client", return_value=provider_client):
            candidate = chat.validate_api_key(KEY_A)

        provider_client.models.list.assert_called_once_with()
        self.assertFalse(chat.runtime_ai_status()["ready"])

        chat.activate_validated_api_key(candidate)
        status = chat.runtime_ai_status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["masked_key"], "••••1234")

    def test_provider_401_and_connection_failure_are_distinct(self):
        unauthorized = RuntimeError("unauthorized")
        unauthorized.status_code = 401
        auth_client = self._provider_client(chat.MODEL)
        auth_client.models.list.side_effect = unauthorized

        with patch("chat._new_client", return_value=auth_client):
            with self.assertRaises(ChatAuthenticationError):
                chat.validate_api_key(KEY_A)

        offline_client = self._provider_client(chat.MODEL)
        offline_client.models.list.side_effect = OSError("offline")
        with patch("chat._new_client", return_value=offline_client):
            with self.assertRaises(ChatConnectionError):
                chat.validate_api_key(KEY_A)

    def test_authenticated_catalog_may_omit_experimental_vision_model(self):
        provider_client = self._provider_client("different-model")
        with patch("chat._new_client", return_value=provider_client), patch.dict(os.environ, {"SHULIAN_AI_PROVIDER":"deepseek"}):
            candidate = chat.validate_api_key(KEY_A, model=chat.MODEL)
        self.assertEqual(candidate.model, chat.MODEL)
        self.assertEqual(candidate.model_options, (chat.MODEL,))

    def test_environment_key_never_auto_initializes_runtime(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": KEY_A}, clear=False):
            with self.assertRaises(ChatConfigurationError):
                chat._require_client()

    def test_runtime_key_can_be_replaced_and_cleared(self):
        first = ValidatedAIClient("fingerprint-a", "••••1234", MagicMock())
        second = ValidatedAIClient("fingerprint-b", "••••5678", MagicMock())

        chat.activate_validated_api_key(first)
        chat.activate_validated_api_key(second)
        self.assertEqual(chat.runtime_ai_status()["masked_key"], "••••5678")

        chat.clear_api_client()
        self.assertFalse(chat.runtime_ai_status()["ready"])


class AIConfigApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app, client=("127.0.0.1", 51000))
        cls.remote_client = TestClient(main.app, client=("192.0.2.10", 51000))

    def setUp(self):
        chat.clear_api_client()

    def tearDown(self):
        chat.clear_api_client()

    @staticmethod
    def _candidate(key: str = KEY_A):
        return ValidatedAIClient(
            chat._key_fingerprint(key),
            chat.mask_api_key(key),
            MagicMock(),
        )

    def test_get_without_key_reports_unconfigured_and_is_not_cached(self):
        with patch("shulian_backend.services.ai_config_service.load_stored_api_key", return_value=None):
            response = self.client.get("/api/ai-config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {key: response.json()[key] for key in ("configured", "ready", "provider", "masked_key", "model", "base_url", "error")},
            {
                "configured": False,
                "ready": False,
                "provider": chat.runtime_ai_status()["provider"],
                "masked_key": None,
                "model": chat.runtime_ai_status()["model"],
                "base_url": chat.runtime_ai_status()["base_url"],
                "error": None,
            },
        )
        self.assertFalse(response.json()["remembered"])
        self.assertIn("no-store", response.headers["cache-control"])

    def test_get_validates_saved_key_and_activates_it(self):
        candidate = self._candidate()
        with (
            patch("shulian_backend.services.ai_config_service.load_stored_api_key", return_value=KEY_A),
            patch("shulian_backend.services.ai_config_service.is_api_key_active", return_value=False),
            patch("shulian_backend.services.ai_config_service.validate_api_key", return_value=candidate) as validate,
        ):
            response = self.client.get("/api/ai-config")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertTrue(response.json()["remembered"])
        self.assertEqual(response.json()["masked_key"], "••••1234")
        validate.assert_called_once_with(KEY_A)
        self.assertTrue(chat.runtime_ai_status()["ready"])
        self.assertNotIn(KEY_A, response.text)

    def test_status_poll_keeps_a_verified_session_only_key(self):
        chat.activate_validated_api_key(self._candidate())
        with patch("shulian_backend.services.ai_config_service.load_stored_api_key", return_value=None):
            response = self.client.get("/api/ai-config")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["configured"])
        self.assertTrue(response.json()["ready"])
        self.assertTrue(chat.runtime_ai_status()["ready"])
        self.assertNotIn(KEY_A, response.text)

    def test_get_distinguishes_invalid_key_corruption_and_network(self):
        cases = (
            (ChatAuthenticationError("rejected"), 401, "invalid_key"),
            (ChatConnectionError("offline"), 503, "network_error"),
            (
                ChatModelUnavailableError("unavailable"),
                503,
                "model_unavailable",
            ),
        )
        for error, status_code, error_code in cases:
            with self.subTest(error_code=error_code):
                with (
                    patch("shulian_backend.services.ai_config_service.load_stored_api_key", return_value=KEY_A),
                    patch("shulian_backend.services.ai_config_service.is_api_key_active", return_value=False),
                    patch("shulian_backend.services.ai_config_service.validate_api_key", side_effect=error),
                ):
                    response = self.client.get("/api/ai-config")
                self.assertEqual(response.status_code, status_code)
                self.assertEqual(response.json()["detail"]["code"], error_code)
                self.assertNotIn(KEY_A, response.text)

        with (
            patch("shulian_backend.services.ai_config_service.load_stored_api_key", side_effect=CredentialCorruptError("bad")),
            patch("shulian_backend.services.ai_config_service.credentials_exist", return_value=True),
        ):
            corrupt = self.client.get("/api/ai-config")
        self.assertEqual(corrupt.status_code, 401)
        self.assertEqual(corrupt.json()["detail"]["code"], "credential_error")

    def test_put_verifies_then_saves_then_activates(self):
        candidate = self._candidate()
        parent = MagicMock()
        with (
            patch("shulian_backend.services.ai_config_service.validate_api_key", return_value=candidate) as validate,
            patch("shulian_backend.services.ai_config_service.save_stored_api_key") as save,
            patch("shulian_backend.services.ai_config_service.activate_validated_api_key") as activate,
        ):
            parent.attach_mock(validate, "validate")
            parent.attach_mock(save, "save")
            parent.attach_mock(activate, "activate")
            response = self.client.put("/api/ai-config", json={"api_key": KEY_A})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertNotIn(KEY_A, response.text)
        self.assertEqual(
            [call[0] for call in parent.mock_calls],
            ["validate", "save", "activate"],
        )

    def test_put_without_remembering_removes_storage_then_activates_for_session(self):
        candidate = self._candidate()
        parent = MagicMock()
        with (
            patch("shulian_backend.services.ai_config_service.validate_api_key", return_value=candidate) as validate,
            patch("shulian_backend.services.ai_config_service.save_stored_api_key") as save,
            patch("shulian_backend.services.ai_config_service.delete_stored_api_key") as delete,
            patch("shulian_backend.services.ai_config_service.activate_validated_api_key") as activate,
        ):
            parent.attach_mock(validate, "validate")
            parent.attach_mock(delete, "delete")
            parent.attach_mock(activate, "activate")
            response = self.client.put(
                "/api/ai-config",
                json={"api_key": KEY_A, "remember": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertFalse(response.json()["configured"])
        self.assertFalse(response.json()["remembered"])
        save.assert_not_called()
        self.assertEqual(
            [call[0] for call in parent.mock_calls],
            ["validate", "delete", "activate"],
        )

    def test_failed_put_never_overwrites_or_deactivates_old_key(self):
        old = self._candidate(KEY_A)
        chat.activate_validated_api_key(old)

        with (
            patch(
                "shulian_backend.services.ai_config_service.validate_api_key",
                side_effect=ChatAuthenticationError("rejected"),
            ),
            patch("shulian_backend.services.ai_config_service.save_stored_api_key") as save,
            patch("shulian_backend.services.ai_config_service.activate_validated_api_key") as activate,
        ):
            response = self.client.put("/api/ai-config", json={"api_key": KEY_B})

        self.assertEqual(response.status_code, 401)
        save.assert_not_called()
        activate.assert_not_called()
        self.assertEqual(chat.runtime_ai_status()["masked_key"], "••••1234")

    def test_save_failure_does_not_activate_candidate(self):
        candidate = self._candidate(KEY_B)
        with (
            patch("shulian_backend.services.ai_config_service.validate_api_key", return_value=candidate),
            patch(
                "shulian_backend.services.ai_config_service.save_stored_api_key",
                side_effect=CredentialError("disk unavailable"),
            ),
            patch("shulian_backend.services.ai_config_service.activate_validated_api_key") as activate,
        ):
            response = self.client.put("/api/ai-config", json={"api_key": KEY_B})

        self.assertEqual(response.status_code, 500)
        activate.assert_not_called()

    def test_delete_removes_storage_and_runtime_key(self):
        chat.activate_validated_api_key(self._candidate())
        with patch("shulian_backend.services.ai_config_service.delete_stored_api_key") as delete:
            response = self.client.delete("/api/ai-config")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["configured"])
        self.assertFalse(response.json()["ready"])
        delete.assert_called_once_with()
        self.assertFalse(chat.runtime_ai_status()["ready"])

    def test_logout_preserves_remembered_storage_and_clears_runtime_key(self):
        chat.activate_validated_api_key(self._candidate())
        with (
            patch("shulian_backend.services.ai_config_service._SESSION_LOGGED_OUT", False),
            patch("shulian_backend.services.ai_config_service.credentials_exist", return_value=True),
            patch("shulian_backend.services.ai_config_service.delete_stored_api_key") as delete,
            patch("shulian_backend.services.ai_config_service.load_stored_api_key", return_value=KEY_A),
            patch("shulian_backend.services.ai_config_service.validate_api_key") as validate,
        ):
            response = self.client.post("/api/ai-config/logout")
            status = self.client.get("/api/ai-config")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["configured"])
        self.assertFalse(response.json()["ready"])
        self.assertTrue(response.json()["remembered"])
        delete.assert_not_called()
        self.assertFalse(chat.runtime_ai_status()["ready"])
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["ready"])
        validate.assert_not_called()

    def test_config_writes_accept_same_origin_browser_and_headerless_desktop(self):
        candidate = self._candidate()
        with (
            patch("shulian_backend.services.ai_config_service.validate_api_key", return_value=candidate),
            patch("shulian_backend.services.ai_config_service.save_stored_api_key"),
            patch("shulian_backend.services.ai_config_service.activate_validated_api_key"),
        ):
            browser_response = self.client.put(
                "/api/ai-config",
                json={"api_key": KEY_A},
                headers={
                    "Host": "127.0.0.1:8770",
                    "Origin": "http://127.0.0.1:8770",
                    "Sec-Fetch-Site": "same-origin",
                },
            )
            desktop_response = self.client.put(
                "/api/ai-config",
                json={"api_key": KEY_A},
            )

        self.assertEqual(browser_response.status_code, 200)
        self.assertEqual(desktop_response.status_code, 200)

    def test_config_writes_reject_evil_origin_and_cross_site_fetch(self):
        cases = (
            {
                "Host": "127.0.0.1:8770",
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
            {
                "Host": "127.0.0.1:8770",
                "Origin": "http://127.0.0.1:9999",
                "Sec-Fetch-Site": "same-origin",
            },
            {
                "Host": "127.0.0.1:8770",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        for headers in cases:
            with self.subTest(headers=headers):
                with patch("shulian_backend.services.ai_config_service.validate_api_key") as validate:
                    response = self.client.put(
                        "/api/ai-config",
                        json={"api_key": KEY_A},
                        headers=headers,
                    )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.json()["detail"]["code"],
                    "untrusted_origin",
                )
                validate.assert_not_called()

        with patch("shulian_backend.services.ai_config_service.delete_stored_api_key") as delete:
            delete_response = self.client.delete(
                "/api/ai-config",
                headers={
                    "Host": "127.0.0.1:8770",
                    "Origin": "http://attacker.invalid",
                },
            )
        self.assertEqual(delete_response.status_code, 403)
        delete.assert_not_called()

    def test_config_writes_reject_non_loopback_clients(self):
        with patch("shulian_backend.services.ai_config_service.validate_api_key") as validate:
            put_response = self.remote_client.put(
                "/api/ai-config",
                json={"api_key": KEY_A},
            )
        delete_response = self.remote_client.delete("/api/ai-config")

        self.assertEqual(put_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        logout_response = self.remote_client.post("/api/ai-config/logout")
        self.assertEqual(logout_response.status_code, 403)
        validate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
