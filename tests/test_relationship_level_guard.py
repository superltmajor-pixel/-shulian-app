import unittest

from shulian_backend.services.companion_context_service import (
    consolidate_companion_context,
    default_companion_context,
)


class RelationshipLevelGuardTests(unittest.TestCase):
    def consolidate_pair(self, user_text: str, assistant_text: str):
        return consolidate_companion_context(
            "sample_a",
            default_companion_context("sample_a"),
            current_messages=[
                {"from": "me", "text": user_text, "ts": 1},
                {"from": "her", "text": assistant_text, "ts": 2},
            ],
        )

    def test_ex_partner_breakup_story_does_not_downgrade_current_relationship(self):
        context, result = self.consolidate_pair(
            "前对象总是嫌弃我头发少，太胖，然后后面就被分手了",
            "那个人太没眼光。本座早就接受了你的全部。",
        )

        self.assertEqual(context["relationship"]["level"], 10)
        self.assertEqual(context["relationship"]["title"], "永恒契约")
        self.assertNotIn("relationship_redefined", context["relationship"]["confirmed_events"])
        self.assertFalse(result["stage_changed"])

    def test_explicit_mutual_breakup_can_redefine_relationship(self):
        context, result = self.consolidate_pair(
            "我们分手吧，结束我们的关系",
            "我尊重你的决定，我们的关系到此结束。",
        )

        self.assertEqual(context["relationship"]["level"], 4)
        self.assertEqual(context["relationship"]["title"], "信赖")
        self.assertIn("relationship_redefined", context["relationship"]["confirmed_events"])
        self.assertTrue(result["stage_changed"])

    def test_generic_acceptance_word_is_not_breakup_acceptance(self):
        context, _ = self.consolidate_pair(
            "我们分手吧",
            "我接受你的全部，但不同意分手。",
        )

        self.assertEqual(context["relationship"]["level"], 10)
        self.assertNotIn("relationship_redefined", context["relationship"]["confirmed_events"])


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
