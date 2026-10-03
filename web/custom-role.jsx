// Application-owned custom roles. These helpers deliberately keep imported data
// in the editor until the user reviews and saves it.
const CUSTOM_ROLE_API = '/api/role-library/roles';
const CUSTOM_ROLE_MAX_CHAT_BYTES = 8 * 1024 * 1024;
const CUSTOM_ROLE_MAX_IMAGE_BYTES = 10 * 1024 * 1024;

function customRoleEmptyProfile() {
  return {
    name: '', en: '', persona: '', profileIntro: '', personality: '',
    speakingStyle: '', relationship: '', relationshipLevel: 0, greet: '', mood: '', tags: [],
    cat: '自建', img: '', face: '', imgPos: '50% 50%', facePos: '50% 50%',
  };
}

function customRoleProfileForSave(profile) {
  const defaults = customRoleEmptyProfile();
  return {
    ...defaults,
    name: String(profile.name || '').trim(),
    en: String(profile.en || '').trim(),
    persona: String(profile.persona || '').trim(),
    profileIntro: String(profile.profileIntro || '').trim(),
    personality: String(profile.personality || '').trim(),
    speakingStyle: String(profile.speakingStyle || '').trim(),
    relationship: String(profile.relationship || '').trim(),
    relationshipLevel: Number(profile.relationshipLevel || 0),
    greet: String(profile.greet || '').trim(),
    mood: String(profile.mood || '').trim(),
    tags: Array.isArray(profile.tags) ? profile.tags.filter(Boolean).slice(0, 12) : [],
    img: String(profile.img || ''), face: String(profile.face || ''),
    imgPos: String(profile.imgPos || defaults.imgPos), facePos: String(profile.facePos || defaults.facePos),
  };
}

async function customRoleRequest(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { cache: 'no-store', ...options });
  } catch (_) {
    throw new Error('无法连接本机角色服务，请稍后重试。');
  }
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* HTTP error still has a useful fallback */ }
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === 'string' ? detail : `角色操作失败（${response.status}）`);
  }
  return payload || {};
}

function customRoleCsvRows(source) {
  const rows = [];
  let row = [], field = '', quoted = false;
  const text = String(source || '').replace(/^\uFEFF/, '');
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { field += '"'; i++; }
      else quoted = !quoted;
    } else if (char === ',' && !quoted) {
      row.push(field); field = '';
    } else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.some(value => value.trim())) rows.push(row);
      row = [];
    } else {
      field += char;
    }
  }
  if (quoted) throw new Error('CSV 引号没有闭合，请检查文件格式。');
  row.push(field);
  if (row.some(value => value.trim())) rows.push(row);
  return rows;
}

function customRoleRawMessage(row) {
  if (!row || typeof row !== 'object') return null;
  const speaker = String(row.from ?? row.sender ?? row.speaker ?? row.role ?? row.发送者 ?? row.角色 ?? '').trim();
  const rawText = row.text ?? row.content ?? row.message ?? row.内容 ?? row.消息;
  if (typeof rawText !== 'string') return null;
  const text = rawText.trim();
  if (!speaker || !text) return null;
  return { speaker, text, ts: row.ts ?? row.timestamp ?? row.time ?? row.时间 ?? null };
}

function customRoleParseChatText(source, filename = '') {
  const isCsv = /\.csv$/i.test(filename);
  let sessions;
  if (isCsv) {
    const rows = customRoleCsvRows(source);
    if (rows.length < 2) throw new Error('CSV 至少需要表头和一条消息。');
    const keys = rows[0].map(value => value.trim().replace(/^\uFEFF/, ''));
    sessions = [{ messages: rows.slice(1).map(values => Object.fromEntries(keys.map((key, i) => [key, values[i] || '']))) }];
  } else {
    let parsed;
    try { parsed = JSON.parse(String(source || '').replace(/^\uFEFF/, '')); }
    catch (_) { throw new Error('聊天 JSON 格式不正确。'); }
    if (Array.isArray(parsed)) sessions = [{ messages: parsed }];
    else if (Array.isArray(parsed?.sessions)) sessions = parsed.sessions;
    else if (Array.isArray(parsed?.archived_sessions)) sessions = parsed.archived_sessions;
    else if (Array.isArray(parsed?.messages)) sessions = [parsed];
    else throw new Error('JSON 需要 messages、sessions 或 archived_sessions。');
  }
  if (sessions.length > 500) throw new Error('最多支持 500 段会话。');
  if (sessions.some(session => !Array.isArray(session?.messages)
      || session.messages.some(message => !customRoleRawMessage(message)))) {
    throw new Error('存在缺少发送者或文本内容的消息，请修正文件后重新导入。');
  }
  const normalized = sessions.map(session => ({
    startTs: session?.startTs ?? null,
    endTs: session?.endTs ?? null,
    messages: (Array.isArray(session?.messages) ? session.messages : []).map(customRoleRawMessage).filter(Boolean),
  })).filter(session => session.messages.length);
  const speakers = [...new Set(normalized.flatMap(session => session.messages.map(message => message.speaker)))];
  if (!normalized.length || !speakers.length) throw new Error('没有找到可导入的聊天消息；请检查发送者和内容字段。');
  return { sessions: normalized, speakers, total: normalized.reduce((sum, session) => sum + session.messages.length, 0) };
}

function customRoleGuessSpeakers(speakers) {
  const meAliases = /^(me|user|human|我|用户|自己)$/i;
  const themAliases = /^(them|her|assistant|ai|角色|对方)$/i;
  if (speakers.length === 1 && themAliases.test(speakers[0])) return { me: '', them: speakers[0] };
  const me = speakers.find(value => meAliases.test(value)) || speakers[0] || '';
  const them = speakers.find(value => value !== me && themAliases.test(value)) || speakers.find(value => value !== me) || '';
  return { me, them };
}

function customRoleTimestamp(value) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 0) return Math.round(numeric < 1e11 ? numeric * 1000 : numeric);
  const parsed = Date.parse(String(value));
  return Number.isFinite(parsed) ? parsed : null;
}

function customRoleMapChat(imported, me, them) {
  if (!imported || (!me && !them) || me === them) return { sessions: [], included: 0, skipped: imported?.total || 0, duplicates: 0 };
  let included = 0, skipped = 0, duplicates = 0;
  const sessions = imported.sessions.map(session => {
    const seen = new Set();
    const messages = session.messages.map((message, index) => {
      const from = message.speaker === me ? 'me' : message.speaker === them ? 'them' : null;
      if (!from) { skipped++; return null; }
      const ts = customRoleTimestamp(message.ts);
      const key = `${from}\0${message.text}\0${ts === null ? `row-${index}` : ts}`;
      if (seen.has(key)) { duplicates++; return null; }
      seen.add(key); included++;
      return { from, text: message.text, ...(ts === null ? {} : { ts }), index };
    }).filter(Boolean).sort((a, b) => (a.ts && b.ts ? a.ts - b.ts : 0) || a.index - b.index)
      .map(({ index, ...message }) => message);
    return { startTs: customRoleTimestamp(session.startTs) || messages[0]?.ts || null,
      endTs: customRoleTimestamp(session.endTs) || messages[messages.length - 1]?.ts || null, messages };
  }).filter(session => session.messages.length);
  return { sessions, included, skipped, duplicates };
}

async function customRoleReadChatFile(file) {
  if (!file || file.size > CUSTOM_ROLE_MAX_CHAT_BYTES) throw new Error('聊天文件不能超过 8 MiB。');
  if (!/\.(json|csv)$/i.test(file.name)) throw new Error('请选择 JSON 或 CSV 聊天文件。');
  return customRoleParseChatText(await file.text(), file.name);
}

async function customRoleReadPersonaFile(file) {
  if (!file || file.size > 1024 * 1024) throw new Error('人设文件不能超过 1 MiB。');
  if (!/\.(txt|md|json)$/i.test(file.name)) throw new Error('请选择 TXT、Markdown 或 JSON 人设文件。');
  const source = await file.text();
  if (/\.json$/i.test(file.name)) {
    let parsed;
    try { parsed = JSON.parse(source); } catch (_) { throw new Error('人设 JSON 格式不正确。'); }
    const data = parsed?.profile && typeof parsed.profile === 'object' ? parsed.profile : parsed;
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('人设 JSON 需要角色字段对象。');
    const fields = Object.fromEntries(['name', 'en', 'persona', 'profileIntro', 'personality', 'speakingStyle', 'relationship', 'greet', 'mood']
      .filter(key => typeof data[key] === 'string').map(key => [key, data[key]]));
    if (Array.isArray(data.tags) && data.tags.every(tag => typeof tag === 'string')) fields.tags = data.tags;
    if (Number.isInteger(data.relationshipLevel) && data.relationshipLevel >= 0 && data.relationshipLevel <= 10) {
      fields.relationshipLevel = data.relationshipLevel;
    }
    if (!Object.keys(fields).length) throw new Error('没有找到支持的人设字段。');
    return fields;
  }
  return { profileIntro: source.trim() };
}

async function customRoleCropImage(source, { x, y, zoom }, width, height) {
  const image = new Image();
  image.src = source;
  await image.decode();
  const canvas = document.createElement('canvas');
  canvas.width = width; canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('无法处理图片，请换一张重试。');
  const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight) * zoom;
  const sourceWidth = width / scale, sourceHeight = height / scale;
  const left = Math.max(0, (image.naturalWidth - sourceWidth) * x / 100);
  const top = Math.max(0, (image.naturalHeight - sourceHeight) * y / 100);
  context.fillStyle = '#ffffff'; context.fillRect(0, 0, width, height);
  context.drawImage(image, left, top, sourceWidth, sourceHeight, 0, 0, width, height);
  return canvas.toDataURL('image/jpeg', 0.87);
}

async function customRoleOpenGalleryAfterReload() {
  await window.shulianStorageFlush?.();
  sessionStorage.setItem('sl_open_custom_roles', '1');
  window.location.reload();
}

function CustomRoleField({ label, value, onChange, rows = 0, placeholder = '', required = false, maxLength = 4000 }) {
  return <label className="custom-role-field">
    <span>{uiT(label)}{required && <em aria-hidden="true"> *</em>}</span>
    {rows ? <textarea value={value || ''} onChange={event => onChange(event.target.value)} rows={rows} maxLength={maxLength} placeholder={uiT(placeholder)} />
      : <input value={value || ''} onChange={event => onChange(event.target.value)} maxLength={maxLength} placeholder={uiT(placeholder)} />}
  </label>;
}

function CustomRoleImageField({ label, value, onChange, ratio = 1 }) {
  const [source, setSource] = React.useState('');
  const [crop, setCrop] = React.useState({ x: 50, y: 50, zoom: 1 });
  const [preview, setPreview] = React.useState('');
  const [error, setError] = React.useState('');
  React.useEffect(() => {
    if (!source) return undefined;
    let active = true;
    const width = ratio === 1 ? 512 : 768;
    const height = ratio === 1 ? 512 : 1024;
    customRoleCropImage(source, crop, width, height).then(dataUrl => {
      if (!active) return;
      setPreview(dataUrl);
      onChange(dataUrl);
      setError('');
    }).catch(() => { if (active) setError('图片处理失败，请尝试其他文件。'); });
    return () => { active = false; };
  }, [source, crop.x, crop.y, crop.zoom]);
  React.useEffect(() => () => { if (source.startsWith('blob:')) URL.revokeObjectURL(source); }, [source]);
  const openFile = event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type) || file.size > CUSTOM_ROLE_MAX_IMAGE_BYTES) {
      setError('请选择不超过 10 MiB 的 PNG、JPEG、WebP 或 GIF 图片。');
      return;
    }
    setError(''); setCrop({ x: 50, y: 50, zoom: 1 });
    setSource(URL.createObjectURL(file));
  };
  return <div className="custom-role-image-field">
    <div className="custom-role-image-preview" style={{ aspectRatio: ratio }}>
      {(preview || value) ? <img src={preview || value} alt={`${label}预览`} /> : <span>{uiT('暂无图片')}</span>}
    </div>
    <div className="custom-role-image-actions">
      <strong>{uiT(label)}</strong>
      <label className="custom-role-secondary-button">{uiT('上传图片')}<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={openFile} hidden /></label>
      {value && <button type="button" className="custom-role-text-button" onClick={() => { setPreview(''); setSource(''); onChange(''); }}>{uiT('移除')}</button>}
    </div>
    {source && <div className="custom-role-crop-controls">
      <label>{uiT('左右位置')}<input type="range" min="0" max="100" value={crop.x} onChange={event => setCrop(old => ({ ...old, x: Number(event.target.value) }))} /></label>
      <label>{uiT('上下位置')}<input type="range" min="0" max="100" value={crop.y} onChange={event => setCrop(old => ({ ...old, y: Number(event.target.value) }))} /></label>
      <label>{uiT('放大')}<input type="range" min="1" max="3" step="0.05" value={crop.zoom} onChange={event => setCrop(old => ({ ...old, zoom: Number(event.target.value) }))} /></label>
    </div>}
    {error && <p className="custom-role-error" role="alert">{error}</p>}
  </div>;
}

function CustomRoleStudio({ roleId = null, onClose }) {
  const [profile, setProfile] = React.useState(customRoleEmptyProfile);
  const [tagsText, setTagsText] = React.useState('');
  const [memory, setMemory] = React.useState('');
  const [imported, setImported] = React.useState(null);
  const [meSpeaker, setMeSpeaker] = React.useState('');
  const [themSpeaker, setThemSpeaker] = React.useState('');
  const [chatConfirmed, setChatConfirmed] = React.useState(false);
  const [existingMessages, setExistingMessages] = React.useState(0);
  const [trialText, setTrialText] = React.useState('');
  const [trialHistory, setTrialHistory] = React.useState([]);
  const [trialBusy, setTrialBusy] = React.useState(false);
  const [suggestBusy, setSuggestBusy] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(Boolean(roleId));
  const [error, setError] = React.useState('');
  const [step, setStep] = React.useState('profile');
  const update = (key, value) => setProfile(previous => ({ ...previous, [key]: value }));
  const mapped = React.useMemo(() => customRoleMapChat(imported, meSpeaker, themSpeaker), [imported, meSpeaker, themSpeaker]);

  React.useEffect(() => {
    if (!roleId) return undefined;
    let active = true;
    customRoleRequest(`${CUSTOM_ROLE_API}/${encodeURIComponent(roleId)}?include_history=false`).then(result => {
      if (!active) return;
      const loaded = { ...customRoleEmptyProfile(), ...(result.profile || {}) };
      setProfile(loaded);
      setTagsText(Array.isArray(loaded.tags) ? loaded.tags.join('、') : '');
      setMemory(localStorage.getItem(`sl_memory_${roleId}`) ?? String(result.memory || ''));
      setExistingMessages(Number(result.importedMessageCount || 0));
    }).catch(failure => { if (active) setError(failure.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [roleId]);

  const importChat = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const parsed = await customRoleReadChatFile(file);
      const guessed = customRoleGuessSpeakers(parsed.speakers);
      setImported(parsed); setMeSpeaker(guessed.me); setThemSpeaker(guessed.them);
      setChatConfirmed(false); setError(''); setStep('history');
    } catch (failure) { setError(failure.message); }
  };
  const importPersona = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const fields = await customRoleReadPersonaFile(file);
      setProfile(previous => ({ ...previous, ...fields })); setError('');
      if (fields.tags) setTagsText(fields.tags.join('、'));
    } catch (failure) { setError(failure.message); }
  };
  const importRolePackage = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!/\.zip$/i.test(file.name) || file.size > 32 * 1024 * 1024) { setError('请选择不超过 32 MiB 的角色 ZIP 包。'); return; }
    setBusy(true); setError('');
    try {
      const result = await customRoleRequest('/api/role-library/import/inspect', {
        method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file,
      });
      const loaded = { ...customRoleEmptyProfile(), ...(result.profile || {}) };
      setProfile(loaded); setTagsText(Array.isArray(loaded.tags) ? loaded.tags.join('、') : '');
      setMemory(String(result.memory || ''));
      const sessions = Array.isArray(result.archived_sessions) ? result.archived_sessions : [];
      if (sessions.length) {
        const parsed = customRoleParseChatText(JSON.stringify({ archived_sessions: sessions }), 'role.json');
        const guessed = customRoleGuessSpeakers(parsed.speakers);
        setImported(parsed); setMeSpeaker(guessed.me); setThemSpeaker(guessed.them); setChatConfirmed(false);
      } else setImported(null);
      setStep('profile');
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  const suggestProfile = async () => {
    const sourceText = [profile.profileIntro, profile.persona, profile.personality, profile.speakingStyle, profile.relationship]
      .map(value => String(value || '').trim()).filter(Boolean).join('\n\n');
    if (sourceText.length < 20) { setError('请先填写或导入至少 20 个字的角色资料。'); return; }
    setSuggestBusy(true); setError('');
    try {
      const result = await customRoleRequest('/api/role-library/draft-suggest', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sourceText, name: profile.name || undefined }),
      });
      const allowed = ['name', 'en', 'persona', 'profileIntro', 'personality', 'speakingStyle', 'relationship', 'greet'];
      const suggestions = Object.fromEntries(allowed.filter(key => typeof result.profile?.[key] === 'string' && result.profile[key].trim())
        .map(key => [key, result.profile[key].trim()]));
      setProfile(previous => ({ ...previous, ...suggestions,
        ...(suggestions.relationship ? { relationshipLevel: 0 } : {}),
      }));
      if (Array.isArray(result.profile?.tags)) setTagsText(result.profile.tags.filter(item => typeof item === 'string').join('、'));
    } catch (failure) { setError(failure.message); }
    finally { setSuggestBusy(false); }
  };
  const normalizedProfile = () => customRoleProfileForSave({
    ...profile,
    tags: tagsText.split(/[、,，]/).map(item => item.trim()).filter(Boolean),
  });
  const validate = () => {
    const next = normalizedProfile();
    if (!next.name) throw new Error('请填写角色姓名。');
    if (!next.persona) throw new Error('请填写一句话人设。');
    if (!next.profileIntro && !next.personality && !next.speakingStyle) throw new Error('请填写背景、性格或说话方式。');
    if (imported && ((!meSpeaker && !themSpeaker) || meSpeaker === themSpeaker || !mapped.included)) throw new Error('请核对聊天双方身份，至少导入一条消息。');
    return next;
  };
  const tryChat = async event => {
    event.preventDefault();
    const message = trialText.trim();
    if (!message || trialBusy) return;
    let draft;
    try { draft = validate(); } catch (failure) { setError(failure.message); return; }
    setTrialBusy(true); setError('');
    try {
      const history = trialHistory.slice(-24);
      const result = await customRoleRequest('/api/role-library/preview-chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile: { ...draft, img: '', face: '' }, message, history, memory }),
      });
      const reply = String(result.reply || '').trim();
      if (!reply) throw new Error('试聊没有返回内容，请重试。');
      setTrialHistory([...history, { from: 'me', text: message }, { from: 'them', text: reply }].slice(-24));
      setTrialText('');
    } catch (failure) { setError(failure.message); }
    finally { setTrialBusy(false); }
  };
  const save = async () => {
    if (busy) return;
    let draft;
    try { draft = validate(); } catch (failure) { setError(failure.message); return; }
    if (imported && !chatConfirmed) { setError('请先确认聊天记录中“我”和角色的对应关系。'); setStep('history'); return; }
    setBusy(true); setError('');
    try {
      const body = { profile: draft, memory };
      if (imported) body.archived_sessions = mapped.sessions;
      await window.shulianStorageFlush?.();
      const saved = await customRoleRequest(roleId ? `${CUSTOM_ROLE_API}/${encodeURIComponent(roleId)}` : CUSTOM_ROLE_API, {
        method: roleId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (roleId) localStorage.setItem(`sl_memory_${roleId}`, memory);
      if (roleId) {
        localStorage.setItem(`sl_memory_context_${roleId}`, JSON.stringify(saved.memoryContext));
        localStorage.setItem(`sl_companion_context_${roleId}`, JSON.stringify(saved.companionContext));
        localStorage.setItem(`sl_intimacy_${roleId}`, String(saved.companionContext.relationship.level));
      }
      await customRoleOpenGalleryAfterReload();
    } catch (failure) { setError(failure.message); setBusy(false); }
  };

  if (loading) return <div className="custom-role-shell" role="status">{uiT('正在载入角色…')}</div>;
  return <div className="custom-role-shell">
    <header className="custom-role-header"><div><h1>{uiT(roleId ? '编辑自建角色' : '新建角色')}</h1><p>{uiT('资料只有保存后才会成为正式角色。草稿试聊不会写入聊天或长期记忆。')}</p></div><button type="button" className="custom-role-secondary-button" onClick={onClose}>{uiT('返回画廊')}</button></header>
    <div className="custom-role-tabs" role="tablist" aria-label={uiT('创建步骤')}>
      {[['profile', '人设与图片'], ['history', '聊天记录'], ['trial', '草稿试聊']].map(([key, label]) => <button type="button" role="tab" aria-selected={step === key} className={step === key ? 'is-active' : ''} key={key} onClick={() => setStep(key)}>{uiT(label)}</button>)}
    </div>
    {error && <p className="custom-role-error" role="alert">{error}</p>}
    {step === 'profile' && <div className="custom-role-section">
      {!roleId && <div className="custom-role-imports">
        <label className="custom-role-secondary-button">{uiT('导入角色包')}<input type="file" accept=".zip,application/zip" onChange={importRolePackage} hidden /></label>
        <label className="custom-role-secondary-button">{uiT('导入人设文件')}<input type="file" accept=".txt,.md,.json,text/plain,application/json" onChange={importPersona} hidden /></label>
      </div>}
      <div className="custom-role-assist"><button type="button" className="custom-role-secondary-button" disabled={suggestBusy} onClick={suggestProfile}>{uiT(suggestBusy ? '正在整理…' : 'AI 整理为人设')}</button><span>{uiT('点击后会调用当前配置的聊天模型；结果只填入可编辑草稿。')}</span></div>
      <div className="custom-role-fields">
        <CustomRoleField label="角色姓名" value={profile.name} onChange={value => update('name', value)} required maxLength={80} />
        <CustomRoleField label="英文名或别名" value={profile.en} onChange={value => update('en', value)} maxLength={80} />
        <CustomRoleField label="一句话人设" value={profile.persona} onChange={value => update('persona', value)} required placeholder="例如：温柔而坚定的星际旅人" maxLength={300} />
        <CustomRoleField label="标签" value={tagsText} onChange={setTagsText} placeholder="用逗号分隔" maxLength={300} />
        <CustomRoleField label="背景经历" value={profile.profileIntro} onChange={value => update('profileIntro', value)} rows={4} />
        <CustomRoleField label="性格" value={profile.personality} onChange={value => update('personality', value)} rows={3} />
        <CustomRoleField label="说话方式" value={profile.speakingStyle} onChange={value => update('speakingStyle', value)} rows={3} />
        <CustomRoleField label="初始关系" value={profile.relationship} onChange={value => setProfile(previous => ({ ...previous, relationship: value, relationshipLevel: 0 }))} rows={3} />
        <label className="custom-role-field"><span>{uiT('初始关系阶段')}</span><select value={profile.relationshipLevel || 0} onChange={event => update('relationshipLevel', Number(event.target.value))}>
          <option value={0}>{uiT('根据关系描述匹配')}</option>
          {['初识', '认识', '熟悉', '信赖', '亲近', '心意相通', '关系确认', '深度伴侣', '灵魂伴侣', '终身伴侣'].map((label, index) => <option key={label} value={index + 1}>{uiT(label)}</option>)}
        </select></label>
        <CustomRoleField label="开场白" value={profile.greet} onChange={value => update('greet', value)} rows={2} maxLength={1000} />
        <CustomRoleField label="当前状态" value={profile.mood} onChange={value => update('mood', value)} rows={2} maxLength={1000} />
        <CustomRoleField label="确认的共同记忆" value={memory} onChange={setMemory} rows={3} placeholder="可选；从聊天记录提炼后，由你确认并填写。" maxLength={4000} />
      </div>
      <div className="custom-role-images">
        <CustomRoleImageField label="头像" value={profile.face} onChange={value => update('face', value)} />
        <CustomRoleImageField label="主图" value={profile.img} onChange={value => update('img', value)} ratio={3 / 4} />
      </div>
      <p className="custom-role-hint">{uiT('图片会裁切成预览所示范围；原图不会自动加入角色包。')}</p>
    </div>}
    {step === 'history' && <div className="custom-role-section">
      <h2>{uiT('导入聊天记录')}</h2>
      <p className="custom-role-hint">{uiT('支持 JSON 或 CSV；至少需要发送者与内容字段。导入前请核对双方身份，试聊和正式聊天不会混入导入记录。')}</p>
      <label className="custom-role-secondary-button">{uiT('选择聊天文件')}<input type="file" accept=".json,.csv,application/json,text/csv" onChange={importChat} hidden /></label>
      {roleId && !imported && existingMessages > 0 && <p className="custom-role-hint">{uiT('当前角色已有导入消息')}：{existingMessages} {uiT('条。选择新文件会替换导入档案，不影响正式聊天。')}</p>}
      {imported && <div className="custom-role-import-review">
        <div className="custom-role-fields">
          <label className="custom-role-field"><span>{uiT('哪个发送者是“我”')}</span><select value={meSpeaker} onChange={event => { setMeSpeaker(event.target.value); setChatConfirmed(false); }}><option value="">{uiT('此文件没有该方消息')}</option>{imported.speakers.map(speaker => <option key={speaker} value={speaker}>{speaker}</option>)}</select></label>
          <label className="custom-role-field"><span>{uiT('哪个发送者是角色')}</span><select value={themSpeaker} onChange={event => { setThemSpeaker(event.target.value); setChatConfirmed(false); }}><option value="">{uiT('此文件没有该方消息')}</option>{imported.speakers.map(speaker => <option key={speaker} value={speaker}>{speaker}</option>)}</select></label>
        </div>
        <p className="custom-role-hint">{uiT('识别')} {imported.total} {uiT('条；将导入')} {mapped.included} {uiT('条，跳过其他发送者')} {mapped.skipped} {uiT('条，去重')} {mapped.duplicates} {uiT('条。共')} {mapped.sessions.length} {uiT('段会话。')}</p>
        <div className="custom-role-chat-preview">{mapped.sessions.flatMap(session => session.messages).slice(0, 6).map((message, i) => <div key={i}><strong>{message.from === 'me' ? uiT('我') : (profile.name || uiT('角色'))}</strong><span>{message.text}</span></div>)}</div>
        <label className="custom-role-confirm"><input type="checkbox" checked={chatConfirmed} onChange={event => setChatConfirmed(event.target.checked)} />{uiT('我已核对发送者身份与预览，确认导入这些记录')}</label>
        <button type="button" className="custom-role-text-button" onClick={() => { setImported(null); setChatConfirmed(false); }}>{uiT('取消本次导入')}</button>
      </div>}
    </div>}
    {step === 'trial' && <div className="custom-role-section">
      <h2>{uiT('草稿试聊')}</h2><p className="custom-role-hint">{uiT('点击发送后会调用当前配置的聊天模型。试聊仅使用当前草稿，不保存为正式消息或记忆。')}</p>
      <div className="custom-role-trial-messages" role="log">{trialHistory.length ? trialHistory.map((message, index) => <div key={index} className={message.from === 'me' ? 'is-me' : 'is-them'}><strong>{message.from === 'me' ? uiT('我') : (profile.name || uiT('角色'))}</strong><p>{message.text}</p></div>) : <p>{uiT('发一句话，看看角色会如何回应。')}</p>}</div>
      <form className="custom-role-trial-form" onSubmit={tryChat}><input value={trialText} maxLength={4000} onChange={event => setTrialText(event.target.value)} placeholder={uiT('输入试聊内容')} aria-label={uiT('输入试聊内容')} /><button type="submit" className="custom-role-primary-button" disabled={trialBusy || !trialText.trim()}>{uiT(trialBusy ? '回应中…' : '发送试聊')}</button></form>
      {trialHistory.length > 0 && <button type="button" className="custom-role-text-button" onClick={() => setTrialHistory([])}>{uiT('清空试聊')}</button>}
    </div>}
    <footer className="custom-role-footer"><span>{uiT('随时可以返回修改；保存后可在“我的角色”管理。')}</span><button type="button" className="custom-role-primary-button" disabled={busy} onClick={save}>{uiT(busy ? '正在保存…' : roleId ? '保存修改' : '保存角色')}</button></footer>
  </div>;
}

function CustomRoleHistory({ roleId }) {
  const [items, setItems] = React.useState([]);
  const [cursor, setCursor] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const load = async next => {
    if (busy || next === null) return;
    setBusy(true); setError('');
    try {
      const result = await customRoleRequest(`${CUSTOM_ROLE_API}/${encodeURIComponent(roleId)}/history?cursor=${next}&limit=50`);
      setItems(previous => next === 0 ? (result.items || []) : [...previous, ...(result.items || [])]);
      setCursor(result.nextCursor ?? null);
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  React.useEffect(() => { setItems([]); setCursor(0); load(0); }, [roleId]);
  return <div className="custom-role-history">
    <p className="custom-role-hint">{uiT('导入记录按原始顺序保存在角色档案。正式聊天仍在消息页。')}</p>
    {error && <p className="custom-role-error" role="alert">{error}</p>}
    {items.length ? <div className="custom-role-chat-preview">{items.map((message, index) => <div key={`${message.conversationId || ''}-${index}`}><strong>{message.from === 'me' ? uiT('我') : uiT('角色')}</strong><span>{message.text}</span>{message.ts && <time>{new Date(message.ts).toLocaleString()}</time>}</div>)}</div>
      : !busy && <p className="custom-role-hint">{uiT('暂无导入记录')}</p>}
    {cursor !== null && <button type="button" className="custom-role-secondary-button" disabled={busy} onClick={() => load(cursor)}>{uiT(busy ? '载入中…' : '加载更多')}</button>}
  </div>;
}

function CustomRoleManager({ onClose, onEdit, onOpenRole }) {
  const [roles, setRoles] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [busyId, setBusyId] = React.useState('');
  const [historyId, setHistoryId] = React.useState('');
  const [error, setError] = React.useState('');
  React.useEffect(() => {
    let active = true;
    customRoleRequest(CUSTOM_ROLE_API).then(result => {
      if (active) setRoles(Array.isArray(result.roles) ? result.roles : []);
    }).catch(failure => { if (active) setError(failure.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const toggle = async role => {
    setBusyId(role.id); setError('');
    try {
      await customRoleRequest(`${CUSTOM_ROLE_API}/${encodeURIComponent(role.id)}/${role.disabled ? 'restore' : 'disable'}`, { method: 'POST' });
      await customRoleOpenGalleryAfterReload();
    } catch (failure) { setError(failure.message); setBusyId(''); }
  };
  const exportRole = async role => {
    setBusyId(role.id); setError('');
    try {
      await window.shulianStorageFlush?.();
      const response = await fetch(`${CUSTOM_ROLE_API}/${encodeURIComponent(role.id)}/export`, { cache: 'no-store' });
      if (!response.ok) {
        let detail = null;
        try { detail = (await response.json()).detail; } catch (_) { /* keep fallback */ }
        throw new Error(typeof detail === 'string' ? detail : '角色包导出失败。');
      }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `${role.name || role.id}.shulian-role.zip`;
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (failure) { setError(failure.message); }
    finally { setBusyId(''); }
  };
  return <div className="custom-role-shell">
    <header className="custom-role-header"><div><h1>{uiT('管理我的角色')}</h1><p>{uiT('编辑资料、回看导入记录，或停用与恢复角色。')}</p></div><button type="button" className="custom-role-secondary-button" onClick={onClose}>{uiT('返回画廊')}</button></header>
    {error && <p className="custom-role-error" role="alert">{error}</p>}
    {loading ? <p role="status">{uiT('正在载入角色…')}</p> : roles.length ? <div className="custom-role-manager-list">
      {roles.map(role => <section key={role.id} className="custom-role-manager-card">
        <div><h2>{role.name || role.id}</h2><p>{role.disabled ? uiT('已停用') : uiT('已启用')}</p></div>
        <div className="custom-role-manager-actions">
          {!role.disabled && <button type="button" className="custom-role-secondary-button" onClick={() => onOpenRole(role.id)}>{uiT('查看角色')}</button>}
          <button type="button" className="custom-role-secondary-button" onClick={() => onEdit(role.id)}>{uiT('编辑')}</button>
          <button type="button" className="custom-role-secondary-button" disabled={busyId === role.id} onClick={() => exportRole(role)}>{uiT('导出角色包')}</button>
          <button type="button" className="custom-role-secondary-button" onClick={() => setHistoryId(previous => previous === role.id ? '' : role.id)}>{uiT('导入的聊天记录')}</button>
          <button type="button" className="custom-role-secondary-button" disabled={busyId === role.id} onClick={() => toggle(role)}>{uiT(role.disabled ? '恢复' : '停用')}</button>
        </div>
        {historyId === role.id && <CustomRoleHistory roleId={role.id} />}
      </section>)}
    </div> : <p className="custom-role-hint">{uiT('还没有自建角色。')}</p>}
  </div>;
}
