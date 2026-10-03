// glass.jsx — 液态玻璃设计系统：图标 / 玻璃原件 / 占位立绘 / 手机外壳 / Tab
// 共享到 window 供其它 babel 脚本使用

// ───────────────── 线性图标（简单 UI 图标，非插画）─────────────────
const Icon = ({ d, size = 24, sw = 1.8, fill = 'none', stroke = 'currentColor', style }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={stroke}
       strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={style}>
    {Array.isArray(d) ? d.map((p, i) => <path key={i} d={p} />) : <path d={d} />}
  </svg>
);
const BrandIcon = ({ size = 32, style = {} }) => (
  <img
    src="shulian-brand-icon.png?v=2026-09-20-i18n-v25-22"
    alt=""
    aria-hidden="true"
    draggable="false"
    width={size}
    height={size}
    style={{ display: 'block', flexShrink: 0, ...style }}
  />
);
const I = {
  home:  (p) => <Icon {...p} d={["M3.2 11.3 12 4l8.8 7.3","M5.2 9.8V19a1 1 0 0 0 1 1H10v-5h4v5h3.8a1 1 0 0 0 1-1V9.8"]} />,
  heart: (p) => <Icon {...p} d="M12 20.5C5.5 16.3 3 12.9 3 9.4 3 6.9 5 5 7.4 5c1.6 0 3 .8 3.9 2.1.9-1.3 2.3-2.1 3.9-2.1C18.6 5 20.6 6.9 20.6 9.4c0 3.5-2.5 6.9-9 11.1Z" />,
  chat:  (p) => <Icon {...p} d="M4 5.5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-4.2 3.4A.5.5 0 0 1 4 19.5V6.5a1 1 0 0 1 1-1Z" />,
  user:  (p) => <Icon {...p} d={["M12 12.2a3.6 3.6 0 1 0 0-7.2 3.6 3.6 0 0 0 0 7.2Z","M5 20c.7-3.4 3.5-5.4 7-5.4s6.3 2 7 5.4"]} />,
  phone: (p) => <Icon {...p} d="M6.5 4.5 9 5l1 3.2-1.8 1.4a11 11 0 0 0 5.2 5.2L15.8 13l3.2 1 .5 2.5c.1.7-.4 1.4-1.1 1.5C11.8 19.2 4.8 12.2 5 6.1c0-.7.7-1.3 1.5-1.6Z" />,
  phoneOff:(p)=> <Icon {...p} d={["M6.5 4.5 9 5l1 3.2-1.8 1.4a11 11 0 0 0 5.2 5.2L15.8 13l3.2 1 .5 2.5c.1.7-.4 1.4-1.1 1.5C11.8 19.2 4.8 12.2 5 6.1c0-.7.7-1.3 1.5-1.6Z"]} />,
  mic:   (p) => <Icon {...p} d={["M12 14.5a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5.5a3 3 0 0 0 3 3Z","M6 11a6 6 0 0 0 12 0","M12 17.5V21"]} />,
  micOff:(p) => <Icon {...p} d={["M9 6a3 3 0 0 1 6 0v4","M6 11a6 6 0 0 0 9.2 5.1","M4 4l16 16","M12 17.5V21"]} />,
  send:  (p) => <Icon {...p} fill="currentColor" stroke="none" d="M4.4 11.2 19 4.6c.7-.3 1.4.4 1.1 1.1l-6.6 14.6c-.3.7-1.3.6-1.5-.1l-1.7-5.5-5.5-1.7c-.7-.2-.8-1.2-.1-1.5Z" />,
  plus:  (p) => <Icon {...p} d={["M12 5v14","M5 12h14"]} />,
  gift:  (p) => <Icon {...p} d={["M4 11h16v8a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-8Z","M3 8h18v3H3z","M12 8v12","M12 8C9 8 7.5 4 9.5 4S12 6.5 12 8Zm0 0c3 0 4.5-4 2.5-4S12 6.5 12 8Z"]} />,
  sparkle:(p) => <Icon {...p} d="M12 3.5l1.7 4.6 4.6 1.7-4.6 1.7L12 16.1l-1.7-4.6L5.7 9.8l4.6-1.7L12 3.5Z" />,
  eye:   (p) => <Icon {...p} d={["M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z","M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"]} />,
  eyeOff:(p) => <Icon {...p} d={["M3 3l18 18","M10.6 6.2A9.8 9.8 0 0 1 12 6c6 0 9.5 6 9.5 6a15.7 15.7 0 0 1-2.6 3.2","M6.1 6.7C3.8 8.5 2.5 12 2.5 12s3.5 6 9.5 6a9.8 9.8 0 0 0 2.2-.2","M9.9 9.9a3 3 0 0 0 4.2 4.2"]} />,
  speaker:(p)=> <Icon {...p} d={["M4 9v6h3.5L13 19V5L7.5 9H4Z","M16.5 9a4 4 0 0 1 0 6","M19 7a7 7 0 0 1 0 10"]} />,
  video: (p) => <Icon {...p} d={["M4 7h10a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1Z","M15 11l5-3v8l-5-3"]} />,
  grid:  (p) => <Icon {...p} d={["M4 4h7v7H4z","M13 4h7v7h-7z","M4 13h7v7H4z","M13 13h7v7h-7z"]} />,
  search:(p) => <Icon {...p} d={["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z","M16.5 16.5 21 21"]} />,
  back:  (p) => <Icon {...p} d="M15 5l-7 7 7 7" />,
  chevR: (p) => <Icon {...p} d="M9 5l7 7-7 7" />,
  panelLeft:(p) => <Icon {...p} d={["M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z","M10 4v16"]} />,
  language:(p) => <Icon {...p} d={["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z","M3.5 9h17","M3.5 15h17","M12 3c2.2 2.5 3.3 5.5 3.3 9S14.2 18.5 12 21M12 3C9.8 5.5 8.7 8.5 8.7 12s1.1 6.5 3.3 9"]} />,
  windowMinimize:(p) => <Icon {...p} d="M5 12h14" />,
  windowMaximize:(p) => <Icon {...p} d="M5 5h14v14H5z" />,
  windowRestore:(p) => <Icon {...p} d={["M8 8h11v11H8z","M5 16V5h11"]} />,
  windowClose:(p) => <Icon {...p} d={["M5 5l14 14","M19 5 5 19"]} />,
  bell:  (p) => <Icon {...p} d={["M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z","M10 20a2 2 0 0 0 4 0"]} />,
  moon:  (p) => <Icon {...p} d="M20 13.5A8 8 0 1 1 10.5 4 6.5 6.5 0 0 0 20 13.5Z" />,
  flame: (p) => <Icon {...p} fill="currentColor" stroke="none" d="M12 2.5c2.5 3 1 5 .2 6 1.6-.4 2.3-2 2.3-2 2 2.4 2.5 4.6 2.5 6a5 5 0 1 1-10 0c0-2 1-3.6 2.2-4.6-.2 1.2.3 2 .3 2C10.7 8.4 9.5 6 12 2.5Z" />,
  diary: (p) => <Icon {...p} d={["M6 4h12a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z","M9 4v17","M12 9h4","M12 13h4"]} />,
  camera:(p) => <Icon {...p} d={["M4 8h3l1.4-2h7.2L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z","M12 16.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"]} />,
  edit:  (p) => <Icon {...p} d={["M4 20h4l11-11-4-4L4 16v4Z","m13.5 6.5 4 4"]} />,
  info:  (p) => <Icon {...p} d={["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z","M12 10v6","M12 7h.01"]} />,
  settings:(p) => <Icon {...p} d={["M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z","M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.86 2.86-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1.1 1.57V21H9.86v-.03A1.7 1.7 0 0 0 8.76 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.86-2.86.06-.06A1.7 1.7 0 0 0 4.36 15a1.7 1.7 0 0 0-1.57-1.1H2.7V9.86h.09A1.7 1.7 0 0 0 4.36 8.76a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.86-2.86.06.06a1.7 1.7 0 0 0 1.88.34A1.7 1.7 0 0 0 9.86 2.8V2.7h4.04v.1A1.7 1.7 0 0 0 15 4.36a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.86 2.86-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.57 1.1h.03v4.04h-.03A1.7 1.7 0 0 0 19.4 15Z"]} />,
  save:  (p) => <Icon {...p} d={["M5 4h12l3 3v13H4V5a1 1 0 0 1 1-1Z","M8 4v6h8V4","M8 20v-6h8v6"]} />,
  brain: (p) => <Icon {...p} d={["M12 4C8 4 5 7 5 10.5c0 2.4 1.5 4.5 3.5 5.5V18a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1v-2c2-1 3.5-3.1 3.5-5.5C19 7 16 4 12 4Z","M9.5 21h5","M12 4v15"]} />,
  image: (p) => <Icon {...p} d={["M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z","M3 16l5-5 4 4 3-3 5 5","M15.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z"]} />,
  smile: (p) => <Icon {...p} d={["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z","M8.5 14s1.5 2 3.5 2 3.5-2 3.5-2","M9 9.5h.01","M15 9.5h.01"]} />,
};

// ───────────────── 占位立绘（条纹 + 等宽标注，不手绘人物）─────────────────
function ArtPlaceholder({ label = '角色立绘', dim = '1024×1536', hue = 320, style = {}, rounded = 22, faceTop = false, src = null, pos = '50% 30%', imgFit = 'cover' }) {
  // 真实图片模式
  if (src) {
    return (
      <div style={{ position: 'relative', overflow: 'hidden', borderRadius: rounded, width: '100%', height: '100%', background: `linear-gradient(150deg, oklch(0.30 0.08 ${hue}), oklch(0.20 0.06 ${hue + 20}))`, ...style }}>
        <img src={src} alt={label} draggable="false" loading="lazy" decoding="async" style={{ width: '100%', height: '100%', objectFit: imgFit, objectPosition: pos, display: 'block' }} />
      </div>
    );
  }
  const c1 = `oklch(0.62 0.14 ${hue})`;
  const c2 = `oklch(0.50 0.13 ${hue + 30})`;
  return (
    <div style={{
      position: 'relative', overflow: 'hidden', borderRadius: rounded,
      width: '100%', height: '100%',
      background: `linear-gradient(150deg, ${c1}, ${c2})`,
      ...style,
    }}>
      {/* diagonal stripes */}
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: 'repeating-linear-gradient(135deg, rgba(255,255,255,0.10) 0 2px, transparent 2px 16px)',
      }} />
      {/* soft head-glow to suggest a portrait subject */}
      <div style={{
        position: 'absolute', left: '50%', top: faceTop ? '26%' : '40%',
        width: '52%', aspectRatio: '1', transform: 'translate(-50%,-50%)',
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(255,255,255,0.30), transparent 70%)',
      }} />
      {/* label chip */}
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0,
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
        padding: '10px 8px',
        background: 'linear-gradient(0deg, rgba(0,0,0,0.42), transparent)',
      }}>
        <span style={{
          fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: 0.4,
          color: 'rgba(255,255,255,0.92)',
          padding: '3px 8px', borderRadius: 7,
          border: '1px dashed rgba(255,255,255,0.5)',
          background: 'rgba(255,255,255,0.10)', whiteSpace: 'nowrap',
        }}>{label}</span>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 8.5, color: 'rgba(255,255,255,0.6)' }}>{dim}</span>
      </div>
    </div>
  );
}

// ───────────────── 玻璃容器 ─────────────────
function Glass({ as: Component = 'div', children, radius = 22, variant = '', className = '', style = {}, onClick, ...rest }) {
  return (
    <Component onClick={onClick} className={`glass ${variant} ${className}`}
      style={{ borderRadius: radius, ...style }} {...rest}>
      {children}
    </Component>
  );
}

// ───────────────── 状态栏（深色）─────────────────
function StatusBar() {
  return (
    <div style={{
      position: 'absolute', top: 0, left: 0, right: 0, height: 54, zIndex: 40,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 30px', pointerEvents: 'none',
    }}>
      <span style={{ fontSize: 16, fontWeight: 600, color: '#fff', letterSpacing: 0.2, paddingTop: 6 }}>9:41</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingTop: 6 }}>
        <svg width="18" height="11" viewBox="0 0 18 11"><g fill="#fff">
          <rect x="0" y="6.5" width="3" height="4.5" rx="0.6"/><rect x="4.5" y="4.5" width="3" height="6.5" rx="0.6"/>
          <rect x="9" y="2.3" width="3" height="8.7" rx="0.6"/><rect x="13.5" y="0" width="3" height="11" rx="0.6"/>
        </g></svg>
        <svg width="16" height="11" viewBox="0 0 16 11" fill="#fff"><path d="M8 3c1.9 0 3.6.7 4.9 1.9l1-1A8 8 0 0 0 8 1.6 8 8 0 0 0 2.1 3.9l1 1A7 7 0 0 1 8 3Z"/><path d="M8 6.2c1 0 2 .4 2.7 1.1l1-1A6 6 0 0 0 8 4.6a6 6 0 0 0-3.7 1.7l1 1A4 4 0 0 1 8 6.2Z"/><circle cx="8" cy="9.2" r="1.4"/></svg>
        <svg width="25" height="12" viewBox="0 0 25 12"><rect x="0.5" y="0.5" width="21" height="11" rx="3" stroke="#fff" strokeOpacity="0.4" fill="none"/><rect x="2" y="2" width="18" height="8" rx="1.8" fill="#fff"/><path d="M23 4v4c.8-.3 1.3-1 1.3-2S23.8 4.3 23 4Z" fill="#fff" fillOpacity="0.5"/></svg>
      </div>
    </div>
  );
}

// ───────────────── 响应式布局容器 ─────────────────
// 移动端（<769px）：底部 TabBar，内容铺满
// 桌面端（≥769px）：左侧 Sidebar，内容区占满剩余宽度

const DESKTOP_LAYOUT_MIN_WIDTH = 769;
const DESKTOP_LAYOUT_MEDIA_QUERY = `(min-width: ${DESKTOP_LAYOUT_MIN_WIDTH}px)`;

// 桌面壳、消息双栏和角色色注入必须共享同一个宽度快照。
// WebView2 原生 resize/maximize 并不保证只靠 matchMedia.change 就能收到更新，
// 因此统一监听所有可靠信号，并用 ResizeObserver 兜住原生窗口尺寸变化。
const desktopLayoutStore = (() => {
  const listeners = new Set();
  let stopListening = null;
  let animationFrame = 0;

  const read = () => window.innerWidth >= DESKTOP_LAYOUT_MIN_WIDTH;
  const emit = () => listeners.forEach(listener => listener());
  const schedule = () => {
    window.cancelAnimationFrame(animationFrame);
    animationFrame = window.requestAnimationFrame(emit);
  };

  const startListening = () => {
    const media = window.matchMedia(DESKTOP_LAYOUT_MEDIA_QUERY);
    const visualViewport = window.visualViewport;
    const resizeObserver = typeof ResizeObserver === 'function'
      ? new ResizeObserver(schedule)
      : null;
    const delayedChecks = [100, 300, 1000].map(delay => window.setTimeout(schedule, delay));

    if (media.addEventListener) media.addEventListener('change', schedule);
    else media.addListener?.(schedule);
    window.addEventListener('resize', schedule);
    window.addEventListener('orientationchange', schedule);
    window.addEventListener('pageshow', schedule);
    document.addEventListener('visibilitychange', schedule);
    visualViewport?.addEventListener('resize', schedule);
    resizeObserver?.observe(document.documentElement);
    schedule();

    return () => {
      delayedChecks.forEach(timer => window.clearTimeout(timer));
      window.cancelAnimationFrame(animationFrame);
      if (media.removeEventListener) media.removeEventListener('change', schedule);
      else media.removeListener?.(schedule);
      window.removeEventListener('resize', schedule);
      window.removeEventListener('orientationchange', schedule);
      window.removeEventListener('pageshow', schedule);
      document.removeEventListener('visibilitychange', schedule);
      visualViewport?.removeEventListener('resize', schedule);
      resizeObserver?.disconnect();
    };
  };

  return {
    getSnapshot: read,
    subscribe(listener) {
      listeners.add(listener);
      if (listeners.size === 1) stopListening = startListening();
      schedule();
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0 && stopListening) {
          stopListening();
          stopListening = null;
        }
      };
    },
  };
})();

function useWideLayout() {
  return React.useSyncExternalStore(
    desktopLayoutStore.subscribe,
    desktopLayoutStore.getSnapshot,
    desktopLayoutStore.getSnapshot,
  );
}

function UserProfileAvatar({ profile, size = 42 }) {
  return (
    <span className="desktop-user-avatar" style={{
      width: size, height: size, borderRadius: '50%', flexShrink: 0, overflow: 'hidden',
      display: 'grid', placeItems: 'center', color: '#fff',
      background: 'linear-gradient(145deg, oklch(0.70 0.17 230), oklch(0.52 0.16 264))',
      boxShadow: '0 0 0 1px rgba(255,255,255,.16)',
    }}>
      {profile?.avatarImg ? (
        <img src={profile.avatarImg} alt="我的头像" draggable="false" loading="lazy" decoding="async" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
      ) : (
        <I.user size={Math.max(16, Math.round(size * .46))} sw={2} />
      )}
    </span>
  );
}

function SideBar({ active, onTab, onOpenAccount, onOpenSettings, userProfile }) {
  const [collapsed, setCollapsed] = React.useState(() => {
    try { return localStorage.getItem('sl_sidebar_collapsed') === '1'; }
    catch (e) { return false; }
  });
  const [accountMenuOpen, setAccountMenuOpen] = React.useState(false);
  const collapsedAccountRef = React.useRef(null);
  React.useEffect(() => {
    try { localStorage.setItem('sl_sidebar_collapsed', collapsed ? '1' : '0'); }
    catch (e) { /* 本地存储不可用时仅保留当前会话状态 */ }
  }, [collapsed]);
  React.useEffect(() => {
    if (!collapsed || !accountMenuOpen) return undefined;
    const onPointerDown = (event) => {
      if (!collapsedAccountRef.current?.contains(event.target)) setAccountMenuOpen(false);
    };
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setAccountMenuOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [collapsed, accountMenuOpen]);
  const tabs = [
    { id: 'home',     label: uiT('今日'), icon: I.home },
    { id: 'gallery',  label: uiT('恋人'), icon: I.heart },
    { id: 'messages', label: uiT('消息'), icon: I.chat },
  ];
  const openAccount = () => {
    setAccountMenuOpen(false);
    onOpenAccount?.();
  };
  const openSettings = () => {
    setAccountMenuOpen(false);
    onOpenSettings?.();
  };
  return (
    <div className={`desktop-sidebar${collapsed ? ' is-collapsed' : ''}`} style={{
      width: collapsed ? 56 : 196, flexShrink: 0, height: '100%', display: 'flex', flexDirection: 'column',
      background: 'var(--sidebar-background, #090a0d)', borderRight: '1px solid var(--sidebar-border, #25262c)',
      position: 'relative', zIndex: 20, transition: 'width .28s cubic-bezier(.2,.75,.25,1)',
    }}>
      {/* 展开时显示品牌；收起时保留原有侧栏开关。 */}
      <div className="desktop-sidebar-head" style={{
        minHeight: 64, padding: collapsed ? '13px 10px 10px' : '14px 10px 10px 12px', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'space-between', gap: 8,
      }}>
        {!collapsed && (
          <div className="desktop-sidebar-brand" aria-label={uiT('数恋')}>
            <BrandIcon size={30} />
            <span>{uiT('数恋')}</span>
          </div>
        )}
        <button type="button" onClick={() => {
          setAccountMenuOpen(false);
          setCollapsed(value => !value);
        }} className="desktop-sidebar-toggle"
          aria-label={uiT(collapsed ? '展开侧边栏' : '收起侧边栏')} aria-expanded={!collapsed} title={uiT(collapsed ? '展开侧边栏' : '收起侧边栏')}
          style={{ width: 34, height: 34, flexShrink: 0, display: 'grid', placeItems: 'center', borderRadius: 8, border: 'none', cursor: 'pointer', color: 'var(--ink-soft)', background: 'transparent', zIndex: 2 }}>
          <I.panelLeft size={19} sw={1.8} />
        </button>
      </div>

      {/* 导航项 */}
      <nav style={{ flex: 1, padding: collapsed ? '4px 10px 0' : '4px 10px 0' }}>
        {tabs.map(t => {
          const on = active === t.id;
          return (
            <button key={t.id} onClick={() => onTab(t.id)} className="desktop-nav-button" title={collapsed ? t.label : undefined} aria-label={collapsed ? t.label : undefined} aria-current={on ? 'page' : undefined} style={{
              width: '100%', display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'flex-start', gap: collapsed ? 0 : 13,
              padding: collapsed ? '9px 0' : '10px 12px', borderRadius: collapsed ? 8 : 10, border: '1px solid transparent', cursor: 'pointer', marginBottom: 4,
              background: on
                ? (collapsed
                  ? 'color-mix(in oklch, var(--accent) 18%, var(--surface-secondary))'
                  : 'color-mix(in oklch, var(--accent) 13%, var(--surface-secondary))')
                : 'transparent',
              color: on ? 'var(--ink)' : 'var(--ink-soft)',
              transition: 'background .2s, color .2s',
              boxShadow: on && !collapsed ? 'inset 3px 0 0 var(--accent)' : 'none',
            }}>
              <t.icon size={21} sw={on ? 2.1 : 1.8} style={{ flexShrink: 0 }} />
              {!collapsed && <span style={{ fontSize: 14.5, fontWeight: on ? 650 : 520 }}>{t.label}</span>}
            </button>
          );
        })}
      </nav>

      {/* 展开态为同排双入口；收起态由头像弹层承载资料与设置。 */}
      <div className="desktop-account-entry" style={{ padding: collapsed ? '0 10px 14px' : '0 10px 16px' }}>
        {collapsed ? (
          <div ref={collapsedAccountRef} className="desktop-sidebar-collapsed-profile">
            <button type="button" onClick={() => setAccountMenuOpen(value => !value)} className="desktop-sidebar-profile is-collapsed-trigger"
              data-account-entry="profile-menu" aria-label={uiT('打开账户菜单')} title={uiT('账户')}
              aria-haspopup="menu" aria-expanded={accountMenuOpen}>
              <UserProfileAvatar profile={userProfile} size={34} />
            </button>
            {accountMenuOpen && (
              <div className="desktop-account-menu" role="menu" aria-label={uiT('账户菜单')}>
                <button type="button" role="menuitem" onClick={openAccount} data-account-entry="profile">
                  <I.user size={18} />
                  <span>{uiT('个人资料')}</span>
                </button>
                <button type="button" role="menuitem" onClick={openSettings} data-account-entry="settings">
                  <I.settings size={18} />
                  <span>{uiT('设置')}</span>
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="desktop-account-dock">
            <button type="button" onClick={openAccount} className="desktop-sidebar-profile desktop-profile-summary"
              data-account-entry="profile" aria-label={uiT('打开个人资料')} title={uiT('个人资料')}>
              <UserProfileAvatar profile={userProfile} size={36} />
              <span className="desktop-profile-copy">
                <strong>{userProfile?.name || '你'}</strong>
                <small>{uiT('个人资料')}</small>
              </span>
            </button>
            <span className="desktop-account-divider" aria-hidden="true" />
            <button type="button" onClick={openSettings} className="desktop-settings-button is-dock-button"
              data-account-entry="settings" aria-label={uiT('打开设置')} title={uiT('设置')}>
              <I.settings size={19} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

const Aurora = () => (
  <div className="ambient-background" style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }}>
    <div style={{ position: 'absolute', top: '-8%', left: '-6%', width: '70%', paddingTop: '70%', borderRadius: '50%',
      background: 'radial-gradient(circle, rgba(48,56,76,0.72), transparent 68%)',
      filter: 'blur(30px)', animation: 'auroraA 14s ease-in-out infinite', animationPlayState: 'var(--aurora-play, running)' }} />
    <div style={{ position: 'absolute', top: '20%', right: '-10%', width: '65%', paddingTop: '65%', borderRadius: '50%',
      background: 'radial-gradient(circle, rgba(46,40,60,0.68), transparent 68%)',
      filter: 'blur(32px)', animation: 'auroraB 17s ease-in-out infinite', animationPlayState: 'var(--aurora-play, running)' }} />
    <div style={{ position: 'absolute', bottom: '-8%', left: '8%', width: '65%', paddingTop: '65%', borderRadius: '50%',
      background: 'radial-gradient(circle, rgba(52,45,58,0.58), transparent 70%)',
      filter: 'blur(36px)', animation: 'auroraA 19s ease-in-out infinite', animationPlayState: 'var(--aurora-play, running)' }} />
    <div style={{ position: 'absolute', inset: 0, opacity: 0.45,
      backgroundImage: 'radial-gradient(1px 1px at 8% 5%, rgba(255,255,255,.5), transparent), radial-gradient(1px 1px at 30% 22%, rgba(255,255,255,.4), transparent), radial-gradient(1px 1px at 62% 14%, rgba(255,255,255,.45), transparent), radial-gradient(1px 1px at 80% 45%, rgba(255,255,255,.35), transparent), radial-gradient(1px 1px at 20% 60%, rgba(255,255,255,.4), transparent), radial-gradient(1px 1px at 90% 73%, rgba(255,255,255,.3), transparent), radial-gradient(1px 1px at 45% 82%, rgba(255,255,255,.4), transparent)' }} />
  </div>
);

function Phone({ children, bottomBar = true, activeTab, onTab, onOpenAccount, onOpenSettings, userProfile }) {
  const wide = useWideLayout();

  // ── 桌面端：左侧 Sidebar + 右侧内容区 ──
  if (wide) {
    return (
      <div style={{ display: 'flex', width: '100%', height: '100%', position: 'relative', overflow: 'hidden',
        background: 'var(--app-background)' }}>
        <Aurora />
        <SideBar active={activeTab} onTab={onTab} onOpenAccount={onOpenAccount} onOpenSettings={onOpenSettings} userProfile={userProfile} />
        {/* 内容区：填满剩余宽度 */}
        <div style={{ flex: 1, position: 'relative', overflow: 'hidden', zIndex: 5, minWidth: 0 }}>
          {children}
        </div>
      </div>
    );
  }

  // ── 移动端：全屏 + 底部 TabBar ──
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', overflow: 'hidden',
      background: 'var(--app-background)' }}>
      <Aurora />
      <div style={{ position: 'absolute', inset: 0, zIndex: 5 }}>{children}</div>
      {bottomBar && (
        <TabBar
          active={activeTab}
          onTab={onTab}
          onOpenAccount={onOpenAccount}
          onOpenSettings={onOpenSettings}
          userProfile={userProfile}
        />
      )}
    </div>
  );
}

// ───────────────── 悬浮液态玻璃 Tab ─────────────────
function TabBar({ active, onTab, onOpenAccount, onOpenSettings, userProfile }) {
  const [accountMenuOpen, setAccountMenuOpen] = React.useState(false);
  const mobileAccountRef = React.useRef(null);
  const mobileAccountTriggerRef = React.useRef(null);
  React.useEffect(() => {
    if (!accountMenuOpen) return undefined;
    const onPointerDown = (event) => {
      if (!mobileAccountRef.current?.contains(event.target)) setAccountMenuOpen(false);
    };
    const onKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      setAccountMenuOpen(false);
      mobileAccountTriggerRef.current?.focus();
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [accountMenuOpen]);
  const openAccount = () => {
    setAccountMenuOpen(false);
    onOpenAccount?.();
  };
  const openSettings = () => {
    setAccountMenuOpen(false);
    onOpenSettings?.();
  };
  const tabs = [
    { id: 'home',    label: uiT('今日'), icon: I.home },
    { id: 'gallery', label: uiT('恋人'), icon: I.heart },
    { id: 'messages',label: uiT('消息'), icon: I.chat },
  ];
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, bottom: 26, display: 'flex', justifyContent: 'center', zIndex: 55 }}>
      <Glass radius={30} variant="glass-strong" className="mobile-tabbar" style={{ display: 'flex', gap: 4, padding: 6 }}>
        {tabs.map(t => {
          const on = active === t.id;
          return (
            <button key={t.id} onClick={() => {
              setAccountMenuOpen(false);
              onTab(t.id);
            }} style={{
              border: 'none', cursor: 'pointer', background: 'transparent',
              width: 74, height: 52, borderRadius: 24, position: 'relative',
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 3,
              color: on ? '#fff' : 'var(--ink-faint)', transition: 'color .25s',
            }}>
              {on && <div className="glass" style={{ position: 'absolute', inset: 0, borderRadius: 24,
                background: 'linear-gradient(150deg, color-mix(in oklch, var(--accent) 70%, transparent), color-mix(in oklch, var(--accent-2) 55%, transparent))',
                boxShadow: '0 6px 18px color-mix(in oklch, var(--accent) 40%, transparent), inset 0 1px 0 rgba(255,255,255,0.5)', border: 'none' }} />}
              <t.icon size={22} sw={on ? 2.1 : 1.8} style={{ position: 'relative', zIndex: 1 }} />
              <span style={{ position: 'relative', zIndex: 1, fontSize: 10.5, fontWeight: on ? 600 : 500 }}>{t.label}</span>
            </button>
          );
        })}
        <span className="mobile-account-divider" aria-hidden="true" />
        <div ref={mobileAccountRef} className="mobile-account-entry">
          <button ref={mobileAccountTriggerRef} type="button"
            onClick={() => setAccountMenuOpen(value => !value)}
            className="mobile-account-trigger" data-account-entry="profile-menu"
            aria-label={uiT('打开账户菜单')} title={uiT('账户')} aria-haspopup="menu" aria-expanded={accountMenuOpen}>
            <UserProfileAvatar profile={userProfile} size={34} />
          </button>
          {accountMenuOpen && (
            <div className="desktop-account-menu mobile-account-menu" role="menu" aria-label={uiT('账户菜单')}>
              <button type="button" role="menuitem" onClick={openAccount} data-account-entry="profile">
                <I.user size={18} />
                <span>{uiT('个人资料')}</span>
              </button>
              <button type="button" role="menuitem" onClick={openSettings} data-account-entry="settings">
                <I.settings size={18} />
                <span>{uiT('设置')}</span>
              </button>
            </div>
          )}
        </div>
      </Glass>
    </div>
  );
}

Object.assign(window, { Icon, BrandIcon, I, ArtPlaceholder, Glass, StatusBar, Phone, TabBar });
