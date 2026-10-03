// compatible-voice.jsx — 复用现有聊天模型和 TTS 的免配置通话线路。

class CompatibleVoiceSession {
  constructor(character, onSend, emit) {
    this.character = character;
    this.characterId = character.id;
    this.onSend = onSend;
    this.emit = emit;
    this.turns = [];
    this.connected = false;
    this.closed = false;
    this.muted = false;
    this.speaker = true;
    this.pending = false;
    this.phase = 'idle';
    this.recognition = null;
    this.listenTimer = null;
    this.ttsController = null;
    this.audio = null;
    this.audioUrl = '';
    this.finishPlayback = null;
    this.speechSeq = 0;
    this.requestSeq = 0;
    this.recognitionFailures = 0;
    this.Recognition = window.SpeechRecognition || window.webkitSpeechRecognition || null;
    this.nativeShell = Boolean(window.pywebview);
    this.recognitionAvailable = this.nativeShell ? false : Boolean(this.Recognition);
    this.recognitionUnavailableMessage = '';
    this.localSequence = 0;
    this.localStarting = false;
    this.localSocket = null;
    this.localAudio = null;
    this.localStream = null;
    this.localCapture = null;
    this.localInput = null;
  }

  update(type, data = {}) {
    if (!this.closed) this.emit({ type, ...data });
  }

  setPhase(phase) {
    this.phase = phase;
    this.update('phase', { phase });
  }

  start() {
    if (this.connected || this.closed) return;
    this.connected = true;
    this.muted = false;
    this.update('ready');
    this.update('muted', { muted: false });
    if (this.nativeShell) {
      if (!this.recognitionAvailable) {
        this.update('capability', { hasSR: false });
        this.setPhase('idle');
        this.update('error', { message: this.recognitionUnavailableMessage || '请先准备本地中文语音识别' });
        return;
      }
      this.beginListening();
      return;
    }
    if (!this.Recognition) {
      this.recognitionAvailable = false;
      this.update('capability', { hasSR: false });
      this.setPhase('idle');
      this.update('error', { message: '当前环境不支持语音识别，可以使用通话文字输入' });
      return;
    }
    this.beginListening();
  }

  disableRecognition(message) {
    this.recognitionAvailable = false;
    this.recognitionUnavailableMessage = message;
    this.muted = true;
    this.update('capability', { hasSR: false });
    this.update('muted', { muted: true });
    this.setPhase('idle');
    this.update('error', { message });
  }

  scheduleListening(delay = 220) {
    clearTimeout(this.listenTimer);
    if (this.closed || !this.connected || this.muted || this.pending || this.phase === 'speaking') return;
    this.listenTimer = setTimeout(() => this.beginListening(), delay);
  }

  beginListening() {
    clearTimeout(this.listenTimer);
    if (this.nativeShell) {
      void this.beginLocalListening();
      return;
    }
    if (!this.Recognition || !this.recognitionAvailable || this.recognition || this.closed || !this.connected || this.muted || this.pending) return;
    this.stopSpeech();
    const recognition = new this.Recognition();
    recognition.lang = 'zh-CN';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    let restartDelay = 220;
    recognition.onresult = event => {
      let finalText = '';
      let interimText = '';
      const start = Number.isInteger(event.resultIndex) ? event.resultIndex : 0;
      for (let index = start; index < event.results.length; index++) {
        const result = event.results[index];
        const text = String(result?.[0]?.transcript || '');
        if (result?.isFinal) finalText += text;
        else interimText += text;
      }
      const heard = `${finalText}${interimText}`.trim();
      if (heard) {
        this.recognitionFailures = 0;
        this.update('error', { message: '' });
        this.update('heard', { text: heard });
      }
      if (finalText.trim()) {
        this.stopRecognition();
        this.submit(finalText);
      }
    };
    recognition.onerror = event => {
      if (this.recognition === recognition) this.recognition = null;
      const reason = String(event?.error || '');
      if (reason === 'not-allowed') {
        this.muted = true;
        this.update('muted', { muted: true });
        this.setPhase('idle');
        this.update('error', { message: '麦克风权限被拒绝，请允许麦克风后重试' });
        return;
      }
      if (reason === 'service-not-allowed' || reason === 'language-not-supported'
          || reason === 'language-unavailable') {
        this.disableRecognition('桌面客户端的语音识别不可用，请切换豆包端到端或使用文字输入');
        return;
      }
      if (reason === 'audio-capture') {
        this.muted = true;
        this.update('muted', { muted: true });
        this.setPhase('idle');
        this.update('error', { message: '无法启动语音识别，请检查麦克风' });
        return;
      }
      if (reason && reason !== 'no-speech' && reason !== 'aborted') {
        this.recognitionFailures += 1;
        this.setPhase('idle');
        if (this.recognitionFailures >= 5) {
          this.muted = true;
          this.update('muted', { muted: true });
          this.update('error', { message: '语音识别持续失败，请点击麦克风重试或使用文字输入' });
          return;
        }
        restartDelay = Math.min(8000, 1000 * (2 ** (this.recognitionFailures - 1)));
        this.update('error', { message: '语音识别服务暂时不可用，正在自动重试' });
      }
    };
    recognition.onend = () => {
      if (this.recognition === recognition) this.recognition = null;
      if (!this.closed && this.connected && this.recognitionAvailable && !this.muted && !this.pending) this.scheduleListening(restartDelay);
    };
    try {
      this.recognition = recognition;
      recognition.start();
      this.setPhase('listening');
    } catch {
      if (this.recognition === recognition) this.recognition = null;
      this.setPhase('idle');
      this.update('error', { message: '无法启动语音识别，请检查麦克风' });
    }
  }

  setLocalAsrReady(ready, message = '') {
    if (!this.nativeShell) return;
    this.recognitionAvailable = Boolean(ready);
    this.recognitionUnavailableMessage = message;
  }

  async beginLocalListening() {
    if (this.localStarting || this.localSocket || this.closed || !this.connected || this.muted || this.pending) return;
    if (!this.recognitionAvailable) {
      this.update('capability', { hasSR: false });
      this.setPhase('idle');
      this.update('error', { message: this.recognitionUnavailableMessage || '请先准备本地中文语音识别' });
      return;
    }
    const sequence = ++this.localSequence;
    this.localStarting = true;
    this.stopSpeech();
    let timeout = null;
    try {
      const AudioContextType = window.AudioContext || window.webkitAudioContext;
      if (!navigator.mediaDevices?.getUserMedia || !AudioContextType) throw Error('当前环境不支持实时录音');
      const audio = new AudioContextType();
      this.localAudio = audio;
      await audio.resume();
      if (this.closed || sequence !== this.localSequence) return;

      let rejectPermission;
      const permissionTimeout = new Promise((_, reject) => { rejectPermission = reject; });
      timeout = setTimeout(() => rejectPermission(Error('microphone timeout')), 30000);
      const microphone = navigator.mediaDevices.getUserMedia({ audio: {
        channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
      }});
      microphone.then(lateStream => {
        if (this.closed || sequence !== this.localSequence) lateStream.getTracks().forEach(track => track.stop());
      }, () => {});
      const stream = await Promise.race([microphone, permissionTimeout]);
      clearTimeout(timeout);
      timeout = null;
      if (this.closed || sequence !== this.localSequence) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      this.localStream = stream;
      stream.getAudioTracks().forEach(track => { track.onended = () => {
        if (sequence === this.localSequence) this.pauseLocalRecognition('麦克风已断开，请重新连接');
      }; });

      await audio.audioWorklet.addModule('/realtime-audio-worklet.js');
      if (this.closed || sequence !== this.localSequence) return;
      const capture = new AudioWorkletNode(audio, 'shulian-microphone');
      const input = audio.createMediaStreamSource(stream);
      this.localCapture = capture;
      this.localInput = input;
      input.connect(capture);
      capture.connect(audio.destination);

      const url = new URL('/api/local-asr/stream', window.location.href);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      const socket = new WebSocket(url);
      socket.binaryType = 'arraybuffer';
      this.localSocket = socket;
      await new Promise((resolve, reject) => {
        let ready = false;
        timeout = setTimeout(() => reject(Error('local ASR connection timeout')), 15000);
        socket.onmessage = ({ data }) => {
          let message;
          try { message = JSON.parse(data); } catch {
            const error = Error('本地语音识别处理失败，请重试');
            if (ready) this.pauseLocalRecognition(error.message);
            else reject(error);
            return;
          }
          if (message.type === 'ready') {
            ready = true;
            clearTimeout(timeout);
            timeout = null;
            resolve();
          } else if (message.type === 'error') {
            const error = Error(message.message || '本地语音识别连接失败');
            if (ready) this.pauseLocalRecognition(error.message);
            else reject(error);
          } else if (message.type === 'partial') {
            this.update('heard', { text: String(message.text || '') });
          } else if (message.type === 'final') {
            const text = String(message.text || '').trim();
            this.update('heard', { text });
            if (text && sequence === this.localSequence) {
              this.stopRecognition();
              void this.submit(text);
            }
          }
        };
        socket.onerror = () => reject(Error('本地语音识别连接失败，请重试'));
        socket.onclose = () => {
          if (!ready) reject(Error('本地语音识别连接失败，请重试'));
          else if (sequence === this.localSequence && !this.closed && this.connected && !this.muted && !this.pending) {
            this.pauseLocalRecognition('本地语音识别已断开，请点击麦克风重试');
          }
        };
      });
      if (this.closed || sequence !== this.localSequence) return;
      clearTimeout(timeout);
      timeout = null;
      capture.port.onmessage = ({ data }) => {
        if (this.closed || sequence !== this.localSequence || this.muted || socket.readyState !== WebSocket.OPEN) return;
        if (socket.bufferedAmount > 12800) {
          this.pauseLocalRecognition('本地语音识别处理较慢，请点击麦克风重试');
          return;
        }
        socket.send(data);
      };
      this.localStarting = false;
      this.update('capability', { hasSR: true });
      this.update('error', { message: '' });
      this.setPhase('listening');
    } catch (error) {
      clearTimeout(timeout);
      if (sequence !== this.localSequence || this.closed) return;
      this.stopLocalRecognition();
      this.setPhase('idle');
      const message = error?.name === 'NotAllowedError'
        ? '麦克风权限被拒绝，请允许麦克风后重试'
        : error?.message === '当前环境不支持实时录音'
          ? error.message
          : error?.message === '本地语音识别连接失败，请重试' || error?.message === '本地语音识别连接失败'
            ? error.message
            : error?.message === '请先下载本地中文语音模型' || error?.message?.includes('客户端未包含本地识别组件')
              ? error.message
              : '本地语音识别启动失败，请检查麦克风或重试';
      this.update('error', { message });
    } finally {
      if (sequence === this.localSequence) this.localStarting = false;
    }
  }

  stopLocalRecognition() {
    this.localSequence += 1;
    this.localStarting = false;
    const socket = this.localSocket;
    this.localSocket = null;
    if (socket) {
      socket.onmessage = socket.onerror = socket.onclose = null;
      try { socket.close(); } catch {}
    }
    if (this.localCapture) {
      this.localCapture.port.onmessage = null;
      try { this.localCapture.disconnect(); } catch {}
      this.localCapture = null;
    }
    try { this.localInput?.disconnect(); } catch {}
    this.localInput = null;
    this.localStream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    this.localStream = null;
    if (this.localAudio && this.localAudio.state !== 'closed') this.localAudio.close().catch(() => {});
    this.localAudio = null;
  }

  pauseLocalRecognition(message) {
    if (this.closed) return;
    this.stopRecognition();
    this.muted = true;
    this.update('muted', { muted: true });
    this.setPhase('idle');
    this.update('error', { message });
  }

  stopRecognition() {
    clearTimeout(this.listenTimer);
    this.stopLocalRecognition();
    const recognition = this.recognition;
    this.recognition = null;
    if (!recognition) return;
    recognition.onend = null;
    recognition.onresult = null;
    recognition.onerror = null;
    try { recognition.abort(); } catch {}
  }

  appendTurn(from, text) {
    this.turns = [...this.turns, { from, text, ts: Date.now() }].slice(-24);
    this.update('turns', { turns: [...this.turns] });
  }

  async submit(rawText) {
    const text = String(rawText || '').trim();
    if (!text || this.closed || !this.connected || this.pending) return false;
    this.pending = true;
    const request = ++this.requestSeq;
    const previousTurns = [...this.turns];
    this.stopRecognition();
    this.stopSpeech();
    this.appendTurn('me', text);
    this.update('heard', { text });
    this.setPhase('thinking');
    try {
      const reply = String(await this.onSend(text, previousTurns) || '').trim();
      if (!reply) throw new Error('empty reply');
      if (this.closed || request !== this.requestSeq) return false;
      this.appendTurn('her', reply);
      this.update('line', { text: reply });
      this.pending = false;
      await this.speak(reply);
      if (!this.closed && this.connected && !this.muted && this.recognitionAvailable) {
        this.setPhase('listening');
        this.scheduleListening(120);
      } else if (!this.closed) {
        this.setPhase('idle');
      }
      return true;
    } catch {
      if (this.closed || request !== this.requestSeq) return false;
      this.pending = false;
      this.setPhase(this.muted || !this.recognitionAvailable ? 'idle' : 'listening');
      this.update('error', { message: '通话回复失败，请检查 AI 服务后重试' });
      this.scheduleListening();
      return false;
    }
  }

  spokenText(text) {
    return String(text || '')
      .replace(/[（(][^）)]*[）)]/g, '')
      .replace(/[*_#`]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  speechSegments(text) {
    const value = this.spokenText(text);
    if (!value) return [];
    const pieces = value.match(/[^。！？!?；;\n]+[。！？!?；;\n]?/g) || [value];
    const segments = [];
    let current = '';
    pieces.forEach(piece => {
      const next = `${current}${piece}`.trim();
      if (current && next.length > 110) {
        segments.push(current);
        current = piece.trim();
      } else current = next;
    });
    if (current) segments.push(current);
    return segments;
  }

  async fetchClip(text, signal) {
    const response = await fetch(`/api/tts/${encodeURIComponent(this.characterId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal,
    });
    if (!response.ok) throw new Error('tts failed');
    return response.blob();
  }

  playClip(blob, sequence) {
    return new Promise(resolve => {
      if (this.closed || sequence !== this.speechSeq) { resolve(false); return; }
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      let finished = false;
      const finish = played => {
        if (finished) return;
        finished = true;
        if (this.finishPlayback === finish) this.finishPlayback = null;
        if (this.audio === audio) this.audio = null;
        if (this.audioUrl === url) this.audioUrl = '';
        URL.revokeObjectURL(url);
        resolve(played);
      };
      this.audio = audio;
      this.audioUrl = url;
      this.finishPlayback = finish;
      audio.onended = () => finish(true);
      audio.onerror = () => finish(false);
      audio.play().catch(() => finish(false));
    });
  }

  browserSpeak(text, sequence) {
    return new Promise(resolve => {
      if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === 'undefined' || this.closed || sequence !== this.speechSeq) {
        resolve(false);
        return;
      }
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'zh-CN';
      utterance.rate = 1;
      const voices = window.speechSynthesis.getVoices?.() || [];
      const chineseVoice = voices.find(voice => /^zh/i.test(voice.lang || ''));
      if (chineseVoice) utterance.voice = chineseVoice;
      let finished = false;
      const finish = played => {
        if (finished) return;
        finished = true;
        if (this.finishPlayback === finish) this.finishPlayback = null;
        resolve(played);
      };
      this.finishPlayback = finish;
      utterance.onend = () => finish(true);
      utterance.onerror = () => finish(false);
      window.speechSynthesis.speak(utterance);
    });
  }

  async speak(text) {
    const segments = this.speechSegments(text);
    if (!this.speaker || !segments.length || this.closed) return;
    const sequence = ++this.speechSeq;
    const controller = new AbortController();
    this.ttsController = controller;
    this.setPhase('speaking');
    const preload = segment => this.fetchClip(segment, controller.signal)
      .then(blob => ({ blob, error: null }))
      .catch(error => ({ blob: null, error }));
    let nextClip = preload(segments[0]);
    for (let index = 0; index < segments.length; index++) {
      const { blob: clip, error } = await nextClip;
      if (error) {
        if (index === 0 && sequence === this.speechSeq) await this.browserSpeak(this.spokenText(text), sequence);
        break;
      }
      if (this.closed || sequence !== this.speechSeq) break;
      nextClip = index + 1 < segments.length ? preload(segments[index + 1]) : null;
      const played = await this.playClip(clip, sequence);
      if (!played || this.closed || sequence !== this.speechSeq) break;
    }
    if (this.ttsController === controller) this.ttsController = null;
  }

  stopSpeech() {
    this.speechSeq++;
    this.ttsController?.abort();
    this.ttsController = null;
    const finish = this.finishPlayback;
    this.finishPlayback = null;
    try { this.audio?.pause(); } catch {}
    this.audio = null;
    if (this.audioUrl) {
      try { URL.revokeObjectURL(this.audioUrl); } catch {}
      this.audioUrl = '';
    }
    try { window.speechSynthesis?.cancel(); } catch {}
    finish?.(false);
  }

  mute(value) {
    if (!this.connected || this.closed) return;
    this.muted = Boolean(value);
    this.update('muted', { muted: this.muted });
    if (this.muted) {
      this.stopRecognition();
      if (!this.pending && this.phase !== 'speaking') this.setPhase('idle');
    } else if (!this.pending) {
      this.beginListening();
    }
  }

  setSpeaker(value) {
    this.speaker = Boolean(value);
    if (!this.speaker && this.phase === 'speaking') {
      this.stopSpeech();
      if (!this.muted && !this.pending) {
        this.setPhase('listening');
        this.scheduleListening(80);
      }
    }
  }

  startListening() {
    if (!this.connected) { this.start(); return; }
    if (this.pending) return;
    if (!this.recognitionAvailable) {
      this.disableRecognition(this.recognitionUnavailableMessage
        || '桌面客户端的语音识别不可用，请切换豆包端到端或使用文字输入');
      return;
    }
    this.recognitionFailures = 0;
    this.muted = false;
    this.update('muted', { muted: false });
    this.update('error', { message: '' });
    this.beginListening();
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.connected = false;
    this.requestSeq++;
    clearTimeout(this.listenTimer);
    this.stopRecognition();
    this.stopSpeech();
  }
}

function useCompatibleCallEngine(c, onSend) {
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
  const nativeShell = Boolean(window.pywebview);
  const [hasSR, setHasSR] = React.useState(!nativeShell && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition));
  const [localAsr, setLocalAsr] = React.useState({
    checking: nativeShell, downloading: false, runtime_available: false, model_installed: false,
    ready: false, status_error: false, route_missing: false,
  });
  const session = React.useRef(null);
  const alive = React.useRef(true);
  React.useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; session.current?.close(); };
  }, [c.id]);
  React.useEffect(() => {
    if (!connected) return;
    const timer = setInterval(() => setSec(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, [connected]);
  React.useEffect(() => {
    if (!nativeShell) return undefined;
    let active = true;
    setLocalAsr(value => ({ ...value, checking: true }));
    fetch('/api/local-asr/status')
      .then(async response => {
        const value = await response.json();
        if (!response.ok) {
          const error = Error(value?.detail || '本地语音识别状态读取失败');
          error.status = response.status;
          throw error;
        }
        if (!active) return;
        setLocalAsr(current => ({ ...current, ...value, checking: false, status_error: false, route_missing: false }));
        setHasSR(Boolean(value.ready));
      })
      .catch(error => {
        if (!active) return;
        setLocalAsr(current => ({ ...current, checking: false, status_error: true, route_missing: error?.status === 404 }));
        setHasSR(false);
      });
    return () => { active = false; };
  }, [c.id, nativeShell]);
  const downloadLocalAsr = async () => {
    if (!nativeShell || localAsr.downloading) return;
    setLocalAsr(value => ({ ...value, downloading: true }));
    setError('');
    try {
      const response = await fetch('/api/local-asr/download', { method: 'POST' });
      const value = await response.json();
      if (!response.ok) throw Error(value?.detail || '本地语音模型下载失败，请检查网络后重试');
      setLocalAsr(current => ({ ...current, ...value, checking: false, downloading: false, status_error: false, route_missing: false }));
      setHasSR(Boolean(value.ready));
    } catch (error) {
      setLocalAsr(value => ({ ...value, downloading: false }));
      setError(error?.message || '本地语音模型下载失败，请检查网络后重试');
    }
  };
  const start = () => {
    if (connected || session.current) return;
    setError('');
    const current = new CompatibleVoiceSession(c, onSend, event => {
      if (!alive.current) return;
      if (event.type === 'ready') setConnected(true);
      if (event.type === 'phase') setPhase(event.phase);
      if (event.type === 'line') setLine(event.text);
      if (event.type === 'heard') setHeard(event.text);
      if (event.type === 'muted') setMuted(event.muted);
      if (event.type === 'capability') setHasSR(event.hasSR);
      if (event.type === 'turns') setTurns(event.turns);
      if (event.type === 'error') setError(event.message);
    });
    current.speaker = speaker;
    current.setLocalAsrReady(localAsr.ready, localAsr.status_error && !localAsr.route_missing
      ? '无法读取本地语音识别状态，请重启客户端后重试。'
      : !localAsr.runtime_available
        ? '当前客户端未包含本地识别组件，请更新客户端后重试'
        : '请先下载本地中文语音模型');
    session.current = current;
    current.start();
  };
  const hangupCleanup = () => {
    const completed = session.current ? [...session.current.turns] : turns;
    session.current?.close();
    return completed;
  };
  const startListen = () => session.current?.startListening();
  const stopListen = () => session.current?.mute(true);
  const submitTurn = text => {
    if (!session.current) return;
    if (String(text || '').trim()) setDraft('');
    session.current.submit(text);
  };
  const setSpeaker = updater => setSpeakerState(old => {
    const value = typeof updater === 'function' ? updater(old) : updater;
    session.current?.setSpeaker(value);
    return value;
  });
  return { sec, speaker, setSpeaker, line, phase, heard, draft, setDraft, error, turns,
    isListening: phase === 'listening' && !muted, callTyping: phase === 'thinking', isSpeaking: phase === 'speaking',
    hasSR, submitTurn, startListen, stopListen,
    hangupCleanup, connected, muted, start, nativeShell, localAsr, downloadLocalAsr };
}

function useVoiceCallEngine(c, onContext, onSend) {
  const realtimeEngine = useRealtimeCallEngine(c, onContext);
  const compatibleEngine = useCompatibleCallEngine(c, onSend);
  const [mode, setModeState] = React.useState('compatible');
  const active = mode === 'realtime' ? realtimeEngine : compatibleEngine;
  const setMode = value => {
    if (!active.connected && (value === 'compatible' || value === 'realtime')) setModeState(value);
  };
  return { ...active, mode, setMode, realtimeEngine, compatibleEngine,
    modeLabel: mode === 'realtime' ? '豆包端到端' : '兼容模式' };
}

function VoiceCallModeControls({ engine, characterId }) {
  if (engine.mode === 'realtime') return <RealtimeVoiceControls engine={engine.realtimeEngine} characterId={characterId} />;
  return <div className="voice-mode-active-note">
    {uiT(!engine.hasSR ? '兼容模式 · 当前仅支持文字输入'
      : engine.muted ? '兼容模式 · 麦克风已静音'
        : '兼容模式 · 使用现有大模型与 TTS，回复结束后自动继续收音')}
  </div>;
}

function VoiceCallLobby({ engine, c, onEnd }) {
  const realtime = engine.realtimeEngine;
  const compatible = engine.compatibleEngine;
  return <div className="realtime-voice-lobby">
    <section className="realtime-voice-card">
      <h2>{uiT('与 {name} 通话', { name: c.name })}</h2>
      <div className="voice-mode-picker" role="radiogroup" aria-label={uiT('选择语音通话模式')}>
        <button type="button" role="radio" aria-checked={engine.mode === 'compatible'} className={engine.mode === 'compatible' ? 'is-selected' : ''} onClick={() => engine.setMode('compatible')}>
          <strong>{uiT('兼容模式')}</strong>
          <span>{uiT('使用现有 AI 服务与 TTS，无需开通豆包；双方轮流说话')}</span>
        </button>
        <button type="button" role="radio" aria-checked={engine.mode === 'realtime'} className={engine.mode === 'realtime' ? 'is-selected' : ''} onClick={() => engine.setMode('realtime')}>
          <strong>{uiT('豆包端到端')}</strong>
          <span>{uiT('持续全双工收音，支持说话打断；需要单独开通豆包语音')}</span>
        </button>
      </div>
      {engine.mode === 'compatible' ? <div className="voice-compatible-start">
        <p>{uiT(compatible.nativeShell
          ? '兼容模式在本机识别中文语音，再使用现有大模型与 TTS 回复。'
          : '接通后会尝试自动收音；若当前环境不支持中文识别，可使用文字输入或切换豆包端到端')}</p>
        {compatible.nativeShell && (compatible.localAsr.checking
          ? <p>{uiT('正在检查本地语音识别组件…')}</p>
          : compatible.localAsr.status_error && !compatible.localAsr.route_missing
            ? <p role="alert">{uiT('无法读取本地语音识别状态，请重启客户端后重试。')}</p>
          : !compatible.localAsr.runtime_available
            ? <p role="alert">{uiT('当前客户端尚未包含本地语音识别组件；请更新到 0.25.27 后使用麦克风。')}</p>
            : !compatible.localAsr.model_installed
              ? <div className="voice-local-asr-setup">
                <p>{uiT('首次使用需下载约 25 MB 中文语音模型；录音只在本机识别，不会上传音频。')}</p>
                <button type="button" onClick={compatible.downloadLocalAsr} disabled={compatible.localAsr.downloading}>
                  {uiT(compatible.localAsr.downloading ? '正在下载本地语音模型…' : '下载本地中文语音模型')}
                </button>
              </div>
              : <p>{uiT('本地中文语音模型已就绪，语音识别在本机运行。')}</p>)}
        {!engine.hasSR && !compatible.nativeShell && <p role="alert">{uiT('当前环境不支持语音识别，可以使用通话文字输入')}</p>}
        <button type="button" onClick={engine.start} disabled={compatible.nativeShell && compatible.localAsr.checking}>{uiT('使用兼容模式接通')}</button>
      </div> : <RealtimeVoiceControls engine={realtime} characterId={c.id} />}
      {engine.error && <p role="alert">{uiT(engine.error)}</p>}
      <button type="button" className="voice-lobby-back" onClick={onEnd}>{uiT('返回聊天')}</button>
    </section>
  </div>;
}
