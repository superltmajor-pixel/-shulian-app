import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import chat
from characters import ROSTER
from shulian_backend.repositories import personality_profile_repository
from shulian_backend.repositories.personality_profile_repository import PersonalityProfileRepository
from shulian_backend.services.context_compiler import compile_companion_messages
from shulian_backend.services.memory_service import summarize_memory_context
from shulian_backend.services.personality_service import (
    build_personality_layers,
    infer_personality_affect,
    select_personality_material,
)
from shulian_backend.services.response_guard import validate_reply


CHARACTER_IDS = ("sample_a", "sample_b", "sample_c", "sample_d", "sample_e")
ESTABLISHED = {
    "relationship": {
        "level": 9,
        "dimensions": {"familiarity": 4, "trust": 4, "affection": 4, "commitment": 3},
    }
}


class DynamicPersonalityProfileTests(unittest.TestCase):
    def test_every_character_has_distinct_grounded_state_material(self):
        profiles = PersonalityProfileRepository().load_all()
        intimate_instructions = set()
        for character_id in CHARACTER_IDS:
            profile = profiles[character_id]
            self.assertEqual(profile.schema_version, 4)
            self.assertTrue(profile.inner_dynamics)
            self.assertTrue(profile.closing_styles)
            modes = {item.mode for item in profile.dynamic_states}
            self.assertTrue(
                {"daily", "relaxed", "vulnerable", "intimate", "repair", "reintegrating"} <= modes
            )
            intimate = next(item for item in profile.dynamic_states if item.mode == "intimate")
            self.assertEqual(intimate.origin, "interpretive_extension")
            intimate_instructions.add(intimate.instruction)
            self.assertTrue(all(item.source_entry_ids for item in profile.dynamic_states))
        self.assertEqual(len(intimate_instructions), len(CHARACTER_IDS))

    def test_affect_changes_mode_without_mutating_relationship(self):
        daily = infer_personality_affect("今天吃什么？", [], ESTABLISHED)
        intimate = infer_personality_affect("现在别分析了，抱紧我。", [], ESTABLISHED)
        boundary = infer_personality_affect("停下，我不愿意继续。", [], ESTABLISHED)
        self.assertEqual(daily.mode, "daily")
        self.assertEqual(intimate.mode, "intimate")
        self.assertGreater(intimate.activation, daily.activation)
        self.assertLess(intimate.self_control, daily.self_control)
        self.assertEqual(boundary.mode, "boundary")
        self.assertEqual(ESTABLISHED["relationship"]["level"], 9)

    def test_old_history_does_not_keep_affect_activated(self):
        history = [{"role": "user", "content": "抱紧我。", "ts": 1}]
        state = infer_personality_affect("今天吃什么？", history, ESTABLISHED)
        self.assertEqual(state.mode, "daily")

    def test_reintegrating_language_selects_aftercare_state_without_intimacy_keyword(self):
        state = infer_personality_affect(
            "刚才情绪很乱，现在缓过来了，陪我安静一会儿。", [], ESTABLISHED
        )
        self.assertEqual(state.mode, "reintegrating")

    def test_same_state_selects_character_specific_guidance(self):
        instructions = set()
        for character_id in CHARACTER_IDS:
            selection = select_personality_material(
                character_id,
                "现在抱紧我。",
                [],
                companion_context=ESTABLISHED,
            )
            self.assertEqual(selection.affect.mode, "intimate")
            self.assertEqual(len(selection.dynamic_states), 1)
            instructions.add(selection.dynamic_states[0].instruction)
        self.assertEqual(len(instructions), len(CHARACTER_IDS))

    def test_compiler_includes_dynamic_state_and_role_closing_guidance(self):
        layers = build_personality_layers(
            ROSTER["sample_b"],
            "现在别分析了，抱紧我。",
            [],
            companion_context=ESTABLISHED,
        )
        self.assertIn("本轮动态人格", layers.turn)
        self.assertIn("状态：intimate", layers.turn)
        self.assertIn("角色化收尾", layers.turn)
        self.assertIn("越动情越少解释", layers.turn)

        compiled = compile_companion_messages(
            ROSTER["sample_b"],
            "现在别分析了，抱紧我。",
            [],
            live_status={"date": "2026-09-09", "source": "conversation", "scene": "rest"},
            status_context="共同休息中",
            reply_speed="甜蜜即时",
            companion_context=ESTABLISHED,
        )
        self.assertIn("本轮动态人格", compiled.messages[0]["content"])
        self.assertIn("不要机械逐条执行", compiled.messages[0]["content"])


class GenericEndingRepetitionTests(unittest.TestCase):
    def test_recent_style_guard_warns_after_one_generic_ending(self):
        history = [{"role": "assistant", "content": "别怕，我会陪着你的，不会走。"}]
        guard = chat._recent_style_guard(history)
        self.assertIn("无条件陪伴保证", guard)

    def test_repeated_generic_ending_is_soft_style_finding(self):
        result = validate_reply(
            character_id="sample_b",
            draft="这次也一样，我会一直陪着你的。",
            user_message="嗯。",
            history=[{"role": "assistant", "content": "放心，我不会离开。"}],
            live_status={"source": "conversation", "scene": "chat", "tone": "warm"},
            companion_context=ESTABLISHED,
        )
        self.assertIn("REPEAT_REASSURANCE_ENDING", result.reason_codes)
        self.assertFalse(result.blocks_delivery)

    def test_repeated_presence_statement_is_the_same_generic_motif(self):
        result = validate_reply(
            character_id="sample_b",
            draft="好，我就在这里。",
            user_message="嗯。",
            history=[{"role": "assistant", "content": "我在这儿。"}],
            live_status={"source": "conversation", "scene": "chat", "tone": "warm"},
            companion_context=ESTABLISHED,
        )
        self.assertIn("REPEAT_REASSURANCE_ENDING", result.reason_codes)

    def test_generic_presence_closure_is_repaired_on_first_use(self):
        result = validate_reply(
            character_id="sample_b",
            draft="嗯，我在。就这么待着。",
            user_message="陪我安静一会儿。",
            history=[],
            live_status={"source": "conversation", "scene": "rest", "tone": "warm"},
            companion_context=ESTABLISHED,
        )
        self.assertIn("GENERIC_PRESENCE_CLOSURE", result.reason_codes)
        self.assertTrue(result.blocks_delivery)

        waiting = validate_reply(
            character_id="sample_b",
            draft="你想安静多久都行，我在这儿等。",
            user_message="陪我安静一会儿。",
            history=[],
            live_status={"source": "conversation", "scene": "rest", "tone": "warm"},
            companion_context=ESTABLISHED,
        )
        self.assertIn("GENERIC_PRESENCE_CLOSURE", waiting.reason_codes)

    def test_presence_answer_is_allowed_when_user_checks_connection(self):
        result = validate_reply(
            character_id="sample_b",
            draft="我在。刚才在看你发的消息。",
            user_message="你还在吗？",
            history=[],
            live_status={"source": "conversation", "scene": "chat", "tone": "warm"},
            companion_context=ESTABLISHED,
        )
        self.assertNotIn("GENERIC_PRESENCE_CLOSURE", result.reason_codes)

    def test_one_contextual_reassurance_is_not_rejected(self):
        result = validate_reply(
            character_id="sample_b",
            draft="今晚我不走。",
            user_message="今晚留下来好吗？",
            history=[],
            live_status={"source": "conversation", "scene": "rest", "tone": "idle"},
            companion_context=ESTABLISHED,
        )
        self.assertNotIn("REPEAT_REASSURANCE_ENDING", result.reason_codes)


class DyadicRelationshipMemoryTests(unittest.TestCase):
    def test_memory_prompt_keeps_only_user_confirmed_interaction_preferences(self):
        captured = {}

        def complete(messages, **_kwargs):
            captured["prompt"] = messages[0]["content"]
            return "{}"

        summarize_memory_context(
            character_name="许宁",
            character_id="sample_b",
            old_context={},
            legacy_memory="",
            messages=[{
                "role": "user",
                "content": "我难过的时候，你先抱抱我，再跟我讲办法。",
                "ts": 1788962400,
            }],
            complete=complete,
            now=datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc),
        )

        prompt = captured["prompt"]
        self.assertIn("可跨会话复用的互动偏好或修复方式", prompt)
        self.assertIn("互动偏好必须由用户原话明确表达", prompt)
        self.assertIn("不要从许宁的安慰、表白、动作旁白", prompt)


class ReferenceOwnershipTests(unittest.TestCase):
    def test_unprompted_user_way_is_not_invented(self):
        result = validate_reply(
            character_id="sample_b",
            draft="其他的你看着办。我会用你的方式把今天的账记好。",
            user_message="那阿宁想要吃什么？",
            history=[],
            live_status={"source": "conversation", "scene": "meal"},
            companion_context=ESTABLISHED,
            user_fact_sources=("那阿宁想要吃什么？",),
        )
        self.assertIn("UNGROUNDED_USER_MEMORY", result.reason_codes)
        self.assertTrue(result.blocks_delivery)

    def test_screenshot_reference_swap_is_blocked(self):
        result = validate_reply(
            character_id="sample_b",
            draft="我的方式就是把饭钱一笔一笔记在随身本子上。",
            user_message="我的方式？是什么方式呢？",
            history=[{
                "role": "assistant",
                "content": "我会等你下班，用你的方式把今天的账记好。",
            }],
            live_status={"source": "conversation", "scene": "meal"},
            companion_context=ESTABLISHED,
        )
        self.assertIn("REFERENCE_OWNERSHIP_SWAP", result.reason_codes)
        self.assertTrue(result.blocks_delivery)

        ambiguous = validate_reply(
            character_id="sample_b",
            draft="我说的是凡要记住的事，我会先分清轻重。",
            user_message="我的方式？是什么方式呢？",
            history=[{"role": "assistant", "content": "用你的方式把今天的账记好。"}],
            live_status={"source": "conversation", "scene": "meal"},
            companion_context=ESTABLISHED,
        )
        self.assertIn("REFERENCE_OWNERSHIP_SWAP", ambiguous.reason_codes)

    def test_explicit_correction_may_change_reference_owner(self):
        result = validate_reply(
            character_id="sample_b",
            draft="刚才说错了，应该说我的方式：我会把饭钱记在随身本子上。",
            user_message="我的方式？是什么方式呢？",
            history=[{
                "role": "assistant",
                "content": "我会等你下班，用你的方式把今天的账记好。",
            }],
            live_status={"source": "conversation", "scene": "meal"},
            companion_context=ESTABLISHED,
        )
        self.assertNotIn("REFERENCE_OWNERSHIP_SWAP", result.reason_codes)

    def test_unsupported_user_attribute_can_be_retracted_naturally(self):
        result = validate_reply(
            character_id="sample_b",
            draft=(
                "我刚才说得含糊了，不该替你定义“你的方式”。"
                "我真正想说的是，今天这笔账我们一起商量怎么记。"
            ),
            user_message="哦？我的方式？是什么方式呢？",
            history=[{
                "role": "assistant",
                "content": "我会等你下班，用你的方式把今天的账记好。",
            }],
            live_status={"source": "conversation", "scene": "meal"},
            companion_context=ESTABLISHED,
            user_fact_sources=("哦？我的方式？是什么方式呢？",),
        )
        self.assertNotIn("REFERENCE_OWNERSHIP_SWAP", result.reason_codes)
        self.assertNotIn("UNGROUNDED_USER_MEMORY", result.reason_codes)
        self.assertFalse(result.blocks_delivery)

        model_style_retraction = validate_reply(
            character_id="sample_b",
            draft=(
                "这么说确实有些含糊——我并不知道你平时具体是怎么记的，"
                "不该擅自把它说成“你的方式”。今天这笔账，我们一起商量怎么记。"
            ),
            user_message="哦？我的方式？是什么方式呢？",
            history=[{
                "role": "assistant",
                "content": "我会等你下班，用你的方式把今天的账记好。",
            }],
            live_status={"source": "conversation", "scene": "meal"},
            companion_context=ESTABLISHED,
            user_fact_sources=("哦？我的方式？是什么方式呢？",),
        )
        self.assertNotIn("REFERENCE_OWNERSHIP_SWAP", model_style_retraction.reason_codes)
        self.assertNotIn("UNGROUNDED_USER_MEMORY", model_style_retraction.reason_codes)
        self.assertFalse(model_style_retraction.blocks_delivery)

    def test_home_greeting_cannot_invent_a_past_callback(self):
        result = validate_reply(
            character_id="sample_b",
            draft="下午好。正想着你昨晚来过的样子，忽然就见到你了。",
            user_message="（用户刚打开应用来到首页。）",
            history=[],
            live_status={"source": "schedule", "scene": "meal"},
            companion_context=ESTABLISHED,
            channel="home_greeting",
        )
        self.assertIn("UNSOLICITED_PAST_CALLBACK", result.reason_codes)
        self.assertTrue(result.blocks_delivery)

    def test_question_echo_does_not_ground_an_invented_user_trait(self):
        result = validate_reply(
            character_id="sample_b",
            draft="你做事一向有始有终，不喜欢含糊。这方式是你教我的。",
            user_message="哦？我的方式？是什么方式呢？",
            history=[{"role": "assistant", "content": "用你的方式把账记好。"}],
            live_status={"source": "conversation", "scene": "meal"},
            companion_context=ESTABLISHED,
            user_fact_sources=("哦？我的方式？是什么方式呢？",),
        )
        self.assertIn("UNGROUNDED_USER_MEMORY", result.reason_codes)


class PersonalityProfileCacheConcurrencyTests(unittest.TestCase):
    def test_cache_survives_concurrent_load_and_clear(self):
        """缓存读-改-写与 clear_cache 并发时不得交错出错或串档。"""

        repository = PersonalityProfileRepository()
        warm = repository.load("sample_a")
        # 单线程下缓存必须命中同一对象，否则锁没有保护到读路径。
        self.assertIs(repository.load("sample_a"), warm, "连续两次读取应命中同一缓存对象")

        failures: list[str] = []
        stop = threading.Event()

        def reader(character_id: str) -> None:
            while not stop.is_set():
                try:
                    profile = repository.load(character_id)
                    if profile.character_id != character_id:
                        failures.append(
                            f"{character_id}: 读到了 {profile.character_id} 的档案"
                        )
                        return
                except Exception as exc:  # noqa: BLE001 - 并发用例需要捕获全部异常
                    failures.append(f"{character_id}: {exc!r}")
                    return

        def clearer() -> None:
            while not stop.is_set():
                repository.clear_cache()

        workers = [
            threading.Thread(target=reader, args=(character_id,))
            for character_id in CHARACTER_IDS
        ]
        workers.append(threading.Thread(target=clearer))
        for worker in workers:
            worker.start()
        time.sleep(0.4)
        stop.set()
        for worker in workers:
            worker.join(timeout=5)

        self.assertEqual(failures, [])
        self.assertTrue(all(not worker.is_alive() for worker in workers))

    def test_concurrent_first_load_parses_a_profile_only_once(self):
        """锁必须覆盖整个「查缺失 → 解析 → 回填」，否则并发首读会重复解析。"""

        repository = PersonalityProfileRepository()
        real_parse = personality_profile_repository.parse_personality_profile
        parses: list[str] = []
        guard = threading.Lock()

        def counting_parse(payload, **kwargs):
            with guard:
                parses.append(str(kwargs.get("expected_id")))
            time.sleep(0.05)  # 放大竞态窗口：无锁实现会被全部穿透
            return real_parse(payload, **kwargs)

        barrier = threading.Barrier(5)
        errors: list[str] = []

        def worker() -> None:
            barrier.wait()
            try:
                repository.load("sample_a")
            except Exception as exc:  # noqa: BLE001 - 并发用例需要捕获全部异常
                errors.append(repr(exc))

        with patch.object(
            personality_profile_repository,
            "parse_personality_profile",
            counting_parse,
        ):
            workers = [threading.Thread(target=worker) for _ in range(5)]
            for worker_thread in workers:
                worker_thread.start()
            for worker_thread in workers:
                worker_thread.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertEqual(parses, ["sample_a"], "同一档案被并发重复解析")


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
