import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import chat
from shulian_backend.services.context_compiler import CompiledContext
from shulian_backend.services.response_guard import normalize_action_narration, validate_reply


class ActionNarrationRecoveryTests(unittest.TestCase):
    def test_internal_timestamp_is_removed_without_another_model_request(self):
        adapter = MagicMock()
        adapter.complete.return_value = self.response('【消息时间：2026-09-07 21:37】\n怎么了，突然闷闷的。')
        self.assertEqual(self.complete(adapter), '怎么了，突然闷闷的。')
        adapter.complete.assert_called_once()

    def test_label_only_reply_still_requires_a_real_answer(self):
        adapter = MagicMock()
        adapter.complete.side_effect = [self.response('【消息时间：2026-09-07 21:37】'),
                                        self.response('嗯。今天过得怎么样？')]
        self.assertEqual(self.complete(adapter), '嗯。今天过得怎么样？')
        self.assertEqual(adapter.complete.call_count, 2)

    def test_stripping_labels_does_not_bypass_content_validation(self):
        adapter = MagicMock()
        adapter.complete.return_value = self.response('【消息时间：2026-09-07 21:37】作为AI，我没有真实感情。')
        with self.assertRaises(chat.ChatConsistencyError):
            self.complete(adapter)

    def check(self, draft, channel='text', grounding=None):
        return validate_reply(character_id='sample_b', draft=draft, user_message='你好',
            history=[], live_status={}, companion_context={}, channel=channel,
            image_grounding=grounding)

    def response(self, text):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    def complete(self, adapter, **kwargs):
        with patch.object(chat, '_model_adapter', return_value=adapter):
            return chat._guarded_completion('sample_b', '你好', [], {},
                CompiledContext(messages=[], companion_context={}, relevant_experiences=()), **kwargs)

    def test_excess_actions_repaired_locally_without_extra_request(self):
        draft = '（看了一眼屏幕）点心买好了。（放下手机）路上慢点走。'
        original = self.check(draft)
        self.assertEqual(original.hard_reason_codes, ('ACTION_NARRATION_FORMAT',))
        adapter = MagicMock()
        adapter.complete.return_value = self.response(draft)
        result = self.complete(adapter)
        self.assertEqual(result, '（看了一眼屏幕）点心买好了。路上慢点走。')
        self.assertFalse(self.check(result).blocks_delivery)
        adapter.complete.assert_called_once()

    def test_long_action_is_removed_without_truncating_dialogue(self):
        draft = '（' + '看着屏幕' * 13 + '）点心买好了。'
        self.assertEqual(normalize_action_narration(draft, self.check(draft)), '点心买好了。')
        short = '(' + '看' * 48 + ')你好。'
        self.assertEqual(normalize_action_narration(short, self.check(short)), short)

    def test_action_only_candidate_still_requires_model_repair(self):
        draft = '（看了看屏幕）（放下手机）……'
        self.assertEqual(normalize_action_narration(draft, self.check(draft)), draft)
        adapter = MagicMock()
        adapter.complete.side_effect = [self.response(draft), self.response('点心买好了。')]
        self.assertEqual(self.complete(adapter), '点心买好了。')
        self.assertEqual(adapter.complete.call_count, 2)

    def test_content_violation_cannot_be_hidden_by_stripping_parentheses(self):
        draft = '（我是AI）（看了看屏幕）你好。'
        result = self.check(draft)
        self.assertIn('IDENTITY_AI', result.hard_reason_codes)
        self.assertEqual(normalize_action_narration(draft, result), draft)
        adapter = MagicMock()
        adapter.complete.return_value = self.response(draft)
        with self.assertRaises(chat.ChatConsistencyError):
            self.complete(adapter)
        self.assertEqual(adapter.complete.call_count, 3)

    def test_repair_and_regeneration_also_get_local_format_recovery(self):
        invalid = '作为AI，我无法真正拥有感情。'
        formatted = '（看了一眼屏幕）你好。（放下手机）点心买好了。'
        for failures in (1, 2):
            with self.subTest(failures=failures):
                adapter = MagicMock()
                adapter.complete.side_effect = [self.response(invalid)] * failures + [self.response(formatted)]
                self.assertEqual(self.complete(adapter), '（看了一眼屏幕）你好。点心买好了。')
                self.assertEqual(adapter.complete.call_count, failures + 1)

    def test_image_identity_and_remote_action_rails_remain_blocking(self):
        for draft, channel, grounding, rule in [
            ('（看了一眼）图里的我真漂亮。（点了点头）', 'image',
             {'subject_relation': 'unknown'}, 'IMAGE_SUBJECT_IDENTITY'),
            ('（抱住你）（摸摸你的头）你好。', 'text', None, 'CHANNEL_REMOTE_ACTION'),
        ]:
            with self.subTest(rule=rule):
                result = self.check(draft, channel, grounding)
                self.assertIn(rule, result.hard_reason_codes)
                self.assertEqual(normalize_action_narration(draft, result), draft)


if __name__ == '__main__':
    unittest.main()


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()
