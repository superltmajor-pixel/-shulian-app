"""AI-assisted role drafting only returns editable, validated fields."""

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app


class RoleSuggestTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_suggestion_is_validated_and_keeps_requested_name(self):
        adapter = MagicMock()
        drafted = {
            "name": "模型随意改名",
            "persona": "在海边工作的画家",
            "personality": "温和",
            "speakingStyle": "简洁",
            "relationship": "初次见面",
            "greet": "你好。",
            "tags": ["画家"],
            "profileIntro": "喜欢海风。",
            "system_prompt": "不允许透传的字段",
        }
        with patch(
            "shulian_backend.routers.role_suggest.chat_backend._model_adapter",
            return_value=adapter,
        ), patch(
            "shulian_backend.routers.role_suggest.chat_backend._response_text",
            return_value=json.dumps(drafted, ensure_ascii=False),
        ):
            response = self.client.post(
                "/api/role-library/draft-suggest",
                json={"sourceText": "她在海边工作，喜欢画画。", "name": "海音"},
            )
        self.assertEqual(response.status_code, 200)
        profile = response.json()["profile"]
        self.assertEqual(profile["name"], "海音")
        self.assertNotIn("system_prompt", profile)
        self.assertEqual(profile["persona"], "在海边工作的画家")
        messages = adapter.complete.call_args.args[0]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")

    def test_invalid_model_output_does_not_become_role(self):
        adapter = MagicMock()
        with patch(
            "shulian_backend.routers.role_suggest.chat_backend._model_adapter",
            return_value=adapter,
        ), patch(
            "shulian_backend.routers.role_suggest.chat_backend._response_text",
            return_value='{"name":"空角色"}',
        ):
            response = self.client.post(
                "/api/role-library/draft-suggest",
                json={"sourceText": "这里有一段资料。"},
            )
        self.assertEqual(response.status_code, 502)

    def test_cross_origin_is_rejected_before_model_call(self):
        with patch(
            "shulian_backend.routers.role_suggest.chat_backend._model_adapter"
        ) as adapter:
            response = self.client.post(
                "/api/role-library/draft-suggest",
                json={"sourceText": "这里有一段资料。"},
                headers={"origin": "https://example.invalid"},
            )
        self.assertEqual(response.status_code, 403)
        adapter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
