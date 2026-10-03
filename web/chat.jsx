// chat.jsx — 聊天对话主界面 + 语音通话
const { useState: useStateC, useEffect: useEffectC, useMemo: useMemoC, useRef: useRefC } = React;
const CHAT_WINDOW_INITIAL = 160;
const CHAT_WINDOW_BATCH = 120;

// ══════════════════ 图片压缩工具 ══════════════════
function resizeImage(file, maxSize = 600) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = (e) => {
      const img = new Image();
      img.onerror = reject;
      img.onload = () => {
        let { width, height } = img;
        if (width > maxSize || height > maxSize) {
          const ratio = Math.min(maxSize / width, maxSize / height);
          width = Math.round(width * ratio);
          height = Math.round(height * ratio);
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        canvas.getContext('2d').drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL('image/jpeg', 0.65));
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });
}

// ══════════════════ 内置表情贴纸 ══════════════════
// 注意：只用 Win10 自带 Segoe UI Emoji 能显示的表情（Emoji 12 / 2019 及以前）。
// 这台机器连 Emoji 13（2020，如 🧋🥲）都缺；2021+ 的（🫶🫰🫵🫠🫣🥹🩷😶‍🌫️ 等）更是方框，勿加。
const STICKERS = [
  { cat: '爱心', items: ['❤️','🧡','💛','💚','💙','💜','🖤','🤍','💕','💞','💗','💖','💘','💝','💟','💌','💋','😘','🥰','😍','😻','💓'] },
  { cat: '可爱', items: ['🥺','😊','😋','🤗','😚','😙','☺️','😌','😏','😪','😜','😝','🤭','🙈','🙊','😸','😻','🐱','🐰','🌸','🌷','✨'] },
  { cat: '心情', items: ['😢','😭','😤','😠','😡','😔','😥','😞','😟','😩','😫','😅','😂','🤣','😆','😁','😎','🤩','🥳','😴','🥱','😳','🤔','🙄'] },
  { cat: '手势', items: ['👋','🤚','✋','👌','🤏','✌️','🤞','🤘','🤟','👍','👎','👊','🤛','🤜','👏','🙌','🤲','🙏','💪','👈'] },
  { cat: '动物', items: ['🐱','🐶','🐰','🐻','🐼','🐨','🦊','🐯','🦁','🐮','🐷','🐸','🐥','🐧','🦄','🐳','🐙','🦋','🐝','🐞'] },
  { cat: '美食', items: ['🍰','🧁','🍪','🍩','🍫','🍬','🍭','🍦','🍓','🍑','🍒','🍉','🍇','🍜','🍣','🍙','🍡','🥛','☕','🍵','🥤','🍺'] },
  { cat: '日常', items: ['🎉','🎊','🎁','🎀','🌙','⭐','🌟','💫','☀️','🌈','🔥','💧','❄️','🌹','🌻','🍀','💐','📷','🎵','💤','💯','👀'] },
];

// ══════════════════ 语音 / 转写录制引擎 ══════════════════
// 录音、转写与计时成组出现：状态、引用、副作用和收尾动作都收在这一个 hook 里，
// ChatThread 因此只负责排版，不再自持一套录音状态机。
function useVoiceRecorder({ onVoiceMsg, setText, setShowVoiceModes }) {
  const [isRecording, setIsRecording] = useStateC(false);
  const [recSec, setRecSec] = useStateC(0);
  const [recError, setRecError] = useStateC('');
  const recSecRef = useRefC(0);
  const recStartedAtRef = useRefC(0);
  const recTimerRef = useRefC(null);
  const srRef = useRefC(null);
  const recTranscriptRef = useRefC('');
  const mediaRecorderRef = useRefC(null);
  const mediaStreamRef = useRefC(null);
  const recChunksRef = useRefC([]);
  const recCancelledRef = useRefC(false);
  const recModeRef = useRefC('voice');
  const [recTranscript, setRecTranscript] = useStateC('');

  // 卸载时释放麦克风与识别器，避免通话中留下的音轨泄漏到下一段会话。
  useEffectC(() => () => {
    clearInterval(recTimerRef.current);
    if (srRef.current) { try { srRef.current.abort(); } catch(e) {} }
    if (mediaRecorderRef.current?.state === 'recording') {
      recCancelledRef.current = true;
      try { mediaRecorderRef.current.stop(); } catch(e) {}
    }
    if (mediaStreamRef.current) mediaStreamRef.current.getTracks().forEach(track => track.stop());
  }, []);

  const startRec = async (mode = 'voice') => {
    if (isRecording) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setRecError('当前浏览器不支持录音，请使用最新版 Chrome 或 Edge');
      return;
    }
    setRecError('');
    setRecSec(0);
    recSecRef.current = 0;
    recStartedAtRef.current = Date.now();
    recTranscriptRef.current = '';
    setRecTranscript('');
    recChunksRef.current = [];
    recCancelledRef.current = false;
    recModeRef.current = mode;
    setShowVoiceModes(false);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      mediaStreamRef.current = stream;
      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
        .find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = event => {
        if (event.data?.size) recChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(recChunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        if (mediaStreamRef.current) mediaStreamRef.current.getTracks().forEach(track => track.stop());
        mediaStreamRef.current = null;
        mediaRecorderRef.current = null;
        if (!recCancelledRef.current && blob.size > 0) {
          window.setTimeout(() => {
            const transcript = recTranscriptRef.current.trim();
            if (recModeRef.current === 'transcript') {
              if (transcript) {
                setText(current => `${current}${current && !/\s$/.test(current) ? ' ' : ''}${transcript}`.slice(0, 4000));
                setRecError('语音已转成文字，可编辑后发送。');
              } else {
                setRecError('没有识别到清晰文字，请重试或改用“发送原语音”。');
              }
            } else {
              onVoiceMsg(Math.max(1, recSecRef.current), transcript, blob);
            }
            setRecTranscript('');
          }, 180);
        } else {
          setRecTranscript('');
        }
      };
      recorder.start(250);
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
      recTimerRef.current = setInterval(() => {
        recSecRef.current = Math.max(1, Math.round((Date.now() - recStartedAtRef.current) / 1000));
        setRecSec(recSecRef.current);
        if (recSecRef.current >= 60) stopRec();
      }, 250);

      // 转文字模式把识别结果放回输入框；原语音模式保留录音并用转写辅助角色理解。
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (mode === 'transcript' && !SR) {
        recCancelledRef.current = true;
        clearInterval(recTimerRef.current);
        recTimerRef.current = null;
        recorder.stop();
        setIsRecording(false);
        setRecSec(0);
        setRecError('当前环境不支持语音转文字，请使用“发送原语音”。');
        return;
      }
      if (SR) {
        const sr = new SR();
        sr.lang = 'zh-CN';
        sr.continuous = true;
        sr.interimResults = true;
        sr.onresult = (e) => {
          let recognized = '';
          for (let i = 0; i < e.results.length; i++) {
            recognized += e.results[i][0].transcript;
          }
          recTranscriptRef.current = recognized;
          setRecTranscript(recognized);
        };
        sr.onerror = () => {};
        sr.start();
        srRef.current = sr;
      }
    } catch(e) {
      setRecError(e?.name === 'NotAllowedError' ? '麦克风权限被拒绝，请在浏览器地址栏中允许麦克风' : '无法启动录音，请检查麦克风是否被其他程序占用');
      if (mediaStreamRef.current) mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
    }
  };
  const stopRec = () => {
    clearInterval(recTimerRef.current);
    recTimerRef.current = null;
    if (srRef.current) { try { srRef.current.stop(); } catch(e) {} srRef.current = null; }
    recSecRef.current = Math.max(1, Math.round((Date.now() - recStartedAtRef.current) / 1000));
    if (mediaRecorderRef.current?.state === 'recording') {
      try { mediaRecorderRef.current.stop(); } catch(e) {}
    }
    setIsRecording(false);
    setRecSec(0);
  };
  const cancelRec = () => {
    recCancelledRef.current = true;
    clearInterval(recTimerRef.current);
    recTimerRef.current = null;
    if (srRef.current) { try { srRef.current.abort(); } catch(e) {} srRef.current = null; }
    if (mediaRecorderRef.current?.state === 'recording') {
      try { mediaRecorderRef.current.stop(); } catch(e) {}
    }
    if (mediaStreamRef.current) mediaStreamRef.current.getTracks().forEach(track => track.stop());
    mediaStreamRef.current = null;
    setIsRecording(false);
    setRecSec(0);
    recSecRef.current = 0;
    recTranscriptRef.current = '';
    setRecTranscript('');
  };

  return { isRecording, recSec, recError, setRecError, recTranscript, startRec, stopRec, cancelRec };
}

// ══════════════════ 聊天对话 ══════════════════
function ChatThread({ c, messages, typing, canSend, liveStatusOverride, onSend, onBack, onVoice, onVideo, onProfile, onVoiceMsg, onNewChat, onSendImage, injection }) {
  const [text, setText] = useStateC('');
  const [pendingImage, setPendingImage] = useStateC('');
  const [showActions, setShowActions] = useStateC(false);
  const [showVoiceModes, setShowVoiceModes] = useStateC(false);
  const { isRecording, recSec, recError, setRecError, recTranscript, startRec, stopRec, cancelRec } = useVoiceRecorder({ onVoiceMsg, setText, setShowVoiceModes });
  const [showStickers, setShowStickers] = useStateC(false);
  const fileInputRef = useRefC(null);
  const composerInputRef = useRefC(null);
  const scrollRef = useRefC(null);
  const stickToBottomRef = useRefC(true);
  const scrollFrameRef = useRefC(null);
  const prependAnchorRef = useRefC(null);
  const [visibleStart, setVisibleStart] = useStateC(
    () => Math.max(0, messages.length - CHAT_WINDOW_INITIAL),
  );
  // 切片本身很便宜，但 memo 化的数组引用能让下面的消息行不必每帧重建。
  const visibleMessages = useMemoC(
    () => messages.slice(visibleStart),
    [messages, visibleStart],
  );
  // 只让本次会话中新加入的消息执行入场动画。初次打开已有聊天记录时，
  // 历史消息应保持静止，避免最后一条旧消息被误判为“刚弹出”。
  const previousMessageCountRef = useRefC(messages.length);
  const hasNewMessage = messages.length > previousMessageCountRef.current;
  const showChatFrameInjection = injection?.source === 'message-list' && Number(injection?.token) > 0;
  const clockTick = useLiveClockTick();
  const scheduledStatus = getLiveStatus(c, new Date(clockTick));
  // Opening a chat only reveals the character's current life status. A
  // shared conversation scene must come from the backend transition layer,
  // never from mounting this component.
  const liveStatus = liveStatusOverride || scheduledStatus;

  const trackScrollPosition = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 72;
  };

  const revealOlderMessages = () => {
    const el = scrollRef.current;
    if (!el || visibleStart <= 0) return;
    prependAnchorRef.current = {
      scrollHeight: el.scrollHeight,
      scrollTop: el.scrollTop,
    };
    setVisibleStart(start => Math.max(0, start - CHAT_WINDOW_BATCH));
  };

  useEffectC(() => {
    const anchor = prependAnchorRef.current;
    const el = scrollRef.current;
    if (!anchor || !el) return;
    el.scrollTop = anchor.scrollTop + (el.scrollHeight - anchor.scrollHeight);
    prependAnchorRef.current = null;
  }, [visibleStart]);

  useEffectC(() => {
    setVisibleStart(Math.max(0, messages.length - CHAT_WINDOW_INITIAL));
    stickToBottomRef.current = true;
  }, [c.id]);

  useEffectC(() => {
    if (visibleStart > messages.length) {
      setVisibleStart(Math.max(0, messages.length - CHAT_WINDOW_INITIAL));
    }
  }, [messages.length, visibleStart]);

  useEffectC(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (messages.length > previousMessageCountRef.current) stickToBottomRef.current = true;
    if (!stickToBottomRef.current) return;
    if (scrollFrameRef.current !== null) cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const current = scrollRef.current;
      if (current && stickToBottomRef.current) current.scrollTop = current.scrollHeight;
    });
    return () => {
      if (scrollFrameRef.current !== null) {
        cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [messages.length, messages[messages.length - 1]?.text, typing]);

  useEffectC(() => {
    previousMessageCountRef.current = messages.length;
  }, [messages.length]);

  useEffectC(() => () => {
    if (scrollFrameRef.current !== null) cancelAnimationFrame(scrollFrameRef.current);
  }, []);

  const send = () => {
    if (typing || canSend?.() === false) return;
    const t = text.trim();
    if (!t && !pendingImage) return;
    if (pendingImage) onSendImage(pendingImage, t);
    else onSend(t);
    setText('');
    setPendingImage('');
    setShowActions(false);
    setShowStickers(false);
    setShowVoiceModes(false);
  };

  const stageImage = async (file) => {
    if (!file?.type?.startsWith('image/')) {
      setRecError('请选择 JPG、PNG、GIF 或 WebP 图片。');
      return;
    }
    try {
      setRecError('');
      setPendingImage(await resizeImage(file));
      setShowActions(false);
      setShowStickers(false);
      setShowVoiceModes(false);
    } catch (err) {
      setRecError('图片处理失败，请换一张图片重试。');
    }
  };

  const handleImageSelect = async (e) => {
    const file = e.target.files?.[0];
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (!file) return;
    await stageImage(file);
  };

  const handleComposerPaste = async (event) => {
    const imageItem = Array.from(event.clipboardData?.items || [])
      .find(item => item.kind === 'file' && item.type.startsWith('image/'));
    if (!imageItem) return; // 纯文字仍交给输入框原生粘贴。
    event.preventDefault();
    const pastedText = event.clipboardData?.getData('text/plain') || '';
    if (pastedText) setText(current => `${current}${pastedText}`.slice(0, 4000));
    const file = imageItem.getAsFile();
    if (file) await stageImage(file);
  };

  const insertSticker = (emoji) => {
    const input = composerInputRef.current;
    const start = Number.isInteger(input?.selectionStart) ? input.selectionStart : text.length;
    const end = Number.isInteger(input?.selectionEnd) ? input.selectionEnd : start;
    const nextText = `${text.slice(0, start)}${emoji}${text.slice(end)}`;
    if (nextText.length > 4000) return;
    const nextCursor = start + emoji.length;
    setText(nextText);
    setShowActions(false);
    setShowVoiceModes(false);
    requestAnimationFrame(() => {
      const currentInput = composerInputRef.current;
      currentInput?.focus();
      currentInput?.setSelectionRange(nextCursor, nextCursor);
    });
  };


  const hasOriginOffsetY = injection?.originOffsetY !== null && injection?.originOffsetY !== undefined;
  const rawOriginOffsetY = Number(injection?.originOffsetY);
  const injectionY = hasOriginOffsetY && Number.isFinite(rawOriginOffsetY)
    ? `calc(${Math.round(Math.max(0, rawOriginOffsetY))}px - var(--chat-stage-inset-top, 0px))`
    : `${Math.round(Math.max(0.08, Math.min(0.92, injection?.originY ?? 0.18)) * 100)}%`;

  return (
    <div className="chat-thread desktop-chat-stage" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div className="desktop-chat-frame" style={{ '--chat-inject-y': injectionY }}>
      {showChatFrameInjection && <>
        <span key={`bridge-${injection.token}`} className="desktop-chat-bridge" aria-hidden="true" />
        <span key={`frame-${injection.token}`} className="desktop-chat-frame-injection" aria-hidden="true" />
      </>}
      {/* header */}
      <div className="desktop-chat-header" style={{ zIndex: 30 }}>
          <div className="desktop-chat-rail desktop-chat-header-rail">
          <button type="button" className="desktop-chat-back" onClick={onBack} aria-label={uiT('返回消息列表')}><I.back size={22} /></button>
          <button type="button" className="desktop-chat-profile" onClick={onProfile} aria-label={uiT('查看{name}角色名片', { name: c.name })}>
            <div className="desktop-chat-avatar">
              <Avatar c={c} size={36} />
              <span style={{
                position: 'absolute',
                bottom: 0,
                right: 0,
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: typing ? '#f5b76a' : liveStatus.color,
                border: '2px solid #1a1238',
                boxShadow: `0 0 0 2px rgba(0,0,0,0.16), 0 0 10px ${typing ? 'rgba(245,183,106,0.45)' : `${liveStatus.color}66`}`,
              }} />
            </div>
            <div className="desktop-chat-identity">
              <div className="desktop-chat-name-row">
                <span className="desktop-chat-name">{c.name}</span>
                {c.relationship?.title && (
                  <span className="desktop-chat-relation">
                    {c.relationship.title}
                  </span>
                )}
              </div>
              <div className="desktop-chat-presence" style={{ color: typing ? 'var(--accent)' : liveStatus.color }}>
                <span>{typing ? uiT('正在输入…') : liveStatus.label}</span>
                {!typing && <span className="desktop-chat-status-detail">· {liveStatus.detail}</span>}
              </div>
            </div>
          </button>
          <div className="desktop-chat-header-actions">
            <button type="button" onClick={onVoice} aria-label={uiT('和{name}语音通话', { name: c.name })} style={iconBtn(38)}><I.phone size={19} /></button>
            <button type="button" onClick={onVideo} aria-label={uiT('和{name}视频通话', { name: c.name })} style={iconBtn(38)}><I.video size={19} /></button>
          </div>
          </div>
      </div>

      {/* messages */}
      <div ref={scrollRef} onScroll={trackScrollPosition} className="no-scrollbar desktop-chat-scroll" style={{ flex: 1, overflowY: 'auto', padding: '20px 20px 8px' }}>
        <div className="desktop-chat-rail desktop-chat-message-rail">
        <div className="desktop-chat-date-marker" style={{ textAlign: 'center', margin: '4px 0 22px' }}>
          <span>{(() => { const n = new Date(clockTick); return `${uiT('今天')} ${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')} · ${liveStatus.label}`; })()}</span>
        </div>
        {visibleStart > 0 && (
          <div className="chat-window-more">
            <button type="button" onClick={revealOlderMessages}>
              {uiT('再显示 {count} 条更早消息', { count: Math.min(CHAT_WINDOW_BATCH, visibleStart) })}
            </button>
            <span>{uiT('当前仅渲染最近 {count} 条，完整记录仍保存在本机', { count: visibleMessages.length })}</span>
          </div>
        )}
        {visibleMessages.map((m, i) => {
          const originalIndex = visibleStart + i;
          return (
          <Bubble key={m.ts || originalIndex} m={m} c={c} animate={hasNewMessage && originalIndex === messages.length - 1} language={currentUiLanguage()} />
          );
        })}
        {typing && (
          <div className="desktop-chat-message-row is-her" style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginBottom: 12 }}>
            <Avatar c={c} size={28} />
            <Glass radius={18} style={{ padding: '13px 16px', borderTopLeftRadius: 5, display: 'flex', gap: 5 }}>
              {[0, 1, 2].map(i => <span key={i} style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ink-soft)', animation: `blink 1.2s ${i * 0.18}s infinite` }} />)}
            </Glass>
          </div>
        )}
        </div>
      </div>

      {/* sticker panel — slides up above input bar */}
      {showStickers && (
        <div className="fade-rise desktop-chat-rail desktop-chat-panel-rail" style={{ padding: '8px 14px 4px', maxHeight: 240, overflowY: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <button type="button" onClick={() => { setShowStickers(false); }} aria-label={uiT('关闭表情包')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--ink-soft)', display: 'grid', placeItems: 'center', width: 28, height: 28 }}><I.back size={18} /></button>
            <div style={{ display: 'grid', gap: 1 }}>
              <span style={{ fontSize: 13, color: 'var(--ink)', fontWeight: 650 }}>{uiT('表情')}</span>
              <span style={{ fontSize: 11, color: 'var(--ink-faint)' }}>{uiT('选择后加入输入框，可继续编辑')}</span>
            </div>
          </div>
          {STICKERS.map(cat => (
            <div key={cat.cat}>
              <div style={{ fontSize: 11, color: 'var(--ink-faint)', padding: '4px 4px 6px', fontWeight: 600 }}>{uiT(cat.cat)}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                {cat.items.map(em => (
                  <button key={em} type="button" onClick={() => insertSticker(em)} aria-label={uiT('将{emoji}加入输入框', { emoji: em })} style={{
                    width: 44, height: 44, borderRadius: 12, border: 'none', cursor: 'pointer',
                    background: 'rgba(255,255,255,0.08)', display: 'grid', placeItems: 'center', fontSize: 24,
                    transition: 'background .15s',
                  }} onMouseOver={e => e.currentTarget.style.background = 'rgba(255,255,255,0.18)'}
                     onMouseOut={e => e.currentTarget.style.background = 'rgba(255,255,255,0.08)'}>{em}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {isRecording && (
        <div className="fade-rise desktop-chat-rail desktop-chat-panel-rail" style={{ padding: '10px 16px 4px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#ff4d6d', flexShrink: 0, boxShadow: '0 0 6px #ff4d6d', animation: 'blink 1s infinite' }} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 2.5, flex: 1, height: 28 }}>
              {[0.4, 0.7, 1, 0.55, 0.85, 0.5, 0.75, 0.6, 0.9, 0.45, 0.7, 1].map((h, i) => (
                <span key={i} style={{ width: 3, height: 24 * h, borderRadius: 2,
                  background: 'linear-gradient(0deg, var(--accent), var(--accent-2))',
                  animation: `barDance ${0.6 + (i % 4) * 0.15}s ${i * 0.06}s ease-in-out infinite` }} />
              ))}
            </div>
            <span style={{ fontSize: 13.5, color: 'var(--ink)', fontVariantNumeric: 'tabular-nums', fontWeight: 600, flexShrink: 0 }}>
              {String(Math.floor(recSec / 60)).padStart(2, '0')}:{String(recSec % 60).padStart(2, '0')}
            </span>
            <button type="button" onClick={cancelRec} aria-label={uiT('取消录音')} style={{ width: 26, height: 26, borderRadius: '50%', border: 'none', cursor: 'pointer', background: 'var(--surface-secondary)', color: 'var(--ink)', display: 'grid', placeItems: 'center', fontSize: 13, flexShrink: 0 }}>✕</button>
          </div>
          {recTranscript && (
            <div style={{ marginTop: 6, fontSize: 13, color: 'var(--ink-soft)', padding: '6px 10px', borderRadius: 10, background: 'rgba(255,255,255,0.08)', lineHeight: 1.4 }}>
              {recTranscript}
            </div>
          )}
        </div>
      )}
      {recError && !isRecording && (
        <div className="desktop-chat-rail desktop-chat-panel-rail" style={{ padding: '0 18px 8px', color: '#ffd2dc', fontSize: 12.5, lineHeight: 1.4 }}>
          {recError}
        </div>
      )}
      {/* hidden file input for image upload */}
      <input ref={fileInputRef} type="file" accept="image/*" onChange={handleImageSelect} style={{ display: 'none' }} />
      {/* input bar */}
      <div className="desktop-chat-composer-shell" style={{ padding: showActions && !showStickers ? '0 20px 8px' : '0 20px 24px', zIndex: 30 }}>
        <div className="desktop-chat-rail">
        {pendingImage && (
          <div className="fade-rise" style={{ display: 'flex', alignItems: 'flex-end', gap: 8, padding: '0 8px 8px' }}>
            <div style={{ position: 'relative', width: 96, height: 72, borderRadius: 14, overflow: 'hidden', border: '1px solid rgba(255,255,255,.18)', boxShadow: '0 6px 18px rgba(0,0,0,.2)' }}>
              <img src={pendingImage} alt={uiT('待发送图片')} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
              <button type="button" onClick={() => setPendingImage('')} aria-label={uiT('移除待发送图片')} style={{ position: 'absolute', top: 5, right: 5, width: 22, height: 22, borderRadius: '50%', border: 'none', background: 'rgba(10,10,14,.72)', color: '#fff', cursor: 'pointer' }}>✕</button>
            </div>
            <span style={{ fontSize: 12, color: 'var(--ink-soft)', paddingBottom: 4 }}>{uiT('图片已加入消息，可继续输入文字')}</span>
          </div>
        )}
        {showVoiceModes && !isRecording && (
          <div className="fade-rise" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 4px 8px' }}>
            <button type="button" onClick={() => startRec('transcript')} style={{ border: '1px solid rgba(255,255,255,.15)', borderRadius: 14, padding: '9px 13px', background: 'var(--surface-secondary)', color: 'var(--ink)', cursor: 'pointer', fontFamily: 'var(--font)' }}>{uiT('转成文字')}</button>
            <button type="button" onClick={() => startRec('voice')} style={{ border: '1px solid rgba(255,255,255,.15)', borderRadius: 14, padding: '9px 13px', background: 'linear-gradient(135deg, var(--accent), var(--accent-2))', color: '#fff', cursor: 'pointer', fontFamily: 'var(--font)' }}>{uiT('发送原语音')}</button>
          </div>
        )}
        <Glass radius={18} variant="glass-strong" className="desktop-chat-input" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 6 }}>
          <button type="button" onClick={() => { setShowActions(a => !a); setShowStickers(false); setShowVoiceModes(false); }}
            aria-label={uiT(showActions ? '收起更多操作' : '更多操作')} aria-expanded={showActions}
            style={{ ...iconBtn(38), color: showActions ? '#fff' : 'var(--ink)', background: showActions ? 'linear-gradient(135deg, var(--accent), var(--accent-2))' : 'var(--surface-secondary)', transition: 'background .2s' }}><I.plus size={22} /></button>
          <input
            ref={composerInputRef}
            value={text}
            onChange={e => setText(e.target.value)}
            onPaste={handleComposerPaste}
            onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent?.isComposing) send(); }}
            maxLength={4000}
            aria-label={uiT('给{name}发送消息', { name: c.name })}
            placeholder={uiT('和 {name} 说点什么…', { name: c.name })}
            style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--ink)', fontSize: 15.5, fontFamily: 'var(--font)' }} />
          {text.trim() || pendingImage
            ? <button type="button" onClick={send} aria-label={uiT('发送消息')} style={{ ...iconBtn(40), color: '#fff', background: 'linear-gradient(135deg, var(--accent), var(--accent-2))', boxShadow: '0 4px 14px color-mix(in oklch, var(--accent) 45%, transparent)' }}><I.send size={20} /></button>
            : isRecording
              ? <button type="button" onClick={stopRec} aria-label={uiT('结束录音并发送')} style={{ ...iconBtn(40), color: '#fff', background: '#ff4d6d', boxShadow: '0 4px 14px rgba(255,77,109,0.5)' }}><I.mic size={21} /></button>
              : <button type="button" onClick={() => { setShowVoiceModes(value => !value); setShowActions(false); setShowStickers(false); }} aria-label={uiT('选择语音输入方式')} aria-expanded={showVoiceModes} style={iconBtn(40)}><I.mic size={21} /></button>}
        </Glass>
        </div>
      </div>

      {/* plus panel — 消息附件与会话操作分组，避免把不同层级的动作混在一起。 */}
      {showActions && !showStickers && (
        <div className="fade-rise desktop-chat-rail desktop-chat-actions-panel">
          <div className="desktop-chat-actions-inner">
            <span className="desktop-chat-actions-label">{uiT('添加到消息')}</span>
            <div className="desktop-chat-action-tools">
              {[
                { Icon: I.smile, label: '表情', hue: 'oklch(0.82 0.13 70)', action: () => { setShowStickers(true); setShowActions(false); } },
                { Icon: I.image, label: '图片', hue: 'oklch(0.78 0.12 230)', action: () => fileInputRef.current?.click() },
              ].map(({ Icon, label, hue, action }) => (
                <button className="desktop-chat-action" key={label} onClick={action}>
                  <span className="desktop-chat-action-icon" style={{ '--action-hue': hue }}><Icon size={19} /></span>
                  <span>{uiT(label)}</span>
                </button>
              ))}
            </div>
            <span className="desktop-chat-action-divider" aria-hidden="true" />
            <button className="desktop-chat-action is-conversation-action" onClick={() => { onNewChat(); setShowActions(false); }}>
              <span className="desktop-chat-action-icon" style={{ '--action-hue': 'oklch(0.80 0.12 160)' }}><I.edit size={19} /></span>
              <span>{uiT('新建对话')}</span>
            </button>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}

function LevelUpCard({ level, title }) {
  return (
    <div className="fade-rise" style={{ textAlign: 'center', margin: '10px 0 18px' }}>
      <div style={{
        display: 'inline-flex', flexDirection: 'column', alignItems: 'center',
        padding: '16px 28px', borderRadius: 24,
        background: 'linear-gradient(135deg, color-mix(in oklch, var(--accent-ink) 78%, transparent), color-mix(in oklch, var(--accent-2) 38%, transparent))',
        border: '1px solid color-mix(in oklch, var(--accent) 55%, transparent)',
        boxShadow: '0 0 32px color-mix(in oklch, var(--accent) 28%, transparent), inset 0 1px 0 rgba(255,255,255,0.2)',
        backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)',
      }}>
        <div style={{ fontSize: 26, lineHeight: 1, marginBottom: 6 }}>💖</div>
        <div style={{ fontSize: 11.5, fontWeight: 600, color: 'rgba(255,255,255,0.75)', letterSpacing: 2, textTransform: 'uppercase' }}>Heart Level Up</div>
        <div style={{ fontSize: 30, fontWeight: 800, color: '#fff', lineHeight: 1.1, marginTop: 4,
          background: 'linear-gradient(135deg, var(--accent-3), var(--accent))',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
          Lv.{level}
        </div>
        <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.7)', marginTop: 5 }}>{title || uiT('关系进入新的阶段')} ♡</div>
      </div>
    </div>
  );
}

function VoiceBubble({ message, me = true, c }) {
  const [playing, setPlaying] = useStateC(false);
  const [showTranscript, setShowTranscript] = useStateC(false);
  const audioRef = useRefC(null);

  useEffectC(() => () => {
    if (audioRef.current) audioRef.current.pause();
  }, []);

  const togglePlayback = () => {
    if (!message.audioUrl) return;
    if (!audioRef.current) {
      audioRef.current = new Audio(message.audioUrl);
      audioRef.current.onended = () => setPlaying(false);
      audioRef.current.onerror = () => setPlaying(false);
    }
    if (audioRef.current.paused) {
      audioRef.current.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    } else {
      audioRef.current.pause();
      setPlaying(false);
    }
  };

  const toggleTranscript = (event) => {
    event.preventDefault();
    if (!message.transcript) return;
    setShowTranscript(open => !open);
  };

  const fg = me ? '#fff' : 'var(--ink)';
  const playRow = (
    <button
      onClick={togglePlayback}
      disabled={!message.audioUrl}
      aria-label={uiT(playing ? '暂停语音' : '播放语音')}
      aria-expanded={message.transcript ? showTranscript : undefined}
      title={uiT(message.transcript ? '左键播放 · 右键显示或收起文字' : '左键播放')}
      style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '10px 15px', borderRadius: 20,
      borderBottomRightRadius: me ? 6 : 20, borderTopLeftRadius: me ? 20 : 6,
      border: me ? 'none' : '1px solid rgba(255,255,255,0.16)', color: fg, cursor: message.audioUrl ? 'pointer' : 'default',
      background: me
        ? 'linear-gradient(135deg, var(--accent), var(--accent-2))'
        : 'rgba(255,255,255,0.10)',
      backdropFilter: me ? 'none' : 'blur(12px)',
      boxShadow: me ? '0 6px 18px color-mix(in oklch, var(--accent) 35%, transparent)' : '0 4px 14px rgba(0,0,0,0.3)',
      opacity: message.audioUrl ? 1 : 0.72,
    }}>
      <span style={{ width: 28, height: 28, borderRadius: '50%', background: me ? 'rgba(255,255,255,0.28)' : 'color-mix(in oklch, var(--accent) 38%, transparent)', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
        {playing
          ? <span style={{ display: 'flex', gap: 3 }}><i style={{ width: 3, height: 11, borderRadius: 2, background: fg }} /><i style={{ width: 3, height: 11, borderRadius: 2, background: fg }} /></span>
          : <svg width={10} height={12} viewBox="0 0 10 12" fill={fg}><path d="M1 1l8 5-8 5Z" /></svg>}
      </span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 2.5 }}>
        {[0.5, 0.75, 1, 0.6, 0.85, 0.55, 0.9, 0.7, 0.5, 0.8].map((h, i) => (
          <span key={i} style={{ width: 2.5, height: 14 * h + 2, borderRadius: 2, background: me ? 'rgba(255,255,255,0.85)' : 'var(--accent)', animation: playing ? `barDance ${0.7 + (i % 3) * 0.15}s ${i * 0.05}s ease-in-out infinite` : 'none' }} />
        ))}
      </span>
      <span style={{ fontSize: 12, color: me ? 'rgba(255,255,255,0.85)' : 'var(--ink-soft)', fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>{message.dur}"</span>
    </button>
  );

  if (me) {
    return (
      <div className="fade-rise desktop-chat-message-row desktop-voice-message is-me" onContextMenu={toggleTranscript} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', marginBottom: 12 }}>
        {playRow}
        {showTranscript && message.transcript && (
          <div className="desktop-voice-transcript" style={{ marginTop: 4, fontSize: 12.5, color: 'var(--ink-faint)', maxWidth: '72%', textAlign: 'right', lineHeight: 1.4, padding: '0 4px' }}>
            {message.transcript}
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="fade-rise desktop-chat-message-row is-her" style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginBottom: 12 }}>
      <Avatar c={c} size={28} />
      <div className="desktop-chat-turn-body desktop-voice-message" onContextMenu={toggleTranscript} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
        {playRow}
        {showTranscript && message.transcript && (
          <div className="desktop-voice-transcript" style={{ marginTop: 4, fontSize: 12.5, color: 'var(--ink-faint)', textAlign: 'left', lineHeight: 1.4, padding: '0 4px' }}>
            {message.transcript}
          </div>
        )}
      </div>
    </div>
  );
}

function BubbleView({ m, c, animate = false }) {
  // 历史标记清洗只与文本有关：把结果缓存住，避免每次重渲染都对每条消息重跑正则。
  const cleanHerText = useMemoC(
    () => (m.from === 'her' && m.text ? stripHistoryLabels(m.text) : null),
    [m.from, m.text],
  );
  if (cleanHerText !== null && cleanHerText !== m.text) m = { ...m, text: cleanHerText };
  // iMessage 风格：仅新加入的气泡弹出一次；历史消息和外层消息行不重复动画。
  const popStyle = animate
    ? { animation: 'msgPop .3s cubic-bezier(.34,1.4,.5,1) backwards' }
    : null;
  if (m.from === 'system') {
    if (m.type === 'levelup') return <LevelUpCard level={m.level} title={m.title} />;
    if (m.type === 'error') return (
      <div className="fade-rise" role="status" aria-live="polite" style={{ textAlign: 'center', margin: '8px 0 16px' }}>
        <span style={{ display: 'inline-block', maxWidth: '82%', fontSize: 11.5, lineHeight: 1.5, color: 'var(--ink-faint)', background: 'rgba(255,255,255,0.07)', padding: '6px 12px', borderRadius: 10 }}>
          {m.text || uiT('这条回复生成异常，请再试一次。')}
        </span>
      </div>
    );
    if (m.type === 'gift') return (
      <div className="fade-rise" style={{ textAlign: 'center', margin: '8px 0 16px' }}>
        <span style={{ fontSize: 11, color: 'var(--ink-faint)', background: 'rgba(255,255,255,0.07)', padding: '5px 14px', borderRadius: 10 }}>
          🎁 {uiT(m.day ? '你送给 {name} 一份{day}礼物{gift}' : '你送给 {name} 一份礼物{gift}', {
            name: m.name,
            day: m.day || '',
            gift: m.gift ? `${currentUiLanguage() === 'en' ? ': ' : '：'}${m.gift}` : '',
          })}
        </span>
      </div>
    );
    if (m.type === 'callend') {
      const total = Math.max(0, Math.round(m.duration || 0));
      const mm = String(Math.floor(total / 60)).padStart(2, '0');
      const ss = String(total % 60).padStart(2, '0');
      const CallIcon = m.mode === 'video' ? I.video : I.phone;
      return (
        <div className="fade-rise" style={{ textAlign: 'center', margin: '8px 0 16px' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--ink-faint)', background: 'rgba(255,255,255,0.07)', padding: '5px 14px', borderRadius: 10 }}>
            <CallIcon size={12} /> {uiT(m.mode === 'video' ? '视频通话' : '语音通话')}{total >= 1 ? ` · ${mm}:${ss}` : ''}
          </span>
        </div>
      );
    }
    return null;
  }
  const me = m.from === 'me';
  const messageTime = m.ts
    ? new Date(m.ts).toLocaleTimeString(currentUiLanguage() === 'en' ? 'en-US' : 'zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
    : '';
  // 表情贴纸：大号显示，无气泡背景
  const stickerMatch = m.text && m.text.match(/^\[\[sticker:(.+)\]\]$/);
  if (stickerMatch) {
    return (
      <div className={`fade-rise desktop-chat-message-row ${me ? 'is-me' : 'is-her'}`} style={{ display: 'flex', justifyContent: me ? 'flex-end' : 'flex-start', alignItems: 'flex-end', gap: 8, marginBottom: 12 }}>
        {!me && <Avatar c={c} size={28} />}
        <span style={{ fontSize: 64, lineHeight: 1.1 }}>{stickerMatch[1]}</span>
      </div>
    );
  }
  // 图片消息
  if (m.type === 'image' && m.imageUrl) {
    return (
      <div className={`fade-rise desktop-chat-message-row ${me ? 'is-me' : 'is-her'}`} style={{ display: 'flex', justifyContent: me ? 'flex-end' : 'flex-start', alignItems: 'flex-end', gap: 8, marginBottom: 12 }}>
        {!me && <Avatar c={c} size={28} />}
        <div style={{
          maxWidth: '65%', borderRadius: 18, overflow: 'hidden',
          borderBottomRightRadius: me ? 6 : 18, borderTopLeftRadius: me ? 18 : 6,
          boxShadow: me
            ? '0 6px 18px color-mix(in oklch, var(--accent) 35%, transparent)'
            : '0 4px 14px rgba(0,0,0,0.3)',
        }}>
          <img src={m.imageUrl} alt={uiT('图片消息')} loading="lazy" decoding="async" style={{ display: 'block', width: '100%', maxHeight: 320, objectFit: 'cover', cursor: 'pointer' }}
            onClick={() => window.open(m.imageUrl, '_blank')} />
          {m.text && (
            <div style={{ padding: '10px 13px', fontSize: 14.5, lineHeight: 1.45, color: me ? '#fff' : 'var(--ink)', background: me ? 'linear-gradient(135deg, var(--accent), var(--accent-2))' : 'rgba(255,255,255,.10)' }}>
              {m.text}
            </div>
          )}
        </div>
      </div>
    );
  }
  if (m.type === 'voice') return <VoiceBubble message={m} me={me} c={c} />;
  if (me) {
    return (
      <div className="desktop-chat-message-row is-me" style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <div className="desktop-chat-turn-body">
        <div className="desktop-chat-bubble" style={{ padding: '11px 15px', borderRadius: 20, borderBottomRightRadius: 6, fontSize: 15, lineHeight: 1.5, color: '#fff', background: 'linear-gradient(135deg, var(--accent), var(--accent-2))', boxShadow: '0 6px 18px color-mix(in oklch, var(--accent) 35%, transparent), inset 0 1px 0 rgba(255,255,255,0.3)', textWrap: 'pretty', transformOrigin: 'bottom right', ...popStyle }}>
          {m.type === 'call' && <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3, fontSize: 10.5, color: 'rgba(255,255,255,0.68)' }}><I.phone size={11} /> {uiT('通话')}</div>}
          {m.text}
        </div>
        {messageTime && <div className="desktop-chat-message-meta is-me">{messageTime} · {uiT('已读')}</div>}
        </div>
      </div>
    );
  }
  return (
    <div className="desktop-chat-message-row is-her" style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 18 }}>
      <Avatar c={c} size={28} />
      <div className="desktop-chat-turn-body">
      <div className="desktop-chat-speaker">{c.name}</div>
      <Glass radius={20} className="desktop-chat-bubble" style={{ padding: '11px 15px', borderTopLeftRadius: 6, fontSize: 15, lineHeight: 1.55, color: 'var(--ink)', textWrap: 'pretty', transformOrigin: 'bottom left', ...popStyle }}>
        {m.type === 'call' && <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3, fontSize: 10.5, color: 'var(--ink-faint)' }}><I.phone size={11} /> {uiT('通话')}</div>}
        {m.text}
        {m.streaming && <span className="desktop-chat-stream-caret" aria-label={uiT('正在生成回复')} />}
      </Glass>
      {messageTime && <div className="desktop-chat-message-meta">{m.streaming ? uiT('正在回复') : messageTime}</div>}
      </div>
    </div>
  );
}

// 消息行只在「消息对象 / 入场标记 / 头像素材」变化时才重渲染。
// 长列表里绝大多数旧消息每帧都是同一份引用，因而可以整行跳过。
function bubblePropsEqual(a, b) {
  if (a.m !== b.m || a.animate !== b.animate || a.language !== b.language) return false;
  const ca = a.c;
  const cb = b.c;
  if (ca === cb) return true;
  return !!ca && !!cb
    && ca.id === cb.id
    && ca.hue === cb.hue
    && ca.face === cb.face
    && ca.facePos === cb.facePos
    && ca.name === cb.name;
}

const Bubble = React.memo(BubbleView, bubblePropsEqual);

function iconBtn(size = 38, color = 'var(--ink)') {
  return { width: size, height: size, borderRadius: '50%', border: 'none', cursor: 'pointer', display: 'grid', placeItems: 'center', color, background: 'var(--surface-secondary)', flexShrink: 0 };
}

// 哥特飘落特效：白十字 + 暗玫瑰（角色可选 motif）
const Cross = ({ s = 14 }) => (
  <svg width={s} height={s * 1.4} viewBox="0 0 10 14" fill="rgba(255,255,255,0.92)">
    <rect x="3.6" y="0" width="2.8" height="14" rx="0.6" /><rect x="0.5" y="3.4" width="9" height="2.8" rx="0.6" />
  </svg>
);
const Rose = ({ s = 14 }) => (
  <svg width={s} height={s} viewBox="0 0 16 16">
    <circle cx="8" cy="8" r="7" fill="var(--accent-ink)" />
    <path d="M8 3.5c2 0 3.4 1.6 3.4 3.4S10 11 8 11.6 4.6 9.3 4.6 7.5 6 3.5 8 3.5Z" fill="var(--accent)" />
    <circle cx="8" cy="8" r="2" fill="var(--accent-2)" />
  </svg>
);
function GothicRain() {
  const bits = useRefC(null);
  if (!bits.current) {
    bits.current = Array.from({ length: 16 }, (_, i) => ({
      id: i,
      left: Math.round(Math.random() * 100),
      size: 10 + Math.round(Math.random() * 12),
      dur: 7 + Math.random() * 7,
      delay: -Math.random() * 12,
      drift: (Math.random() * 80 - 40).toFixed(0) + 'px',
      pmax: (0.45 + Math.random() * 0.45).toFixed(2),
      rose: Math.random() > 0.5,
    }));
  }
  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none', zIndex: 2 }}>
      {bits.current.map(b => (
        <div key={b.id} style={{
          position: 'absolute', top: 0, left: b.left + '%',
          animation: `petalFall ${b.dur}s ${b.delay}s linear infinite`,
          '--drift': b.drift, '--pmax': b.pmax,
          filter: 'drop-shadow(0 1px 3px rgba(0,0,0,0.4))',
        }}>
          {b.rose ? <Rose s={b.size} /> : <Cross s={b.size} />}
        </div>
      ))}
    </div>
  );
}

// 两条通话线路共用这一套界面：豆包端到端，或现有大模型 + TTS 兼容模式。

// ══════════════════ 语音通话 ══════════════════
function VoiceCall({ c, onEnd, onContext, onSend }) {
  const engine = useVoiceCallEngine(c, onContext, onSend);
  const {
    sec, speaker, setSpeaker, line, phase, heard, draft, setDraft, error, turns,
    isListening, callTyping, isSpeaking, hasSR,
    submitTurn, startListen, stopListen, hangupCleanup,
  } = engine;

  const endCall = () => {
    const completedTurns = hangupCleanup();
    onEnd?.({ duration: sec, turns: completedTurns });
  };

  const mm = String(Math.floor(sec / 60)).padStart(2, '0');
  const ss = String(sec % 60).padStart(2, '0');
  const status = phase === 'connecting' ? uiT('正在接通')
    : phase === 'listening' ? uiT('正在听你说')
    : phase === 'thinking' ? uiT('正在回应')
    : phase === 'speaking' ? uiT('{name} 正在说话', { name: c.name })
    : uiT(engine.connected ? (hasSR ? '麦克风已静音' : '仅文字模式') : '等待连接');
  const activeWave = isListening || isSpeaking;
  // 字幕只显示真正说出口的话：去掉 （…） 旁白（TTS 本就不读它）
  const subtitle = (line || '').replace(/[（(][^）)]*[）)]/g, '').replace(/[*_]/g, '').replace(/\s+/g, ' ').trim()
    || uiT(engine.connected ? (hasSR ? '已接通，可以直接说话' : '已接通，可以使用文字输入') : '连接后即可开始实时通话');

  if (!engine.connected) return <VoiceCallLobby engine={engine} c={c} onEnd={endCall} />;
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 80, overflow: 'hidden' }}>
      <div style={{ position: 'absolute', inset: 0, filter: 'blur(5px)', transform: 'scale(1.08)' }}>
        <ArtPlaceholder hue={c.hue} label="" dim="" rounded={0} src={c.img} pos={c.imgPos} />
      </div>
      <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(0deg, rgba(8,4,22,0.94) 0%, rgba(8,4,22,0.42) 48%, rgba(8,4,22,0.72) 100%)' }} />

      {c.motif === 'gothic' && <GothicRain />}

      <div style={{ position: 'absolute', inset: 0, zIndex: 3, display: 'flex', flexDirection: 'column', alignItems: 'center', padding: 'clamp(28px, 7vh, 72px) 20px 28px' }}>
        <Glass radius={16} variant="glass-strong" style={{ padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 7, color: '#fff', fontSize: 13 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: phase === 'connecting' ? '#fbbf24' : '#4ade80', boxShadow: `0 0 8px ${phase === 'connecting' ? '#fbbf24' : '#4ade80'}` }} />
          {status} · {mm}:{ss}
        </Glass>
        <div style={{ fontSize: 28, fontWeight: 700, color: '#fff', marginTop: 18, textShadow: '0 2px 16px rgba(0,0,0,0.55)' }}>{c.name}</div>
        <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.85)', marginTop: 4, textShadow: '0 1px 8px rgba(0,0,0,0.5)' }}>{c.persona}</div>

        <div style={{ position: 'relative', width: 164, height: 164, margin: 'clamp(18px, 4vh, 32px) 0 18px', display: 'grid', placeItems: 'center' }}>
          {[0, 1].map(i => (
            <div key={i} style={{ position: 'absolute', width: 126, height: 126, borderRadius: '50%', border: '2px solid color-mix(in oklch, var(--accent) 55%, transparent)', animation: activeWave ? `pulseRing 2.6s ${i * 0.8}s ease-out infinite` : 'none', opacity: activeWave ? 1 : 0.25 }} />
          ))}
          <div style={{ width: 126, height: 126, borderRadius: '50%', overflow: 'hidden', boxShadow: '0 0 50px color-mix(in oklch, var(--accent) 45%, transparent), inset 0 2px 0 rgba(255,255,255,0.4)' }}>
            <ArtPlaceholder hue={c.hue} label="" dim="" rounded={63} faceTop src={c.face || c.img} pos={c.facePos || c.imgPos} />
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 4, height: 32, marginBottom: 12, opacity: activeWave ? 1 : 0.35, transition: 'opacity .2s' }}>
          {[0.5, 0.8, 1, 0.6, 0.9, 0.4, 0.75, 1, 0.55, 0.85, 0.45, 0.7].map((h, i) => (
            <span key={i} style={{ width: 4, height: 28 * h, borderRadius: 3, background: 'linear-gradient(0deg, var(--accent), var(--accent-2))', transformOrigin: 'center', animation: activeWave ? `barDance ${0.7 + (i % 4) * 0.18}s ${i * 0.07}s ease-in-out infinite` : 'none' }} />
          ))}
        </div>

        <Glass radius={18} className="no-scrollbar" style={{ width: 'min(100%, 430px)', padding: '12px 15px', textAlign: 'center', minHeight: 54, maxHeight: 'min(32vh, 190px)', overflowY: 'auto', flexShrink: 0 }}>
          {callTyping ? (
            <div style={{ display: 'flex', gap: 5, justifyContent: 'center', alignItems: 'center' }}>
              {[0,1,2].map(i => <span key={i} style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ink-soft)', animation: `blink 1.2s ${i * 0.18}s infinite` }} />)}
            </div>
          ) : phase === 'listening' ? (
            <div style={{ fontSize: 14, color: 'var(--accent)', fontWeight: 600, lineHeight: 1.55 }}>{heard || uiT('正在聆听…')}</div>
          ) : (
            <div style={{ fontSize: 15, lineHeight: 1.55, color: 'var(--ink)', textWrap: 'pretty' }}>{subtitle}</div>
          )}
        </Glass>

        {error && <div style={{ color: '#ffd2dc', fontSize: 12.5, marginTop: 7 }}>{uiT(error)}</div>}
        <VoiceCallModeControls engine={engine} characterId={c.id} />
        <form onSubmit={event => { event.preventDefault(); submitTurn(draft); }} style={{ width: 'min(100%, 430px)', display: 'flex', gap: 7, marginTop: 10 }}>
          <input value={draft} onChange={event => setDraft(event.target.value)} disabled={!engine.connected} aria-label={uiT('通话文字输入')} placeholder={uiT('输入要说的话')} maxLength={4000} style={{ flex: 1, minWidth: 0, height: 38, borderRadius: 18, border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(8,4,22,0.45)', color: '#fff', outline: 'none', padding: '0 14px', fontFamily: 'var(--font)', fontSize: 13.5 }} />
          <button type="submit" disabled={!draft.trim() || !engine.connected || callTyping} aria-label={uiT('发送')} style={{ ...iconBtn(38, '#fff'), opacity: draft.trim() && !callTyping && phase !== 'connecting' ? 1 : 0.45, background: 'rgba(255,255,255,0.18)' }}><I.send size={17} /></button>
        </form>

        <div style={{ flex: 1, minHeight: 14 }} />
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'center', gap: 32, width: 'min(100%, 430px)' }}>
          <CallBtn
            on={isListening}
            active={isListening}
            disabled={!engine.connected || !hasSR}
            onClick={isListening ? stopListen : startListen}
            icon={I.mic}
            label={uiT(isListening ? '静音麦克风' : '开启麦克风')}
          />

          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <button type="button" onClick={endCall} aria-label={uiT('挂断')} style={{ width: 68, height: 68, borderRadius: '50%', border: 'none', cursor: 'pointer', display: 'grid', placeItems: 'center', color: '#fff', background: 'linear-gradient(135deg, #ff4d6d, #d11f43)', boxShadow: '0 10px 28px rgba(209,31,67,0.52), inset 0 1px 0 rgba(255,255,255,0.38)' }}>
              <I.phoneOff size={28} style={{ transform: 'rotate(135deg)' }} />
            </button>
            <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,0.75)' }}>{uiT('挂断')}</span>
          </div>

          <CallBtn on={speaker} onClick={() => setSpeaker(s => !s)} icon={I.speaker} label={uiT('扬声器')} active={speaker} />
        </div>
      </div>
    </div>
  );
}

function CallBtn({ icon: Ic, label, onClick, on, active, disabled = false }) {
  const lit = on || active;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
      <button type="button" onClick={onClick} disabled={disabled} aria-label={label} aria-pressed={typeof on === 'boolean' ? lit : undefined} style={{
        width: 60, height: 60, borderRadius: '50%', border: '1px solid rgba(255,255,255,0.22)', cursor: disabled ? 'default' : 'pointer', display: 'grid', placeItems: 'center',
        color: lit ? '#1a1238' : '#fff',
        background: lit ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.14)',
        backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)', transition: 'all .2s', opacity: disabled ? 0.45 : 1,
      }}><Ic size={24} /></button>
      <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,0.75)' }}>{label}</span>
    </div>
  );
}

// ══════════════════ 历史会话 - 工具函数 ══════════════════
function fmtTs(ts) {
  if (!ts) return '';
  const d = new Date(ts), now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const isYesterday = new Date(now - 86400000).toDateString() === d.toDateString();
  const hm = `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  if (isToday) return `${uiT('今天')} ${hm}`;
  if (isYesterday) return `${uiT('昨天')} ${hm}`;
  return currentUiLanguage() === 'en'
    ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : `${d.getMonth()+1}月${d.getDate()}日`;
}

function sessionPreview(messages) {
  const last = [...messages].reverse().find(m => m.from !== 'system' && m.text);
  if (!last) return uiT('（暂无内容）');
  return last.text.length > 26 ? last.text.slice(0, 26) + '…' : last.text;
}

// ══════════════════ 历史会话列表 ══════════════════
function ChatHistoryScreen({ c, currentThread, archived, onOpenChat, onViewSession, onDeleteSession, onBack }) {
  const [sessionMenu, setSessionMenu] = useStateC(null);
  // 当前会话 + 历史（倒序，最新在前）
  const sessions = [
    { idx: -1, messages: currentThread, startTs: currentThread[0]?.ts, isCurrent: true },
    ...[...archived].map((s, i) => ({ ...s, idx: i })).reverse(),
  ];

  useEffectC(() => {
    if (!sessionMenu) return undefined;
    const closeMenu = () => setSessionMenu(null);
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') closeMenu();
    };
    window.addEventListener('blur', closeMenu);
    document.addEventListener('click', closeMenu);
    document.addEventListener('contextmenu', closeMenu);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('blur', closeMenu);
      document.removeEventListener('click', closeMenu);
      document.removeEventListener('contextmenu', closeMenu);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [sessionMenu]);

  const openSessionMenu = (event, session) => {
    if (session.isCurrent) return;
    event.preventDefault();
    event.stopPropagation();
    const menuWidth = 176;
    const menuHeight = 48;
    setSessionMenu({
      idx: session.idx,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - menuWidth - 8)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - menuHeight - 8)),
    });
  };

  const deleteSession = () => {
    if (!sessionMenu) return;
    const idx = sessionMenu.idx;
    setSessionMenu(null);
    if (!window.confirm(uiT('确定删除这次历史会话吗？\n\n删除后无法恢复。'))) return;
    onDeleteSession(idx);
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ paddingTop: 50, flexShrink: 0 }}>
        <Glass radius={0} variant="glass-strong" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none', borderTop: 'none', display: 'flex', alignItems: 'center', gap: 11, padding: '9px 14px 11px' }}>
          <button type="button" onClick={onBack} aria-label={uiT('返回角色资料')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--ink)', display: 'grid', placeItems: 'center', width: 32, height: 32 }}><I.back size={24} /></button>
          <Avatar c={c} size={36} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)' }}>{uiT('与 {name} 的对话', { name: c.name })}</div>
            <div style={{ fontSize: 11.5, color: 'var(--ink-soft)', marginTop: 1 }}>{uiT('{count} 次会话', { count: sessions.length })}</div>
          </div>
        </Glass>
      </div>

      <div className="no-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
        {sessions.map((s) => {
          const msgCount = s.messages.filter(m => m.from !== 'system').length;
          return (
            <button key={s.idx} onClick={() => s.isCurrent ? onOpenChat() : onViewSession(s.idx)}
              onContextMenu={(event) => openSessionMenu(event, s)}
              title={uiT(s.isCurrent ? '当前会话' : '右键可管理这次历史会话')}
              style={{ display: 'block', width: '100%', textAlign: 'left', background: 'none', border: 'none', padding: '0 0 10px', cursor: 'pointer' }}>
              <Glass radius={20} style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 7 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {s.isCurrent && (
                      <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.8, padding: '2px 8px', borderRadius: 8,
                        background: 'linear-gradient(135deg, var(--accent), var(--accent-2))', color: '#fff' }}>{uiT('进行中')}</span>
                    )}
                    <span style={{ fontSize: 12.5, color: 'var(--ink-soft)' }}>{fmtTs(s.startTs)}</span>
                  </div>
                  <span style={{ fontSize: 11.5, color: 'var(--ink-faint)' }}>{uiT('{count} 条消息', { count: msgCount })}</span>
                </div>
                <div style={{ fontSize: 14.5, color: 'var(--ink)', lineHeight: 1.5 }}>{sessionPreview(s.messages)}</div>
              </Glass>
            </button>
          );
        })}
      </div>
      {sessionMenu && (
        <div role="menu" aria-label={uiT('历史会话操作')} onClick={(event) => event.stopPropagation()}
          style={{ position: 'fixed', left: sessionMenu.x, top: sessionMenu.y, zIndex: 120, width: 176, padding: 6,
            borderRadius: 12, border: '1px solid var(--line-color)', background: 'var(--surface-raised)',
            boxShadow: '0 14px 36px rgba(0,0,0,.28)' }}>
          <button type="button" role="menuitem" onClick={deleteSession}
            style={{ width: '100%', minHeight: 36, padding: '8px 10px', border: 'none', borderRadius: 8,
              background: 'transparent', color: '#ef4444', cursor: 'pointer', textAlign: 'left', font: 'inherit', fontSize: 13.5 }}>
            {uiT('删除历史会话')}
          </button>
        </div>
      )}
    </div>
  );
}

// ══════════════════ 只读会话内容 ══════════════════
function SessionReadScreen({ c, session, onBack }) {
  const scrollRef = useRefC(null);
  const prependAnchorRef = useRefC(null);
  const [visibleStart, setVisibleStart] = useStateC(
    () => Math.max(0, session.messages.length - CHAT_WINDOW_INITIAL),
  );
  const visibleMessages = useMemoC(
    () => session.messages.slice(visibleStart),
    [session, visibleStart],
  );
  useEffectC(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, []);
  useEffectC(() => {
    const anchor = prependAnchorRef.current;
    const el = scrollRef.current;
    if (!anchor || !el) return;
    el.scrollTop = anchor.scrollTop + (el.scrollHeight - anchor.scrollHeight);
    prependAnchorRef.current = null;
  }, [visibleStart]);

  const revealOlderMessages = () => {
    const el = scrollRef.current;
    if (!el || visibleStart <= 0) return;
    prependAnchorRef.current = {
      scrollHeight: el.scrollHeight,
      scrollTop: el.scrollTop,
    };
    setVisibleStart(start => Math.max(0, start - CHAT_WINDOW_BATCH));
  };

  const dateLabel = session.startTs
    ? new Date(session.startTs).toLocaleString(currentUiLanguage() === 'en' ? 'en-US' : 'zh-CN', { month: 'long', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' })
    : '';

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ paddingTop: 50, flexShrink: 0 }}>
        <Glass radius={0} variant="glass-strong" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none', borderTop: 'none', display: 'flex', alignItems: 'center', gap: 11, padding: '9px 14px 11px' }}>
          <button type="button" onClick={onBack} aria-label={uiT('返回会话列表')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--ink)', display: 'grid', placeItems: 'center', width: 32, height: 32 }}><I.back size={24} /></button>
          <Avatar c={c} size={36} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)' }}>{c.name}</div>
            <div style={{ fontSize: 11.5, color: 'var(--ink-soft)', marginTop: 1 }}>{dateLabel}</div>
          </div>
        </Glass>
      </div>

      <div ref={scrollRef} className="no-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '16px 16px 30px' }}>
        {dateLabel && (
          <div style={{ textAlign: 'center', margin: '4px 0 16px' }}>
            <span style={{ fontSize: 11, color: 'var(--ink-faint)', background: 'rgba(255,255,255,0.07)', padding: '4px 12px', borderRadius: 10 }}>{dateLabel}</span>
          </div>
        )}
        {visibleStart > 0 && (
          <div className="chat-window-more">
            <button type="button" onClick={revealOlderMessages}>
              {uiT('再显示 {count} 条更早消息', { count: Math.min(CHAT_WINDOW_BATCH, visibleStart) })}
            </button>
            <span>{uiT('完整会话未被截断')}</span>
          </div>
        )}
        {visibleMessages.map((m, i) => <Bubble key={m.ts || visibleStart + i} m={m} c={c} language={currentUiLanguage()} />)}
      </div>
    </div>
  );
}

// ══════════════════ 视频通话（真实摄像头 + 对话，微信 PiP 风格）══════════════════
function VideoCall({ c, onEnd, onContext, onSend }) {
  const engine = useVoiceCallEngine(c, onContext, onSend);
  const {
    sec, speaker, setSpeaker, line, phase, heard, draft, setDraft, error, turns,
    isListening, callTyping, isSpeaking, hasSR,
    submitTurn, startListen, stopListen, hangupCleanup,
  } = engine;
  const [camOn, setCamOn] = useStateC(true);
  const [camReady, setCamReady] = useStateC(false);
  const [camError, setCamError] = useStateC('');
  const [swapped, setSwapped] = useStateC(false); // false=角色大/用户小，true=用户大/角色小
  const streamRef = useRefC(null);
  const cameraRequestRef = useRefC(0);

  const stopCam = () => {
    cameraRequestRef.current++;
    if (streamRef.current) { streamRef.current.getTracks().forEach(track => track.stop()); streamRef.current = null; }
    setCamReady(false);
  };

  const startCam = async () => {
    const request = ++cameraRequestRef.current;
    if (!navigator.mediaDevices?.getUserMedia) {
      setCamOn(false);
      setCamError('当前浏览器不支持摄像头');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      if (request !== cameraRequestRef.current) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      if (streamRef.current) streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = stream;
      setCamError('');
      setCamOn(true);
      setCamReady(true);
    } catch(e) {
      if (request !== cameraRequestRef.current) return;
      setCamOn(false);
      setCamError(e && e.name === 'NotAllowedError' ? '摄像头权限被拒绝，请在地址栏允许' : '摄像头暂时无法使用');
    }
  };

  useEffectC(() => { if (engine.connected) startCam(); return stopCam; }, [engine.connected]);

  // 行内 ref 每次渲染都会执行，确保 PiP/大窗切换重挂载后画面流不丢
  const attachVideo = (el) => {
    if (el && streamRef.current && el.srcObject !== streamRef.current) el.srcObject = streamRef.current;
  };

  const toggleCam = () => {
    if (camOn) { stopCam(); setCamOn(false); }
    else startCam();
  };

  const endCall = () => {
    const completedTurns = hangupCleanup();
    stopCam();
    onEnd?.({ duration: sec, turns: completedTurns });
  };

  const mm = String(Math.floor(sec / 60)).padStart(2, '0');
  const ss2 = String(sec % 60).padStart(2, '0');
  const status = phase === 'connecting' ? uiT('正在接通')
    : phase === 'listening' ? uiT('正在听你说')
    : phase === 'thinking' ? uiT('正在回应')
    : phase === 'speaking' ? uiT('{name} 正在说话', { name: c.name })
    : uiT(engine.connected ? (hasSR ? '麦克风已静音' : '仅文字模式') : '等待连接');
  const subtitle = (line || '').replace(/[（(][^）)]*[）)]/g, '').replace(/[*_]/g, '').replace(/\s+/g, ' ').trim()
    || uiT(engine.connected ? (hasSR ? '已接通，可以直接说话' : '已接通，可以使用文字输入') : '连接后即可开始实时通话');

  const pipStyle = {
    position: 'absolute', top: 68, right: 16, width: 112, height: 170,
    borderRadius: 18, overflow: 'hidden', background: '#0a0717',
    boxShadow: '0 6px 28px rgba(0,0,0,0.75)', cursor: 'pointer', zIndex: 10,
  };
  const pipBorder = { position: 'absolute', inset: 0, border: '2.5px solid rgba(255,255,255,0.52)', borderRadius: 18, pointerEvents: 'none' };
  const pipTag = { position: 'absolute', bottom: 6, left: 0, right: 0, textAlign: 'center', fontSize: 10, color: 'rgba(255,255,255,0.9)', fontWeight: 700, textShadow: '0 1px 6px rgba(0,0,0,0.9)' };

  // 用户侧：真实摄像头画面（镜像）；未就绪/已关闭时显示占位
  const userPane = (pip) => (camOn && camReady) ? (
    <video ref={attachVideo} autoPlay playsInline muted
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', transform: 'scaleX(-1)', background: '#0a0717' }} />
  ) : (
    <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', background: 'linear-gradient(160deg, #1c0f3a 0%, #0a0717 100%)' }}>
      <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.45)' }}>
        <I.camera size={pip ? 20 : 44} />
        {!pip && <div style={{ fontSize: 12.5, marginTop: 8 }}>{camError ? uiT(camError) : uiT(camOn ? '摄像头启动中…' : '摄像头已关闭')}</div>}
      </div>
    </div>
  );

  // 角色侧：立绘 + 呼吸感，说话时加光晕
  const herPane = (pip) => (
    <div style={{ position: 'absolute', inset: 0 }}>
      <div style={{ position: 'absolute', inset: 0, animation: pip ? 'none' : 'breathe 5s ease-in-out infinite' }}>
        <ArtPlaceholder hue={c.hue} label="" dim="" rounded={pip ? 18 : 0} src={c.img} pos={c.imgPos} />
      </div>
      {isSpeaking && (
        <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none',
          boxShadow: 'inset 0 0 90px color-mix(in oklch, var(--accent) 55%, transparent)',
          animation: 'blink 2.2s ease-in-out infinite' }} />
      )}
    </div>
  );

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 80, background: '#0a0717', overflow: 'hidden' }}>
      {!engine.connected && <VoiceCallLobby engine={engine} c={c} onEnd={endCall} />}
      {/* 大画面 */}
      <div style={{ position: 'absolute', inset: 0 }}>
        {swapped ? userPane(false) : herPane(false)}
      </div>
      {/* 小画面（PiP），点击切换 */}
      <button type="button" aria-label={uiT('切换主画面和小画面')} style={{ ...pipStyle, padding: 0, border: 'none' }} onClick={() => setSwapped(s => !s)}>
        {swapped ? herPane(true) : userPane(true)}
        <div style={pipBorder} />
        <div style={pipTag}>{swapped ? c.name : uiT('我')}</div>
      </button>

      {/* 顶部渐变 + 名字/状态/计时 */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, zIndex: 5,
        paddingTop: 52, paddingBottom: 22, paddingLeft: 18, paddingRight: 18,
        background: 'linear-gradient(180deg, rgba(8,4,22,0.82) 0%, transparent 100%)',
        pointerEvents: 'none' }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: '#fff', textShadow: '0 2px 12px rgba(0,0,0,0.55)' }}>{c.name}</div>
        <div style={{ fontSize: 12.5, color: 'rgba(255,255,255,0.75)', marginTop: 3, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: phase === 'connecting' ? '#fbbf24' : '#4ade80', boxShadow: `0 0 7px ${phase === 'connecting' ? '#fbbf24' : '#4ade80'}`, flexShrink: 0, display: 'inline-block' }} />
          {status} · {mm}:{ss2}
        </div>
      </div>

      {/* 底部：字幕 + 文字输入 + 控制栏 */}
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 5,
        padding: '60px 16px 34px',
        background: 'linear-gradient(0deg, rgba(8,4,22,0.92) 0%, rgba(8,4,22,0.55) 60%, transparent 100%)',
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
        <Glass radius={18} className="no-scrollbar" style={{ width: 'min(100%, 430px)', padding: '11px 15px', textAlign: 'center', minHeight: 48, maxHeight: 'min(26vh, 150px)', overflowY: 'auto', flexShrink: 0 }}>
          {callTyping ? (
            <div style={{ display: 'flex', gap: 5, justifyContent: 'center', alignItems: 'center' }}>
              {[0,1,2].map(i => <span key={i} style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ink-soft)', animation: `blink 1.2s ${i * 0.18}s infinite` }} />)}
            </div>
          ) : phase === 'listening' ? (
            <div style={{ fontSize: 14, color: 'var(--accent)', fontWeight: 600, lineHeight: 1.55 }}>{heard || uiT('正在聆听…')}</div>
          ) : (
            <div style={{ fontSize: 14.5, lineHeight: 1.55, color: 'var(--ink)', textWrap: 'pretty' }}>{subtitle}</div>
          )}
        </Glass>

        {error && <div style={{ color: '#ffd2dc', fontSize: 12.5 }}>{uiT(error)}</div>}
        <VoiceCallModeControls engine={engine} characterId={c.id} />
        <form onSubmit={event => { event.preventDefault(); submitTurn(draft); }} style={{ width: 'min(100%, 430px)', display: 'flex', gap: 7 }}>
          <input value={draft} onChange={event => setDraft(event.target.value)} disabled={!engine.connected} aria-label={uiT('通话文字输入')} placeholder={uiT('输入要说的话')} maxLength={4000} style={{ flex: 1, minWidth: 0, height: 36, borderRadius: 18, border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(8,4,22,0.45)', color: '#fff', outline: 'none', padding: '0 14px', fontFamily: 'var(--font)', fontSize: 13.5 }} />
          <button type="submit" disabled={!draft.trim() || !engine.connected || callTyping} aria-label={uiT('发送')} style={{ ...iconBtn(36, '#fff'), opacity: draft.trim() && !callTyping && phase !== 'connecting' ? 1 : 0.45, background: 'rgba(255,255,255,0.18)' }}><I.send size={16} /></button>
        </form>

        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'flex-start', gap: 26, marginTop: 2 }}>
          <CallBtn
            on={isListening}
            active={isListening}
            disabled={!engine.connected || !hasSR}
            onClick={isListening ? stopListen : startListen}
            icon={I.mic}
            label={uiT(isListening ? '静音麦克风' : '开启麦克风')}
          />
          <CallBtn on={speaker} active={speaker} onClick={() => setSpeaker(s => !s)} icon={I.speaker} label={uiT('扬声器')} />
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <button type="button" onClick={endCall} aria-label={uiT('挂断')} style={{ width: 60, height: 60, borderRadius: '50%', border: 'none', cursor: 'pointer',
              display: 'grid', placeItems: 'center', color: '#fff',
              background: 'linear-gradient(135deg, #ff4d6d, #d11f43)',
              boxShadow: '0 8px 26px rgba(209,31,67,0.55), inset 0 1px 0 rgba(255,255,255,0.3)' }}>
              <I.phoneOff size={26} style={{ transform: 'rotate(135deg)' }} />
            </button>
            <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,0.75)' }}>{uiT('挂断')}</span>
          </div>
          <CallBtn on={camOn} active={camOn} onClick={toggleCam} icon={I.camera} label={uiT(camOn ? '摄像头' : '已关闭')} />
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ChatThread, VoiceCall, VideoCall, ChatHistoryScreen, SessionReadScreen });
