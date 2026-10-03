"""同源约束：跨模块共享的词表与门槛只能有一份定义。

这些常量原先在生成前/生成后、记忆/关系、状态卡片等多处各存一份，改一处就会
悄悄分叉（历史上 ``REPEAT_STARTLE`` 就丢掉过「明显顿住」）。这里用断言把它们
钉在 ``shulian_backend.domain`` 上：既是回归防线，也是给下一位改动者的说明书。
"""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "shulian_backend" / "services"


class DomainSingleSourceTests(unittest.TestCase):
    def test_explicit_content_cues_are_shared_by_memory_and_companion_context(self):
        from shulian_backend.domain import EXPLICIT_CONTENT_CUES
        from shulian_backend.services import companion_context_service, memory_service

        self.assertIs(memory_service.EXPLICIT_CONTENT_CUES, EXPLICIT_CONTENT_CUES)
        self.assertIs(companion_context_service.EXPLICIT_CONTENT_CUES, EXPLICIT_CONTENT_CUES)

        # 并集必须同时覆盖两份旧词表，不再出现「一处拦、一处放行」。
        cues = set(EXPLICIT_CONTENT_CUES)
        for word in (
            "床上", "裸", "射", "私密部位",  # 旧 _SENSITIVE_CUES 的软边界
            "肛交", "后庭", "射精", "舔舐", "手交", "指交", "床笫",  # 旧 _PRIVATE_CUES 独有
        ):
            self.assertIn(word, cues)
        self.assertEqual(len(EXPLICIT_CONTENT_CUES), len(cues), "词表存在重复项")

        for module in (memory_service, companion_context_service):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn("_SENSITIVE_CUES", source)
            self.assertNotIn("_PRIVATE_CUES", source)

    def test_repeat_motifs_are_shared_by_prompt_and_guard(self):
        import chat

        from shulian_backend.domain import REPEAT_ENDING_MOTIFS, REPEAT_MOTIFS
        from shulian_backend.services import response_guard

        self.assertIs(chat.REPEAT_MOTIFS, REPEAT_MOTIFS)
        self.assertIs(chat.REPEAT_ENDING_MOTIFS, REPEAT_ENDING_MOTIFS)
        self.assertIs(response_guard.REPEAT_MOTIFS, REPEAT_MOTIFS)
        self.assertIs(response_guard.REPEAT_ENDING_MOTIFS, REPEAT_ENDING_MOTIFS)

        # 曾经的漂移：生成前的提示认「明显顿住」，生成后的检测却不认。
        motifs = {code: cues for code, _label, cues in REPEAT_MOTIFS}
        self.assertIn("明显顿住", motifs["REPEAT_STARTLE"])
        self.assertEqual(
            set(motifs),
            {
                "REPEAT_BLUSH",
                "REPEAT_GAZE",
                "REPEAT_SOFT_VOICE",
                "REPEAT_FINGERS",
                "REPEAT_STARTLE",
            },
        )
        self.assertEqual(
            {code for code, _label, _cues in REPEAT_ENDING_MOTIFS},
            {
                "REPEAT_REASSURANCE_ENDING",
                "REPEAT_BURDEN_ENDING",
                "REPEAT_THERAPIST_ENDING",
            },
        )

        for module in (chat, response_guard):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn("_REPETITION_MOTIFS =", source)
            self.assertNotIn("_REPETITION_ENDING_MOTIFS =", source)

    def test_live_status_tone_colors_have_one_definition(self):
        import status_engine

        from shulian_backend.domain import LIVE_STATUS_TONES, tone_color
        from shulian_backend.services import scene_status_service

        self.assertIs(status_engine.LIVE_STATUS_TONES, LIVE_STATUS_TONES)
        self.assertFalse(hasattr(scene_status_service, "_TONE_COLORS"))
        self.assertEqual(tone_color("sleep"), "#8b97c9")
        # 未知色调回落到默认色，而不是旧实现的 KeyError。
        self.assertEqual(tone_color("no-such-tone"), "#7ee0a4")

        source = (SERVICES / "scene_status_service.py").read_text(encoding="utf-8")
        self.assertIn('tone_color(spec["tone"])', source)

    def test_relationship_level_thresholds_are_named_constants(self):
        from shulian_backend.domain import (
            GUARD_COMMITMENT_LEVEL,
            GUARD_STAGE_LEVEL,
            LEVEL_LIFELONG,
            LEVEL_MUTUAL_AFFECTION,
            LEVEL_SHARED_FUTURE,
        )

        self.assertEqual(
            (LEVEL_MUTUAL_AFFECTION, LEVEL_SHARED_FUTURE, LEVEL_LIFELONG),
            (6, 7, 10),
        )
        self.assertEqual(GUARD_STAGE_LEVEL, LEVEL_MUTUAL_AFFECTION)
        self.assertEqual(GUARD_COMMITMENT_LEVEL, LEVEL_LIFELONG)

        companion = (SERVICES / "companion_context_service.py").read_text(encoding="utf-8")
        guard = (SERVICES / "response_guard.py").read_text(encoding="utf-8")
        self.assertIn("max(target_level, LEVEL_MUTUAL_AFFECTION)", companion)
        self.assertIn("max(target_level, LEVEL_SHARED_FUTURE)", companion)
        self.assertIn("target_level = LEVEL_LIFELONG", companion)
        self.assertIn("level >= GUARD_STAGE_LEVEL", guard)
        self.assertIn("level >= GUARD_COMMITMENT_LEVEL", guard)

        self.assertNotIn("max(target_level, 6)", companion)
        self.assertNotIn("max(target_level, 7)", companion)
        self.assertNotIn("target_level = 10", companion)
        self.assertNotIn("level >= 6 ", guard)
        self.assertNotIn("level >= 10 ", guard)


if __name__ == "__main__":
    unittest.main()
