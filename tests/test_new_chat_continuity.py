import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def slice_between(source, start, end):
    """Return the text from start up to (but excluding) end, keeping both markers intact."""
    start_at = source.index(start)
    end_at = source.index(end, start_at)
    return source[start_at:end_at]


class NewChatContinuityTests(unittest.TestCase):
    """新建会话的窗口交接、过期与静默开窗，全部离线执行真实前端函数。"""

    def run_js(self, script):
        result = subprocess.run(['node', '--input-type=module', '-e', script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def history_harness(self, body):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        globals_source = (
            slice_between(source, 'function toApiHistory(', '\nfunction countCompleteHistoryPairs(')
            + slice_between(source, 'const WINDOW_HANDOVER_TTL_MS', '\nfunction toConsolidationMessages(')
        )
        component_source = slice_between(source, '  const windowHandoverFor = (id) => {',
                                        '\n  const historyForRequest = (id, messages, limit = 24, consume = true) => {')
        history_source = '\n  ' + slice_between(source, '  const historyForRequest = (id, messages, limit = 24, consume = true) => {',
                                              '\n  const recordHomeGreeting')
        return '''const ROSTER=[{id:'sample_b'}];
const useR=value=>({current:value});
const localStorage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const readStoredObject=()=>null;
const windowHandoversRef={current:{sample_b:null,__ready:true}};
const callCarryoverRef={current:{sample_b:[]}};
const giftContextText=()=>'';
const isLegacyGuardFallbackText=()=>false;
const isLegacyStaticGreetingText=()=>false;
''' + globals_source + component_source + history_source + body

    def test_new_window_keeps_previous_tail_for_following_turns(self):
        self.run_js(self.history_harness('''
const base=Date.now()-60000;
const tail=[{from:'me',text:'婚礼的事你别急',ts:base},{from:'her',text:'我知道，我们慢慢来',ts:base+1000}];
setWindowHandover('sample_b', tail);
// 用户在新窗口的第一句话本身由 message 字段发送，历史里只保留已完成的问答与旧尾部。
const first=historyForRequest('sample_b', [{from:'me',text:'那明天去吗',ts:base+2000}]);
if(JSON.stringify(first.map(m=>m.content))!==JSON.stringify(['婚礼的事你别急','我知道，我们慢慢来']))
  throw Error('new window lost previous tail: '+JSON.stringify(first));
const second=historyForRequest('sample_b', [
  {from:'me',text:'那明天去吗',ts:base+2000},
  {from:'her',text:'好，我等你',ts:base+3000},
  {from:'me',text:'我订下午的',ts:base+4000},
]);
if(second[second.length-1].content!=='好，我等你') throw Error('later turn order broken: '+JSON.stringify(second));
if(!second.some(m=>m.content==='婚礼的事你别急')) throw Error('tail dropped on later turn');
if(!second.some(m=>m.content==='那明天去吗')) throw Error('new window turn dropped');'''))

    def test_handover_expires_after_turn_budget(self):
        self.run_js(self.history_harness('''
const base=Date.now()-60000;
setWindowHandover('sample_b', [
  {from:'me',text:'旧窗口上一句',ts:base},
  {from:'her',text:'旧窗口最后一句',ts:base+1},
]);
const turn=i=>[
  {from:'me',text:'新窗口'+i,ts:base+2000+i*10},
  {from:'her',text:'回应'+i,ts:base+2001+i*10},
];
for(let i=0;i<4;i+=1){
  const history=historyForRequest('sample_b', turn(i));
  if(!history.some(m=>m.content==='旧窗口最后一句')) throw Error('tail missing at turn '+i);
}
const after=historyForRequest('sample_b', turn(4));
if(after.some(m=>m.content==='旧窗口最后一句')) throw Error('handover did not expire');
if(!after.some(m=>m.content==='新窗口4')) throw Error('current window lost after expiry');'''))

    def test_stale_and_cross_day_handover_is_not_injected(self):
        self.run_js(self.history_harness('''
const base=Date.now()-60000;
const stale={messages:[{from:'me',text:'一小时前的话',ts:base}],createdAt:Date.now()-60*60*1000,turns:0};
windowHandoversRef.current={...windowHandoversRef.current,sample_b:stale};
if(historyForRequest('sample_b',[{from:'me',text:'现在这句',ts:Date.now()}]).some(m=>m.content==='一小时前的话'))
  throw Error('stale handover injected');
const yesterday=new Date(Date.now()-24*60*60*1000).getTime();
windowHandoversRef.current={...windowHandoversRef.current,sample_b:{messages:[{from:'her',text:'昨晚没来得及洞房',ts:yesterday}],createdAt:Date.now(),turns:0}};
if(historyForRequest('sample_b',[{from:'me',text:'早上好',ts:Date.now()}]).some(m=>m.content==='昨晚没来得及洞房'))
  throw Error('cross-day handover injected');'''))

    def test_new_window_waits_for_user_without_requesting_model_opening(self):
        source = (ROOT / 'web/app.jsx').read_text(encoding='utf-8')
        function = slice_between(source, '  const archiveAndNewChat = async (id) => {', '\n  const openHistory =')
        self.run_js('''let statusCalls=0, chatCalls=0;
const ROSTER=[{id:'sample_b'}];
const localStorage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const readStoredObject=()=>null;
const API_BASE='', archivedSessions={}, threads={sample_b:[{from:'me',text:'婚礼的事你别急',ts:1000},{from:'her',text:'我知道，我们慢慢来',ts:2000}]};
const pendingIds={current:new Set()}, windowHandoversRef={current:{sample_b:null,__ready:true}};
const countCompleteHistoryPairs=()=>1, isLegacyStaticGreetingText=()=>false, isLegacyGuardFallbackText=()=>false;
const applyLiveStatus=()=>{}, flash=()=>{}, updateMemory=()=>Promise.resolve(true);
const setArchivedSessions=()=>{}, setThreads=fn=>{threads.sample_b=fn({sample_b:threads.sample_b}).sample_b;};
const normalizeWindowHandover=value=>{
  if(!value||!Array.isArray(value.messages)) return null;
  return {messages:value.messages.slice(-12),createdAt:Number(value.createdAt)||Date.now(),turns:Number(value.turns)||0};
};
const windowHandoverExpired=()=>false;
const windowHandoverFor=id=>windowHandoversRef.current[id];
const setWindowHandover=(id,messages)=>{
  windowHandoversRef.current={...windowHandoversRef.current,[id]:normalizeWindowHandover({messages,createdAt:Date.now(),turns:0})};
  return windowHandoversRef.current[id];
};
const fetch=async url=>{
  if(String(url).includes('/status')){ statusCalls+=1; return {ok:true,json:async()=>({source:'schedule'})}; }
  chatCalls+=1;
  return {ok:true,json:async()=>({reply:'未经用户输入的虚构开场'})};
};
''' + function + '''const started=Date.now();
const opened=await archiveAndNewChat('sample_b');
if(!opened) throw Error('new window refused');
if(Date.now()-started>80) throw Error('new window blocked on model');
if(threads.sample_b.length) throw Error('new window not cleared immediately');
if(!windowHandoversRef.current.sample_b) throw Error('handover not stored');
if(!windowHandoversRef.current.sample_b.messages.some(m=>m.text==='婚礼的事你别急'))
  throw Error('handover lost previous tail');
await new Promise(resolve=>setTimeout(resolve,20));
if(statusCalls!==1) throw Error('status was not refreshed once: '+statusCalls);
if(chatCalls!==0) throw Error('new chat requested a model opening');
if(threads.sample_b.length!==0) throw Error('character spoke before user: '+JSON.stringify(threads.sample_b));''')


if __name__ == '__main__':
    unittest.main()


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()
