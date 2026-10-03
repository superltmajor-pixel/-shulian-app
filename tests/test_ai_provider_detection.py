import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import chat
from ai_provider import candidate_profiles, configured_profile, model_candidates


class ProviderCatalogTests(unittest.TestCase):
    def test_ark_key_is_routed_only_to_doubao(self):
        profiles = candidate_profiles("ark-example-key")
        self.assertEqual([profile.id for profile in profiles], ["doubao"])

    def test_generic_key_is_routed_only_to_deepseek(self):
        profiles = candidate_profiles("sk-example-key")
        ids = [profile.id for profile in profiles]
        self.assertEqual(ids, ["deepseek"])

    def test_provider_catalog_cannot_add_arbitrary_models(self):
        profile = candidate_profiles("sk-example-key")[0]
        options = model_candidates(
            [
                "inception/mercury-2.5",
                "deepseek-flash",
                "deepseek-v4-pro",
                "openai/gpt-4o-mini",
            ],
            profile,
        )
        self.assertEqual(options, ("deepseek-flash",))

    def test_explicit_custom_endpoint_remains_supported(self):
        profile = configured_profile(
            {
                "SHULIAN_AI_PROVIDER": "auto",
                "SHULIAN_BASE_URL": "https://example.test/v1",
                "SHULIAN_PROVIDER_LABEL": "测试服务",
            }
        )
        self.assertEqual(profile.id, "custom")
        self.assertEqual(profile.label, "测试服务")
        self.assertEqual(profile.base_url, "https://example.test/v1")


class ProviderDetectionRuntimeTests(unittest.TestCase):
    def setUp(self):
        chat.clear_api_client()

    def tearDown(self):
        chat.clear_api_client()

    @staticmethod
    def _client(*model_ids):
        client = MagicMock()
        client.models.list.return_value = SimpleNamespace(
            data=[SimpleNamespace(id=model_id) for model_id in model_ids]
        )
        return client

    def test_doubao_key_selects_endpoint_model_without_env_model(self):
        doubao = self._client("doubao-seed-character-260628", "unrelated-model")

        with patch.dict(
            os.environ,
            {"SHULIAN_AI_PROVIDER": "auto", "SHULIAN_BASE_URL": ""},
            clear=False,
        ), patch("chat._new_client", return_value=doubao) as new_client:
            candidate = chat.validate_api_key("ark-example-key")

        self.assertEqual(candidate.provider_profile.id, "doubao")
        self.assertEqual(candidate.model, "doubao-seed-character-260628")
        self.assertEqual(candidate.model_options, ("doubao-seed-character-260628",))
        self.assertEqual(new_client.call_args.args[1], candidate.provider_profile.base_url)

    def test_deepseek_catalog_may_omit_vision_model_without_changing_it(self):
        deepseek = self._client("deepseek-flash", "deepseek-v4-pro")
        with patch.dict(
            os.environ,
            {"SHULIAN_AI_PROVIDER": "auto", "SHULIAN_BASE_URL": ""},
            clear=False,
        ), patch("chat._new_client", return_value=deepseek) as new_client:
            candidate = chat.validate_api_key("sk-example-key")

        self.assertEqual(candidate.provider_profile.id, "deepseek")
        self.assertEqual(candidate.model, "deepseek-flash")
        self.assertEqual(candidate.model_options, ("deepseek-flash",))
        self.assertEqual(new_client.call_count, 1)
        self.assertEqual(new_client.call_args.args[1], "https://api.deepseek.com")
        chat.activate_validated_api_key(candidate)
        status = chat.runtime_ai_status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["provider"], "deepseek")
        self.assertEqual(status["base_url"], "https://api.deepseek.com")


if __name__ == "__main__":
    unittest.main()
