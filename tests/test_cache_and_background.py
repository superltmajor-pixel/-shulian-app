import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import desktop
import diagnostics
from shulian_backend.services import context_compiler as compiler
from shulian_backend.services.model_adapter_service import OpenAICompatibleModelAdapter


class CacheAndBackgroundTests(unittest.TestCase):
    def test_cache_summary_is_token_weighted_and_model_scoped(self):
        events = [{'code': 'model_usage', 'context': dict(provider='deepseek', model=model,
            cache_hit_tokens=hit, cache_miss_tokens=miss)}
            for model, hit, miss in [('a', 90, 10), ('a', 0, 900), ('b', None, None)]]
        with patch.object(diagnostics, '_EVENTS', events):
            summary = diagnostics.cache_usage_summary()['models']
        self.assertEqual(summary[0]['hit_ratio'], .09)
        self.assertEqual(summary[0]['measured_requests'], 2)
        self.assertIsNone(summary[1]['hit_ratio'])
        self.assertEqual(summary[1]['measured_requests'], 0)

    def test_completed_update_does_not_render_progress(self):
        source = (Path(__file__).resolve().parents[1] / 'web/screens.jsx').read_text(encoding='utf-8')
        prefix = source.split('className="maintenance-progress-wrap"')[0].rsplit('{(', 1)[1]
        self.assertIn("updateActive || updateJob?.status === 'failed'", prefix)
        self.assertNotIn("'completed'", prefix)

    def test_nonstream_usage_and_other_provider_compatibility(self):
        response = NS(usage=NS(prompt_tokens=100, completion_tokens=2,
            prompt_cache_hit_tokens=80, prompt_cache_miss_tokens=20))
        create = MagicMock(return_value=response)
        client = NS(chat=NS(completions=NS(create=create)))
        adapter = OpenAICompatibleModelAdapter(provider='custom', model='test', client_factory=lambda: client)
        self.assertNotIn('stream_options', adapter._request_kwargs([], temperature=.5, stream=True))
        with patch('shulian_backend.services.model_adapter_service.log_event') as log:
            self.assertIs(adapter.complete([], temperature=.5), response)
            self.assertEqual(log.call_args.kwargs['cache_hit_ratio'], .8)

    def test_static_prefix_survives_different_retrieval(self):
        character = NS(id='test', name='角色', system_prompt='固定设定')
        context = {'relationship': {}, 'stable_facts': []}
        with patch.object(compiler, 'normalize_companion_context', return_value=context), \
             patch.object(compiler, '_relationship_block', return_value='关系'), \
             patch.object(compiler, 'format_memory_context', return_value='记忆'), \
             patch.object(compiler, 'build_character_bible_context', side_effect=['资料甲', '资料乙']), \
             patch.object(compiler, 'build_personality_layers', return_value=NS(stable='固定人格', turn='本轮人格')):
            outputs = [compiler.compile_companion_messages(character, query, [],
                live_status={}, status_context='实时状态', reply_speed='日常自然').messages
                for query in ('甲', '乙')]
        for messages, bible in zip(outputs, ('资料甲', '资料乙')):
            system = messages[0]['content']
            self.assertLess(system.index('固定人格'), system.index(bible))
            self.assertEqual(system.count(compiler.SHARED_IMMERSION_RULES), 1)
            self.assertIn('实时状态', system)
            self.assertIn('记忆', system)
            self.assertIn('本轮人格', system)
        self.assertEqual(outputs[0][0]['content'].split('资料甲')[0],
                         outputs[1][0]['content'].split('资料乙')[0])

    def test_usage_only_stream_chunk_and_missing_cache_fields(self):
        chunks = [NS(choices=[NS(delta=NS(content='答'))], usage=None),
                  NS(choices=[], usage=NS(prompt_tokens=100, completion_tokens=2,
                     prompt_cache_hit_tokens=80, prompt_cache_miss_tokens=20))]
        upstream = MagicMock()
        upstream.__iter__.return_value = iter(chunks)
        create = MagicMock(return_value=upstream)
        client = NS(chat=NS(completions=NS(create=create)))
        adapter = OpenAICompatibleModelAdapter(provider='deepseek', model='test', client_factory=lambda: client)
        with patch('shulian_backend.services.model_adapter_service.log_event') as log:
            self.assertEqual(list(adapter.stream([], temperature=.5)), chunks)
            self.assertEqual(log.call_args.kwargs['cache_hit_ratio'], .8)
            self.assertIsNotNone(log.call_args.kwargs['first_token_ms'])
            self.assertEqual(log.call_count, 1)
            adapter._record_usage(NS(usage=NS(prompt_tokens=10)), 0)
            self.assertIsNone(log.call_args.kwargs['cache_hit_ratio'])
        upstream.close.assert_called_once()
        self.assertTrue(create.call_args.kwargs['stream_options']['include_usage'])

    def test_close_hides_but_explicit_exit_destroys(self):
        api = desktop._DesktopWindowApi(lambda: [])
        window = MagicMock()
        api.attach_window(window)
        api._tray = MagicMock()
        self.assertTrue(api.close_window()['ok'])
        window.hide.assert_called_once()
        window.destroy.assert_not_called()
        with patch.object(desktop._MAINTENANCE, 'update_job', return_value={'job': None}):
            self.assertFalse(api._on_closing())
        api._destroy_for_uninstall()
        window.destroy.assert_called_once()
        self.assertTrue(api._on_closing())

    def test_update_close_bypasses_tray_only_for_old_client(self):
        api = desktop._DesktopWindowApi(lambda: [])
        api.attach_window(MagicMock())
        api._tray = MagicMock()
        with patch.object(desktop._MAINTENANCE, 'update_job', return_value={'job': {
            'status': 'restarting', 'sourceVersion': 'next'}}):
            self.assertTrue(api._on_closing())
        with patch.object(desktop._MAINTENANCE, 'update_job', return_value={'job': {
            'status': 'restarting', 'sourceVersion': desktop.APP_VERSION}}):
            self.assertFalse(api._on_closing())


if __name__ == '__main__':
    unittest.main()
