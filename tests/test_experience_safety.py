import subprocess
import unittest
from pathlib import Path

from shulian_backend.domain.scene_evidence import user_asserts_shared_presence

ROOT = Path(__file__).resolve().parents[1]


class ExperienceSafetyTests(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(['node', '--input-type=module', '-e', script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_recollection_cannot_establish_current_presence(self):
        for text in ('昨天我抱住你', '上次我在你身边', '昨天（抱住你）', '（昨天抱住你）', '如果（抱住你）'):
            with self.subTest(text=text):
                self.assertFalse(user_asserts_shared_presence(text))
        for text in ('（抱住你）', '我在你身边', '我抱住你'):
            self.assertTrue(user_asserts_shared_presence(text))

    def test_busy_composer_keeps_text_and_image(self):
        source = (ROOT / 'web/chat.jsx').read_text(encoding='utf-8')
        send = source.split('  const send = () => {', 1)[1].split('\n  const stageImage', 1)[0]
        self.run_js('''let typing=false, busy=true, text='草稿', pendingImage='图片', sent=0;
const canSend=()=>!busy, onSend=()=>sent++, onSendImage=()=>sent++;
const setText=v=>text=v, setPendingImage=v=>pendingImage=v;
const setShowActions=()=>{}, setShowStickers=()=>{}, setShowVoiceModes=()=>{};
const send=()=>{''' + send + '''
send();
if(text!=='草稿'||pendingImage!=='图片'||sent) throw Error('busy draft lost');
busy=false; send();
if(text||pendingImage||sent!==1) throw Error('normal send broken');''')

    def test_late_camera_stream_is_released(self):
        source = (ROOT / 'web/chat.jsx').read_text(encoding='utf-8').split('function VideoCall(', 1)[1]
        functions = source.split('  const stopCam =', 1)[1].split('  useEffectC(() => { if (engine.connected)', 1)[0]
        self.run_js('''let resolveCamera, stopped=0;
const navigator={mediaDevices:{getUserMedia:()=>new Promise(r=>resolveCamera=r)}};
const streamRef={current:null}, cameraRequestRef={current:0};
const setCamReady=()=>{}, setCamOn=()=>{}, setCamError=()=>{};
const stopCam=''' + functions + '''
const pending=startCam(); stopCam();
resolveCamera({getTracks:()=>[{stop:()=>stopped++}]}); await pending;
if(stopped!==1||streamRef.current!==null) throw Error('late camera leaked');''')

    def test_hangup_prevents_late_speech_submission(self):
        source = (ROOT / 'web/realtime-voice.jsx').read_text(encoding='utf-8')
        transport = source.split('function useRealtimeCallEngine', 1)[0]
        self.run_js(transport + '''
let sent=0;
const session=new RealtimeVoiceSession('sample_a', {}, ()=>{});
session.ws={readyState:1,send:()=>sent++,close:()=>{}};
session.ready=true;
session.close();
const atHangup=sent;
session.text('迟到转写');
session.send({type:'text',text:'迟到消息'});
if(sent!==atHangup||!session.closed) throw Error('sent after hangup');''')

    def test_late_nudge_is_discarded_after_user_starts_chat(self):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        function = source.split('  const nudgeChar =', 1)[1].split('\n  useE(', 1)[0]
        self.run_js('''let replyResolve, appended=0;
const chatIdRef={current:null}, pendingIds={current:new Set()}, memoryPendingRef={current:new Set()};
const localStorage={getItem:()=> '{}'}, window={__threads:{sample_b:[]}}, API_BASE='';
const applyLiveStatus=()=>{}, historyForRequest=()=>[], memoryForRequest=()=>'',
intimacyForRequest=()=>0, companionForRequest=()=>({}), requireSafeCharacterReply=()=> '问候';
const setThreads=()=>appended++, setNotifications=()=>{}, flash=()=>{};
const fetch=async url=>url.includes('/status')?{ok:true,json:async()=>({source:'schedule'})}:
{ok:true,json:()=>new Promise(r=>replyResolve=r)};
const nudgeChar=''' + function + '''
const pending=nudgeChar('sample_b');
while(!replyResolve) await new Promise(r=>setTimeout(r,0));
pendingIds.current.add('sample_b'); replyResolve({reply:'问候'}); await pending;
if(appended) throw Error('stale nudge inserted');''')

    def test_recent_conversation_suppresses_proactive_nudge(self):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        function = source.split('  const nudgeChar =', 1)[1].split('\n  useE(', 1)[0]
        self.run_js('''let fetched=0;
const PROACTIVE_IDLE_MS=20*60*1000, chatIdRef={current:null}, pendingIds={current:new Set()}, memoryPendingRef={current:new Set()};
const localStorage={getItem:()=> '{}'}, window={__threads:{sample_b:[{from:'me',text:'刚聊完',ts:Date.now()-120000}]}}, API_BASE='';
const fetch=async()=>{fetched++;throw Error('must not fetch')}, applyLiveStatus=()=>{}, historyForRequest=()=>[],
memoryForRequest=()=>'', intimacyForRequest=()=>0, companionForRequest=()=>({}), requireSafeCharacterReply=()=>'';
const setThreads=()=>{}, setNotifications=()=>{}, flash=()=>{};
const nudgeChar=''' + function + '''
await nudgeChar('sample_b');
if(fetched) throw Error('recent conversation was interrupted');''')

    def test_home_greeting_enters_chat_only_after_user_clicks_it(self):
        source = (ROOT / 'web/screens.jsx').read_text(encoding='utf-8')
        self.assertNotIn(
            "if (!greetingSuppressed && !greetTyping && greetingKey && greetText) onGreetingShown",
            source,
        )
        button = source.split('className="glass bubble-pop greet-bubble', 1)[1].split('</button>', 1)[0]
        self.assertIn('onGreetingShown?.(greetingKey, greetText);', button)
        self.assertIn('openMessagesChat(c.id);', button)

    def test_open_chat_updates_nudge_guard_synchronously(self):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        open_chat = source.split('  const openChat =', 1)[1].split('  const openLoverArchive', 1)[0]
        self.assertLess(open_chat.index('chatIdRef.current = id;'), open_chat.index('setChatId(id);'))


if __name__ == '__main__':
    unittest.main()


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()
