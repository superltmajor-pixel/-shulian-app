import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const helpers = fs.readFileSync(new URL('../web/custom-role.jsx', import.meta.url), 'utf8')
  .split('function CustomRoleField')[0];
const context = vm.createContext({ Date });
const api = vm.runInContext(`${helpers}\n({ customRoleParseChatText, customRoleGuessSpeakers, customRoleMapChat, customRoleProfileForSave })`, context);

test('JSON conversations retain chronological turns and remove exact duplicates', () => {
  const imported = api.customRoleParseChatText(JSON.stringify({
    sessions: [{ messages: [
      { speaker: 'assistant', text: '下午好', ts: '2026-09-25T13:00:00Z' },
      { speaker: 'user', text: '你好', ts: '2026-09-25T12:00:00Z' },
      { speaker: 'user', text: '你好', ts: '2026-09-25T12:00:00Z' },
    ] }],
  }), 'history.json');
  const speakers = api.customRoleGuessSpeakers(imported.speakers);
  assert.equal(speakers.me, 'user');
  assert.equal(speakers.them, 'assistant');
  const mapped = api.customRoleMapChat(imported, speakers.me, speakers.them);
  assert.equal(mapped.included, 2);
  assert.equal(mapped.duplicates, 1);
  assert.deepEqual(Array.from(mapped.sessions[0].messages, message => `${message.from}:${message.text}`),
    ['me:你好', 'them:下午好']);
});

test('CSV handles quoted commas/newlines and reports skipped speakers', () => {
  const imported = api.customRoleParseChatText('sender,text,time\n"Alice","hello, world","2026-09-25"\n"Bob","line 1\nline 2","2026-09-25"\n"Other","skip",\n', 'chat.csv');
  assert.equal(imported.total, 3);
  const mapped = api.customRoleMapChat(imported, 'Alice', 'Bob');
  assert.equal(mapped.included, 2);
  assert.equal(mapped.skipped, 1);
  assert.equal(mapped.sessions[0].messages[0].text, 'hello, world');
  assert.equal(mapped.sessions[0].messages[1].text, 'line 1\nline 2');
});

test('unknown or ambiguous chat formats cannot silently import', () => {
  assert.throws(() => api.customRoleParseChatText('{"wrong":[]}', 'a.json'), /messages/);
  assert.throws(() => api.customRoleParseChatText('from,text\n', 'a.csv'), /至少需要/);
  const imported = api.customRoleParseChatText('[{"from":"me","text":"one"}]', 'a.json');
  const mapped = api.customRoleMapChat(imported, 'me', 'me');
  assert.equal(mapped.included, 0);
});

test('draft payload does not forward unknown role-package fields', () => {
  const saved = api.customRoleProfileForSave({ name: '  青禾 ', persona: '旅人', tags: ['勇敢'], id: 'built-in', secret: 'do-not-save' });
  assert.equal(saved.name, '青禾');
  assert.equal(saved.id, undefined);
  assert.equal(saved.secret, undefined);
  assert.equal(saved.cat, '自建');
});

test('undated and single-speaker history remains importable without inventing timestamps', () => {
  const imported = api.customRoleParseChatText('[{"from":"assistant","text":"来自星海"}]', 'a.json');
  const speakers = api.customRoleGuessSpeakers(imported.speakers);
  assert.equal(speakers.me, '');
  assert.equal(speakers.them, 'assistant');
  const result = api.customRoleMapChat(imported, speakers.me, speakers.them);
  assert.equal(result.included, 1);
  assert.equal(result.sessions[0].messages[0].from, 'them');
  assert.equal(result.sessions[0].messages[0].ts, undefined);
});

test('malformed message content cannot be silently discarded or stringified', () => {
  assert.throws(() => api.customRoleParseChatText('[{"from":"user","text":{"secret":"object"}}]', 'a.json'), /文本内容/);
});
