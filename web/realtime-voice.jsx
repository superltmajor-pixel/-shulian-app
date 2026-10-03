// Realtime transport and audio lifecycle, independent of React and chat rendering.
class RealtimeVoiceSession {
  constructor(characterId, context, emit) {
    this.characterId = characterId;
    this.context = context;
    this.emit = emit;
    this.closed = false;
    this.ready = false;
    this.muted = false;
    this.speaker = true;
    this.sources = new Set();
    this.timers = new Set();
    this.turns = [];
    this.rejectedReplies = new Set();
    this.replyId = '';
    this.questionId = '';
    this.replyText = '';
    this.heard = '';
    this.audioCursor = 0;
    this.replyStart = null;
    this.segments = [];
    this.allowAudio = false;
  }
  update(type, data = {}) {
    if (type === 'phase') this.phase = data.phase;
    if (!this.closed) this.emit({ type, ...data });
  }
  send(data) {
    if (!this.closed && this.ws?.readyState === 1) this.ws.send(JSON.stringify(data));
  }
  later(callback, delay) {
    const timer = setTimeout(() => { this.timers.delete(timer); if (!this.closed) callback(); }, delay);
    this.timers.add(timer);
    return timer;
  }
  fail(message) {
    if (this.closed) return;
    this.update('error', { message });
    this.close();
  }
  async start() {
    if (this.closed) return;
    try {
      const AudioContextType = window.AudioContext || window.webkitAudioContext;
      if (!navigator.mediaDevices?.getUserMedia || !AudioContextType) throw Error('当前环境不支持实时录音');
      this.audio = new AudioContextType();
      await this.audio.resume();
      if (this.closed) return;
      let rejectPermission;
      const permissionTimeout = new Promise((_, reject) => { rejectPermission = reject; });
      this.permissionTimer = this.later(() => {
        this.fail('无法启动实时录音，请检查麦克风');
        rejectPermission(Error('microphone timeout'));
      }, 30000);
      const microphone = navigator.mediaDevices.getUserMedia({ audio: {
        channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
      }});
      // getUserMedia cannot be cancelled. If the browser resolves it after our timeout,
      // release that late track instead of leaving the microphone active.
      microphone.then(lateStream => {
        if (this.closed) lateStream.getTracks().forEach(track => track.stop());
      }, () => {});
      const stream = await Promise.race([microphone, permissionTimeout]);
      if (this.closed) { stream.getTracks().forEach(track => track.stop()); return; }
      this.stream = stream;
      stream.getAudioTracks().forEach(track => { track.onended = () => this.fail('麦克风已断开，请重新连接'); });
      await this.audio.audioWorklet.addModule('/realtime-audio-worklet.js');
      if (this.closed) return;
      clearTimeout(this.permissionTimer);
      this.timers.delete(this.permissionTimer);
      this.capture = new AudioWorkletNode(this.audio, 'shulian-microphone');
      this.input = this.audio.createMediaStreamSource(stream);
      this.input.connect(this.capture);
      this.capture.connect(this.audio.destination); // Processor outputs silence.
      this.capture.port.onmessage = ({ data }) => {
        if (this.closed || !this.ready || this.muted || this.ws?.readyState !== 1) return;
        if (this.ws.bufferedAmount > 64000) { this.fail('网络较慢，实时通话已停止，请重新连接'); return; }
        this.ws.send(data);
      };
      const url = new URL(`/api/realtime-voice/${encodeURIComponent(this.characterId)}`, window.location.href);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      this.ws = new WebSocket(url);
      this.ws.binaryType = 'arraybuffer';
      this.ws.onopen = () => this.send({ type: 'start', ...this.context });
      this.ws.onmessage = ({ data }) => {
        if (this.closed) return;
        try {
          if (data instanceof ArrayBuffer) this.play(data);
          else this.receive(JSON.parse(data));
        } catch { this.fail('实时语音数据异常，请重新连接'); }
      };
      this.ws.onerror = () => this.fail('实时语音连接失败，请检查服务开通、凭据和网络');
      this.ws.onclose = () => this.fail('实时语音已断开，请重新连接');
      this.connectTimer = this.later(() => this.fail('实时语音连接超时，请重新连接'), 30000);
    } catch (error) {
      this.fail(error?.name === 'NotAllowedError' ? '麦克风权限被拒绝，请允许麦克风后重试' : '无法启动实时录音，请检查麦克风');
    }
  }
  append(from, text) {
    if (!text?.trim()) return;
    // Keep the whole call for consolidation; UI subtitles are separate.
    if (from === 'her' && this.turns.at(-1)?.from === 'her') this.turns.at(-1).text += text;
    else this.turns.push({ from, text, ts: Date.now() });
    this.update('turns', { turns: [...this.turns] });
  }
  stopPlayback(truncate = true) {
    if (truncate && this.replyId && this.replyStart !== null) {
      const duration = this.segments.reduce((sum, segment) => sum + Math.max(0, Math.min(segment.duration, this.audio.currentTime - segment.start)), 0) * 1000;
      this.send({ type: 'truncate', reply_id: this.replyId, audio_end_ms: Math.floor(duration) });
    }
    for (const source of this.sources) { source.onended = null; try { source.stop(); } catch {} source.disconnect(); }
    this.sources.clear();
    for (const timer of this.timers) clearTimeout(timer);
    this.timers.clear();
    this.audioCursor = this.audio?.currentTime || 0;
    this.replyStart = null;
    this.segments = [];
  }
  play(bytes) {
    if (!this.allowAudio || !this.ready) return;
    this.waitForReply(20000);
    if (!this.speaker) return;
    if (bytes.byteLength % 2) throw Error('invalid pcm');
    const pcm = new DataView(bytes);
    const buffer = this.audio.createBuffer(1, bytes.byteLength / 2, 24000);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) samples[i] = pcm.getInt16(i * 2, true) / 32768;
    const start = Math.max(this.audio.currentTime + 0.015, this.audioCursor);
    if (start - this.audio.currentTime > 30) throw Error('playback backlog');
    if (this.replyStart === null) this.replyStart = start;
    const source = this.audio.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audio.destination);
    this.sources.add(source);
    source.onended = () => { this.sources.delete(source); source.disconnect(); };
    source.start(start);
    this.audioCursor = start + buffer.duration;
    this.segments.push({ start, duration: buffer.duration });
    this.update('phase', { phase: 'speaking' });
  }
  receive(message) {
    if (message.type === 'error') { this.fail(message.message); return; }
    if (message.type === 'ready') {
      clearTimeout(this.connectTimer);
      this.timers.delete(this.connectTimer);
      this.ready = true;
      this.update('ready');
      this.update('phase', { phase: 'listening' });
      return;
    }
    const { event, data = {} } = message;
    if (event === 450) {
      this.questionId = data.question_id || '';
      if (this.replyId) this.rejectedReplies.add(this.replyId);
      if (this.rejectedReplies.size > 128) this.rejectedReplies.delete(this.rejectedReplies.values().next().value);
      this.stopPlayback();
      this.allowAudio = false;
      this.replyId = '';
      this.replyText = '';
      this.heard = '';
      this.update('heard', { text: '' });
      this.update('line', { text: '' });
      this.update('phase', { phase: 'listening' });
    } else if (event === 553) {
      this.questionId = data.question_id || '';
      if (this.pendingText) this.append('me', this.pendingText);
      this.pendingText = '';
    } else if (event === 451) {
      this.heard = (data.results || []).map(result => result.text || '').join('');
      this.update('heard', { text: this.heard });
    } else if (event === 459) {
      this.append('me', this.heard);
      this.heard = '';
      this.update('phase', { phase: 'thinking' });
      this.waitForReply();
    } else if ([350, 351, 359, 550, 559].includes(event)) {
      if (this.rejectedReplies.has(data.reply_id)) return;
      if (this.pendingText || (this.questionId && data.question_id && this.questionId !== data.question_id)) return;
      if (data.reply_id && this.replyId !== data.reply_id) {
        this.replyId = data.reply_id;
        this.replyText = '';
        this.replyStart = null;
        this.segments = [];
      }
      if (event === 350) {
        this.allowAudio = true;
        this.sentence = data.text || '';
      } else if (event === 550) {
        this.replyText += data.content || '';
        this.update('line', { text: this.replyText });
      } else if (event === 351) {
        const sentence = this.sentence;
        if (this.speaker) this.afterPlayback(() => this.append('her', sentence));
      } else if (event === 359) {
        clearTimeout(this.replyTimer);
        this.timers.delete(this.replyTimer);
        this.allowAudio = false;
        this.afterPlayback(() => this.update('phase', { phase: this.muted ? 'idle' : 'listening' }));
      }
    }
  }
  waitForReply(timeout = 45000) {
    clearTimeout(this.replyTimer);
    this.timers.delete(this.replyTimer);
    this.replyTimer = this.later(() => this.fail('实时语音回复超时，请重新连接'), timeout);
  }
  afterPlayback(callback) {
    const end = this.audioCursor;
    const check = () => {
      const delay = (end - this.audio.currentTime) * 1000;
      if (delay > 1) this.later(check, Math.max(20, delay));
      else callback();
    };
    check();
  }
  text(text) {
    text = String(text || '').trim();
    if (!this.ready || this.closed || this.pendingText || !text || text.length > 4000) return false;
    if (this.replyId) this.rejectedReplies.add(this.replyId);
    this.stopPlayback();
    this.allowAudio = false;
    this.pendingText = text;
    this.send({ type: 'text', text });
    this.update('phase', { phase: 'thinking' });
    this.waitForReply();
    return true;
  }
  mute(value) {
    this.muted = value;
    this.stream?.getAudioTracks().forEach(track => { track.enabled = !value; });
    this.update('muted', { muted: value });
    if (this.phase === 'listening' || this.phase === 'idle') this.update('phase', { phase: value ? 'idle' : 'listening' });
  }
  setSpeaker(value) {
    this.speaker = value;
    if (!value) {
      if (this.replyId) this.rejectedReplies.add(this.replyId);
      this.stopPlayback();
      this.allowAudio = false;
      this.update('phase', { phase: this.muted ? 'idle' : 'listening' });
    }
  }
  close() {
    if (this.closed) return;
    this.stopPlayback();
    this.send({ type: 'end' });
    this.closed = true;
    this.ready = false;
    this.capture?.disconnect();
    this.input?.disconnect();
    if (this.capture) this.capture.port.onmessage = null;
    this.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    if (this.audio && this.audio.state !== 'closed') this.audio.close().catch(() => {});
    if (this.ws) {
      this.ws.onmessage = this.ws.onerror = this.ws.onclose = null;
      this.ws.close();
    }
  }
}

function useRealtimeCallEngine(c, onContext) {
  const [sec, setSec] = React.useState(0);
  const [speaker, setSpeakerState] = React.useState(true);
  const [phase, setPhase] = React.useState('idle');
  const [line, setLine] = React.useState('');
  const [heard, setHeard] = React.useState('');
  const [draft, setDraft] = React.useState('');
  const [error, setError] = React.useState('');
  const [turns, setTurns] = React.useState([]);
  const [muted, setMuted] = React.useState(false);
  const [connected, setConnected] = React.useState(false);
  const [config, setConfig] = React.useState(null);
  const [editing, setEditing] = React.useState(false);
  const session = React.useRef(null);
  const alive = React.useRef(true);
  const starting = React.useRef(false);
  const previousTurns = React.useRef([]);
  React.useEffect(() => {
    const controller = new AbortController();
    alive.current = true;
    fetch(`/api/realtime-voice/config?character_id=${encodeURIComponent(c.id)}`, { signal: controller.signal })
      .then(async response => { if (!response.ok) throw Error(); return response.json(); })
      .then(value => { if (alive.current) { setConfig(value); setEditing(!value.configured); } })
      .catch(() => { if (alive.current) setError('实时语音配置读取失败'); });
    return () => { alive.current = false; controller.abort(); session.current?.close(); };
  }, [c.id]);
  React.useEffect(() => {
    if (!connected) return;
    const timer = setInterval(() => setSec(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, [connected]);
  const start = async () => {
    if (starting.current || connected || !config?.configured || !alive.current) return;
    starting.current = true;
    setError(''); setPhase('connecting'); setMuted(false);
    previousTurns.current = turns;
    try {
      const context = onContext(turns);
      if (!alive.current) return;
      const current = new RealtimeVoiceSession(c.id, context, event => {
        if (!alive.current) return;
        if (event.type === 'ready') setConnected(true);
        if (event.type === 'phase') setPhase(event.phase);
        if (event.type === 'line') setLine(event.text);
        if (event.type === 'heard') setHeard(event.text);
        if (event.type === 'muted') setMuted(event.muted);
        if (event.type === 'turns') setTurns([...previousTurns.current, ...event.turns]);
        if (event.type === 'error') { setError(event.message); setConnected(false); setPhase('idle'); }
      });
      current.speaker = speaker;
      session.current = current;
      await current.start();
    } catch { setError('实时语音连接失败，请检查服务开通、凭据和网络'); setPhase('idle'); }
    finally { starting.current = false; }
  };
  const hangupCleanup = () => {
    alive.current = false;
    session.current?.close();
    return session.current ? [...previousTurns.current, ...session.current.turns] : turns;
  };
  const startListen = () => { if (!connected) start(); else session.current?.mute(false); };
  const stopListen = () => session.current?.mute(true);
  const submitTurn = text => { if (session.current?.text(text)) setDraft(''); };
  const setSpeaker = updater => setSpeakerState(old => {
    const value = typeof updater === 'function' ? updater(old) : updater;
    session.current?.setSpeaker(value); return value;
  });
  return { sec, speaker, setSpeaker, line, phase, heard, draft, setDraft, error, turns,
    isListening: connected && !muted, callTyping: phase === 'thinking', isSpeaking: phase === 'speaking',
    hasSR: true, submitTurn, startListen, stopListen, hangupCleanup,
    connected, muted, config, setConfig, editing, setEditing, start };
}

function RealtimeVoiceControls({ engine, characterId }) {
  const { config, setConfig, editing, setEditing, connected, phase, start } = engine;
  const [appId, setAppId] = React.useState('');
  const [token, setToken] = React.useState('');
  const [voice, setVoice] = React.useState('saturn_zh_female_wenrouwenya_tob');
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState('');
  React.useEffect(() => { if (config) { setAppId(config.app_id); setVoice(config.speaker); } }, [config]);
  if (connected) return <div style={{ fontSize: 12, color: '#fff', marginTop: 8 }}>{uiT(engine.muted ? '麦克风已静音' : '持续收音中，可直接开口打断；麦克风按钮切换静音')}</div>;
  const save = async event => {
    event.preventDefault(); setSaving(true); setMessage('');
    try {
      const response = await fetch('/api/realtime-voice/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: appId.trim(), access_key: token.trim(), speaker: voice.trim(), character_id: characterId }) });
      if (!response.ok) throw Error();
      setConfig(await response.json()); setToken(''); setEditing(false);
    } catch { setMessage('保存失败，请检查应用 ID、凭据和音色 ID'); }
    finally { setSaving(false); }
  };
  const fieldStyle = { width: '100%', boxSizing: 'border-box', padding: '7px 10px', borderRadius: 8, border: '1px solid var(--line-color)', background: 'var(--surface-secondary)', color: 'var(--ink)' };
  return <div style={{ width: 'min(100%, 430px)', margin: '8px auto', fontSize: 12 }}>
    {editing ? <form onSubmit={save} style={{ display: 'grid', gap: 6 }}>
      <strong>{uiT('豆包实时语音 · SC 2.0')}</strong>
      <input style={fieldStyle} aria-label="App ID" placeholder="App ID" value={appId} onChange={e => setAppId(e.target.value)} required maxLength={100} />
      <input style={fieldStyle} type="password" autoComplete="off" aria-label="Access Token" placeholder={config?.configured ? uiT('Access Token（留空保留）') : 'Access Token'} value={token} onChange={e => setToken(e.target.value)} required={!config?.configured} maxLength={4096} />
      <input style={fieldStyle} aria-label={uiT('当前角色音色 ID')} placeholder={uiT('当前角色音色 ID')} value={voice} onChange={e => setVoice(e.target.value)} required maxLength={150} />
      <span>{uiT('凭据加密保存在本机；保存不发起付费调用')}</span>
      {message && <span role="alert">{uiT(message)}</span>}
      <button disabled={saving} type="submit">{uiT(saving ? '正在保存…' : '保存语音配置')}</button>
      {config?.configured && <button type="button" onClick={() => setEditing(false)}>{uiT('取消')}</button>}
    </form> : <div style={{ display: 'grid', gap: 6 }}>
      <span>{uiT('连接后麦克风持续上传至豆包语音，按服务用量计费')}</span>
      <button type="button" disabled={!config?.configured || phase === 'connecting'} onClick={start}>{uiT(phase === 'connecting' ? '正在接通' : '连接实时通话')}</button>
      <button type="button" disabled={phase === 'connecting'} onClick={() => setEditing(true)}>{uiT('配置语音服务')}</button>
    </div>}
  </div>;
}
