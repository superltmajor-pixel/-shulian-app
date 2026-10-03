import base64
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import chat
from ai_preferences import DEFAULT_MODEL, SUPPORTED_MODELS
from shulian_backend.routers.chat import chat_with_character
from shulian_backend.schemas.api import ChatRequest
from shulian_backend.services.context_compiler import CompiledContext
from shulian_backend.services.vision_grounding_service import VisualEntity, VisionFacts


VISION_MODEL = "deepseek-flash"
ROOT = Path(__file__).resolve().parents[1]


class V4VisionRouteTests(unittest.TestCase):
    def tearDown(self):
        chat.clear_api_client()

    def test_formal_default_is_the_single_vision_model(self):
        self.assertEqual(DEFAULT_MODEL, VISION_MODEL)
        self.assertEqual(
            SUPPORTED_MODELS,
            (VISION_MODEL, "doubao-seed-character-260628"),
        )

    def test_deepseek_validation_discards_old_text_models(self):
        client = MagicMock()
        client.models.list.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(id="deepseek-v4-flash"),
                SimpleNamespace(id=VISION_MODEL),
                SimpleNamespace(id="deepseek-v4-pro"),
            ]
        )
        with patch("chat._new_client", return_value=client):
            candidate = chat.validate_api_key("sk-example-key")

        self.assertEqual(candidate.model, VISION_MODEL)
        self.assertEqual(candidate.model_options, (VISION_MODEL,))

    def test_image_data_url_is_grounded_without_reaching_role_model(self):
        jpeg = b"\xff\xd8\xff\xe0formal-vision-test"
        image_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        request = ChatRequest(message="请看看这张图", channel="image", image_url=image_url)
        compiled = CompiledContext(
            messages=[
                {"role": "system", "content": "stay in character"},
                {"role": "user", "content": request.message},
            ],
            companion_context={},
            relevant_experiences=(),
        )

        facts = VisionFacts(
            model=VISION_MODEL,
            summary="画面中有一只白色杯子。",
            entities=(VisualEntity("object", "白色杯子", "high"),),
            visible_text=(),
            uncertainties=(),
        )
        with patch("chat.analyze_image", return_value=facts), patch("chat.log_event"):
            result = chat._with_vision_context(compiled, request.image_url)

        self.assertIn("画面中有一只白色杯子", result.messages[-1]["content"])
        self.assertIn("主体归因规则", result.messages[-1]["content"])
        self.assertNotIn("data:image", result.messages[-1]["content"])
        self.assertEqual(result.image_grounding.subject_relation, "unknown")
        self.assertIsInstance(compiled.messages[-1]["content"], str)

    def test_invalid_or_mismatched_image_data_is_rejected(self):
        with self.assertRaises(ValueError):
            ChatRequest(message="看图", image_url="https://example.test/image.png")
        bad_png = "data:image/png;base64," + base64.b64encode(b"not-a-png").decode("ascii")
        with self.assertRaises(ValueError):
            ChatRequest(message="看图", image_url=bad_png)

    def test_chat_router_forwards_the_validated_image_to_model_backend(self):
        jpeg = b"\xff\xd8\xff\xe0router-vision-test"
        image_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        request = ChatRequest(message="看看这个", channel="image", image_url=image_url)
        status = {"character_id": "sample_a", "label": "休息中"}
        with (
            patch("shulian_backend.routers.chat.get_schedule_status", return_value=status),
            patch("shulian_backend.routers.chat.get_character_status", return_value=status),
            patch("shulian_backend.routers.chat.recover_recent_rest_scene"),
            patch(
                "shulian_backend.routers.chat.chat_backend.get_reply",
                return_value="我看到了。",
            ) as get_reply,
        ):
            response = chat_with_character("sample_a", request)

        self.assertEqual(response.reply, "我看到了。")
        self.assertEqual(get_reply.call_args.kwargs["image_url"], image_url)
        self.assertEqual(get_reply.call_args.kwargs["image_caption"], "")
        self.assertEqual(get_reply.call_args.kwargs["channel"], "image")

    def test_old_image_request_is_normalized_to_image_channel(self):
        jpeg = b"\xff\xd8\xff\xe0legacy-channel-test"
        image_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        request = ChatRequest(message="看看这个", image_url=image_url)
        self.assertEqual(request.channel, "image")

    def test_frontend_sends_image_instead_of_placeholder_only(self):
        source = (ROOT / "web" / "app.jsx").read_text(encoding="utf-8")
        self.assertIn("image_url: imageUrl", source)
        self.assertIn("image_caption: cleanCaption", source)
        self.assertNotIn("请先认真观察图片，再以角色身份自然回应", source)
        self.assertNotIn("不要假装能看到图片的具体内容", source)


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
