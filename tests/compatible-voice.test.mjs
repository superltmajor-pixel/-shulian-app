import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../web/compatible-voice.jsx', import.meta.url), 'utf8')
  .split('function useCompatibleCallEngine')[0];

function harness({ send, ttsOk = true, recognition = true, nativeShell = false } = {}) {
  let clock = 0, nextTimer = 0, objectId = 0;
  const timers = new Map(), events = [], recognitions = [], requests = [], revoked = [], spoken = [];
  const sockets = [], workletNodes = [], tracks = [];
  class Recognition {
    constructor() { recognitions.push(this); }
    start() { this.started = true; }
    abort() { this.aborted = true; }
  }
  class Audio {
    constructor(url) { this.url = url; }
    play() { queueMicrotask(() => this.onended?.()); return Promise.resolve(); }
    pause() { this.paused = true; }
  }
  class Utterance { constructor(text) { this.text = text; } }
  const speechSynthesis = {
    getVoices: () => [{ lang: 'zh-CN' }],
    speak(utterance) { spoken.push(utterance.text); queueMicrotask(() => utterance.onend?.()); },
    cancel() {},
  };
  class BrowserURL extends URL {
    static createObjectURL() { return `blob:test-${++objectId}`; }
    static revokeObjectURL(url) { revoked.push(url); }
  }
  class NativeAudioContext {
    constructor() {
      this.state = 'running';
      this.destination = {};
      this.audioWorklet = { addModule: async () => {} };
    }
    resume() { return Promise.resolve(); }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    close() { this.state = 'closed'; return Promise.resolve(); }
  }
  class NativeWorkletNode {
    constructor() { this.port = { onmessage: null }; workletNodes.push(this); }
    connect() {}
    disconnect() {}
  }
  class NativeSocket {
    static OPEN = 1;
    constructor(url) {
      this.url = url;
      this.readyState = NativeSocket.OPEN;
      this.bufferedAmount = 0;
      this.frames = [];
      sockets.push(this);
      queueMicrotask(() => this.onmessage?.({ data: JSON.stringify({ type: 'ready', sample_rate: 16000 }) }));
    }
    send(frame) { this.frames.push(frame); }
    close() { this.readyState = 3; this.closed = true; }
  }
  const browser = {
    speechSynthesis,
    AudioContext: NativeAudioContext,
    location: { href: 'http://127.0.0.1:8770/' },
  };
  if (recognition) browser.SpeechRecognition = Recognition;
  if (nativeShell) browser.pywebview = { api: {} };
  const context = vm.createContext({
    window: browser,
    navigator: { mediaDevices: { getUserMedia: async () => {
      const track = { stopped: false, stop() { this.stopped = true; }, onended: null };
      tracks.push(track);
      return { getTracks: () => [track], getAudioTracks: () => [track] };
    } } },
    AudioWorkletNode: NativeWorkletNode,
    WebSocket: NativeSocket,
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: ttsOk, blob: async () => ({ type: 'audio/mpeg' }) };
    },
    Audio, SpeechSynthesisUtterance: Utterance, AbortController, Date,
    encodeURIComponent, queueMicrotask,
    URL: BrowserURL,
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, at: clock + delay }); return id; },
    clearTimeout: id => timers.delete(id),
  });
  const Session = vm.runInContext(source + '\nCompatibleVoiceSession', context);
  const sent = [];
  const session = new Session({ id: 'ruri', name: 'Ruri' }, send || (async (text, turns) => {
    sent.push({ text, turns });
    return '我听见了。';
  }), event => events.push(event));
  const advance = ms => {
    clock += ms;
    for (const [id, timer] of [...timers]) if (timer.at <= clock) { timers.delete(id); timer.callback(); }
  };
  const flush = async () => {
    for (let index = 0; index < 40; index++) await Promise.resolve();
  };
  return { session, events, recognitions, requests, revoked, spoken, sent, timers,
    sockets, workletNodes, tracks, advance, flush };
}

test('recognized turn uses existing chat and TTS then resumes listening', async () => {
  const h = harness();
  h.session.start();
  assert.equal(h.recognitions.length, 1);
  assert.equal(h.session.phase, 'listening');
  const result = [{ 0: { transcript: '你好' }, isFinal: true }];
  result.resultIndex = 0;
  h.recognitions[0].onresult({ results: result, resultIndex: 0 });
  await h.flush();
  assert.equal(h.sent.length, 1);
  assert.equal(h.sent[0].text, '你好');
  assert.equal(h.sent[0].turns.length, 0);
  assert.equal(h.requests[0].url, '/api/tts/ruri');
  assert.equal(h.session.turns.length, 2);
  assert.equal(h.session.turns[1].text, '我听见了。');
  h.advance(120);
  assert.equal(h.recognitions.length, 2, 'listening should resume after the spoken reply');
  assert.equal(h.session.phase, 'listening');
});

test('mute stops automatic recognition restart and close clears resources', () => {
  const h = harness();
  h.session.start();
  h.session.mute(true);
  assert.equal(h.recognitions[0].aborted, true);
  assert.equal(h.session.phase, 'idle');
  h.advance(1000);
  assert.equal(h.recognitions.length, 1);
  h.session.close();
  assert.equal(h.session.closed, true);
  assert.equal(h.timers.size, 0);
});

test('recognition service failures back off and stop until manual retry', () => {
  const h = harness();
  h.session.start();
  const delays = [1000, 2000, 4000, 8000];
  delays.forEach((delay, index) => {
    const recognition = h.recognitions[index];
    recognition.onerror({ error: 'network' });
    recognition.onend();
    assert.equal(h.session.muted, false);
    h.advance(delay - 1);
    assert.equal(h.recognitions.length, index + 1);
    h.advance(1);
    assert.equal(h.recognitions.length, index + 2);
  });
  const fifth = h.recognitions[4];
  fifth.onerror({ error: 'network' });
  fifth.onend();
  h.advance(30000);
  assert.equal(h.recognitions.length, 5);
  assert.equal(h.session.muted, true);
  assert.match(h.events.at(-1).message, /点击麦克风重试/);
  h.session.startListening();
  assert.equal(h.session.muted, false);
  assert.equal(h.recognitions.length, 6);
});

test('desktop shell waits for the local model and never starts browser recognition', async () => {
  const h = harness({ nativeShell: true });
  h.session.start();
  assert.equal(h.recognitions.length, 0);
  assert.equal(h.sockets.length, 0);
  assert.equal(h.session.phase, 'idle');
  assert.equal(h.session.recognitionAvailable, false);
  assert.equal(h.events.find(event => event.type === 'capability')?.hasSR, false);
  assert.match(h.events.at(-1).message, /本地中文语音识别/);
  await h.session.submit('文字仍可发送');
  assert.equal(h.sent[0].text, '文字仍可发送');
});

test('desktop shell streams local audio and resumes after the spoken reply', async () => {
  const h = harness({ nativeShell: true });
  h.session.setLocalAsrReady(true);
  h.session.start();
  await h.flush();
  assert.equal(h.recognitions.length, 0);
  assert.equal(h.sockets.length, 1);
  assert.equal(h.sockets[0].url.pathname, '/api/local-asr/stream');
  assert.equal(h.session.phase, 'listening');
  h.workletNodes[0].port.onmessage({ data: new ArrayBuffer(640) });
  assert.equal(h.sockets[0].frames.length, 1);
  h.sockets[0].onmessage({ data: JSON.stringify({ type: 'final', text: '你好' }) });
  await h.flush();
  assert.equal(h.sent[0].text, '你好');
  assert.equal(h.requests[0].url, '/api/tts/ruri');
  assert.equal(h.sockets[0].closed, true);
  assert.equal(h.tracks[0].stopped, true);
  h.advance(120);
  await h.flush();
  assert.equal(h.sockets.length, 2);
  assert.equal(h.session.phase, 'listening');
  h.session.close();
  assert.equal(h.sockets[1].closed, true);
  assert.equal(h.tracks[1].stopped, true);
});

test('failed server TTS falls back to browser speech', async () => {
  const h = harness({ ttsOk: false });
  h.session.start();
  await h.session.submit('说句话');
  await h.flush();
  assert.deepEqual(h.spoken, ['我听见了。']);
  assert.equal(h.session.turns.length, 2);
});

test('typed calls still work when browser speech recognition is unavailable', async () => {
  const h = harness({ recognition: false });
  h.session.start();
  assert.equal(h.session.connected, true);
  assert.equal(h.recognitions.length, 0);
  await h.session.submit('文字也行');
  await h.flush();
  assert.equal(h.sent[0].text, '文字也行');
  assert.equal(h.session.turns.length, 2);
  assert.equal(h.session.phase, 'idle');
});

test('hangup ignores a late model reply', async () => {
  let resolveReply;
  const h = harness({ send: () => new Promise(resolve => { resolveReply = resolve; }) });
  h.session.start();
  const pending = h.session.submit('晚点回答');
  h.session.close();
  resolveReply('不应播放');
  await pending;
  assert.equal(h.requests.length, 0);
  assert.equal(h.session.turns.length, 1);
});
