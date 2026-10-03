import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shulian_backend.services.context_compiler import trim_complete_history_pairs
from shulian_backend.services.companion_context_service import complete_conversation_messages
from shulian_backend.schemas.api import SummarizeRequest
from shulian_backend.routers import chat


class ConversationBoundaryTests(unittest.TestCase):
    def test_greeting_does_not_answer_failed_turn(self):
        history = [
            {'role': 'user', 'content': '未得到回答的问题'},
            {'role': 'assistant', 'content': '午安', 'origin': 'home-greeting'},
        ]
        result = trim_complete_history_pairs(history)
        self.assertEqual([m['content'] for m in result], ['午安'])

    def test_finished_pairs_survive_greeting_boundary(self):
        history = [
            {'role': 'user', 'content': '旧问题'},
            {'role': 'assistant', 'content': '旧回答'},
            {'role': 'user', 'content': '失败的问题'},
            {'role': 'assistant', 'content': '问候', 'origin': 'proactive'},
            {'role': 'user', 'content': '新问题'},
            {'role': 'assistant', 'content': '新回答'},
        ]
        self.assertEqual([m['content'] for m in trim_complete_history_pairs(history)],
                         ['旧问题', '旧回答', '问候', '新问题', '新回答'])

    def test_unfinished_reply_cannot_become_memory(self):
        messages = [{'from': 'me', 'text': '问题', 'ts': 1},
                    {'from': 'her', 'text': '未完成的答案', 'ts': 2, 'streaming': True}]
        self.assertEqual(complete_conversation_messages(messages), [])
        messages[1]['streaming'] = False
        self.assertEqual(len(complete_conversation_messages(messages)), 2)

    def test_summary_route_keeps_message_time(self):
        req = SummarizeRequest(messages=[{'role': 'user', 'content': '问题', 'ts': 1788782400000}])
        with patch.object(chat.chat_backend, 'summarize_memory_context', return_value='{}') as summarize:
            chat.summarize('sample_b', req)
        self.assertEqual(summarize.call_args.args[-1][0]['ts'], 1788782400000)

    def test_frontend_excludes_partial_text_from_both_paths(self):
        source = (Path(__file__).resolve().parents[1] / 'web/app.jsx').read_text(encoding='utf-8')
        history = source.split('function toApiHistory(', 1)[1].split('\nfunction countCompleteHistoryPairs', 1)[0]
        consolidation = source.split('function toConsolidationMessages(', 1)[1].split('\nfunction toConsolidationSessions', 1)[0]
        script = '''const giftContextText=()=>'';
const isLegacyGuardFallbackText=()=>false;
const isLegacyStaticGreetingText=()=>false;
function toApiHistory(''' + history + '\nfunction toConsolidationMessages(' + consolidation + '''
const input=[{from:'me',text:'问题',ts:1},{from:'her',text:'半句',ts:2,streaming:true}];
if(toApiHistory(input).length!==0) throw Error('partial reply entered history');
if(toConsolidationMessages(input).some(m=>m.from==='her')) throw Error('partial reply entered memory');
input[1].streaming=false;
if(toApiHistory(input).length!==2) throw Error('completed reply was lost');
console.log('ok');'''
        result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()
