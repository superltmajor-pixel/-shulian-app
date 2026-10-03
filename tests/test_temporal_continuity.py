import json
import unittest
from datetime import datetime, timezone

from characters import ROSTER
from shulian_backend.schemas.api import Message
from shulian_backend.services.context_compiler import compile_companion_messages
from shulian_backend.services.memory_service import (
    normalize_memory_context,
    summarize_memory_context,
)


class TemporalContinuityTests(unittest.TestCase):
    def test_relative_recent_events_are_not_persisted(self):
        now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
        result = normalize_memory_context(
            {
                "recent_events": [
                    {
                        "text": "用户与许宁今天去了月老祠。",
                        "captured_at": "2026-09-07T10:00:00+00:00",
                        "expires_at": "2026-09-08T10:00:00+00:00",
                    },
                    {
                        "text": "用户与许宁于2026-09-07去了月老祠。",
                        "captured_at": "2026-09-07T10:00:00+00:00",
                        "expires_at": "2026-09-08T10:00:00+00:00",
                    },
                    {
                        "text": "用户与许宁于2026-09-07今天去了月老祠。",
                        "captured_at": "2026-09-07T10:00:00+00:00",
                        "expires_at": "2026-09-08T10:00:00+00:00",
                    },
                ]
            },
            now=now,
        )
        self.assertEqual(
            [event["text"] for event in result["recent_events"]],
            ["用户与许宁于2026-09-07去了月老祠。"],
        )

    def test_history_time_and_origin_are_rendered_for_model(self):
        compiled = compile_companion_messages(
            ROSTER["sample_b"],
            "现在想和你聊聊。",
            [
                {
                    "role": "assistant",
                    "content": "我刚整理好手头的事。",
                    "ts": 1788782400000,
                    "origin": "new-chat-opening",
                },
            ],
            live_status={},
            status_context="",
            reply_speed="日常自然",
            companion_context={},
            memory_context="",
        )
        history = compiled.messages[1:-1]
        self.assertEqual(len(history), 1)
        self.assertIn("我刚整理好手头的事。", history[0]["content"])
        self.assertNotIn("【消息时间", history[0]["content"])
        self.assertIn("消息时间：2026-09-07", compiled.messages[0]["content"])
        self.assertIn("来源：新对话开场", compiled.messages[0]["content"])
        self.assertIn("【时间连续性】", compiled.messages[0]["content"])

    def test_memory_prompt_has_absolute_times_and_rejects_relative_output(self):
        prompts = []

        def complete(messages, **_kwargs):
            prompts.append(messages[0]["content"])
            return json.dumps({"recent_events": ["今天去了月老祠。"]}, ensure_ascii=False)

        result = summarize_memory_context(
            character_name="许宁",
            character_id="sample_b",
            old_context="",
            legacy_memory="",
            messages=[
                {
                    "role": "user",
                    "content": "我们今天去了月老祠。",
                    "ts": 1788746400000,
                }
            ],
            complete=complete,
            now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
        )
        self.assertIn("[消息时间：2026-09-07 10:00]", prompts[0])
        self.assertIn("每条 recent_events 必须带消息对应的绝对日期", prompts[0])
        self.assertEqual(json.loads(result)["recent_events"], [])

    def test_message_schema_accepts_legacy_and_timestamped_history(self):
        self.assertEqual(Message(role="user", content="旧客户端").ts, None)
        message = Message(role="assistant", content="带时间", ts=1788782400000, origin="proactive")
        self.assertEqual(message.ts, 1788782400000)
        self.assertEqual(message.origin, "proactive")


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
