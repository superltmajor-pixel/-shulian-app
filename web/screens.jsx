// screens.jsx — 今日 / 恋人 / 消息 / 我的
const { useState, useEffect, useMemo, useRef } = React;

// 小圆头像占位（按色相生成，无文字）
function Avatar({ c, size = 44, ring = false }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', position: 'relative', flexShrink: 0,
      background: `linear-gradient(150deg, oklch(0.66 0.14 ${c.hue}), oklch(0.52 0.13 ${c.hue + 30}))`,
      boxShadow: ring ? '0 0 0 2px rgba(255,255,255,0.85), 0 0 0 4px color-mix(in oklch, var(--accent) 60%, transparent)' : 'inset 0 1px 0 rgba(255,255,255,0.4)',
      overflow: 'hidden',
    }}>
      {c.face ? (
        <img src={c.face} alt={c.name} draggable="false" loading="lazy" decoding="async" style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: c.facePos || '50% 30%', display: 'block' }} />
      ) : (
        <React.Fragment>
          <div style={{ position: 'absolute', inset: 0, backgroundImage: 'repeating-linear-gradient(135deg, rgba(255,255,255,0.12) 0 1.5px, transparent 1.5px 11px)' }} />
          <div style={{ position: 'absolute', left: '50%', top: '34%', width: '54%', aspectRatio: 1, transform: 'translate(-50%,-50%)', borderRadius: '50%', background: 'radial-gradient(circle, rgba(255,255,255,0.4), transparent 70%)' }} />
        </React.Fragment>
      )}
    </div>
  );
}

function UserAvatar({ profile, size = 64, ring = false }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', display: 'grid', placeItems: 'center', flexShrink: 0, overflow: 'hidden',
      background: 'linear-gradient(150deg, oklch(0.64 0.14 230), oklch(0.46 0.13 265))',
      boxShadow: ring ? '0 0 0 2px rgba(255,255,255,0.85), 0 0 0 4px color-mix(in oklch, var(--accent) 55%, transparent)' : 'inset 0 1px 0 rgba(255,255,255,0.35)',
    }}>
      {profile?.avatarImg ? (
        <img src={profile.avatarImg} alt="我的头像" draggable="false" loading="lazy" decoding="async" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
      ) : (
        <I.user size={Math.round(size * 0.45)} style={{ color: 'rgba(255,255,255,0.9)' }} />
      )}
    </div>
  );
}

// 全屏灯箱：点头像/图片看大图，Esc 或点空白关闭
function ImageLightbox({ img, caption, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, zIndex: 200,
      background: 'rgba(4,2,14,0.94)',
      backdropFilter: 'blur(18px)', WebkitBackdropFilter: 'blur(18px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      cursor: 'zoom-out',
    }}>
      <img src={img} alt={caption || ''} draggable="false" decoding="async" onClick={e => e.stopPropagation()} style={{
        maxWidth: 'calc(100vw - 32px)', maxHeight: 'calc(100vh - 96px)',
        objectFit: 'contain',
        borderRadius: 12,
        boxShadow: '0 32px 80px rgba(0,0,0,0.8)',
        cursor: 'default',
      }} />
      <button type="button" onClick={onClose} aria-label="关闭图片预览" style={{
        position: 'absolute', top: 20, right: 20,
        width: 40, height: 40, borderRadius: '50%',
        background: 'rgba(255,255,255,0.12)', border: '1px solid rgba(255,255,255,0.2)',
        color: '#fff', fontSize: 22, cursor: 'pointer',
        display: 'grid', placeItems: 'center',
      }}>×</button>
      {caption && (
        <div style={{ position: 'absolute', bottom: 20, left: '50%', transform: 'translateX(-50%)',
          fontSize: 13, color: 'rgba(255,255,255,0.4)', letterSpacing: 1, whiteSpace: 'nowrap' }}>
          {caption}
        </div>
      )}
    </div>
  );
}

const HERO_PALETTE_FALLBACK = {
  deep: 'rgb(21 22 27)',
  tone: 'rgb(116 92 138)',
  soft: 'rgb(224 214 232)',
};

function mixRgb(rgb, target, amount) {
  return rgb.map((value, index) => Math.round(value + (target[index] - value) * amount));
}

function rgbCss(rgb) {
  return `rgb(${rgb[0]} ${rgb[1]} ${rgb[2]})`;
}

function sampleHeroPalette(image) {
  try {
    const canvas = document.createElement('canvas');
    const size = 32;
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context) return HERO_PALETTE_FALLBACK;
    context.drawImage(image, 0, 0, size, size);
    const pixels = context.getImageData(0, 0, size, size).data;
    let red = 0;
    let green = 0;
    let blue = 0;
    let weightTotal = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index + 3] < 96) continue;
      const r = pixels[index];
      const g = pixels[index + 1];
      const b = pixels[index + 2];
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      const saturation = max - min;
      const luminance = (r * .2126) + (g * .7152) + (b * .0722);
      // White studio backgrounds should not wash every adaptive palette to gray.
      if (luminance > 238 && saturation < 18) continue;
      const weight = .35 + (saturation / 255) * .9 + (luminance > 34 ? .18 : 0);
      red += r * weight;
      green += g * weight;
      blue += b * weight;
      weightTotal += weight;
    }
    if (weightTotal < 1) return HERO_PALETTE_FALLBACK;
    const sampled = [red, green, blue].map(channel => Math.round(channel / weightTotal));
    const channelAverage = sampled.reduce((sum, channel) => sum + channel, 0) / 3;
    const tone = sampled.map(channel => Math.max(0, Math.min(255,
      Math.round(channelAverage + ((channel - channelAverage) * 1.18)),
    )));
    return {
      deep: rgbCss(mixRgb(tone, [12, 14, 18], .56)),
      tone: rgbCss(mixRgb(tone, [108, 88, 130], .06)),
      soft: rgbCss(mixRgb(tone, [246, 244, 248], .62)),
    };
  } catch (error) {
    return HERO_PALETTE_FALLBACK;
  }
}

function HeroMedia({ c, onOpen, onPalette }) {
  if (!c.img) {
    return <ArtPlaceholder hue={c.hue} label={`${c.name} 立绘`} dim="角色图片" rounded={30} faceTop />;
  }
  const isContained = c.imgFit === 'contain';
  return (
    <button type="button" onClick={onOpen} aria-label={`查看${c.name}原图`}
      className={`hero-media-button${isContained ? ' is-contain' : ''}`}>
      <img src={c.img} alt="" aria-hidden="true" draggable="false" decoding="async" className="hero-media-backdrop"
        style={{ objectPosition: c.imgPos || '50% 50%' }} />
      <img src={c.img} alt={`${c.name}原图`} draggable="false" decoding="async" fetchPriority="high" className="hero-media-image"
        onLoad={(event) => onPalette?.(sampleHeroPalette(event.currentTarget))}
        style={{ objectPosition: c.imgPos || '50% 50%', objectFit: c.imgFit || undefined }} />
    </button>
  );
}

function HeroGallery({ c, onOpenPhoto }) {
  const photos = c.gallery && c.gallery.length > 0
    ? c.gallery
    : [{ title: '影像等待补充', img: c.img || '', pos: c.imgPos || '50% 50%' }];
  const [idx, setIdx] = useState(0);
  const safeIdx = Math.min(idx, photos.length - 1);
  const total = photos.length;

  const go = (dir) => {
    setIdx(prev => {
      const next = prev + dir;
      if (next < 0) return total - 1;
      if (next >= total) return 0;
      return next;
    });
  };

  useEffect(() => { setIdx(0); }, [c.id]);

  const offsets = [-2, -1, 0, 1, 2];
  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden' }}>
      {/* stacked cards */}
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {offsets.map(off => {
          const i = ((safeIdx + off) % total + total) % total;
          const photo = photos[i];
          const absOff = Math.abs(off);
          if (absOff > 2) return null;
          const scale = 1 - absOff * 0.06;
          const tx = off * 18;
          const rot = off * 3.5;
          const z = 10 - absOff;
          const opacity = off === 0 ? 1 : absOff === 1 ? 0.55 : 0.25;
          return (
            <div key={`${off}-${i}`} onClick={off === 0 && photo.img ? () => onOpenPhoto(photo) : undefined}
              style={{
                position: 'absolute', width: '82%', height: '88%',
                borderRadius: 16, overflow: 'hidden',
                transform: `translateX(${tx}px) rotate(${rot}deg) scale(${scale})`,
                zIndex: z, opacity,
                transition: 'all 0.4s cubic-bezier(.22,.9,.3,1)',
                cursor: off === 0 && photo.img ? 'zoom-in' : 'default',
                boxShadow: off === 0
                  ? '0 8px 32px rgba(0,0,0,0.5)'
                  : '0 4px 16px rgba(0,0,0,0.3)',
                border: '1px solid rgba(255,255,255,0.12)',
              }}>
              {photo.img ? (
                <img src={photo.img} alt={photo.title} draggable="false" loading="lazy" decoding="async"
                  style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: photo.pos || '50% 50%', display: 'block' }} />
              ) : (
                <ArtPlaceholder hue={c.hue} label={`${c.name} · 影像待补充`} dim="稍后添加图集" rounded={16} faceTop />
              )}
            </div>
          );
        })}
      </div>

      {/* navigation arrows */}
      {total > 1 && (
        <React.Fragment>
          <button type="button" onClick={(e) => { e.stopPropagation(); go(-1); }} aria-label="上一张照片"
            style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', zIndex: 20, width: 32, height: 32, borderRadius: '50%', border: '1px solid rgba(255,255,255,0.25)', background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)', color: '#fff', cursor: 'pointer', display: 'grid', placeItems: 'center', fontSize: 16 }}>
            ‹
          </button>
          <button type="button" onClick={(e) => { e.stopPropagation(); go(1); }} aria-label="下一张照片"
            style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', zIndex: 20, width: 32, height: 32, borderRadius: '50%', border: '1px solid rgba(255,255,255,0.25)', background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)', color: '#fff', cursor: 'pointer', display: 'grid', placeItems: 'center', fontSize: 16 }}>
            ›
          </button>
          {/* dot indicators */}
          <div style={{ position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)', zIndex: 20, display: 'flex', gap: 5 }}>
            {photos.map((_, di) => (
              <div key={di} onClick={(e) => { e.stopPropagation(); setIdx(di); }}
                style={{ width: di === safeIdx ? 16 : 6, height: 6, borderRadius: 3, cursor: 'pointer', background: di === safeIdx ? 'var(--accent)' : 'rgba(255,255,255,0.4)', transition: 'all 0.3s ease' }} />
            ))}
          </div>
        </React.Fragment>
      )}
    </div>
  );
}

const Scroll = ({ children, padTop = 24 }) => (
  <div className="no-scrollbar scroll-desktop-pad" style={{ height: '100%', overflowY: 'auto', overflowX: 'hidden', paddingTop: padTop, paddingBottom: 130 }}>{children}</div>
);

const Eyebrow = ({ children }) => (
  <div style={{ fontSize: 12.5, fontWeight: 600, letterSpacing: 2, textTransform: 'uppercase', color: 'var(--ink-faint)', fontFamily: 'var(--mono)' }}>{children}</div>
);

const quizProgressKey = (characterId) => `sl_quiz_answered_${characterId}`;

function readAnsweredQuizIds(characterId, quizBank) {
  const validIds = new Set(quizBank.map(question => question.id));
  try {
    const parsed = JSON.parse(localStorage.getItem(quizProgressKey(characterId)) || '[]');
    if (!Array.isArray(parsed)) return [];
    return [...new Set(parsed.filter(id => typeof id === 'string' && validIds.has(id)))];
  } catch (e) {
    return [];
  }
}

function writeAnsweredQuizIds(characterId, ids) {
  try {
    localStorage.setItem(quizProgressKey(characterId), JSON.stringify([...new Set(ids)]));
  } catch (e) { /* 存储不可用时仍允许本次答题继续 */ }
}

function pickUnansweredQuiz(quizBank, answeredIds) {
  const answered = new Set(answeredIds);
  const unanswered = quizBank.filter(question => !answered.has(question.id));
  return unanswered.length ? unanswered[Math.floor(Math.random() * unanswered.length)] : null;
}

// ══════════════════ 今日 ══════════════════
function HomeScreen({ current, liveStatusOverride, aiGreet, greetingKey, onGreetingShown, openMessagesChat, openVoice, formIdx = 0, setForm, notifications = [], onBellClick, threads = {}, onGiftHome, openArchive }) {
  const c = current;
  const [giftOpen, setGiftOpen] = useState(false);
  const [photoOpen, setPhotoOpen] = useState(false);
  const [imgLightbox, setImgLightbox] = useState(null);
  const [quizOpen, setQuizOpen] = useState(false);    // 心有灵犀
  const [heroPalette, setHeroPalette] = useState(HERO_PALETTE_FALLBACK);
  useEffect(() => setHeroPalette(HERO_PALETTE_FALLBACK), [c.id, c.img]);
  // 默契加成：心有灵犀答对累积（与亲密度分开存，不污染等级/心动值）
  const [tacitBonus, setTacitBonus] = useState(0);
  useEffect(() => {
    const v = parseFloat(localStorage.getItem(`sl_tacit_${c.id}`) || '0');
    setTacitBonus(Number.isFinite(v) ? v : 0);
  }, [c.id]);
  const gainTacit = (amt) => {
    setTacitBonus(b => {
      const nb = Math.min(40, b + amt);
      try { localStorage.setItem(`sl_tacit_${c.id}`, String(nb)); } catch (e) {}
      return nb;
    });
  };
  // 心有灵犀 quiz state
  const quizBank = (typeof QUIZ_BANK !== 'undefined' && QUIZ_BANK[c.id]) || [];
  const [answeredQuizIds, setAnsweredQuizIds] = useState(() => readAnsweredQuizIds(c.id, quizBank));
  const [quizQuestionId, setQuizQuestionId] = useState(() => pickUnansweredQuiz(quizBank, readAnsweredQuizIds(c.id, quizBank))?.id || null);
  const [quizPicked, setQuizPicked] = useState(null);
  const [quizShuffled, setQuizShuffled] = useState([]);
  const [quizCount, setQuizCount] = useState(0);
  const [quizStreak, setQuizStreak] = useState(0);
  const unansweredQuiz = quizBank.filter(question => !answeredQuizIds.includes(question.id));
  const quizCurrent = quizBank.find(question => question.id === quizQuestionId) || null;

  useEffect(() => {
    const restored = readAnsweredQuizIds(c.id, quizBank);
    setAnsweredQuizIds(restored);
    setQuizQuestionId(pickUnansweredQuiz(quizBank, restored)?.id || null);
    setQuizPicked(null);
    setQuizCount(0);
    setQuizStreak(0);
  }, [c.id]);

  useEffect(() => {
    if (!quizCurrent) { setQuizShuffled([]); return; }
    const indices = quizCurrent.options.map((_, i) => i);
    for (let j = indices.length - 1; j > 0; j--) {
      const k = Math.floor(Math.random() * (j + 1));
      [indices[j], indices[k]] = [indices[k], indices[j]];
    }
    setQuizShuffled(indices);
    setQuizPicked(null);
  }, [quizQuestionId, c.id]);

  useEffect(() => {
    if (quizOpen && quizBank.length > 0 && answeredQuizIds.length >= quizBank.length) {
      setQuizQuestionId(null);
      setQuizPicked(null);
    }
  }, [quizOpen]);
  const clockTick = useLiveClockTick();
  const liveStatus = liveStatusOverride || getLiveStatus(c, new Date(clockTick));
  const sharedSceneActive = liveStatus?.source === 'conversation';
  const sleeping = liveStatus?.tone === 'sleep' || liveStatus?.scene === 'sleep';
  const greetingSuppressed = sharedSceneActive || sleeping;
  const liveLifeCopy = String(liveStatus?.detail || '').trim()
    || (liveStatus?.label ? `${c.name}此刻正在${liveStatus.label}。` : `${c.name}正在过自己的生活。`);
  // 送礼只在特殊日子开放：节日 / 生日 / 纪念日
  const giftDay = getGiftDay(c, new Date(clockTick));

  // 招呼气泡：至少“打字”1秒做演出；AI 招呼还在生成就多等一会（最多4秒）。
  // 一旦某条招呼已经显示，本轮就不再被迟到的网络结果替换，避免用户看到两句相互冲突的话。
  const [greetWaited, setGreetWaited] = useState(false);
  const [greetGaveUp, setGreetGaveUp] = useState(false);
  const greetingIdentity = `${c.id}|${greetingKey || 'pending'}`;
  const [settledGreeting, setSettledGreeting] = useState({ key: '', text: '' });
  useEffect(() => {
    setGreetWaited(false); setGreetGaveUp(false); setSettledGreeting({ key: '', text: '' });
    const t1 = setTimeout(() => setGreetWaited(true), 1000);
    const t2 = setTimeout(() => setGreetGaveUp(true), 4000);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [c.id, greetingKey]);
  const greetPending = aiGreet == null; // null/undefined = AI 生成中，'' = 失败
  const settledText = settledGreeting.key === greetingIdentity ? settledGreeting.text : '';
  const greetTyping = !greetingSuppressed && !settledText && (!greetWaited || (greetPending && !greetGaveUp));
  // 角色气泡只允许显示后端已经校验过的模型文本；失败时显示中性 UI 状态。
  const greetCandidate = String(aiGreet || '').trim();
  const greetText = settledText || greetCandidate;
  const greetUnavailable = !greetingSuppressed && !greetTyping && !greetText;
  useEffect(() => {
    if (!greetingSuppressed && !greetTyping && !settledText && greetCandidate) {
      setSettledGreeting({ key: greetingIdentity, text: greetCandidate });
    }
  }, [greetingSuppressed, greetTyping, settledText, greetCandidate, greetingIdentity]);
  // 动态统计：在一起天数（按角色独立记录起始时间）
  // 起始时间只在惰性初始化里读一次，写入放到 effect —— 渲染阶段不做 setItem，
  // 否则 StrictMode 或任何一次重渲染都会重复触发这个副作用。
  const [startTs, setStartTs] = useState(() => {
    try {
      const stored = parseInt(localStorage.getItem(`sl_start_${c.id}`) || '', 10);
      return Number.isFinite(stored) && stored > 0 ? stored : 0;
    } catch (e) {
      return 0;
    }
  });
  useEffect(() => {
    const key = `sl_start_${c.id}`;
    let existing = 0;
    try {
      const stored = parseInt(localStorage.getItem(key) || '', 10);
      if (Number.isFinite(stored) && stored > 0) existing = stored;
    } catch (e) {
      existing = 0; // localStorage 不可用时按今天起算
    }
    if (existing) {
      setStartTs(prev => (prev === existing ? prev : existing));
      return;
    }
    const now = Date.now();
    try { localStorage.setItem(key, String(now)); } catch (e) { /* 写入失败则仅内存内有效 */ }
    setStartTs(prev => (prev === now ? prev : now));
  }, [c.id]);
  const daysWithChar = Math.max(1, Math.floor((Date.now() - (startTs || Date.now())) / 86400000));

  // v21 展示值统一读取结构化关系四维，不再由消息数量机械累加。
  const relationMetrics = companionContextMetrics(c.companionContext, c.id);
  const heartRaw = relationMetrics.heart;
  const heartStr = heartRaw >= 1000 ? (heartRaw / 1000).toFixed(1) + 'k' : String(heartRaw);

  // 心有灵犀答题仍是独立加成，不污染关系等级。
  const compat = Math.min(99, relationMetrics.compatibility + tacitBonus);

  const GIFTS_DATA = [
    { emoji: '🌹', name: '玫瑰', bonus: 0.3 },
    { emoji: '🍰', name: '蛋糕', bonus: 0.4 },
    { emoji: '🎀', name: '发带', bonus: 0.45 },
    { emoji: '💎', name: '钻石', bonus: 0.8 },
    { emoji: '🍫', name: '巧克力', bonus: 0.35 },
    { emoji: '📿', name: '项链', bonus: 0.6 },
    { emoji: '🌟', name: '星愿', bonus: 0.5 },
    { emoji: '🎭', name: '面具', bonus: 0.7 },
  ];

  const sheetBase = {
    width: 'min(100%, 560px)',
    margin: '0 auto 16px',
    padding: '20px 20px 44px',
    borderRadius: '28px 28px 22px 22px',
    background: 'var(--surface-primary)',
    backdropFilter: 'blur(24px)',
    WebkitBackdropFilter: 'blur(24px)',
    border: '1px solid var(--line-color)',
    boxShadow: '0 24px 64px rgba(0,0,0,0.28)',
  };
  const sheetHandle = { width: 36, height: 4, borderRadius: 2, background: 'var(--line-color)', margin: '0 auto 18px' };
  const overlayBg = {
    position: 'absolute',
    inset: 0,
    zIndex: 40,
    background: 'rgba(0,0,0,0.6)',
    display: 'flex',
    alignItems: 'flex-end',
    justifyContent: 'center',
    padding: '0 16px',
  };

  return (
    <div style={{ position: 'relative', height: '100%' }}>
      <Scroll>
        <div className="dc" style={{ padding: '0 20px' }}>
          {/* 今日招呼与通知并列，避免重复占用一整行日期空间。 */}
          <div className="fade-rise home-greeting-row">
            <div className="home-greeting-message">
              {!greetUnavailable && <Avatar c={c} size={38} ring />}
              {greetUnavailable ? (
                <div role="status" className="home-greeting-unavailable">
                  {uiT('今日招呼暂时没有生成，你仍可以进入消息页继续聊天。')}
                </div>
              ) : greetingSuppressed ? (
                <Glass radius={18} className="home-greeting-bubble" style={{ borderTopLeftRadius: 6, fontSize: 13.5, color: 'var(--ink-soft)' }}>
                  {sharedSceneActive
                    ? (liveStatus?.scene === 'sleep'
                        ? '你们正在安静休息，先让这一刻继续。'
                        : `共同场景仍在继续：${liveLifeCopy}`)
                    : `${c.name}正在休息，醒来后再继续说。`}
                </Glass>
              ) : greetTyping ? (
                <Glass key="typing" radius={18} className="bubble-pop home-greeting-bubble is-typing" style={{ borderTopLeftRadius: 6 }}>
                  {[0, 1, 2].map(i => <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--ink-soft)', animation: `blink 1.2s ${i * 0.18}s infinite` }} />)}
                </Glass>
              ) : (
                <button
                  key={greetText}
                  type="button"
                  className="glass bubble-pop greet-bubble home-greeting-bubble"
                  onClick={() => {
                    onGreetingShown?.(greetingKey, greetText);
                    openMessagesChat(c.id);
                  }}
                  aria-label={uiT('回复{name}的消息', { name: c.name })}>
                  {greetText}
                </button>
              )}
            </div>
            <button type="button" className="home-notification-button" onClick={onBellClick}
              aria-label={notifications.some(n => !n.read)
                ? (currentUiLanguage() === 'en' ? `Open notifications, ${notifications.filter(n => !n.read).length} unread` : `打开通知，${notifications.filter(n => !n.read).length}条未读`)
                : uiT('打开通知')}>
              <Glass radius={20} style={{ width: 40, height: 40, display: 'grid', placeItems: 'center', color: 'var(--ink)' }}>
                <I.bell size={20} />
              </Glass>
              {(() => { const u = notifications.filter(n => !n.read).length; return u > 0 ? (
                <span>{u > 9 ? '9+' : u}</span>
              ) : null; })()}
            </button>
          </div>

          {/* hero card */}
          <Glass radius={30} className="fade-rise home-hero-card" style={{
            overflow: 'hidden', padding: 0, animationDelay: '.05s',
            '--hero-deep': heroPalette.deep,
            '--hero-tone': heroPalette.tone,
            '--hero-soft': heroPalette.soft,
          }}>
            <HeroMedia key={`${c.id}-${formIdx || 0}`} c={c} onPalette={setHeroPalette}
              onOpen={() => setImgLightbox({ img: c.img, pos: c.imgPos })} />
            <div className="home-hero-copy">
              <div className="home-hero-meta">
                <Glass radius={14} variant="glass-strong" style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 11px', color: '#fff', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: liveStatus.color, boxShadow: `0 0 8px ${liveStatus.color}` }} />
                {liveStatus.label}
                </Glass>
                <Glass radius={14} variant="glass-strong" style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '6px 11px', color: '#fff', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}>
                  <I.flame size={14} style={{ color: 'var(--accent)' }} /> {relationMetrics.title} · Lv.{relationMetrics.level}
                </Glass>
              </div>

              <div className="home-hero-info">
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 30, fontWeight: 700, color: '#fff' }}>{c.name}</span>
                  <span style={{ fontSize: 13, color: 'rgba(255,255,255,0.62)', fontFamily: 'var(--mono)' }}>{c.en}</span>
                </div>
                <div style={{ fontSize: 13.5, color: 'rgba(255,255,255,0.78)', marginTop: 4 }}>{c.persona}</div>
                <div className="home-hero-mood">{liveLifeCopy}</div>
              </div>

              <div className="home-hero-actions">
                <button type="button" className="home-voice-action" onClick={() => openVoice(c.id)} aria-label={uiT('和{name}语音', { name: c.name })} style={btn('glass')}>
                  <I.phone size={18} /> {uiT('语音')}
                </button>
              </div>
            </div>
            {c.forms && c.forms.length > 1 && (
              <div className="home-form-dots" role="group" aria-label={uiT('角色造型')}>
                {c.forms.map((f, i) => {
                  const on = (formIdx || 0) === i;
                  return (
                    <button
                      key={i}
                      type="button"
                      className={`home-form-dot${on ? ' is-active' : ''}`}
                      onClick={() => setForm(i)}
                      aria-label={`切换至${f.label}`}
                      aria-pressed={on}
                      title={f.label}
                    />
                  );
                })}
              </div>
            )}
          </Glass>

          <div className="home-summary-row">
            {/* mood card */}
            <Glass radius={24} className="fade-rise home-mood-card" style={{ marginTop: 14, padding: 16, display: 'flex', gap: 13, alignItems: 'flex-start', animationDelay: '.1s' }}>
              <Avatar c={c} size={42} />
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
                  <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--ink)', whiteSpace: 'nowrap' }}>{currentUiLanguage() === 'en' ? `${c.name}'s note` : `${c.name}的悄悄话`}</span>
                  <I.sparkle size={14} style={{ color: 'var(--accent)' }} />
                </div>
                <div style={{ fontSize: 14, lineHeight: 1.55, color: 'var(--ink-soft)', textWrap: 'pretty' }}>{liveLifeCopy}</div>
              </div>
            </Glass>

            {/* stats - 动态；"在一起"可点开合照相册 */}
            <div className="home-stats-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: 14 }}>
              {[[String(daysWithChar), currentUiLanguage() === 'en' ? (daysWithChar === 1 ? ' day' : ' days') : uiT('天'), uiT('在一起'), () => setPhotoOpen(true), I.camera], [heartStr, '♡', uiT('心动值'), () => openArchive(c.id, 'history'), I.flame], [String(compat), '%', uiT('默契'), () => setQuizOpen(true), I.sparkle]].map(([v, u, k, action, Hint], i) => (
                <Glass as="button" type="button" key={i} radius={20} variant="glass-quiet" className="fade-rise home-stat-card" onClick={action}
                  aria-label={`${k}：${v}${u}`}
                  style={{ width: '100%', padding: '14px 10px', textAlign: 'center', animationDelay: `${.12 + i*.04}s`, cursor: 'pointer', font: 'inherit', color: 'inherit' }}>
                  <div style={{ fontSize: 23, fontWeight: 700, color: 'var(--ink)' }}>{v}<span style={{ fontSize: 12, color: 'var(--ink-faint)', marginLeft: 2 }}>{u}</span></div>
                  <div style={{ fontSize: 11.5, color: 'var(--ink-faint)', marginTop: 2, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                    {k}{Hint && <Hint size={12} style={{ opacity: 0.8 }} />}
                  </div>
                </Glass>
              ))}
            </div>
          </div>

          {/* 特殊日子：送礼入口随之点亮 */}
          {giftDay && (
            <Glass as="button" type="button" radius={22} variant="glass-strong" className="fade-rise" onClick={() => setGiftOpen(true)}
              aria-label={`今天是${giftDay.label}，给${c.name}挑一份心意`}
              style={{ width: '100%', marginTop: 18, padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer', textAlign: 'left', font: 'inherit', color: 'inherit' }}>
              <span style={{ fontSize: 28 }}>{giftDay.kind === 'birthday' ? '🎂' : giftDay.kind === 'anniversary' ? '💞' : '🎀'}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)' }}>今天是{giftDay.label}</div>
                <div style={{ fontSize: 12, color: 'var(--ink-faint)', marginTop: 2 }}>给 {c.name} 挑一份心意</div>
              </div>
              <I.gift size={20} style={{ color: 'var(--accent)' }} />
            </Glass>
          )}

        </div>
      </Scroll>

      {/* ── 礼物面板（只在特殊日子能打开）── */}
      {giftOpen && giftDay && (
        <div style={overlayBg} onClick={() => setGiftOpen(false)}>
          <div className="fade-rise" onClick={e => e.stopPropagation()} style={sheetBase}>
            <div style={sheetHandle} />
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)', marginBottom: 3 }}>送给 {c.name}</div>
            <div style={{ fontSize: 12, color: 'var(--ink-faint)', marginBottom: 16 }}>今天是{giftDay.label}，挑一份心意吧</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
              {GIFTS_DATA.map(g => (
                <button key={g.name} type="button" onClick={() => { onGiftHome(g); setGiftOpen(false); }}
                  style={{ background: 'var(--surface-secondary)', border: '1px solid var(--line-color)', borderRadius: 18, padding: '12px 4px', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5 }}>
                  <span style={{ fontSize: 26 }}>{g.emoji}</span>
                  <span style={{ fontSize: 11.5, color: 'var(--ink-soft)' }}>{g.name}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── 合照 / 图集 ── */}
      {photoOpen && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 40, background: 'rgba(0,0,0,0.88)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }} onClick={() => setPhotoOpen(false)}>
          <div className="fade-rise" onClick={e => e.stopPropagation()} style={{ position: 'relative', width: '88%', maxWidth: 380, height: 480 }}>
            <HeroGallery c={c} onOpenPhoto={(photo) => setImgLightbox(photo)} />
            {/* bottom info overlay */}
            <div style={{ position: 'absolute', bottom: 0, left: '50%', transform: 'translateX(-50%)', zIndex: 30, textAlign: 'center', pointerEvents: 'none', paddingBottom: 36 }}>
              <div style={{ fontSize: 10.5, color: 'rgba(255,255,255,0.5)', letterSpacing: 2.5, fontFamily: 'var(--mono)', marginBottom: 6 }}>TOGETHER</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#fff', textShadow: '0 2px 12px rgba(0,0,0,0.7)' }}>{c.name} <span style={{ color: 'rgba(255,255,255,0.38)', fontSize: 15 }}>&</span> 你</div>
              <div style={{ fontSize: 12, color: 'var(--accent)', marginTop: 5 }}>在一起 {daysWithChar} 天 · {relationMetrics.title}</div>
            </div>
          </div>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.38)', marginTop: 16 }}>{uiT('点击图片查看原图 · 点击空白处关闭')}</div>
        </div>
      )}

      {/* ── 心有灵犀 ── */}
      {quizOpen && (() => {
        if (!quizBank.length) return (
          <div style={overlayBg} onClick={() => setQuizOpen(false)}>
            <div className="fade-rise" onClick={e => e.stopPropagation()} style={sheetBase}>
              <div style={sheetHandle} />
              <div style={{ textAlign: 'center', color: 'var(--ink-faint)', fontSize: 14, padding: '32px 0' }}>暂无题库</div>
            </div>
          </div>
        );

        if (!quizCurrent) return (
          <div style={overlayBg} onClick={() => setQuizOpen(false)}>
            <div className="fade-rise" onClick={e => e.stopPropagation()} style={sheetBase}>
              <div style={sheetHandle} />
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 14 }}><Avatar c={c} size={58} ring /></div>
              <div style={{ textAlign: 'center', fontSize: 24, fontWeight: 800, color: 'var(--ink)', marginBottom: 6 }}>10 / 10</div>
              <div style={{ textAlign: 'center', fontSize: 16, fontWeight: 700, color: 'var(--ink)', marginBottom: 8 }}>题库已全部完成</div>
              <div style={{ textAlign: 'center', color: 'var(--ink-soft)', fontSize: 13.5, lineHeight: 1.6 }}>你已经答完关于 TA 的全部题目</div>
            </div>
          </div>
        );

        const cur = quizCurrent;
        const isCorrect = quizPicked === cur.answer;
        const nextQ = () => {
          const next = pickUnansweredQuiz(quizBank, answeredQuizIds);
          setQuizQuestionId(next?.id || null);
          setQuizCount(a => a + 1);
        };
        const handlePick = (origIdx) => {
          if (quizPicked !== null) return;
          const nextAnswered = [...new Set([...answeredQuizIds, cur.id])];
          writeAnsweredQuizIds(c.id, nextAnswered);
          setAnsweredQuizIds(nextAnswered);
          setQuizPicked(origIdx);
          if (origIdx === cur.answer) {
            gainTacit(2);
            setQuizStreak(s => s + 1);
          } else {
            setQuizStreak(0);
          }
        };

        return (
          <div style={overlayBg} onClick={() => setQuizOpen(false)}>
            <div className="fade-rise" onClick={e => e.stopPropagation()} style={{ ...sheetBase, maxHeight: '78vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <div style={sheetHandle} />
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 18 }}>💫</span>
                  <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)' }}>心有灵犀</span>
                </div>
                {quizStreak >= 2 && <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>连对 {quizStreak} 题</span>}
              </div>
              <div style={{ fontSize: 12, color: 'var(--ink-faint)', marginBottom: 18 }}>答对可提升默契度 · 第 {quizCount + 1} 题</div>

              <div style={{ fontSize: 15.5, fontWeight: 600, color: 'var(--ink)', lineHeight: 1.5, marginBottom: 16 }}>{cur.q}</div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {quizShuffled.map((origIdx) => {
                  const isThis = quizPicked === origIdx;
                  const correct = origIdx === cur.answer;
                  let bg = 'var(--surface-secondary)';
                  let border = '1px solid var(--line-color)';
                  if (quizPicked !== null && correct) { bg = 'rgba(74,222,128,0.15)'; border = '1px solid rgba(74,222,128,0.5)'; }
                  else if (isThis && !correct) { bg = 'rgba(251,113,133,0.15)'; border = '1px solid rgba(251,113,133,0.5)'; }
                  return (
                    <button key={origIdx} onClick={() => handlePick(origIdx)} style={{
                      background: bg, border, borderRadius: 14, padding: '12px 14px', cursor: quizPicked !== null ? 'default' : 'pointer',
                      textAlign: 'left', fontSize: 14, color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: 10,
                    }}>
                      <span style={{ width: 22, height: 22, borderRadius: '50%', flexShrink: 0, display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 700, fontFamily: 'var(--mono)',
                        background: quizPicked !== null && correct ? 'rgba(74,222,128,0.3)' : isThis && !correct ? 'rgba(251,113,133,0.3)' : 'var(--surface-raised)',
                        color: quizPicked !== null && correct ? '#4ade80' : isThis && !correct ? '#fb7185' : 'var(--ink-soft)',
                      }}>
                        {quizPicked !== null && correct ? '✓' : isThis && !correct ? '✗' : String.fromCharCode(65 + quizShuffled.indexOf(origIdx))}
                      </span>
                      {cur.options[origIdx]}
                    </button>
                  );
                })}
              </div>

              {quizPicked !== null && (
                <div className="fade-rise" style={{ marginTop: 16 }}>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 14 }}>
                    <Avatar c={c} size={32} />
                    <Glass radius={14} style={{ padding: '10px 14px', borderTopLeftRadius: 4, fontSize: 13.5, lineHeight: 1.5, color: 'var(--ink)', maxWidth: '85%' }}>
                      {isCorrect ? cur.hit : cur.miss}
                    </Glass>
                  </div>
                  {isCorrect && <div style={{ fontSize: 12, color: 'rgba(74,222,128,0.8)', textAlign: 'center', marginBottom: 8 }}>默契 +2</div>}
                  <button onClick={nextQ} style={{
                    width: '100%', height: 42, borderRadius: 14, border: 'none', cursor: 'pointer',
                    background: 'linear-gradient(135deg, var(--accent), var(--accent-2))',
                    color: '#fff', fontSize: 14, fontWeight: 600,
                    boxShadow: '0 6px 16px color-mix(in oklch, var(--accent) 36%, transparent)',
                  }}>{unansweredQuiz.length > 0 ? '下一题' : '查看完成结果'}</button>
                </div>
              )}
            </div>
          </div>
        );
      })()}

      {/* ── 全图灯箱 ── */}
      {imgLightbox && (
        <ImageLightbox img={imgLightbox.img} caption={`${c.name} · ${imgLightbox.title || c.persona}`} onClose={() => setImgLightbox(null)} />
      )}
    </div>
  );
}

function btn(kind) {
  const base = { flex: 1, height: 46, borderRadius: 16, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, fontSize: 15, fontWeight: 600, color: '#fff' };
  if (kind === 'solid') return { ...base, background: 'linear-gradient(135deg, var(--accent), var(--accent-2))', boxShadow: '0 8px 22px color-mix(in oklch, var(--accent) 45%, transparent), inset 0 1px 0 rgba(255,255,255,0.4)' };
  return { ...base, maxWidth: 120, background: 'rgba(255,255,255,0.16)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)', border: '1px solid rgba(255,255,255,0.25)' };
}

function parseLoverMemory(memory) {
  const sections = {};
  let active = '';
  String(memory || '').split(/\r?\n/).forEach(raw => {
    const line = raw.trim();
    if (!line) return;
    const heading = line.match(/^#{1,3}\s+(.+)$/);
    if (heading) {
      active = heading[1].trim();
      if (!sections[active]) sections[active] = [];
      return;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (!active) active = '其他';
    if (!sections[active]) sections[active] = [];
    if (bullet) sections[active].push(bullet[1].trim());
    else if (sections[active].length) sections[active][sections[active].length - 1] += ` ${line}`;
    else sections[active].push(line);
  });
  return sections;
}

function serializeLoverMemory(sections) {
  return Object.entries(sections || {})
    .map(([title, items]) => {
      const clean = (Array.isArray(items) ? items : []).map(item => String(item || '').trim()).filter(Boolean);
      return clean.length ? `## ${title}\n${clean.map(item => `- ${item}`).join('\n')}` : '';
    })
    .filter(Boolean)
    .join('\n\n');
}

function formatArchiveDate(ts) {
  const value = Number(ts);
  if (!Number.isFinite(value) || value <= 0) return '';
  const date = new Date(value);
  if (currentUiLanguage() === 'en') {
    return date.toLocaleDateString('en-US', {
      month: 'short', day: 'numeric',
      ...(date.getFullYear() === new Date().getFullYear() ? {} : { year: 'numeric' }),
    });
  }
  const now = new Date();
  const sameYear = date.getFullYear() === now.getFullYear();
  return sameYear
    ? `${date.getMonth() + 1}月${date.getDate()}日`
    : `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function formatArchiveDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (currentUiLanguage() === 'en') {
    if (total < 60) return `${total} ${total === 1 ? 'second' : 'seconds'}`;
    const minutes = Math.floor(total / 60);
    const remain = total % 60;
    return remain
      ? `${minutes} ${minutes === 1 ? 'minute' : 'minutes'} ${remain} ${remain === 1 ? 'second' : 'seconds'}`
      : `${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`;
  }
  if (total < 60) return `${total} 秒`;
  const minutes = Math.floor(total / 60);
  const remain = total % 60;
  return remain ? `${minutes} 分 ${remain} 秒` : `${minutes} 分钟`;
}

function buildLoverArchiveEvents(c, thread, archived) {
  const events = [];
  const storedStart = Number(localStorage.getItem(`sl_start_${c.id}`));
  const startTs = Number.isFinite(storedStart) && storedStart > 0 ? storedStart : null;
  if (startTs) {
    events.push({ id: `met-${c.id}-${startTs}`, type: 'met', ts: startTs, title: uiT('遇见 {name}', { name: c.name }), detail: uiT('二人档案从这一天开始。') });
  }

  const archivedMessages = [];
  (Array.isArray(archived) ? archived : []).forEach((session, index) => {
    const messages = Array.isArray(session) ? session : (Array.isArray(session?.messages) ? session.messages : []);
    archivedMessages.push(...messages);
    const start = Number(session?.startTs || messages[0]?.ts || 0);
    const end = Number(session?.endTs || messages[messages.length - 1]?.ts || start || 0);
    const count = messages.filter(message => message?.from !== 'system').length;
    if (count) {
      events.push({
        id: `session-${c.id}-${start || index}-${index}`,
        type: 'session',
        ts: end || start,
        title: uiT('保存了一段共同对话'),
        detail: uiT('{count} 条消息已归入会话历史。', { count }),
      });
    }
  });

  const allMessages = [...archivedMessages, ...(Array.isArray(thread) ? thread : [])];
  const firstUserMessage = allMessages.find(message => message?.from === 'me');
  if (firstUserMessage) {
    const ts = Number(firstUserMessage.ts || startTs || 0);
    events.push({ id: `first-message-${c.id}-${ts}`, type: 'message', ts, title: uiT('第一次主动说话'), detail: uiT('你向 {name} 发出了第一条消息。', { name: c.name }) });
  }

  allMessages.forEach((message, index) => {
    if (!message || message.from !== 'system') return;
    const ts = Number(message.ts || 0);
    if (message.type === 'callend') {
      const mode = message.mode === 'video' ? uiT('视频') : uiT('语音');
      events.push({ id: `call-${c.id}-${ts}-${index}`, type: 'call', ts, title: uiT('{mode}通话', { mode }), detail: uiT('你们通话了 {duration}。', { duration: formatArchiveDuration(message.duration) }) });
    } else if (message.type === 'gift') {
      events.push({ id: `gift-${c.id}-${ts}-${index}`, type: 'gift', ts, title: uiT('送出了一份心意'), detail: String(message.gift || message.giftName || uiT('一份特别的礼物')) });
    } else if (message.type === 'levelup') {
      events.push({ id: `level-${c.id}-${ts}-${index}`, type: 'level', ts, title: uiT('关系提升至 {title}', { title: message.title || `Lv.${message.level || '?'}` }), detail: uiT('这是双方确认后形成的新关系阶段。') });
    }
  });

  const seen = new Set();
  return events
    .filter(event => event.id && !seen.has(event.id) && seen.add(event.id))
    .sort((a, b) => (b.ts || 0) - (a.ts || 0));
}

function ArchiveEventIcon({ type, size = 18 }) {
  const Component = type === 'call' ? I.phone
    : type === 'gift' ? I.gift
    : type === 'level' ? I.heart
    : type === 'session' ? I.diary
    : type === 'met' ? I.sparkle
    : I.chat;
  return <Component size={size} />;
}

function normalizeSavedLoverEvents(items) {
  return (Array.isArray(items) ? items : [])
    .filter(item => item && typeof item.id === 'string' && item.id)
    .slice(0, 100)
    .map(item => ({
      id: item.id,
      type: String(item.type || 'message'),
      ts: Number(item.ts || 0),
      title: String(item.title || '收藏记忆').slice(0, 160),
      detail: String(item.detail || '').slice(0, 500),
    }));
}

function readSavedLoverEvents(characterId) {
  return normalizeSavedLoverEvents(readStoredArray(`sl_saved_memories_${characterId}`));
}

// ══════════════════ 二人档案 ══════════════════
function LoverArchiveScreen({ c, memory, thread = [], archived = [], agreements = {}, initialSection = 'known', onBack, onOpenMessages, onOpenHistory, onUpdateMemory, onSaveAgreements }) {
  const language = currentUiLanguage();
  const sections = [
    { id: 'known', label: uiT('她记得的你'), icon: I.brain },
    { id: 'history', label: uiT('共同经历'), icon: I.diary },
    { id: 'agreements', label: uiT('关系约定'), icon: I.heart },
    { id: 'saved', label: uiT('收藏记忆'), icon: I.save },
  ];
  const validSection = sections.some(item => item.id === initialSection) ? initialSection : 'known';
  const [section, setSection] = useState(validSection);
  const [editingMemory, setEditingMemory] = useState(null);
  const [editingAgreements, setEditingAgreements] = useState(false);
  const normalizedAgreements = {
    character_to_user_address: String(agreements.character_to_user_address || ''),
    user_to_character_address: String(agreements.user_to_character_address || ''),
    boundary: String(agreements.boundary || ''),
    contact: String(agreements.contact || ''),
  };
  const [agreementDraft, setAgreementDraft] = useState(normalizedAgreements);
  const [saved, setSaved] = useState(() => readSavedLoverEvents(c.id));

  useEffect(() => {
    setSection(sections.some(item => item.id === initialSection) ? initialSection : 'known');
    setEditingMemory(null);
    setEditingAgreements(false);
  }, [c.id, initialSection]);

  useEffect(() => {
    setAgreementDraft({
      character_to_user_address: String(agreements.character_to_user_address || ''),
      user_to_character_address: String(agreements.user_to_character_address || ''),
      boundary: String(agreements.boundary || ''),
      contact: String(agreements.contact || ''),
    });
  }, [c.id, agreements.character_to_user_address, agreements.user_to_character_address, agreements.boundary, agreements.contact]);

  useEffect(() => {
    setSaved(readSavedLoverEvents(c.id));
  }, [c.id]);

  const parsedMemory = useMemo(() => parseLoverMemory(memory), [memory]);
  const knownGroups = useMemo(() => Object.entries(parsedMemory).filter(([title, items]) => title !== '我们之间' && title !== '用户确认的关系约定' && items.length), [parsedMemory]);
  const relationshipMemories = parsedMemory['我们之间'] || [];
  const events = useMemo(() => buildLoverArchiveEvents(c, thread, archived), [c.id, thread, archived, language]);
  const savedIds = new Set(saved.map(item => item.id));

  const persistSaved = (next) => {
    const clean = normalizeSavedLoverEvents(next);
    setSaved(clean);
    try { localStorage.setItem(`sl_saved_memories_${c.id}`, JSON.stringify(clean)); } catch (e) { /* 容量不足时保留当前界面状态 */ }
  };
  const toggleSaved = (event) => {
    if (savedIds.has(event.id)) persistSaved(saved.filter(item => item.id !== event.id));
    else persistSaved([{ id: event.id, type: event.type, ts: event.ts, title: event.title, detail: event.detail }, ...saved].slice(0, 100));
  };

  const updateMemoryEntry = (category, index, nextText) => {
    const next = Object.fromEntries(Object.entries(parsedMemory).map(([title, items]) => [title, [...items]]));
    if (!next[category]) return;
    if (nextText == null) next[category].splice(index, 1);
    else next[category][index] = String(nextText).trim();
    onUpdateMemory(serializeLoverMemory(next));
    setEditingMemory(null);
  };

  const renderKnown = () => (
    <React.Fragment>
      <div className="lover-archive-panel-heading">
        <div><h2>{uiT('她记得的你')}</h2><p>{uiT('这里只整理会影响以后相处的长期记忆。')}</p></div>
      </div>
      {knownGroups.length ? knownGroups.map(([category, items]) => (
        <section className="lover-memory-group" key={category}>
          <div className="lover-memory-group-title"><I.brain size={17} /><span>{category}</span></div>
          {items.map((item, index) => {
            const editing = editingMemory?.category === category && editingMemory?.index === index;
            return (
              <div className="lover-memory-row" key={`${category}-${index}`}>
                <div className="lover-memory-copy">
                  {editing ? (
                    <textarea value={editingMemory.value} maxLength={500} autoFocus onChange={event => setEditingMemory({ ...editingMemory, value: event.target.value })} aria-label={uiT('修改{category}记忆', { category })} />
                  ) : <p>{item}</p>}
                </div>
                <div className="lover-row-actions">
                  {editing ? (
                    <React.Fragment>
                      <button type="button" className="lover-text-button is-primary" onClick={() => updateMemoryEntry(category, index, editingMemory.value)} disabled={!editingMemory.value.trim()}>{uiT('保存')}</button>
                      <button type="button" className="lover-text-button" onClick={() => setEditingMemory(null)}>{uiT('取消')}</button>
                      <button type="button" className="lover-text-button is-danger" onClick={() => { if (window.confirm(uiT('删除这条长期记忆？'))) updateMemoryEntry(category, index, null); }}>{uiT('删除')}</button>
                    </React.Fragment>
                  ) : <button type="button" className="lover-text-button" onClick={() => setEditingMemory({ category, index, value: item })}><I.edit size={15} />{uiT('管理')}</button>}
                </div>
              </div>
            );
          })}
        </section>
      )) : (
        <div className="lover-archive-empty"><I.brain size={28} /><strong>{uiT('还没有形成长期记忆')}</strong><p>{uiT('继续相处并归档对话后，她记住的重要内容会出现在这里。')}</p></div>
      )}
    </React.Fragment>
  );

  const renderHistory = () => (
    <React.Fragment>
      <div className="lover-archive-panel-heading">
        <div><h2>{uiT('共同经历')}</h2><p>{uiT('只保留相识、归档对话、通话、礼物和关系节点。')}</p></div>
        <button type="button" className="lover-text-button" onClick={onOpenHistory}><I.diary size={16} />{uiT('会话归档')}</button>
      </div>
      {events.length ? <div className="lover-timeline">
        {events.map(event => {
          const isSaved = savedIds.has(event.id);
          return (
            <div className="lover-timeline-row" key={event.id}>
              <time>{formatArchiveDate(event.ts)}</time>
              <span className="lover-timeline-mark"><ArchiveEventIcon type={event.type} /></span>
              <div className="lover-timeline-copy"><strong>{event.title}</strong><p>{event.detail}</p></div>
              <button type="button" className={`lover-save-button${isSaved ? ' is-saved' : ''}`} aria-pressed={isSaved} aria-label={uiT(isSaved ? '取消收藏' : '收藏这段经历')} onClick={() => toggleSaved(event)}><I.save size={16} />{uiT(isSaved ? '已收藏' : '收藏')}</button>
            </div>
          );
        })}
      </div> : (
        <div className="lover-archive-empty"><I.diary size={28} /><strong>{uiT('还没有共同经历')}</strong><p>{uiT('开始聊天或通话后，值得保留的关系事件会按时间出现。')}</p></div>
      )}
    </React.Fragment>
  );

  const agreementFields = [
    { key: 'character_to_user_address', title: uiT('{name}如何称呼你', { name: c.name }), hint: uiT('只填写她对你的称呼；多个称呼可用顿号分隔') },
    { key: 'user_to_character_address', title: uiT('你如何称呼{name}', { name: c.name }), hint: uiT('只填写你对她的称呼；不会反过来当成你的名字') },
    { key: 'boundary', title: uiT('相处边界'), hint: uiT('例如：不连续催促、不拿现实压力开玩笑') },
    { key: 'contact', title: uiT('主动联系'), hint: uiT('例如：晚间可以问候，工作日上午保持安静') },
  ];
  const renderAgreements = () => (
    <React.Fragment>
      <div className="lover-archive-panel-heading">
        <div><h2>{uiT('关系约定')}</h2><p>{uiT('由你确认的规则会影响之后的聊天、主动消息和通话。')}</p></div>
        {!editingAgreements && <button type="button" className="lover-text-button" onClick={() => setEditingAgreements(true)}><I.edit size={16} />{uiT('修改')}</button>}
      </div>
      {relationshipMemories.length > 0 && (
        <section className="lover-memory-group">
          <div className="lover-memory-group-title"><I.heart size={17} /><span>{uiT('她已经记住的关系内容')}</span></div>
          {relationshipMemories.map((item, index) => <div className="lover-memory-row is-readonly" key={index}><div className="lover-memory-copy"><p>{item}</p></div></div>)}
        </section>
      )}
      <div className="lover-agreement-list">
        {agreementFields.map(field => (
          <div className="lover-agreement-row" key={field.key}>
            <div className="lover-agreement-copy"><strong>{field.title}</strong><span>{field.hint}</span></div>
            {editingAgreements ? (
              <textarea value={agreementDraft[field.key]} maxLength={240} placeholder={uiT('尚未设置')} onChange={event => setAgreementDraft({ ...agreementDraft, [field.key]: event.target.value })} aria-label={field.title} />
            ) : <p className={normalizedAgreements[field.key] ? '' : 'is-empty'}>{normalizedAgreements[field.key] || uiT('尚未设置')}</p>}
          </div>
        ))}
      </div>
      {editingAgreements && (
        <div className="lover-agreement-actions">
          <button type="button" className="lover-primary-button" onClick={() => { onSaveAgreements(agreementDraft); setEditingAgreements(false); }}><I.save size={16} />{uiT('保存约定')}</button>
          <button type="button" className="lover-secondary-button" onClick={() => { setAgreementDraft(normalizedAgreements); setEditingAgreements(false); }}>{uiT('取消')}</button>
        </div>
      )}
      <p className="lover-archive-note">{uiT('约定只影响之后的互动，不会改写过去的聊天记录。')}</p>
    </React.Fragment>
  );

  const renderSaved = () => (
    <React.Fragment>
      <div className="lover-archive-panel-heading"><div><h2>{uiT('收藏记忆')}</h2><p>{uiT('只收纳你在共同经历中主动珍藏的内容。')}</p></div></div>
      {saved.length ? <div className="lover-saved-list">
        {saved.map(item => (
          <div className="lover-saved-row" key={item.id}>
            <span className="lover-saved-icon"><ArchiveEventIcon type={item.type} /></span>
            {(() => { const displayItem = events.find(event => event.id === item.id) || item; return <div><strong>{displayItem.title}</strong><p>{displayItem.detail}</p><time>{formatArchiveDate(item.ts)}</time></div>; })()}
            <button type="button" className="lover-text-button is-danger" onClick={() => persistSaved(saved.filter(savedItem => savedItem.id !== item.id))}>{uiT('移除')}</button>
          </div>
        ))}
      </div> : (
        <div className="lover-archive-empty"><I.save size={28} /><strong>{uiT('还没有收藏记忆')}</strong><p>{uiT('到“共同经历”里收藏你想一直留下的片段。')}</p><button type="button" className="lover-secondary-button" onClick={() => setSection('history')}>{uiT('查看共同经历')}</button></div>
      )}
    </React.Fragment>
  );

  return (
    <div className="lover-archive-page">
      <Scroll>
        <div className="dc lover-archive-shell">
          <header className="lover-archive-header">
            <div className="lover-archive-title">
              <button type="button" className="lover-icon-button" onClick={onBack} aria-label={uiT('返回恋人列表')}><I.back size={23} /></button>
              <Avatar c={c} size={44} ring />
              <div><h1>{c.name} · {uiT('二人档案')}</h1><p>{uiT('共同留下的长期记忆')}</p></div>
            </div>
            <button type="button" className="lover-message-button" onClick={onOpenMessages}><I.chat size={18} />{uiT('去消息')}</button>
          </header>

          <div className="lover-archive-workspace">
            <nav className="lover-archive-index" aria-label={uiT('二人档案目录')}>
              {sections.map(item => {
                const ActiveIcon = item.icon;
                const active = section === item.id;
                return <button type="button" key={item.id} className={active ? 'is-active' : ''} aria-pressed={active} onClick={() => setSection(item.id)}><ActiveIcon size={17} /><span>{item.label}</span>{item.id === 'saved' && saved.length > 0 && <em>{saved.length}</em>}</button>;
              })}
            </nav>
            <Glass radius={24} variant="glass-quiet" className="lover-archive-panel">
              {section === 'known' ? renderKnown() : section === 'history' ? renderHistory() : section === 'agreements' ? renderAgreements() : renderSaved()}
            </Glass>
          </div>
          <div className="lover-archive-route-note"><I.info size={15} />{uiT('聊天与通话统一留在“消息”。')}</div>
        </div>
      </Scroll>
    </div>
  );
}

// ══════════════════ 恋人画廊 ══════════════════
function GalleryScreen({ current, setCurrent, onOpenArchive }) {
  const [cat, setCat] = useState(() => {
    if (sessionStorage.getItem('sl_open_custom_roles') === '1') {
      sessionStorage.removeItem('sl_open_custom_roles');
      return '我的角色';
    }
    return '全部';
  });
  const [q, setQ] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [customMode, setCustomMode] = useState(null);
  const list = ROSTER.filter(c => (cat === '全部' || (cat === '我的角色' ? c.isCustomRole : c.cat === cat))
    && (q === '' || c.name.includes(q) || String(c.en || '').toLowerCase().includes(q.toLowerCase())));
  const closeSearch = () => {
    setQ('');
    setSearchOpen(false);
  };
  if (customMode) {
    const close = () => { setCustomMode(null); setCat('我的角色'); };
    return <Scroll><div className="dc custom-role-page">
      {customMode === 'manage'
        ? <CustomRoleManager onClose={close} onEdit={id => setCustomMode(`edit:${id}`)} onOpenRole={id => { close(); onOpenArchive(id, 'known'); }} />
        : <CustomRoleStudio key={customMode} roleId={customMode.startsWith('edit:') ? customMode.slice(5) : null} onClose={close} />}
    </div></Scroll>;
  }
  return (
    <Scroll>
      <div className="dc" style={{ padding: '0 20px' }}>
        <div className="gallery-toolbar">
          <div className="no-scrollbar gallery-categories">
            {CATS.map(k => {
              const on = cat === k;
              return (
                <button key={k} onClick={() => setCat(k)} style={{
                  flexShrink: 0, height: 34, padding: '0 16px', borderRadius: 17, cursor: 'pointer', fontSize: 13.5, fontWeight: 600,
                  border: on ? 'none' : '1px solid var(--line-color)',
                  color: on ? '#fff' : 'var(--ink-soft)',
                  background: on ? 'linear-gradient(135deg, var(--accent), var(--accent-2))' : 'var(--surface-secondary)',
                  boxShadow: on ? '0 6px 16px color-mix(in oklch, var(--accent) 38%, transparent)' : 'none',
                }}>{uiT(k)}</button>
              );
            })}
          </div>
          {searchOpen ? (
            <Glass radius={17} className="gallery-search is-open">
              <I.search size={17} />
              <input autoFocus value={q} onChange={event => setQ(event.target.value)}
                onKeyDown={event => { if (event.key === 'Escape') closeSearch(); }} aria-label={uiT('搜索恋人')} />
              <button type="button" onClick={closeSearch} aria-label={uiT('关闭搜索')}><I.windowClose size={14} /></button>
            </Glass>
          ) : (
            <button type="button" className="gallery-search-trigger" onClick={() => setSearchOpen(true)} aria-label={uiT('搜索恋人')}>
              <I.search size={18} />
            </button>
          )}
        </div>

        <div className="custom-role-gallery-actions">
          <span>{cat === '我的角色' ? uiT('在这里创建和管理属于你的角色') : ''}</span>
          <button type="button" className="custom-role-secondary-button" onClick={() => setCustomMode('manage')}>{uiT('管理我的角色')}</button>
          <button type="button" className="custom-role-primary-button" onClick={() => setCustomMode('create')}>{uiT('新建角色')}</button>
        </div>

        {/* grid — auto-fill: 手机2列，桌面自动5~6列 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12 }}>
          {list.map((c, i) => {
            const mine = current.id === c.id;
            return (
              <Glass key={c.id} radius={22} className="fade-rise" onClick={() => onOpenArchive(c.id, 'known')} style={{ padding: 6, cursor: 'pointer', animationDelay: `${i*.03}s` }}>
                <div style={{ position: 'relative', borderRadius: 17, overflow: 'hidden', aspectRatio: '3/4' }}>
                  <ArtPlaceholder hue={c.hue} label={uiT('立绘')} dim="" rounded={17} faceTop src={c.face || c.img} pos={c.facePos || c.imgPos} />
                  <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(0deg, rgba(8,4,22,0.7), transparent 50%)' }} />
                  {mine && (
                    <div style={{ position: 'absolute', top: 8, left: 8, display: 'flex', alignItems: 'center', gap: 4, padding: '4px 9px', borderRadius: 11, fontSize: 10.5, fontWeight: 700, color: '#fff', background: 'rgba(10,6,24,0.55)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)', border: '1px solid rgba(255,255,255,0.18)', textShadow: '0 1px 3px rgba(0,0,0,0.55)' }}>
                      <I.heart size={11} fill="var(--accent)" stroke="var(--accent)" /> {uiT('恋爱中')}
                    </div>
                  )}
                  <button type="button" onClick={(e) => { e.stopPropagation(); setCurrent(c.id); }}
                    aria-label={mine ? uiT('{name}当前是我的恋人', { name: c.name }) : uiT('设{name}为我的恋人', { name: c.name })} aria-pressed={mine} title={uiT('设为我的恋人')} style={{
                    position: 'absolute', bottom: 8, right: 8, width: 30, height: 30, borderRadius: '50%', border: 'none', cursor: 'pointer',
                    display: 'grid', placeItems: 'center', color: '#fff',
                    background: mine ? 'linear-gradient(135deg, var(--accent), var(--accent-2))' : 'rgba(255,255,255,0.22)',
                    backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)', border: '1px solid rgba(255,255,255,0.3)',
                  }}>
                    <I.heart size={15} fill={mine ? '#fff' : 'none'} />
                  </button>
                </div>
                <div style={{ padding: '9px 6px 5px' }}>
                  <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)' }}>{c.name}</div>
                  <div style={{ fontSize: 11.5, color: 'var(--ink-faint)', marginTop: 2 }}>{c.persona}</div>
                  <div style={{ display: 'flex', gap: 5, marginTop: 8, flexWrap: 'wrap' }}>
                    {c.tags.slice(0, 2).map(t => (
                      <span key={t} style={{ fontSize: 10.5, color: 'var(--ink-soft)', padding: '3px 8px', borderRadius: 9, background: 'var(--surface-secondary)', border: '1px solid var(--line-color)' }}>{t}</span>
                    ))}
                  </div>
                </div>
              </Glass>
            );
          })}
        </div>
        {!list.length && <div className="custom-role-gallery-empty" role="status">{!ROSTER.length || cat === '我的角色' ? uiT('还没有自建角色。点击“新建角色”创建或导入角色。') : uiT('没有找到相关角色。')}</div>}
      </div>
    </Scroll>
  );
}

// ══════════════════ 消息列表 ══════════════════
function fmtTime(ts) {
  if (!ts) return '';
  const now = new Date();
  const d = new Date(ts);
  const diffMs = now - d;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return uiT('刚刚');
  if (diffMin < 60) return currentUiLanguage() === 'en' ? `${diffMin} min ago` : `${diffMin}分钟前`;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dayDiff = Math.round((today - msgDay) / 86400000);
  if (dayDiff === 0) return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  if (dayDiff === 1) return uiT('昨天');
  const days = ['周日','周一','周二','周三','周四','周五','周六'];
  if (dayDiff < 7) return uiT(days[d.getDay()]);
  return currentUiLanguage() === 'en'
    ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : `${d.getMonth()+1}月${d.getDate()}日`;
}

function hasConversationMessages(messages) {
  return (Array.isArray(messages) ? messages : []).some(message =>
    message && message.from !== 'system' && String(message.text || '').trim()
  );
}

function pickDesktopConversationId(threads, rememberedId, currentId) {
  const available = ROSTER.filter(character => hasConversationMessages(threads?.[character.id]));
  if (!available.length) return null;
  if (available.some(character => character.id === rememberedId)) return rememberedId;
  if (available.some(character => character.id === currentId)) return currentId;
  return [...available].sort((left, right) => {
    const latest = character => Math.max(0, ...(threads?.[character.id] || []).map(message => Number(message?.ts) || 0));
    return latest(right) - latest(left);
  })[0].id;
}

function MessagesScreen({ current, openChat, threads, lastRead = {}, activeChatId = null }) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState('');
  const others = ROSTER.filter(c => c.id !== current.id);
  const ordered = [current, ...others].filter(c => hasConversationMessages(threads[c.id]) || c.id === activeChatId);
  const normalizedQuery = query.trim().toLocaleLowerCase('zh-CN');
  const visible = normalizedQuery
    ? ordered.filter(c => {
        const recentText = (threads[c.id] || []).slice(-24).map(message => message?.text || '').join(' ');
        return `${c.name} ${c.persona || ''} ${recentText}`.toLocaleLowerCase('zh-CN').includes(normalizedQuery);
      })
    : ordered;
  const closeSearch = () => {
    setQuery('');
    setSearchOpen(false);
  };
  return (
    <Scroll padTop={0}>
      <div className="messages-panel">
        <header className="messages-panel-header">
          {ordered.length > 0 && (searchOpen ? (
            <div className="message-search is-open">
              <I.search size={17} style={{ flexShrink: 0, color: 'var(--ink-faint)' }} />
              <input
                autoFocus
                value={query}
                onChange={event => setQuery(event.target.value)}
                onKeyDown={event => { if (event.key === 'Escape') closeSearch(); }}
                aria-label={uiT('搜索会话')}
                placeholder={uiT('搜索角色或消息')}
              />
              <button type="button" onClick={closeSearch} aria-label={uiT('关闭搜索')}><I.windowClose size={15} /></button>
            </div>
          ) : (
            <button type="button" className="message-search-button" onClick={() => setSearchOpen(true)} aria-label={uiT('搜索会话')}><I.search size={18} /></button>
          ))}
        </header>
        <div className="message-list-stack">
          {visible.map((c, i) => {
            const thread = threads[c.id] || [];
            const lastMsg = [...thread].reverse().find(m => m && m.from !== 'system' && m.text) || null;
            const preview = lastMsg ? lastMsg.text : uiT('还没有消息');
            const ts = lastMsg ? lastMsg.ts : null;
            const readTs = lastRead[c.id] || 0;
            const unread = thread.filter(
              m => m.from === 'her' && m.origin === 'proactive' && (m.ts || 0) > readTs
            ).length;
            const pinned = c.id === current.id;
            const selected = c.id === activeChatId;
            return (
              <button key={c.id} type="button" onClick={(event) => {
                const panel = event.currentTarget.closest('.msg-panel-list');
                const panelRect = panel?.getBoundingClientRect();
                const itemRect = event.currentTarget.getBoundingClientRect();
                const originOffsetY = panelRect
                  ? itemRect.top + itemRect.height / 2 - panelRect.top
                  : null;
                const originY = panelRect
                  ? originOffsetY / panelRect.height
                  : 0.18;
                openChat(c.id, { originY, originOffsetY, source: 'message-list' });
              }}
                className={`message-list-item${selected ? ' is-selected' : ''}`}
                aria-current={selected ? 'page' : undefined}
                style={{ borderBottom: i < visible.length - 1 ? '1px solid var(--hairline-color)' : 'none' }}>
                <div className="message-list-avatar">
                  <Avatar c={c} size={46} ring={pinned} />
                  {c.online && <span style={{ position: 'absolute', bottom: 1, right: 1, width: 12, height: 12, borderRadius: '50%', background: '#34c987', border: '2.5px solid var(--surface-primary)' }} />}
                </div>
                <div className="message-list-copy">
                  <div className="message-list-name">
                    <span style={{ fontWeight: unread > 0 ? 700 : 620, color: 'var(--ink)' }}>{c.name}</span>
                    {pinned && <span className="message-list-relation">{uiT('恋人')}</span>}
                  </div>
                  <div className="message-list-preview" style={{ color: unread > 0 ? 'var(--ink)' : 'var(--ink-soft)', fontWeight: unread > 0 ? 520 : 400 }}>{preview}</div>
                </div>
                <div className="message-list-meta">
                  <span>{fmtTime(ts)}</span>
                  {unread > 0 && <span style={{ minWidth: 18, height: 18, padding: '0 5px', borderRadius: 9, background: 'var(--accent)', color: '#fff', fontSize: 11, fontWeight: 700, display: 'grid', placeItems: 'center' }}>{unread}</span>}
                </div>
              </button>
            );
          })}
          {visible.length === 0 && normalizedQuery && (
            <div role="status" className="message-list-empty">{uiT('没有找到相关会话')}</div>
          )}
        </div>
      </div>
    </Scroll>
  );
}

// ══════════════════ 角色名片 ══════════════════
function CharacterProfilePanel({ c, onBack, onOpenChat, onOpenHistory }) {
  const [detail, setDetail] = useState(null);
  const [avatarView, setAvatarView] = useState(false); // 点头像看大图
  useEffect(() => {
    let active = true;
    fetch(`/api/characters/${encodeURIComponent(c.id)}`, { cache: 'no-store' })
      .then(res => res.ok ? res.json() : null)
      .then(data => { if (active && data) setDetail(data); })
      .catch(() => {});
    return () => { active = false; };
  }, [c.id]);

  const facts = Array.isArray(detail?.background) ? detail.background : [];
  const startTs = parseInt(localStorage.getItem(`sl_start_${c.id}`)) || Date.now();
  const daysWithChar = Math.max(1, Math.floor((Date.now() - startTs) / 86400000));
  const companion = normalizeCompanionContext(c.companionContext, c.id);
  const relation = companion.relationship;
  const relationDimensions = [
    [uiT('熟悉'), relation.dimensions.familiarity],
    [uiT('信任'), relation.dimensions.trust],
    [uiT('情感'), relation.dimensions.affection],
    [uiT('承诺'), relation.dimensions.commitment],
  ];

  return (
    <PanelShell title={uiT('角色名片')} onBack={onBack}>
      <div style={{ position: 'relative', height: 230, borderRadius: 22, overflow: 'hidden', marginBottom: 18, background: `linear-gradient(150deg, oklch(0.32 0.1 ${c.hue}), oklch(0.22 0.08 ${c.hue + 30}))` }}>
        <ArtPlaceholder hue={c.hue} label="" dim="" rounded={22} src={c.img || c.face} pos={c.imgPos || c.facePos} imgFit={c.imgFit || 'cover'} />
        <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(0deg, rgba(8,4,22,0.92) 0%, rgba(8,4,22,0.12) 68%)' }} />
        <div style={{ position: 'absolute', left: 18, right: 18, bottom: 16, display: 'flex', alignItems: 'flex-end', gap: 12 }}>
          {c.face ? (
            <button type="button" aria-label={`查看${c.name}的头像`} onClick={() => setAvatarView(true)}
              style={{ background: 'none', border: 'none', padding: 0, cursor: 'zoom-in', flexShrink: 0 }}>
              <Avatar c={c} size={62} ring />
            </button>
          ) : (
            <div style={{ flexShrink: 0 }}><Avatar c={c} size={62} ring /></div>
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 22, fontWeight: 800, color: '#fff' }}>{c.name}</div>
            <div style={{ fontSize: 12.5, color: 'rgba(255,255,255,0.68)', marginTop: 2 }}>{c.en} · {c.persona}</div>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginBottom: 16 }}>
        {[c.cat, ...(c.tags || [])].map(tag => (
          <span key={tag} style={{ padding: '5px 10px', borderRadius: 10, fontSize: 11.5, color: 'var(--ink-soft)', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.1)' }}>{tag}</span>
        ))}
      </div>

      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink-soft)', margin: '0 2px 8px' }}>{uiT('与你的关系')}</div>
      <Glass radius={18} style={{ padding: 15, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--ink)' }}>{relation.title}</div>
            <div style={{ marginTop: 3, fontSize: 11.5, color: 'var(--ink-faint)' }}>{relation.stage}</div>
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>Lv.{relation.level}</div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '11px 14px' }}>
          {relationDimensions.map(([label, value]) => (
            <div key={label}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: 'var(--ink-soft)', marginBottom: 5 }}>
                <span>{label}</span><span>{value}/4</span>
              </div>
              <div style={{ height: 5, borderRadius: 5, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
                <div style={{ width: `${value * 25}%`, height: '100%', borderRadius: 5, background: 'linear-gradient(90deg, var(--accent), var(--accent-2))' }} />
              </div>
            </div>
          ))}
        </div>
      </Glass>

      {c.profileMeta && c.profileMeta.length > 0 && (
        <React.Fragment>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink-soft)', margin: '0 2px 8px' }}>{uiT('资料摘要')}</div>
          <Glass radius={18} style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', padding: '4px 14px', marginBottom: 16 }}>
            {c.profileMeta.map((item, i) => (
              <div key={item.label} style={{ padding: '11px 2px', borderBottom: i < c.profileMeta.length - 2 ? '0.5px solid rgba(255,255,255,0.08)' : 'none' }}>
                <div style={{ fontSize: 11.5, color: 'var(--ink-faint)' }}>{item.label}</div>
                <div style={{ marginTop: 3, fontSize: 13.5, fontWeight: 650, color: 'var(--ink)' }}>{item.value}</div>
              </div>
            ))}
          </Glass>
        </React.Fragment>
      )}

      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink-soft)', margin: '0 2px 8px' }}>{uiT('角色介绍')}</div>
      <Glass radius={18} style={{ padding: 15, marginBottom: 16 }}>
        <div style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--ink)' }}>{c.profileIntro || `${c.name}，${c.persona}。性格中最鲜明的是${(c.tags || []).join('、')}。`}</div>
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.09)', fontSize: 12.5, lineHeight: 1.65, color: 'var(--ink-soft)' }}>“{c.greet}”</div>
      </Glass>

      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink-soft)', margin: '0 2px 8px' }}>{uiT('背景与经历')}</div>
      <Glass radius={18} style={{ padding: '5px 15px', marginBottom: 16 }}>
        {facts.length ? facts.map((fact, i) => (
          <div key={i} style={{ display: 'flex', gap: 10, padding: '11px 0', borderBottom: i < facts.length - 1 ? '0.5px solid rgba(255,255,255,0.08)' : 'none' }}>
            <span style={{ color: 'var(--accent)', fontSize: 14, lineHeight: 1.6 }}>◆</span>
            <div style={{ fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink)' }}>{fact}</div>
          </div>
        )) : (
          <div style={{ padding: '13px 0', fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink-soft)' }}>更多背景正在逐步补全。她会在与你的相处中留下属于你们的故事。</div>
        )}
      </Glass>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 10, marginBottom: 16 }}>
        <Glass radius={16} variant="glass-quiet" style={{ padding: 12, textAlign: 'center' }}>
          <div style={{ fontSize: 17, fontWeight: 800, color: 'var(--ink)' }}>{relation.title}</div>
          <div style={{ fontSize: 11.5, color: 'var(--ink-faint)', marginTop: 2 }}>{uiT('关系称号')}</div>
        </Glass>
        <Glass radius={16} variant="glass-quiet" style={{ padding: 12, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--ink)' }}>{daysWithChar}<span style={{ fontSize: 11, color: 'var(--ink-faint)', marginLeft: 2 }}>{uiT('天')}</span></div>
          <div style={{ fontSize: 11.5, color: 'var(--ink-faint)', marginTop: 2 }}>{uiT('相伴时间')}</div>
        </Glass>
      </div>

      <div style={{ display: 'flex', gap: 10, paddingBottom: 24 }}>
        <button type="button" onClick={onOpenHistory} style={{ flex: 1, height: 46, borderRadius: 15, border: '1px solid var(--line-color)', cursor: 'pointer', color: 'var(--ink)', background: 'var(--surface-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, fontSize: 13.5, fontWeight: 600 }}><I.diary size={17} />{uiT('对话记录')}</button>
        <button type="button" onClick={onOpenChat} style={{ flex: 1.35, height: 46, borderRadius: 15, border: 'none', cursor: 'pointer', color: '#fff', background: 'linear-gradient(135deg, var(--accent), var(--accent-2))', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, fontSize: 13.5, fontWeight: 700 }}><I.chat size={17} />{uiT('找 TA 聊天')}</button>
      </div>

      {avatarView && c.face && <ImageLightbox img={c.face} caption={`${c.name} · 头像`} onClose={() => setAvatarView(false)} />}
    </PanelShell>
  );
}

// 面板外壳：标题栏 + 返回 + 可滚动内容
function PanelShell({ title, onBack, children }) {
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ paddingTop: 50, flexShrink: 0 }}>
        <Glass radius={0} variant="glass-strong" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none', borderTop: 'none', display: 'flex', alignItems: 'center', gap: 11, padding: '9px 14px 11px' }}>
          <button type="button" onClick={onBack} aria-label={`返回，离开${title}`} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--ink)', display: 'grid', placeItems: 'center', width: 32, height: 32 }}><I.back size={24} /></button>
          <div style={{ flex: 1, fontSize: 17, fontWeight: 700, color: 'var(--ink)' }}>{title}</div>
        </Glass>
      </div>
      <div className="no-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>{children}</div>
    </div>
  );
}

// 本地图片 → 居中裁方 → 256px JPEG dataURL（控制 localStorage 体积）
function fileToAvatarDataUrl(file, onSuccess, onError) {
  const fail = message => { if (onError) onError(message); };
  if (!file || !String(file.type || '').startsWith('image/')) {
    fail('请选择图片文件。');
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    fail('图片不能超过 8 MB。');
    return;
  }
  const fr = new FileReader();
  fr.onerror = () => fail('无法读取这张图片，请换一张重试。');
  fr.onload = () => {
    const img = new Image();
    img.onerror = () => fail('暂不支持这张图片的格式，请使用 JPG、PNG 或 WebP。');
    img.onload = () => {
      try {
        if (!img.width || !img.height) throw new Error('图片尺寸无效');
        const S = 256;
        const side = Math.min(img.width, img.height);
        const sx = (img.width - side) / 2, sy = (img.height - side) / 2;
        const canvas = document.createElement('canvas');
        canvas.width = S; canvas.height = S;
        const ctx = canvas.getContext('2d');
        if (!ctx) throw new Error('浏览器无法处理图片');
        ctx.fillStyle = '#0f0c24';
        ctx.fillRect(0, 0, S, S);
        ctx.drawImage(img, sx, sy, side, side, 0, 0, S, S);
        onSuccess(canvas.toDataURL('image/jpeg', 0.86));
      } catch (e) {
        fail('头像处理失败，请换一张图片重试。');
      }
    };
    img.src = fr.result;
  };
  try { fr.readAsDataURL(file); }
  catch (e) { fail('无法读取这张图片，请换一张重试。'); }
}

// ══════════════════ 我的 · 精简账户中心 ══════════════════
function getJoinedDays() {
  const keys = Object.keys(localStorage).filter(key => key.startsWith('sl_start_'));
  if (!keys.length) return 1;
  const earliest = Math.min(...keys.map(key => parseInt(localStorage.getItem(key), 10) || Date.now()));
  return Math.max(1, Math.floor((Date.now() - earliest) / 86400000));
}

function AccountNavRow({ icon: Ic, title, sub, onClick, entry, last = false }) {
  return (
    <button type="button" className={`account-nav-row${last ? ' is-last' : ''}`} data-account-entry={entry} onClick={onClick}>
      <span className="account-row-icon"><Ic size={19} /></span>
      <span className="account-nav-copy">
        <strong>{title}</strong>
        <span>{sub}</span>
      </span>
      <span className="account-row-chevron"><I.chevR size={18} /></span>
    </button>
  );
}

function MeScreen({ openProfile, openSettings, userProfile }) {
  const joinedDays = getJoinedDays();
  return (
    <Scroll padTop={0}>
      <main className="account-page dc">
        <header className="account-header">
          <Eyebrow>ACCOUNT</Eyebrow>
          <h1>{uiT('我的')}</h1>
          <p>{uiT('管理你的身份、应用偏好和本机数据。')}</p>
        </header>

        <section className="account-profile-summary" aria-label={uiT('账户概览')}>
          <UserAvatar profile={userProfile} size={72} ring />
          <div className="account-profile-copy">
            <h2>{userProfile?.name || '你'}</h2>
            <p>{currentUiLanguage() === 'en' ? `Local profile · ${joinedDays} days with Shulian` : `本机资料 · 加入数恋 ${joinedDays} 天`}</p>
            <span>{userProfile?.bio || uiT('把喜欢的人留在身边')}</span>
          </div>
        </section>

        <section className="account-section" aria-labelledby="account-manage-title">
          <h2 id="account-manage-title" className="account-section-title">{uiT('账户与应用')}</h2>
          <div className="account-list">
            <AccountNavRow icon={I.user} title={uiT('我的资料')} sub={uiT('头像、昵称与个人签名')} onClick={openProfile} entry="profile" />
            <AccountNavRow icon={I.settings} title={uiT('设置')} sub={uiT('主动消息、动态效果与本机数据')} onClick={openSettings} entry="settings" last />
          </div>
        </section>

        <aside className="account-local-note">
          <I.info size={18} />
          <div>
            <strong>{uiT('本机账户')}</strong>
            <span>{uiT('资料、会话和记忆仅保存在当前设备，可在设置中导出备份。')}</span>
          </div>
        </aside>

        <footer className="account-footer">{currentUiLanguage() === 'en' ? `Shulian v${SHULIAN_APP_VERSION} · ${uiT('记忆与陪伴')}` : `数恋 v${SHULIAN_APP_VERSION} · ${uiT('记忆与陪伴')}`}</footer>
      </main>
    </Scroll>
  );
}

function SettingsSwitch({ on, onClick, label }) {
  return (
    <button type="button" className={`settings-switch${on ? ' is-on' : ''}`} role="switch" aria-checked={on} aria-label={label} onClick={onClick}>
      <span className="settings-switch-track" aria-hidden="true"><span /></span>
    </button>
  );
}

function AccountPanelShell({ title, onBack, children, variant = '' }) {
  const titleRef = useRef(null);
  useEffect(() => {
    if (titleRef.current) titleRef.current.focus({ preventScroll: true });
  }, []);
  return (
    <div className={`account-panel-shell${variant ? ` is-${variant}` : ''}`}>
      <div className="account-panel-head">
        <button type="button" onClick={onBack} className="account-panel-back" aria-label={currentUiLanguage() === 'en' ? `Back from ${title}` : `返回，离开${title}`}><I.back size={23} /></button>
        <h1 ref={titleRef} tabIndex={-1}>{title}</h1>
      </div>
      <div className={`account-panel-body no-scrollbar${variant ? ` is-${variant}` : ''}`}>{children}</div>
    </div>
  );
}

function AccountSettingRow({ icon: Ic, title, sub, right, last = false, onClick, entry, className = '' }) {
  const content = (
    <React.Fragment>
      {Ic && <span className="settings-row-icon"><Ic size={18} /></span>}
      <div className="settings-row-copy">
        <strong>{title}</strong>
        {sub && <span>{sub}</span>}
      </div>
      {right}
    </React.Fragment>
  );
  if (onClick) {
    return (
      <button type="button" className={`settings-row is-link${last ? ' is-last' : ''}${className ? ` ${className}` : ''}`} data-settings-entry={entry} onClick={onClick}>
        {content}
      </button>
    );
  }
  return <div className={`settings-row${last ? ' is-last' : ''}${className ? ` ${className}` : ''}`}>{content}</div>;
}

function profileSnapshot(profile) {
  return JSON.stringify({
    name: String(profile?.name || ''),
    bio: String(profile?.bio || ''),
    avatarImg: String(profile?.avatarImg || ''),
  });
}

function ProfileScreen({ onBack, userProfile, onSaveProfile, onDirtyChange }) {
  const [profileDraft, setProfileDraft] = useState(userProfile || { name: '你', bio: '' });
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [avatarError, setAvatarError] = useState('');

  useEffect(() => {
    setProfileDraft(userProfile || { name: '你', bio: '' });
    setSaved(false);
    setSaveError('');
    setAvatarError('');
  }, [userProfile?.name, userProfile?.bio, userProfile?.avatarImg]);

  const dirty = profileSnapshot(profileDraft) !== profileSnapshot(userProfile);
  useEffect(() => {
    if (onDirtyChange) onDirtyChange(dirty);
    return () => { if (onDirtyChange) onDirtyChange(false); };
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return undefined;
    const warnBeforeUnload = event => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warnBeforeUnload);
    return () => window.removeEventListener('beforeunload', warnBeforeUnload);
  }, [dirty]);

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!dirty) return;
    setSaveError('');
    const normalized = onSaveProfile && onSaveProfile(profileDraft);
    if (normalized) {
      setProfileDraft(normalized);
      setSaved(true);
    } else {
      setSaved(false);
      setSaveError('保存失败，请检查本机存储空间后重试。');
    }
  };
  return (
    <AccountPanelShell title={uiT('我的资料')} onBack={onBack}>
      <form className="account-panel-form" onSubmit={handleSubmit}>
        <section className="profile-avatar-editor" aria-labelledby="profile-avatar-title">
          <label className="profile-avatar-trigger" htmlFor="profile-avatar-input">
            <input id="profile-avatar-input" className="visually-hidden" type="file" accept="image/*" onChange={event => {
              const file = event.target.files && event.target.files[0];
              if (file) fileToAvatarDataUrl(
                file,
                url => { setAvatarError(''); setSaved(false); setProfileDraft(prev => ({ ...prev, avatarImg: url })); },
                message => setAvatarError(message),
              );
              event.target.value = '';
            }} />
            <UserAvatar profile={profileDraft} size={88} ring />
            <span className="profile-avatar-edit-badge"><I.edit size={14} /></span>
          </label>
          <div className="profile-avatar-copy">
            <h2 id="profile-avatar-title">{uiT('头像')}</h2>
            <p>{currentUiLanguage() === 'en' ? `Local profile · ${getJoinedDays()} days with Shulian` : `本机资料 · 加入数恋 ${getJoinedDays()} 天`}</p>
            <div className="profile-avatar-actions">
              <label className="account-button account-button-secondary is-compact" htmlFor="profile-avatar-input">{uiT('更换头像')}</label>
              {profileDraft.avatarImg && (
                <button type="button" className="account-button account-button-ghost is-compact" onClick={() => { setSaved(false); setProfileDraft(prev => ({ ...prev, avatarImg: '' })); }}>{uiT('移除')}</button>
              )}
            </div>
            {avatarError && <p className="profile-avatar-error" role="alert">{avatarError}</p>}
          </div>
        </section>

        <section className="account-panel-section" aria-labelledby="profile-info-title">
          <h2 id="profile-info-title" className="account-section-title">{uiT('个人信息')}</h2>
          <div className="account-form-card">
            <label className="account-field">
              <span className="account-field-label"><strong>{uiT('昵称')}</strong><small>{String(profileDraft.name || '').length}/20</small></span>
              <input className="account-input" value={profileDraft.name || ''} maxLength={20} autoComplete="nickname" onChange={event => { setSaved(false); setProfileDraft(prev => ({ ...prev, name: event.target.value })); }} />
            </label>
            <label className="account-field">
              <span className="account-field-label"><strong>{uiT('个人签名')}</strong><small>{String(profileDraft.bio || '').length}/80</small></span>
              <textarea className="account-input account-textarea" value={profileDraft.bio || ''} maxLength={80} rows={4} onChange={event => { setSaved(false); setProfileDraft(prev => ({ ...prev, bio: event.target.value })); }} />
            </label>
          </div>
        </section>

        <div className="profile-save-row">
          <span className={`account-save-status${saveError ? ' is-error' : ''}`} role={saveError ? 'alert' : 'status'} aria-live="polite">{saveError || (saved && !dirty ? uiT('已保存') : '')}</span>
          <button type="submit" className="account-button account-button-primary" disabled={!dirty}><I.save size={18} />{uiT('保存资料')}</button>
        </div>
      </form>
    </AccountPanelShell>
  );
}

const ACCOUNT_SETTINGS_DEFAULT = { nudge: true, reduceMotion: false, performanceMode: true, themeMode: 'system', language: 'zh-CN' };
function normalizeSettingBoolean(value, fallback) {
  if (value === true || value === 'true' || value === 1 || value === '1') return true;
  if (value === false || value === 'false' || value === 0 || value === '0') return false;
  return fallback;
}
function normalizeThemeMode(value) {
  return ['light', 'dark', 'system'].includes(value) ? value : ACCOUNT_SETTINGS_DEFAULT.themeMode;
}
function loadAccountSettings() {
  try {
    const raw = JSON.parse(localStorage.getItem('sl_settings') || '{}');
    return {
      nudge: normalizeSettingBoolean(raw?.nudge, ACCOUNT_SETTINGS_DEFAULT.nudge),
      reduceMotion: normalizeSettingBoolean(raw?.reduceMotion, ACCOUNT_SETTINGS_DEFAULT.reduceMotion),
      performanceMode: normalizeSettingBoolean(raw?.performanceMode, ACCOUNT_SETTINGS_DEFAULT.performanceMode),
      themeMode: normalizeThemeMode(raw?.themeMode),
      language: normalizeUiLanguage(raw?.language),
    };
  }
  catch { return { ...ACCOUNT_SETTINGS_DEFAULT }; }
}

function readLocalDataSummary() {
  let msgCount = 0, sessCount = 0, memCount = 0;
  try {
    const threads = JSON.parse(localStorage.getItem('sl_threads') || '{}');
    Object.values(threads).forEach(items => { msgCount += Array.isArray(items) ? items.length : 0; });
    const sessions = JSON.parse(localStorage.getItem('sl_sessions') || '{}');
    Object.values(sessions).forEach(items => { sessCount += Array.isArray(items) ? items.length : 0; });
    for (let index = 0; index < localStorage.length; index++) {
      const key = localStorage.key(index);
      if (key?.startsWith('sl_memory_') && (localStorage.getItem(key) || '').trim()) memCount++;
    }
  } catch (e) { /* 保持可读的零值 */ }
  return { msgCount, sessCount, memCount };
}

function readShulianStorage() {
  const data = {};
  for (let index = 0; index < localStorage.length; index++) {
    const key = localStorage.key(index);
    if (key?.startsWith('sl_') && !key.startsWith('sl_sqlite_')) {
      data[key] = localStorage.getItem(key);
    }
  }
  return data;
}

function aiKeyDisplay(config) {
  if (config?.remembered === true && config?.configured === false) return uiT('已保存，下次启动自动连接');
  if (config?.configured === false && config?.remembered !== true) return uiT('仅当前会话，关闭后需重新验证');
  const masked = config?.masked_key || config?.masked_api_key || config?.api_key_masked || config?.key_hint;
  if (typeof masked === 'string' && masked.trim()) return masked.trim();
  const lastFour = String(config?.last_four || config?.key_last4 || '').replace(/[^a-zA-Z0-9]/g, '').slice(-4);
  return lastFour ? `•••• ${lastFour}` : uiT('已安全保存在此 Windows 账户');
}

function AiServiceScreen({ onBack, aiConfig, onChangeApiKey, onChangeModel, onRemoveApiKey, onForgetApiKey }) {
  const [editing, setEditing] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [isError, setIsError] = useState(false);
  const [modelSaving, setModelSaving] = useState('');
  const providerLabel = aiConfig?.provider_label || uiT('AI 服务');

  const modelOptions = Array.isArray(aiConfig?.model_options) && aiConfig.model_options.length
    ? aiConfig.model_options
    : [
        { id: 'deepseek-flash', label: 'DeepSeek V4.1 Flash', description: '最新版 Flash 多模态模型', recommended: true },
      ];

  const changeModel = async (model) => {
    if (model === aiConfig?.model || modelSaving) return;
    setModelSaving(model);
    setIsError(false);
    setFeedback('');
    const result = await onChangeModel(model);
    setModelSaving('');
    if (!result?.ok) {
      setIsError(true);
      setFeedback(result?.message || uiT('模型切换失败，原档位仍然有效。'));
      return;
    }
    const selected = modelOptions.find(option => option.id === model);
    setFeedback(uiT('已连接 {model}。', { model: selected?.label || model }));
  };

  const replaceKey = async (event) => {
    event.preventDefault();
    const candidate = apiKey.trim();
    if (!candidate) {
      setIsError(true);
      setFeedback(uiT('请输入新的 API Key。'));
      return;
    }
    setSaving(true);
    setIsError(false);
    setFeedback('');
    const result = await onChangeApiKey(candidate);
    setSaving(false);
    if (!result?.ok) {
      setIsError(true);
      setFeedback(result?.message || uiT('验证失败，原连接未更改。'));
      return;
    }
    setApiKey('');
    setVisible(false);
    setEditing(false);
    setFeedback(uiT('账号已切换。'));
  };

  const logoutKey = async () => {
    if (!window.confirm(uiT('退出当前 AI 会话会返回登录界面；已保存的 API Key 会保留，并在下次启动时自动连接。聊天、记忆和个人资料都会保留，继续吗？'))) return;
    setRemoving(true);
    setIsError(false);
    setFeedback('');
    const result = await onRemoveApiKey();
    if (!result?.ok) {
      setRemoving(false);
      setIsError(true);
      setFeedback(result?.message || uiT('退出失败，请稍后重试。'));
    }
  };

  const forgetKey = async () => {
    if (!window.confirm(uiT('清除本机保存的 API Key 会返回登录界面。聊天、记忆和个人资料都会保留，继续吗？'))) return;
    setRemoving(true);
    setIsError(false);
    setFeedback('');
    const result = await onForgetApiKey();
    if (!result?.ok) {
      setRemoving(false);
      setIsError(true);
      setFeedback(result?.message || uiT('清除失败，请稍后重试。'));
    }
  };

  return (
    <AccountPanelShell title={uiT('AI 服务')} onBack={onBack}>
      <div className="account-panel-form">
        <section className="ai-service-summary" aria-labelledby="ai-service-title">
          <span className="ai-service-mark"><I.sparkle size={22} /></span>
          <div>
            <h2 id="ai-service-title">{providerLabel}</h2>
            <p>{uiT('已连接')} · {aiKeyDisplay(aiConfig)}</p>
          </div>
          <span className="ai-service-connected"><span aria-hidden="true" />{uiT('已连接')}</span>
        </section>

        <section className="account-panel-section" aria-labelledby="ai-service-manage-title">
          <h2 id="ai-service-manage-title" className="account-section-title">{uiT('连接管理')}</h2>
          <div className="settings-card">
            <AccountSettingRow icon={I.info} title={uiT('当前服务')} sub={`${providerLabel} API`} right={<span className="settings-local-badge">{uiT('个人 Key')}</span>} />
            <AccountSettingRow icon={I.save} title={uiT('安全存储')} sub={uiT('由当前 Windows 账户加密保护')} last right={<span className="settings-local-badge">{uiT('本机')}</span>} />
          </div>
        </section>

        <section className="account-panel-section" aria-labelledby="ai-service-model-title">
          <h2 id="ai-service-model-title" className="account-section-title">{uiT('回复模型')}</h2>
          <div className="ai-model-options" role="radiogroup" aria-label={uiT('{provider} 回复模型', { provider: providerLabel })}>
            {modelOptions.map(option => {
              const selected = option.id === aiConfig?.model;
              return (
                <button
                  key={option.id}
                  type="button"
                  className={`ai-model-option${selected ? ' is-selected' : ''}`}
                  role="radio"
                  aria-checked={selected}
                  disabled={Boolean(modelSaving)}
                  onClick={() => changeModel(option.id)}
                >
                  <span className="ai-model-option-copy">
                    <strong>{option.label}</strong>
                    <small>{uiT(option.description)}</small>
                  </span>
                  {option.recommended && <span className="settings-local-badge">{uiT('推荐')}</span>}
                  <span className="ai-model-radio" aria-hidden="true">{modelSaving === option.id ? '…' : selected ? '✓' : ''}</span>
                </button>
              );
            })}
          </div>
          <p className="ai-model-note">{uiT('只显示数恋已验证并允许使用的角色模型；服务商返回的其他模型不会自动切换或出现在这里。')}</p>
        </section>

        {editing ? (
          <form className="ai-service-editor" onSubmit={replaceKey}>
            <h2>{uiT('切换账号')}</h2>
            <p>{uiT('输入另一个 {provider} API Key；验证成功后才切换，失败时当前账号仍可继续使用。', { provider: providerLabel })}</p>
            <div className="account-field ai-service-key-field">
              <label className="account-field-label" htmlFor="ai-service-key-input"><strong>{uiT('新账号的 API Key')}</strong></label>
              <span className="ai-service-key-wrap">
                <input id="ai-service-key-input" className="account-input" type={visible ? 'text' : 'password'} value={apiKey} autoFocus autoComplete="off" spellCheck="false" placeholder={uiT('输入 API Key')} disabled={saving} onChange={event => { setApiKey(event.target.value); setFeedback(''); setIsError(false); }} />
                <button type="button" onClick={() => setVisible(value => !value)} disabled={saving} aria-label={uiT(visible ? '隐藏 API Key' : '显示 API Key')}>{uiT(visible ? '隐藏' : '显示')}</button>
              </span>
            </div>
            <div className="ai-service-editor-actions">
              <button type="button" className="account-button account-button-secondary" disabled={saving} onClick={() => { setEditing(false); setApiKey(''); setFeedback(''); setIsError(false); }}>{uiT('取消')}</button>
              <button type="submit" className="account-button account-button-primary" disabled={saving || !apiKey.trim()}>{uiT(saving ? '正在验证…' : '验证并切换')}</button>
            </div>
          </form>
        ) : (
          <div className="ai-service-actions">
            <button type="button" className="account-button account-button-secondary" onClick={() => { setEditing(true); setFeedback(''); setIsError(false); }}>{uiT('切换账号')}</button>
            <button type="button" className="account-button account-button-danger" disabled={removing} onClick={logoutKey}>{uiT(removing ? '正在退出…' : '退出登录')}</button>
            {aiConfig?.remembered === true && <button type="button" className="account-button account-button-secondary" disabled={removing} onClick={forgetKey}>{uiT(removing ? '正在清除…' : '清除已保存 Key')}</button>}
          </div>
        )}

        <p className={`ai-service-feedback${isError ? ' is-error' : ''}`} role={isError ? 'alert' : 'status'} aria-live="polite">{feedback}</p>
        <p className="settings-privacy-note">{uiT('API Key 不会写入浏览器存储、聊天记录或数恋备份。退出登录只断开当前会话；已保存的密钥会在下次启动时自动连接。需要彻底删除时，请使用“清除已保存 Key”。')}</p>
      </div>
    </AccountPanelShell>
  );
}

function diagnosticDuration(summary, name) {
  const value = Number(summary?.[name]?.latest_ms);
  if (!Number.isFinite(value)) return '—';
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)} 秒`;
  return `${Math.round(value)} ms`;
}

function diagnosticUptime(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value < 60) return `${Math.round(value)} 秒`;
  if (value < 3600) return `${Math.floor(value / 60)} 分钟`;
  return `${Math.floor(value / 3600)} 小时 ${Math.floor((value % 3600) / 60)} 分钟`;
}

function SettingsScreen({ onBack, onClearData, aiConfig, onOpenAiService, onArchiveRoleLibrary, maintenance }) {
  const [settings, setSettings] = useState(loadAccountSettings);
  const [activeSection, setActiveSection] = useState('general');
  const [settingsError, setSettingsError] = useState('');
  const [archivingRoles, setArchivingRoles] = useState(false);
  const [archiveFeedback, setArchiveFeedback] = useState('');
  const [archiveError, setArchiveError] = useState(false);
  const { diagnostics, diagnosticsLoading, diagnosticsExporting, diagnosticsFeedback, diagnosticsError, metricSummary, refreshDiagnostics, exportDiagnostics } = useDiagnosticsPanel();
  const [uninstallOpen, setUninstallOpen] = useState(false);
  const [uninstallText, setUninstallText] = useState('');
  const [removeUserData, setRemoveUserData] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);
  const [maintenanceFeedback, setMaintenanceFeedback] = useState('');
  const [maintenanceError, setMaintenanceError] = useState(false);
  // 数据量统计只在进入设置页或诊断刷新完成后重算：原来每次渲染（含卸载确认框
  // 每敲一个字符）都会整份解析 sl_threads / sl_sessions，白白卡主线程。
  const summary = useMemo(() => readLocalDataSummary(), [activeSection, diagnosticsLoading]);
  const updateStatus = maintenance?.status || {};
  const updateJob = maintenance?.job || null;
  const updateActive = ACTIVE_UPDATE_STATUSES.has(updateJob?.status);
  const updatePercent = Math.max(0, Math.min(100, Number(updateJob?.percent) || 0));

  useEffect(() => {
    document.documentElement.dataset.reduceMotion = settings.reduceMotion ? 'true' : 'false';
  }, [settings.reduceMotion]);

  useEffect(() => {
    document.documentElement.dataset.performanceMode = settings.performanceMode !== false ? 'true' : 'false';
  }, [settings.performanceMode]);


  const saveSettings = (next) => {
    try {
      localStorage.setItem('sl_settings', JSON.stringify(next));
      setSettings(next);
      setSettingsError('');
      return true;
    } catch (e) {
      setSettingsError(uiT('设置未保存，请检查本机存储空间后重试。'));
      return false;
    }
  };
  const flip = (key) => saveSettings({ ...settings, [key]: !settings[key] });
  const setThemeMode = (themeMode) => {
    const next = { ...settings, themeMode: normalizeThemeMode(themeMode) };
    if (saveSettings(next) && typeof window.applyShulianTheme === 'function') {
      window.applyShulianTheme(next.themeMode);
    }
  };
  const setLanguage = (language) => {
    const next = { ...settings, language: normalizeUiLanguage(language) };
    if (saveSettings(next)) window.applyShulianLanguage?.(next.language);
  };

  const exportBackup = exportShulianBackup;
  const restoreBackup = restoreShulianBackup;

  const archiveRoles = async () => {
    if (!onArchiveRoleLibrary || archivingRoles) return;
    setArchivingRoles(true);
    setArchiveFeedback('');
    setArchiveError(false);
    try {
      const result = await onArchiveRoleLibrary();
      setArchiveFeedback(`已建立 ${result.roles} 个角色档案快照，共保存 ${result.messages} 条消息。旧快照仍然保留。`);
    } catch (error) {
      const completed = Array.isArray(error?.completed) ? error.completed.length : 0;
      setArchiveError(true);
      setArchiveFeedback(`${error?.message || '角色档案建立失败'}${completed ? `；失败前已完成 ${completed} 个角色，已有快照未被删除。` : ''}`);
    } finally {
      setArchivingRoles(false);
    }
  };

  const settingsSections = [
    { id: 'general', label: uiT('常规'), Icon: I.settings },
    { id: 'data', label: uiT('数据与角色'), Icon: I.diary },
    { id: 'diagnostics', label: uiT('诊断与关于'), Icon: I.info },
    { id: 'maintenance', label: uiT('更新与卸载'), Icon: I.save },
    { id: 'privacy', label: uiT('隐私与重置'), Icon: I.save },
  ];

  return (
    <AccountPanelShell title={uiT('设置')} onBack={onBack} variant="settings">
      <div className="settings-workspace">
        <aside className="settings-index">
          <nav aria-label={uiT('设置分类')}>
            {settingsSections.map(({ id, label, Icon }) => (
              <button key={id} type="button" className={activeSection === id ? 'is-active' : ''}
                aria-current={activeSection === id ? 'page' : undefined} onClick={() => setActiveSection(id)}>
                <Icon size={18} />
                <span><strong>{label}</strong></span>
              </button>
            ))}
          </nav>
        </aside>

        <div className="account-panel-form settings-content">
          {activeSection === 'general' && <SettingsGeneralSection aiConfig={aiConfig} onOpenAiService={onOpenAiService} settings={settings} setThemeMode={setThemeMode} setLanguage={setLanguage} flip={flip} settingsError={settingsError} />}

          {activeSection === 'data' && <SettingsDataSection summary={summary} exportBackup={exportBackup} restoreBackup={restoreBackup} archiveRoles={archiveRoles} archivingRoles={archivingRoles} archiveFeedback={archiveFeedback} archiveError={archiveError} />}

          {activeSection === 'diagnostics' && <SettingsDiagnosticsSection diagnostics={diagnostics} diagnosticsLoading={diagnosticsLoading} diagnosticsExporting={diagnosticsExporting} diagnosticsFeedback={diagnosticsFeedback} diagnosticsError={diagnosticsError} metricSummary={metricSummary} refreshDiagnostics={refreshDiagnostics} exportDiagnostics={exportDiagnostics} />}

          {activeSection === 'maintenance' && <SettingsMaintenanceSection updateActive={updateActive} updateJob={updateJob} updateStatus={updateStatus} updatePercent={updatePercent} maintenance={maintenance} maintenanceFeedback={maintenanceFeedback} maintenanceError={maintenanceError} setMaintenanceFeedback={setMaintenanceFeedback} setMaintenanceError={setMaintenanceError} uninstallOpen={uninstallOpen} setUninstallOpen={setUninstallOpen} removeUserData={removeUserData} setRemoveUserData={setRemoveUserData} uninstallText={uninstallText} setUninstallText={setUninstallText} uninstalling={uninstalling} setUninstalling={setUninstalling} />}

          {activeSection === 'privacy' && <SettingsPrivacySection onClearData={onClearData} />}
        </div>
      </div>
    </AccountPanelShell>
  );
}

// ── 设置页拆分单元 ─────────────────────────────────────────────
// SettingsScreen 原本近 500 行；下列 hook、模块级动作与分区组件都在同一段落内，
// 由 SettingsScreen 组合调用。放在此处是为了让整页结构保持在一处可读。

// 诊断面板：状态、埋点与导出都自成一体，与设置项互不依赖。
function useDiagnosticsPanel() {
  const [diagnostics, setDiagnostics] = useState(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(true);
  const [diagnosticsExporting, setDiagnosticsExporting] = useState(false);
  const [diagnosticsFeedback, setDiagnosticsFeedback] = useState('');
  const [diagnosticsError, setDiagnosticsError] = useState(false);

  const refreshDiagnostics = async () => {
    setDiagnosticsLoading(true);
    setDiagnosticsFeedback('');
    setDiagnosticsError(false);
    try {
      const response = await fetch('/api/diagnostics', { cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.error?.message || payload?.detail || '无法读取诊断信息');
      }
      setDiagnostics(payload);
    } catch (error) {
      setDiagnosticsError(true);
      setDiagnosticsFeedback(error?.message || '无法读取诊断信息，请确认本机服务仍在运行。');
    } finally {
      setDiagnosticsLoading(false);
    }
  };

  useEffect(() => {
    const openedAt = performance.now();
    refreshDiagnostics();
    fetch('/api/diagnostics/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: 'ui.diagnostics_open',
        duration_ms: Math.max(0, performance.now() - openedAt),
        ok: true,
      }),
    }).catch(() => {});
  }, []);

  const exportDiagnostics = async () => {
    if (diagnosticsExporting) return;
    setDiagnosticsExporting(true);
    setDiagnosticsFeedback('');
    setDiagnosticsError(false);
    try {
      const response = await fetch('/api/diagnostics/export', { cache: 'no-store' });
      if (!response.ok) {
        let payload = {};
        try { payload = await response.json(); } catch (e) { /* keep fallback */ }
        throw new Error(payload?.error?.message || payload?.detail || '诊断包生成失败');
      }
      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition') || '';
      const match = disposition.match(/filename="?([^";]+)"?/i);
      const filename = match?.[1] || 'shulian-diagnostics.zip';
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      }, 200);
      await refreshDiagnostics();
      setDiagnosticsFeedback('诊断包已导出。它不包含聊天、记忆、角色图片或 API Key。');
    } catch (error) {
      setDiagnosticsError(true);
      setDiagnosticsFeedback(error?.message || '诊断包导出失败，请稍后重试。');
    } finally {
      setDiagnosticsExporting(false);
    }
  };

  const metricSummary = diagnostics?.metrics?.summary || {};

  return { diagnostics, diagnosticsLoading, diagnosticsExporting, diagnosticsFeedback,
    diagnosticsError, metricSummary, refreshDiagnostics, exportDiagnostics };
}

// 备份与恢复只依赖本机存储接口，不需要组件状态，因此留在模块层。
async function exportShulianBackup() {
    try {
      await window.shulianStorageFlush();
      const response = await fetch('/api/state/export', { cache: 'no-store' });
      if (!response.ok) throw new Error('SQLite 备份导出失败');
      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition') || '';
      const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
      const url = URL.createObjectURL(blob);
      const date = new Date();
      const pad = value => String(value).padStart(2, '0');
      const link = document.createElement('a');
      link.href = url;
      link.download = filenameMatch?.[1]
        || `数恋备份-${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}.json`;
      document.body.appendChild(link);
      link.click();
      setTimeout(() => { document.body.removeChild(link); URL.revokeObjectURL(url); }, 200);
    } catch (e) {
      try {
        const data = readShulianStorage();
        const payload = { _app: 'shulian', _ver: 2, _at: Date.now(), _storage: { engine: 'local-cache-fallback' }, data };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `数恋备份-本机缓存-${Date.now()}.json`;
        document.body.appendChild(link);
        link.click();
        setTimeout(() => { document.body.removeChild(link); URL.revokeObjectURL(url); }, 200);
      } catch (fallbackError) {
        alert('导出失败：' + ((fallbackError && fallbackError.message) || fallbackError));
      }
    }
  };

function restoreShulianBackup() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json,.json';
    input.onchange = () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const parsed = JSON.parse(reader.result);
          if (parsed?._app && parsed._app !== 'shulian') throw new Error('这不是数恋备份文件');
          const data = parsed && parsed.data ? parsed.data : parsed;
          if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('文件格式不对');
          const keys = Object.keys(data).filter(key => key.startsWith('sl_'));
          if (!keys.length) throw new Error('文件里没找到数恋的数据');
          const replacement = {};
          keys.forEach(key => {
            if (typeof data[key] !== 'string') throw new Error(`备份项 ${key} 已损坏`);
            replacement[key] = data[key];
          });
          if (!confirm(`将用备份中的 ${keys.length} 项数据完整替换当前数恋记录。此操作会刷新页面，继续？`)) return;

          const previous = readShulianStorage();
          try {
            await window.shulianReplacePersistentState(replacement);
            const written = readShulianStorage();
            const exact = Object.keys(written).length === keys.length
              && keys.every(key => written[key] === replacement[key]);
            if (!exact) throw new Error('写入后的数据校验未通过');
          } catch (restoreError) {
            try {
              await window.shulianReplacePersistentState(previous);
            } catch (rollbackError) {
              throw new Error(`恢复失败，且原数据回滚未完成：${restoreError.message || restoreError}`);
            }
            throw new Error(`恢复失败，已还原原数据：${restoreError.message || restoreError}`);
          }

          alert(`已恢复 ${keys.length} 项数恋数据，点确定后刷新。`);
          location.reload();
        } catch (e) { alert('恢复失败：' + ((e && e.message) || e)); }
      };
      reader.readAsText(file);
    };
    input.click();
  };

function SettingsGeneralSection({ aiConfig, onOpenAiService, settings, setThemeMode, setLanguage, flip, settingsError }) {
  return <>
    <section className="account-panel-section" aria-labelledby="settings-ai-title">
      <h2 id="settings-ai-title" className="account-section-title">{uiT('AI 服务')}</h2>
      <div className="settings-card">
        <AccountSettingRow
          icon={I.sparkle}
          title={aiConfig?.provider_label || uiT('AI 服务')}
          sub={aiKeyDisplay(aiConfig)}
          entry="ai-service"
          onClick={onOpenAiService}
          last
          right={<span className="settings-row-action"><span className="ai-service-dot" aria-hidden="true" />{uiT('已连接')}<I.chevR size={17} /></span>}
        />
      </div>
    </section>

    <section className="account-panel-section" aria-labelledby="settings-appearance-title">
      <h2 id="settings-appearance-title" className="account-section-title">{uiT('外观')}</h2>
      <div className="settings-card">
        <AccountSettingRow
          icon={I.language}
          title={uiT('界面语言')}
          sub={uiT('只更改应用界面，不影响角色设定和聊天内容')}
          className="settings-language-row"
          right={(
            <div className="settings-theme-options settings-language-options" role="radiogroup" aria-label={uiT('界面语言')}>
              {[
                ['zh-CN', '简体中文'],
                ['en', 'English'],
              ].map(([value, label]) => (
                <button key={value} type="button" role="radio" aria-checked={settings.language === value}
                  className={`settings-theme-option${settings.language === value ? ' is-selected' : ''}`}
                  onClick={() => setLanguage(value)}>{uiT(label)}</button>
              ))}
            </div>
          )}
        />
        <AccountSettingRow
          icon={I.moon}
          title={uiT('主题颜色')}
          sub={uiT('选择浅色、深色或跟随系统')}
          className="settings-theme-row"
          last
          right={(
            <div className="settings-theme-options" role="radiogroup" aria-label={uiT('主题颜色')}>
              {[
                ['light', '浅色'],
                ['dark', '深色'],
                ['system', '跟随系统'],
              ].map(([value, label]) => (
                <button key={value} type="button" role="radio" aria-checked={settings.themeMode === value}
                  className={`settings-theme-option${settings.themeMode === value ? ' is-selected' : ''}`}
                  onClick={() => setThemeMode(value)}>{uiT(label)}</button>
              ))}
            </div>
          )}
        />
      </div>
    </section>

    <section className="account-panel-section" aria-labelledby="settings-companion-title">
      <h2 id="settings-companion-title" className="account-section-title">{uiT('陪伴体验')}</h2>
      <div className="settings-card">
        <AccountSettingRow icon={I.chat} title={uiT('主动消息')} sub={uiT('允许当前恋人偶尔主动发来消息')} right={<SettingsSwitch on={settings.nudge !== false} label={uiT('主动消息')} onClick={() => flip('nudge')} />} />
        <AccountSettingRow icon={I.sparkle} title={uiT('性能模式')} sub={uiT('降低玻璃模糊，并在后台暂停氛围动效')} right={<SettingsSwitch on={settings.performanceMode !== false} label={uiT('性能模式')} onClick={() => flip('performanceMode')} />} />
        <AccountSettingRow icon={I.sparkle} title={uiT('减少动态效果')} sub={uiT('关闭大部分转场和装饰动画')} last right={<SettingsSwitch on={settings.reduceMotion === true} label={uiT('减少动态效果')} onClick={() => flip('reduceMotion')} />} />
      </div>
      {settingsError && <p className="settings-inline-error" role="alert">{settingsError}</p>}
    </section>

  </>;
}

function SettingsDataSection({ summary, exportBackup, restoreBackup, archiveRoles, archivingRoles, archiveFeedback, archiveError }) {
  return <>
    <section className="account-panel-section" aria-labelledby="settings-data-title">
      <h2 id="settings-data-title" className="account-section-title">{uiT('本机数据')}</h2>
      <div className="settings-data-card">
        <div className="settings-data-head">
          <span className="settings-row-icon"><I.diary size={18} /></span>
          <div><strong>{uiT('保存在当前设备')}</strong><span>{uiT('聊天、记忆和关系数据不会自动同步到其他设备。')}</span></div>
        </div>
        <div className="settings-data-grid" role="list" aria-label={uiT('本机数据概览')}>
          {[[summary.msgCount, '当前消息'], [summary.sessCount, '历史会话'], [summary.memCount, '记忆角色']].map(([value, label]) => (
            <div key={label} role="listitem"><strong>{value}</strong><span>{uiT(label)}</span></div>
          ))}
        </div>
      </div>
      <div className="settings-action-row">
        <button type="button" className="account-button account-button-secondary" onClick={exportBackup}>{uiT('导出备份')}</button>
        <button type="button" className="account-button account-button-secondary" onClick={restoreBackup}>{uiT('恢复备份')}</button>
        <button type="button" className="account-button account-button-secondary" onClick={archiveRoles} disabled={archivingRoles}>{uiT(archivingRoles ? '正在建立档案…' : '建立角色档案库')}</button>
      </div>
      {archiveFeedback && <p className={archiveError ? 'settings-inline-error' : 'settings-help'} role={archiveError ? 'alert' : 'status'} aria-live="polite">{archiveFeedback}</p>}
    </section>

  </>;
}

function SettingsDiagnosticsSection({ diagnostics, diagnosticsLoading, diagnosticsExporting, diagnosticsFeedback, diagnosticsError, metricSummary, refreshDiagnostics, exportDiagnostics }) {
  return <>
    <section className="account-panel-section" aria-labelledby="settings-diagnostics-title">
      <h2 id="settings-diagnostics-title" className="account-section-title">{uiT('诊断与支持')}</h2>
      <div className="settings-data-card diagnostics-card" aria-busy={diagnosticsLoading}>
        <div className="settings-data-head">
          <span className="settings-row-icon"><I.info size={18} /></span>
          <div>
            <strong>{uiT(diagnosticsLoading ? '正在检查数恋运行状态…' : diagnostics?.health?.ok ? '本机服务运行正常' : '有项目需要检查')}</strong>
            <span>
              {diagnostics
                ? `${diagnostics.build_id} · 已运行 ${diagnosticUptime(diagnostics.runtime?.uptime_seconds)}`
                : uiT('诊断信息只保存在本机。')}
            </span>
          </div>
          {diagnostics && (
            <span className={`diagnostics-status${diagnostics.health?.ok ? ' is-ok' : ' is-warning'}`}>
              {uiT(diagnostics.health?.ok ? '正常' : '检查')}
            </span>
          )}
        </div>
        <div className="settings-data-grid diagnostics-metrics" role="list" aria-label={uiT('运行性能')}>
          {[
            [diagnosticDuration(metricSummary, 'startup.frontend_ready'), '界面就绪'],
            [diagnosticDuration(metricSummary, 'ai.first_token'), '回复就绪'],
            [diagnosticDuration(metricSummary, 'tts.synthesis'), '语音生成'],
          ].map(([value, label]) => (
            <div key={label} role="listitem"><strong>{value}</strong><span>{uiT(label)}</span></div>
          ))}
        </div>
      </div>
      <div className="settings-action-row">
        <button type="button" className="account-button account-button-secondary" onClick={refreshDiagnostics} disabled={diagnosticsLoading}>
          {uiT(diagnosticsLoading ? '正在刷新…' : '刷新状态')}
        </button>
        <button type="button" className="account-button account-button-primary" onClick={exportDiagnostics} disabled={diagnosticsExporting}>
          {uiT(diagnosticsExporting ? '正在生成…' : '导出诊断包')}
        </button>
      </div>
      {diagnosticsFeedback && <p className={diagnosticsError ? 'settings-inline-error' : 'settings-help'} role={diagnosticsError ? 'alert' : 'status'} aria-live="polite">{diagnosticsFeedback}</p>}
      {(diagnostics?.api_cache?.models || []).map(row => (
        <p className="settings-help" key={`${row.provider}/${row.model}`}>
          {row.model}：{row.hit_ratio == null ? '暂无缓存用量数据' : `输入命中率 ${(row.hit_ratio * 100).toFixed(1)}%`}
          {` · 已统计 ${row.measured_requests}/${row.requests} 次请求`}
        </p>
      ))}
    </section>

    <section className="account-panel-section" aria-labelledby="settings-about-title">
      <h2 id="settings-about-title" className="account-section-title">{uiT('关于')}</h2>
      <div className="settings-card">
        <AccountSettingRow icon={I.info} title={`${currentUiLanguage() === 'en' ? 'Shulian' : '数恋'} v${SHULIAN_APP_VERSION}`} sub={uiT('本地优先的数字恋人体验')} last right={<span className="settings-local-badge">{uiT('本机')}</span>} />
      </div>
    </section>

  </>;
}

function SettingsMaintenanceSection({ updateActive, updateJob, updateStatus, updatePercent, maintenance, maintenanceFeedback, maintenanceError, setMaintenanceFeedback, setMaintenanceError, uninstallOpen, setUninstallOpen, removeUserData, setRemoveUserData, uninstallText, setUninstallText, uninstalling, setUninstalling }) {
  const uninstallConfirmationText = currentUiLanguage() === 'en' ? 'Uninstall Shulian' : '卸载数恋';
  const sourceUpdates = updateStatus.updateMode === 'source' || updateStatus.packagerReady === true;
  return <>
    <section className="account-panel-section" aria-labelledby="settings-update-title">
      <h2 id="settings-update-title" className="account-section-title">{uiT('软件更新')}</h2>
      {!sourceUpdates ? <PublicDownloadUpdate status={updateStatus} maintenance={maintenance} /> : <>
      <div className="settings-data-card maintenance-card" aria-busy={updateActive || maintenance?.loading}>
        <div className="settings-data-head">
          <span className="settings-row-icon"><I.save size={18} /></span>
          <div>
            <strong>{updateActive
              ? updateJob.message || uiT('正在后台更新数恋…')
              : updateStatus.updateAvailable
                ? uiT('发现数恋 v{version}', { version: updateStatus.sourceVersion })
                : updateStatus.reason || uiT('点击检查本机源码版本')}</strong>
            <span>{updateStatus.sourceChanged
              ? uiT('已检测到正式版源码与当前客户端存在差异。')
              : uiT('从已配置的本机源码构建并更新。')}</span>
          </div>
          <span className={`diagnostics-status${updateStatus.updateAvailable ? ' is-warning' : ' is-ok'}`}>
            {updateActive ? `${updatePercent}%` : uiT(updateStatus.updateAvailable ? '可更新' : '本机')}
          </span>
        </div>
        <div className="settings-data-grid maintenance-version-grid" role="list" aria-label={uiT('版本比较')}>
          <div role="listitem"><strong>{updateStatus.clientVersion || SHULIAN_APP_VERSION}</strong><span>{uiT('当前客户端')}</span></div>
          <div role="listitem"><strong>{updateStatus.sourceVersion || '—'}</strong><span>{uiT('正式版源码')}</span></div>
        </div>
        {(updateActive || updateJob?.status === 'failed') && (
          <div className="maintenance-progress-wrap">
            <div className="maintenance-progress" role="progressbar" aria-label={uiT('后台更新进度')}
              aria-valuemin="0" aria-valuemax="100" aria-valuenow={updatePercent}>
              <span style={{ width: `${updatePercent}%` }} />
            </div>
            <span>{updateJob?.status === 'failed' ? updateJob.message : `${updatePercent}%`}</span>
          </div>
        )}
      </div>
      <div className="settings-action-row">
        <button type="button" className="account-button account-button-secondary" onClick={maintenance?.refresh}
          disabled={maintenance?.loading || updateActive}>{uiT(maintenance?.loading ? '正在检查…' : '检查更新')}</button>
        <button type="button" className="account-button account-button-primary" onClick={async () => {
          setMaintenanceFeedback(''); setMaintenanceError(false);
          const result = await maintenance?.startUpdate();
          if (result?.ok) setMaintenanceFeedback(uiT('后台更新已经开始，可以在此查看进度。'));
          else if (!result?.cancelled) { setMaintenanceError(true); setMaintenanceFeedback(result?.message || uiT('无法启动后台更新。')); }
        }} disabled={!updateStatus.updateAvailable || updateActive}>{uiT('后台更新到 v{version}', { version: updateStatus.sourceVersion || '—' })}</button>
      </div>
      </>}
      {maintenance?.error && <p className="settings-inline-error" role="alert">{uiT(maintenance.error)}</p>}
      {maintenanceFeedback && <p className={maintenanceError ? 'settings-inline-error' : 'settings-help'}
        role={maintenanceError ? 'alert' : 'status'} aria-live="polite">{maintenanceFeedback}</p>}
    </section>

    <section className="danger-zone maintenance-uninstall" aria-labelledby="settings-uninstall-title">
      <div>
        <h2 id="settings-uninstall-title">{uiT('卸载数恋')}</h2>
        <p>{uiT('由外部卸载助手在数恋退出后移除程序文件。默认保留聊天、记忆、媒体和 API 配置。')}</p>
      </div>
      <button type="button" className="account-button account-button-danger" onClick={() => setUninstallOpen(open => !open)}>
        {uiT(uninstallOpen ? '取消卸载' : '卸载程序')}
      </button>
    </section>
    {uninstallOpen && (
      <div className="settings-data-card uninstall-confirm-card">
        <label className="uninstall-data-choice">
          <input type="checkbox" checked={removeUserData} onChange={event => setRemoveUserData(event.target.checked)} />
          <span><strong>{uiT('同时删除全部本机数据')}</strong><small>{uiT('包括聊天、记忆、角色档案、媒体、日志和本机配置；默认不勾选。')}</small></span>
        </label>
        <label className="uninstall-confirm-field">
          <span>{uiT('输入“{text}”确认', { text: uninstallConfirmationText })}</span>
          <input value={uninstallText} onChange={event => setUninstallText(event.target.value)} placeholder={uninstallConfirmationText} />
        </label>
        <button type="button" className="account-button account-button-danger" disabled={uninstalling || uninstallText !== uninstallConfirmationText}
          onClick={async () => {
            setUninstalling(true); setMaintenanceFeedback(''); setMaintenanceError(false);
            const result = await maintenance?.uninstall(removeUserData, '卸载数恋');
            if (!result?.ok) {
              setUninstalling(false); setMaintenanceError(true);
              setMaintenanceFeedback(result?.message || uiT('无法启动卸载助手。'));
            } else setMaintenanceFeedback(uiT('卸载助手已启动，数恋即将关闭。'));
          }}>{uiT(uninstalling ? '正在启动卸载助手…' : removeUserData ? '卸载并删除全部数据' : '卸载并保留我的数据')}</button>
      </div>
    )}
  </>;
}

function SettingsPrivacySection({ onClearData }) {
  return <>
    <section className="account-panel-section" aria-labelledby="settings-privacy-title">
      <h2 id="settings-privacy-title" className="account-section-title">{uiT('数据传输')}</h2>
      <div className="settings-data-card settings-privacy-card">
        <div className="settings-data-head">
          <span className="settings-row-icon"><I.save size={18} /></span>
          <div>
            <strong>{uiT('本机保存，按需发送')}</strong>
            <span>{uiT('聊天、记忆和关系数据保存在当前设备；生成回复和整理记忆时，相关对话会发送给你配置的 AI 服务。')}</span>
          </div>
        </div>
      </div>
    </section>

    <section className="danger-zone" aria-labelledby="settings-danger-title">
      <div>
        <h2 id="settings-danger-title">{uiT('清除本机数据')}</h2>
        <p>{uiT('会删除对话、记忆、亲密度、关系约定和个人资料，且无法恢复。')}</p>
      </div>
      <button type="button" className="account-button account-button-danger" onClick={onClearData}>{uiT('清除所有数据')}</button>
    </section>

      <p className="settings-privacy-note">{uiT('API Key 不进入聊天记录或数恋备份。')}</p>
  </>;
}

function PublicDownloadUpdate({ status, maintenance }) {
  return <>
    <div className="settings-data-card maintenance-card" aria-busy={maintenance?.loading}>
      <strong>{uiT('当前版本 v{version}', { version: status.clientVersion || SHULIAN_APP_VERSION })}</strong>
      <p className="settings-help">{uiT(maintenance?.loading ? '正在读取版本信息…' : status.publicReleaseReady ? '前往公开下载页查看版本说明并下载完整程序包。' : '公开测试版正在准备，下载页尚未开放。')}</p>
      <p className="settings-help">{uiT('本页不会自动下载或安装，也尚未检查线上是否有新版本。')}</p>
    </div>
    <div className="settings-action-row">
      <button type="button" className="account-button account-button-primary" onClick={maintenance?.openDownloads}
        disabled={!status.publicReleaseReady || maintenance?.loading}>{uiT(status.publicReleaseReady ? '打开公开下载页' : '下载页尚未开放')}</button>
      <button type="button" className="account-button account-button-secondary" onClick={maintenance?.refresh}
        disabled={maintenance?.loading}>{uiT('刷新版本信息')}</button>
    </div>
    <div className="settings-data-card">
      <strong>{uiT('更新与数据保留')}</strong>
      <ol className="settings-help">
        <li>{uiT('完全退出数恋后，备份原程序目录和 %LOCALAPPDATA%\\Shulian；自定义的数据目录也要备份。')}</li>
        <li>{uiT('下载完整 ZIP 并解压到新目录，不要只复制 EXE。将原目录中的 webview-data、media、local-data 和 .env（如有）复制到新目录同名位置。')}</li>
        <li>{uiT('在同一 Windows 用户下运行新版，确认角色、聊天和设置正常后再处理旧目录。不要先卸载或清除数据。')}</li>
      </ol>
      <p className="settings-help">{uiT('完整备份可能包含聊天和凭据，请仅保存在自己的安全位置，不要上传到 GitHub 或问题反馈中。')}</p>
    </div>
  </>;
}

function MePanel({ kind, onBack, onBackToSettings, onOpenAiService, aiConfig, onAiConfigChange, onAiModelChange, onAiRemoved, onAiLoggedOut, onArchiveRoleLibrary, onClearData, userProfile, onSaveProfile, onProfileDirtyChange, maintenance }) {
  if (kind === 'profile') return <ProfileScreen onBack={onBack} userProfile={userProfile} onSaveProfile={onSaveProfile} onDirtyChange={onProfileDirtyChange} />;
  if (kind === 'settings') return <SettingsScreen onBack={onBack} onClearData={onClearData} aiConfig={aiConfig} onOpenAiService={onOpenAiService} onArchiveRoleLibrary={onArchiveRoleLibrary} maintenance={maintenance} />;
  if (kind === 'ai-service') return <AiServiceScreen onBack={onBackToSettings} aiConfig={aiConfig} onChangeApiKey={onAiConfigChange} onChangeModel={onAiModelChange} onRemoveApiKey={onAiLoggedOut} onForgetApiKey={onAiRemoved} />;
  return null;
}

// ══════════════════ 通知面板 ══════════════════
function NotifPanel({ notifications, onOpenChat, onClose, onMarkAll, onClearAll }) {
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ paddingTop: 50, flexShrink: 0 }}>
        <Glass radius={0} variant="glass-strong" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none', borderTop: 'none', display: 'flex', alignItems: 'center', gap: 11, padding: '9px 14px 11px' }}>
          <button type="button" onClick={onClose} aria-label={uiT('关闭通知')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--ink)', display: 'grid', placeItems: 'center', width: 32, height: 32 }}><I.back size={24} /></button>
          <div style={{ flex: 1, fontSize: 17, fontWeight: 700, color: 'var(--ink)' }}>{uiT('通知')}</div>
          {notifications.some(n => !n.read) && (
            <button type="button" onClick={onMarkAll} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, color: 'var(--accent)', padding: '4px 8px' }}>{uiT('全部已读')}</button>
          )}
          {notifications.length > 0 && (
            <button type="button" onClick={onClearAll} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, color: 'var(--ink-faint)', padding: '4px 8px' }}>{uiT('清空')}</button>
          )}
        </Glass>
      </div>

      <div className="no-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
        {notifications.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--ink-faint)', fontSize: 14 }}>{uiT('暂无通知')}</div>
        ) : notifications.map(n => {
          const c = byId(n.charId);
          if (!c) return null;
          return (
            <button key={n.id} type="button" onClick={() => onOpenChat(n.charId)}
              style={{ display: 'block', width: '100%', textAlign: 'left', background: 'none', border: 'none', padding: '0 0 10px', cursor: 'pointer' }}>
              <Glass radius={20} style={{ padding: '13px 15px', borderColor: !n.read ? 'color-mix(in oklch, var(--accent) 35%, rgba(255,255,255,0.12))' : undefined }}>
                <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                  <Avatar c={c} size={44} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                      <span style={{ fontSize: 14.5, fontWeight: 600, color: 'var(--ink)' }}>{c.name}</span>
                      <span style={{ fontSize: 11.5, color: 'var(--ink-faint)', flexShrink: 0 }}>{fmtTime(n.ts)}</span>
                    </div>
                    <div style={{ fontSize: 14, color: 'var(--ink)', lineHeight: 1.55 }}>{n.text}</div>
                  </div>
                  {!n.read && <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)', flexShrink: 0, marginTop: 5 }} />}
                </div>
              </Glass>
            </button>
          );
        })}
      </div>
    </div>
  );
}

Object.assign(window, { Avatar, UserAvatar, HeroMedia, HeroGallery, HomeScreen, GalleryScreen, LoverArchiveScreen, MessagesScreen, CharacterProfilePanel, MeScreen, Scroll, Eyebrow, NotifPanel, MePanel });
