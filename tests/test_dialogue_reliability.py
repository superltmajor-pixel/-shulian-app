"""Cross-turn and delayed-I/O regressions; no live model or user data."""
import json
import re
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shulian_backend.services.context_compiler import trim_complete_history_pairs, _history_for_model
from shulian_backend.services.companion_context_service import consolidate_companion_context, default_companion_context
from shulian_backend.services.memory_service import normalize_memory_context, summarize_memory_context
from shulian_backend.services.response_guard import validate_reply
from shulian_backend.services.scene_status_service import (
    explicit_shared_rest_scene, validate_scene_decision_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


def run_js(script):
    result = subprocess.run(['node', '--input-type=module', '-e', script],
                            cwd=ROOT, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


class DialogueReliabilityTests(unittest.TestCase):
    def test_frontend_memory_uses_the_same_date_and_capture_limits(self):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        memory = 'const MEMORY_CONTEXT_VERSION =' + source.split('const MEMORY_CONTEXT_VERSION =',1)[1].split('\nfunction reversesCharacterAddressDirection',1)[0]
        run_js(memory + """
const now=Date.parse('2026-09-08T12:00:00Z'); Date.now=()=>now;
const captured=new Date(now-71*3600000).toISOString();
const events=['2026-08-31一起散步。','2026-02-30一起散步。','2026-09-08一起散步。']
 .map(text=>({text,captured_at:captured,expires_at:'2026-10-08T12:00:00Z'}));
const actual=normalizeMemoryContext({recent_events:events}).recent_events;
if(actual.length!==1||actual[0].text!=='2026-09-08一起散步。')throw Error('stale or invalid event survived');
if(Date.parse(actual[0].expires_at)>Date.parse(captured)+MEMORY_EVENT_TTL_MS)throw Error('capture expiry refreshed');
""")

    def test_display_cleanup_preserves_real_dialogue_and_other_brackets(self):
        source = (ROOT / 'web/data.jsx').read_text(encoding='utf-8')
        helper = 'function stripHistoryLabels(' + source.split('function stripHistoryLabels(',1)[1].split('\n}',1)[0] + '\n}'
        run_js(helper + """
if(stripHistoryLabels('【消息时间：2026-09-07 21:37】\\n你好')!=='你好')throw Error('label leaked');
for(const text of ['我们21:37见','【纪念日】很开心','[图片]一只猫'])
 if(stripHistoryLabels(text)!==text)throw Error('dialogue changed');
""")

    def test_failed_sqlite_write_retains_latest_edit_for_retry(self):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        bridge = source.split('const sqliteStateBridge = ', 1)[1].split('\nfunction installSqliteStateBridge', 1)[0]
        run_js("""const API_BASE='',localStorage={},SQLITE_PENDING_KEY='pending';
const nativeStorageRemove=()=>{},nativeStorageSet=()=>{},readPendingStateOperations=()=>new Map(),isPersistentStateKey=()=>true;
const requests=[];const fetch=(url,options)=>new Promise(resolve=>requests.push({payload:JSON.parse(options.body),resolve}));
const sqliteStateBridge = """ + bridge + """
sqliteStateBridge.suspended=false;sqliteStateBridge.queue('sl_threads','old');
const first=sqliteStateBridge.flush();sqliteStateBridge.queue('sl_threads','latest');
requests[0].resolve({ok:false});let failed=false;try{await first}catch(e){failed=true}
if(!failed||sqliteStateBridge.operations.get('sl_threads').value!=='latest')throw Error('failed write lost latest edit');
const retry=sqliteStateBridge.flush();
if(requests[1].payload.items.sl_threads!=='latest')throw Error('retried stale edit');
requests[1].resolve({ok:true,json:async()=>({ok:true})});await retry;
if(sqliteStateBridge.operations.size)throw Error('retry not acknowledged');
""")

    def test_restore_waits_for_older_writes_and_blocks_overtaking_flush(self):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        bridge = source.split('const sqliteStateBridge = ',1)[1].split('\nfunction installSqliteStateBridge',1)[0]
        replace = 'function replaceRawPersistentState' + source.split('function replaceRawPersistentState',1)[1].split('\nasync function loadSqliteStateBeforeRender',1)[0]
        run_js("""const API_BASE='',localStorage={},SQLITE_PENDING_KEY='pending';
const nativeStorageRemove=()=>{},nativeStorageSet=()=>{},readPendingStateOperations=()=>new Map(),isPersistentStateKey=()=>true,readRawPersistentState=()=>({});
const requests=[];const fetch=(url,options)=>new Promise(resolve=>requests.push({url,payload:JSON.parse(options.body),resolve}));
const sqliteStateBridge = """ + bridge + '\n' + replace + """
sqliteStateBridge.suspended=false;sqliteStateBridge.queue('sl_threads','old');
const old=sqliteStateBridge.flush();const restore=replacePersistentState({sl_threads:'restored'});
if(requests.length!==1)throw Error('restore raced an earlier write');
requests[0].resolve({ok:true,json:async()=>({ok:true})});await new Promise(r=>setImmediate(r));
if(requests.length!==2||!requests[1].url.endsWith('/replace'))throw Error('restore not serialized');
sqliteStateBridge.queue('sl_threads','obsolete-page-edit');const flush=sqliteStateBridge.flush();
if(requests.length!==2)throw Error('old page overwrites restored data');
requests[1].resolve({ok:true,json:async()=>({ok:true})});await Promise.all([old,restore,flush]);
if(sqliteStateBridge.operations.size)throw Error('old-page write survived authoritative restore');
""")

    def test_direct_native_writes_stay_inside_the_four_approved_paths(self):
        """契约：SQLite 是唯一真源，localStorage 只是缓存的副本。

        除读取、恢复备份和启动期 hydration 之外，任何地方直接调用原生 Storage
        实现都会让缓存与 SQLite 真源悄悄分叉；桥只负责把页面写入排队推给后端。
        因此把「原生直写」限制在四条受控路径内，越界即失败。
        """
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        self.assertIn('唯一真源是后端 SQLite', source)

        approved_spans = []
        for name, start_marker, end_marker in (
            ('installSqliteStateBridge',
             'function installSqliteStateBridge()',
             '\nfunction replaceRawPersistentState'),
            ('sqliteStateBridge',
             'const sqliteStateBridge = ',
             '\nfunction installSqliteStateBridge'),
            ('replaceRawPersistentState',
             'function replaceRawPersistentState(data)',
             '\nfunction flushAllPersistentState'),
            ('loadSqliteStateBeforeRender',
             'async function loadSqliteStateBeforeRender()',
             '\nwindow.shulianStorageFlush'),
        ):
            start = source.index(start_marker)
            approved_spans.append((name, start, source.index(end_marker, start)))

        calls = list(re.finditer(r'nativeStorage(?:Set|Remove|Clear)\.call\(', source))
        self.assertGreaterEqual(len(calls), 6, '原生直写的受控调用点丢失')

        stray = []
        for match in calls:
            position = match.start()
            if not any(start <= position < end for _name, start, end in approved_spans):
                line_number = source.count('\n', 0, position) + 1
                stray.append((line_number, source.splitlines()[line_number - 1].strip()))
        self.assertEqual(stray, [], f'受控路径之外出现原生直写：{stray}')

    def test_cross_day_transcript_is_reference_not_recent_assistant_speech(self):
        old = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()*1000
        today = datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp()*1000
        history = [{'role':'assistant','content':'一起吃饭吗？','ts':old},
                   {'role':'user','content':'今天想聊书','ts':today},
                   {'role':'assistant','content':'好呀，想读什么？','ts':today}]
        actual = _history_for_model(history, '2026-09-08')
        self.assertEqual(actual[0]['role'], 'user')
        self.assertIn('跨日期的历史会话摘录', actual[0]['content'])
        self.assertEqual(actual[1:], [{'role':'user','content':'今天想聊书'},
                                     {'role':'assistant','content':'好呀，想读什么？'}])

    def test_dated_personal_story_requires_a_recorded_date(self):
        common = dict(character_id='sample_a', draft='你猜我昨天下午在想象什么？',
                      user_message='聊什么？', history=[], live_status={'date':'2026-09-08'}, companion_context={})
        self.assertIn('UNGROUNDED_PAST_EPISODE', validate_reply(**common, history_dates=('2026-09-01',)).hard_reason_codes)
        self.assertNotIn('UNGROUNDED_PAST_EPISODE', validate_reply(**common, history_dates=('2026-09-07',)).hard_reason_codes)

    def test_user_preference_recollection_needs_supplied_evidence(self):
        draft = '我记得你之前对光影的处理挺感兴趣，要不要聊聊这个？'
        common = dict(character_id='sample_a', draft=draft, user_message='聊什么？',
                      history=[], live_status={}, companion_context={})
        self.assertIn('UNGROUNDED_USER_MEMORY', validate_reply(**common,
            user_fact_sources=('好啊', '上周我们吃饭了')).hard_reason_codes)
        self.assertNotIn('UNGROUNDED_USER_MEMORY', validate_reply(**common,
            user_fact_sources=('用户对光影处理感兴趣。',)).hard_reason_codes)

    def test_hypothetical_or_third_party_marriage_does_not_upgrade_relationship(self):
        for user, reply in [('如果我们结婚了，你会怎么称呼我？', '如果成为夫妻，我愿意叫你先生。'),
                            ('朋友要结婚了，帮我选份礼物吧', '我愿意帮你挑一份。')]:
            with self.subTest(user=user):
                baseline = default_companion_context('sample_c')
                actual, _ = consolidate_companion_context('sample_c', baseline, current_messages=[
                    {'from':'me','text':user,'ts':1}, {'from':'her','text':reply,'ts':2}])
                self.assertEqual(actual['relationship']['level'], baseline['relationship']['level'])

    def test_explicit_marriage_proposal_and_acceptance_still_work(self):
        actual, _ = consolidate_companion_context('sample_c', default_companion_context('sample_c'),
            current_messages=[{'from':'me','text':'我们结婚吧','ts':1},
                              {'from':'her','text':'我愿意嫁给你。','ts':2}])
        self.assertEqual(actual['relationship']['level'], 10)

    def test_initiated_question_remains_after_user_accepts_and_next_turn(self):
        history = [
            {'role': 'assistant', 'content': '一起去书店吗？', 'origin': 'proactive', 'ts': 1000},
            {'role': 'user', 'content': '好呀', 'ts': 2000},
            {'role': 'assistant', 'content': '走吧', 'ts': 3000},
        ]
        self.assertEqual([x['content'] for x in trim_complete_history_pairs(history)],
                         ['一起去书店吗？', '好呀', '走吧'])
        self.assertEqual(len(trim_complete_history_pairs(history, max_messages=2)), 2)

    def test_frontend_history_budget_does_not_cut_a_pair_in_half(self):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        history = source.split('function toApiHistory(', 1)[1].split('\nfunction countCompleteHistoryPairs', 1)[0]
        run_js("""const giftContextText=()=>'';
const isLegacyGuardFallbackText=()=>false, isLegacyStaticGreetingText=()=>false;
function toApiHistory(""" + history + """
const input=[{from:'me',text:'旧问题'}, {from:'her',text:'旧回答'},
 {from:'me',text:'新问题'}, {from:'her',text:'新回答'}];
const actual=toApiHistory(input,3);
if(JSON.stringify(actual.map(x=>x.content))!==JSON.stringify(['新问题','新回答']))
 throw Error('budget created an orphan answer: '+JSON.stringify(actual));
""")

    def test_old_or_invalid_event_date_cannot_get_fresh_expiry(self):
        now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        events = [dict(text=text, captured_at=now.isoformat(),
                       expires_at=(now + timedelta(hours=72)).isoformat())
                  for text in ['2026-08-31一起去了书店。', '2026-02-30一起散步。',
                               '2026-09-08一起去了书店。']]
        result = normalize_memory_context({'recent_events': events}, now=now)
        self.assertEqual([x['text'] for x in result['recent_events']], ['2026-09-08一起去了书店。'])

    def test_expiry_cannot_extend_72_hours_from_original_capture(self):
        now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        captured = now - timedelta(hours=71)
        event = dict(text='2026-09-08一起去了书店。', captured_at=captured.isoformat(),
                     expires_at=(now + timedelta(days=30)).isoformat())
        result = normalize_memory_context({'recent_events': [event]}, now=now)
        self.assertLessEqual(datetime.fromisoformat(result['recent_events'][0]['expires_at']),
                             captured + timedelta(hours=72))

    def test_recent_memory_requires_a_recent_source_message(self):
        now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        for ts, keep in [((now-timedelta(days=10)).timestamp()*1000, False),
                         (now.timestamp()*1000, True), (None, False)]:
            with self.subTest(ts=ts):
                result = json.loads(summarize_memory_context(
                    character_name='许宁', character_id='sample_b', old_context='', legacy_memory='',
                    messages=[{'role':'user', 'content':'我们去了书店', 'ts':ts}], now=now,
                    complete=lambda *a, **kw: json.dumps({'recent_events':[
                        {'text':'2026-09-08一起去了书店。', 'source_index':0}]})))
                self.assertEqual(bool(result['recent_events']), keep)

    def test_recalled_or_hypothetical_rest_is_not_current_sleep(self):
        for user, reply in [('昨天我抱着你哄你睡觉', '记得，我在你怀里睡着了。'),
                            ('如果我抱着你哄你睡觉', '那我会在你怀里睡着。'),
                            ('明天我陪你睡觉', '好，明天一起睡。')]:
            with self.subTest(user=user):
                self.assertIsNone(explicit_shared_rest_scene(user, reply))
        self.assertEqual(explicit_shared_rest_scene('（抱着你）一起睡觉吧',
                                                    '（闭上眼）在你怀里慢慢睡着了。'), 'sleep')

    def test_model_cannot_turn_a_recollection_into_a_scene_transition(self):
        cases = [('set', 'meal', '昨天我们一起吃饭', '记得，一起吃饭很开心。'),
                 ('set', 'meal', '以后我们一起吃饭', '好，以后一起去。'),
                 ('clear', '', '你昨天说我走了', '记得，你说了再见。')]
        for action, scene, user, reply in cases:
            with self.subTest(user=user):
                result = validate_scene_decision_evidence(
                    {'action':action, 'scene':scene, 'confidence':1},
                    current_status={'source':'conversation'}, user_message=user, reply=reply)
                self.assertEqual(result['action'], 'keep')
        result = validate_scene_decision_evidence({'action':'set', 'scene':'meal', 'confidence':1},
            current_status={}, user_message='昨天很忙，今天我们一起吃饭吧', reply='好，一起吃饭。')
        self.assertEqual(result['action'], 'set')

    def test_sqlite_flush_serializes_writes_and_waits_for_newer_edits(self):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        bridge = source.split('const sqliteStateBridge = ', 1)[1].split('\nfunction installSqliteStateBridge', 1)[0]
        run_js("""const API_BASE='', localStorage={}, SQLITE_PENDING_KEY='pending';
const nativeStorageRemove=()=>{}, nativeStorageSet=()=>{}, readPendingStateOperations=()=>new Map();
const isPersistentStateKey=()=>true;
const requests=[];
const fetch=(url,options)=>new Promise(resolve=>requests.push({payload:JSON.parse(options.body),resolve}));
const sqliteStateBridge = """ + bridge + """
sqliteStateBridge.suspended=false;
sqliteStateBridge.queue('sl_threads','old');
const first=sqliteStateBridge.flush();
sqliteStateBridge.queue('sl_threads','latest');
const second=sqliteStateBridge.flush();
if(requests.length!==1) throw Error('concurrent writes can overwrite the latest chat');
requests[0].resolve({ok:true,json:async()=>({ok:true})});
await new Promise(resolve=>setImmediate(resolve));
if(requests.length!==2 || requests[1].payload.items.sl_threads!=='latest') throw Error('new edit lost');
requests[1].resolve({ok:true,json:async()=>({ok:true})});
await Promise.all([first,second]);
if(sqliteStateBridge.operations.size) throw Error('flush returned before latest edit was stored');
""")


if __name__ == '__main__':
    unittest.main()


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()
