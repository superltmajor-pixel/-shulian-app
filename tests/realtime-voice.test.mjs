import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../web/realtime-voice.jsx', import.meta.url), 'utf8').split('function useRealtimeCallEngine')[0];

function harness({ microphone } = {}) {
  let clock = 0, nextTimer = 0;
  const timers = new Map(), events = [], sources = [], sockets = [];
  const track = { enabled: true, stopped: false, stop() { this.stopped = true; } };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  class Audio {
    constructor() { this.currentTime = 0; this.state = 'running'; this.destination = {}; this.audioWorklet = { addModule: async () => {} }; }
    async resume() {}
    async close() { this.state = 'closed'; }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createBuffer(channels, size, rate) { return { duration: size / rate, getChannelData: () => new Float32Array(size) }; }
    createBufferSource() {
      const item = { connect() {}, disconnect() {}, start(at) { this.started = at; }, stop() { this.stopped = true; } };
      sources.push(item); return item;
    }
  }
  class Socket {
    constructor(url) { this.url = url; this.sent = []; this.readyState = 0; this.bufferedAmount = 0; sockets.push(this); }
    send(value) { this.sent.push(value); }
    close() { this.readyState = 3; }
  }
  const context = vm.createContext({
    window: { AudioContext: Audio, location: { href: 'http://127.0.0.1:8770/' } },
    navigator: { mediaDevices: { getUserMedia: microphone || (async () => stream) } },
    AudioWorkletNode: class { constructor() { this.port = {}; } connect() {} disconnect() {} },
    WebSocket: Socket, URL, ArrayBuffer, DataView, Int16Array,
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, at: clock + delay }); return id; },
    clearTimeout: id => timers.delete(id),
  });
  const Session = vm.runInContext(source + '\nRealtimeVoiceSession', context);
  const session = new Session('ruri', { message: 'call' }, event => events.push(event));
  const advance = ms => {
    clock += ms; if (session.audio) session.audio.currentTime += ms / 1000;
    for (const [id, timer] of [...timers]) if (timer.at <= clock) { timers.delete(id); timer.callback(); }
  };
  const connect = async () => {
    await session.start();
    session.ws.readyState = 1; session.ws.onopen();
    session.receive({ type: 'ready' });
  };
  const event = (event, data = {}) => session.receive({ type: 'event', event, data });
  return { session, track, stream, events, sources, sockets, timers, advance, connect, event };
}

test('continuous capture only sends after readiness, honors mute and backpressure', async () => {
  const h = harness(); await h.connect();
  const pcm = new ArrayBuffer(640);
  h.session.capture.port.onmessage({ data: pcm });
  assert.equal(h.session.ws.sent.at(-1), pcm);
  const count = h.session.ws.sent.length;
  h.session.mute(true);
  h.session.capture.port.onmessage({ data: pcm });
  assert.equal(h.session.ws.sent.length, count);
  assert.equal(h.track.enabled, false);
  assert.equal(h.session.phase, 'idle');
  h.session.mute(false);
  assert.equal(h.track.enabled, true);
  h.session.ws.bufferedAmount = 64001;
  h.session.capture.port.onmessage({ data: pcm });
  assert.equal(h.session.closed, true);
  assert.equal(h.track.stopped, true);
});

test('barge-in stops queued audio and drops stale reply and unheard memory', async () => {
  const h = harness(); await h.connect();
  h.event(350, { reply_id: 'old', text: '未听完' });
  h.session.play(new ArrayBuffer(4800));
  h.event(351, { reply_id: 'old' });
  h.advance(30);
  h.event(450, { question_id: 'next' });
  assert.equal(h.sources[0].stopped, true);
  assert.equal(h.session.turns.length, 0);
  const truncation = h.session.ws.sent.filter(x => typeof x === 'string').map(JSON.parse).find(x => x.type === 'truncate');
  assert.equal(truncation.reply_id, 'old');
  assert.equal(truncation.audio_end_ms, 15);
  h.event(350, { reply_id: 'old', text: '旧音频' });
  h.session.play(new ArrayBuffer(4800));
  assert.equal(h.sources.length, 1);
  h.event(451, { results: [{ text: '等等', is_interim: false }] });
  h.event(459);
  assert.equal(h.session.turns[0].text, '等等');
  h.event(350, { reply_id: 'new', text: '好的' });
  h.session.play(new ArrayBuffer(960));
  h.event(351, { reply_id: 'new' });
  h.event(359, { reply_id: 'new' });
  h.advance(100);
  assert.equal(h.session.turns[1].text, '好的');
  assert.equal(h.session.phase, 'listening');
  h.session.close();
});

test('microphone permission resolving after hangup releases the late stream', async () => {
  let resolve;
  const h = harness({ microphone: () => new Promise(r => { resolve = r; }) });
  const start = h.session.start();
  for (let i = 0; i < 10 && !resolve; i++) await Promise.resolve();
  assert.equal(typeof resolve, 'function');
  h.session.close();
  resolve(h.stream); await start;
  assert.equal(h.track.stopped, true);
  assert.equal(h.session.audio.state, 'closed');
  assert.equal(h.sockets.length, 0);
  assert.equal(h.timers.size, 0);
});

test('microphone permission timeout finishes startup and releases a later stream', async () => {
  let resolve;
  const h = harness({ microphone: () => new Promise(r => { resolve = r; }) });
  const start = h.session.start();
  for (let i = 0; i < 10 && !resolve; i++) await Promise.resolve();
  h.advance(30000);
  await start;
  assert.equal(h.session.closed, true);
  assert.equal(h.events.at(-1).message, '无法启动实时录音，请检查麦克风');
  resolve(h.stream);
  await Promise.resolve();
  assert.equal(h.track.stopped, true);
});

test('hangup blocks late text, audio and microphone callbacks', async () => {
  const h = harness(); await h.connect();
  h.event(350, { reply_id: 'r', text: 'hello' });
  h.session.play(new ArrayBuffer(960));
  const capture = h.session.capture.port.onmessage;
  h.session.close();
  const count = h.session.ws.sent.length;
  capture({ data: new ArrayBuffer(640) });
  assert.equal(h.session.text('late'), false);
  h.session.play(new ArrayBuffer(960));
  assert.equal(h.session.ws.sent.length, count);
  assert.equal(h.sources.length, 1);
  assert.equal(h.timers.size, 0);
  assert.equal(h.track.stopped, true);
});

test('text is only recorded after acknowledgement; no old audio after text interruption', async () => {
  const h = harness(); await h.connect();
  h.event(350, { reply_id: 'old', text: 'old' });
  h.session.play(new ArrayBuffer(960));
  assert.equal(h.session.text('hello'), true);
  assert.equal(h.session.turns.length, 0);
  h.event(350, { reply_id: 'old', text: 'stale' });
  h.session.play(new ArrayBuffer(960));
  assert.equal(h.sources.length, 1);
  h.event(553, { question_id: 'q' });
  assert.equal(h.session.turns[0].text, 'hello');
  h.event(553, { question_id: 'q' });
  assert.equal(h.session.turns.length, 1);
  h.session.close();
});

test('silent call stays connected, but unanswered speech times out and releases mic', async () => {
  const h = harness(); await h.connect();
  h.advance(120000);
  assert.equal(h.session.closed, false);
  h.event(451, { results: [{ text: 'hello' }] });
  h.event(459);
  h.advance(45001);
  assert.equal(h.session.closed, true);
  assert.equal(h.track.stopped, true);
});

test('late reply from an older question never starts playback after a new utterance', async () => {
  const h = harness(); await h.connect();
  h.event(450, { question_id: 'new-question' });
  h.event(350, { question_id: 'old-question', reply_id: 'previously-unseen', text: 'stale' });
  h.session.play(new ArrayBuffer(960));
  assert.equal(h.sources.length, 0);
  h.event(350, { question_id: 'new-question', reply_id: 'current', text: 'hello' });
  h.session.play(new ArrayBuffer(960));
  assert.equal(h.sources.length, 1);
  h.advance(20001);
  assert.equal(h.session.closed, true, 'stalled audio stream must time out');
  h.session.close();
});

test('speaker toggle cannot resume a discarded response suffix', async () => {
  const h = harness(); await h.connect();
  h.event(350, { reply_id: 'old', text: 'partially heard' });
  h.session.play(new ArrayBuffer(4800));
  h.session.setSpeaker(false);
  h.session.setSpeaker(true);
  h.event(350, { reply_id: 'old', text: 'discarded suffix' });
  h.session.play(new ArrayBuffer(4800));
  assert.equal(h.sources.length, 1);
  assert.equal(h.sources[0].stopped, true);
  h.event(350, { reply_id: 'new', text: 'new reply' });
  h.session.play(new ArrayBuffer(960));
  assert.equal(h.sources.length, 2);
  h.session.close();
});

test('worklet resamples 44.1/48/16 kHz continuously to 20 ms PCM16 frames', () => {
  const worklet = fs.readFileSync(new URL('../web/realtime-audio-worklet.js', import.meta.url), 'utf8');
  for (const rate of [44100, 48000, 16000]) {
    const frames = []; let Processor;
    const context = vm.createContext({ sampleRate: rate, Int16Array,
      AudioWorkletProcessor: class { constructor() { this.port = { postMessage: data => frames.push(data) }; } },
      registerProcessor: (name, type) => { Processor = type; },
    });
    vm.runInContext(worklet, context);
    const processor = new Processor();
    for (let i = 0; i < rate; i += 128) processor.process([[new Float32Array(Math.min(128, rate - i)).fill(0.5)]]);
    assert.equal(frames.length, 50, `wrong duration at ${rate}`);
    assert.ok(frames.every(frame => frame.byteLength === 640));
    assert.equal(new Int16Array(frames[0])[0], 16384);
  }
});
