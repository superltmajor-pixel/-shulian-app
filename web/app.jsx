// app.jsx — 应用外壳：导航 / 聊天回复逻辑 / Tweaks
// ★已接入真实后端：发消息时调用已配置的 AI 服务，不再随机抽台词
const { useState: useS, useEffect: useE, useRef: useR } = React;
const SHULIAN_BUILD_ID = '2026-10-03-public-portable-v26-0';
const SHULIAN_PAGE_STARTED_AT = performance.now();

// 在 React 首次渲染前恢复“减少动态效果”，避免启动时先闪过一帧动画。
try {
  const savedSettings = JSON.parse(localStorage.getItem('sl_settings') || '{}');
  const reduceMotion = savedSettings.reduceMotion;
  const enabled = reduceMotion === true || reduceMotion === 'true' || reduceMotion === 1 || reduceMotion === '1';
  document.documentElement.dataset.reduceMotion = enabled ? 'true' : 'false';
  const performanceMode = savedSettings.performanceMode;
  const performanceEnabled = performanceMode === undefined
    || performanceMode === true || performanceMode === 'true' || performanceMode === 1 || performanceMode === '1';
  document.documentElement.dataset.performanceMode = performanceEnabled ? 'true' : 'false';
} catch (e) {
  document.documentElement.dataset.reduceMotion = 'false';
  document.documentElement.dataset.performanceMode = 'true';
}

const syncRuntimeActivity = () => {
  document.documentElement.dataset.windowActive =
    !document.hidden && document.hasFocus() ? 'true' : 'false';
};
syncRuntimeActivity();
document.addEventListener('visibilitychange', syncRuntimeActivity);
window.addEventListener('focus', syncRuntimeActivity);
window.addEventListener('blur', syncRuntimeActivity);

// 后端地址：与网页同源（由 FastAPI 一起托管），用根路径即可
const API_BASE = '';

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "glassIntensity": 7,
  "aurora": true
}/*EDITMODE-END*/;

const PROACTIVE_IDLE_MS = 20 * 60 * 1000;

// 当前心动角色只负责强调色；背景、玻璃材质与极光结构保持全局一致。
const CHARACTER_ACCENTS = {};

const GREETING_CACHE_VERSION = 2;
const CHARACTER_SELF_VOCATIVES = {};
const LEGACY_GUARD_FALLBACK_PATTERNS = Object.freeze([
  /^……让我重新说。你刚才的话，我有认真听见；这一次我不拿套话敷衍你。$/,
  /^等一下，让我把话说准确。你刚才问的事，我会按(?:照)?我们真实经历过的内容认真回答。$/,
  /^……我刚才没有表达清楚。给我一点时间，我会基于我们真正经历过的事回答你。$/,
  /^我方才的话不够准确。你说的事，我记得；我会先弄清你的意思，再认真回应。$/,
  /^抱歉，我刚才把话说乱了。我们已经一起经历过的事，我不会当作从未发生。$/,
  /^让我重新理清一下。你说的事我会依据真实上下文认真回应。$/,
  /^我听着呢。有什么话就直说吧，别让我猜你的心思。$/,
  /^我在听。慢慢说，我会认真回答。$/,
  /^我在听，你慢慢说就好。$/,
  /^我在。你说，我会认真听。$/,
  /^我在听。想说什么，都可以慢慢告诉我。$/,
  /^我在听，你慢慢说。$/,
]);
const GUARD_PROCESS_LEAK_CUES = Object.freeze([
  '系统指令', '提示词', '一致性校验', '一致性规则', '命中规则', '上面的助手草稿',
  '按照我们真实经历过的内容认真回答', '按我们真实经历过的内容认真回答',
  '给我一点时间，我会基于我们真正经历过的事回答你',
  '我会先弄清你的意思，再认真回应', '我不会当作从未发生',
  '基于我们真正经历过的事回答', '依据真实上下文认真回应',
]);

function isLegacyGuardFallbackText(value) {
  const text = String(value || '').trim();
  return LEGACY_GUARD_FALLBACK_PATTERNS.some(pattern => pattern.test(text))
    || GUARD_PROCESS_LEAK_CUES.some(cue => text.includes(cue));
}

function isLegacyStaticGreetingText(value) {
  const text = String(value || '').trim();
  return Boolean(text) && Array.isArray(ROSTER)
    && ROSTER.some(character => String(character?.greet || '').trim() === text);
}

function giftContextText(message) {
  if (!message || message.type !== 'gift') return '';
  const gift = String(message.gift || '').trim();
  const character = String(message.name || '角色').trim();
  return gift ? `[用户送给${character}一份礼物：${gift}]` : '';
}

function characterSelfAliases(characterId) {
  const known = CHARACTER_SELF_VOCATIVES[characterId];
  if (known) return known;
  const character = Array.isArray(ROSTER) ? ROSTER.find(item => item.id === characterId) : null;
  return character?.name ? [String(character.name).trim()] : [];
}

function isCharacterSelfAlias(characterId, value) {
  const clean = String(value || '').replace(/\s+/g, '').trim();
  return Boolean(clean) && characterSelfAliases(characterId).some(alias => clean === alias.replace(/\s+/g, ''));
}

function startsWithCharacterSelfVocative(characterId, value) {
  const aliases = characterSelfAliases(characterId);
  const text = String(value || '')
    .replace(/^(?:\s*[（(][^）)]{0,80}[）)]\s*)+/, '')
    .trimStart();
  return aliases.some(alias => {
    const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`^${escaped}(?:[，,、：:！!？?]|\\s)`).test(text);
  });
}

function requireSafeCharacterReply(characterId, value) {
  const text = String(value || '').trim();
  if (!text || isLegacyGuardFallbackText(text) || startsWithCharacterSelfVocative(characterId, text)) {
    throw new Error('这条回复生成异常，已停止发送。请再试一次。');
  }
  return text;
}

function readStoredObject(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch (e) {
    return {};
  }
}

function readStoredArray(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(value) ? value : [];
  } catch (e) {
    return [];
  }
}

function splitAddressField(value) {
  const source = Array.isArray(value) ? value : String(value || '').split(/[、,，;；/\n]+/);
  return Array.from(new Set(source.map(item => String(item || '').replace(/\s+/g, ' ').trim().replace(/^[‘’“”"']+|[‘’“”"']+$/g, '')).filter(Boolean))).slice(0, 12);
}

function addressDirectionEvidence(characterId, candidate, memoryContext) {
  let value = memoryContext;
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch (e) { value = {}; }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) value = {};
  const facts = [
    ...(Array.isArray(value.relationship_facts) ? value.relationship_facts : []),
    ...(Array.isArray(value.stable_facts) ? value.stable_facts : []),
  ].map(item => String(item || '').replace(/\s+/g, ''));
  const needle = String(candidate || '').replace(/\s+/g, '');
  const names = [...characterSelfAliases(characterId), '角色'];
  let userToCharacter = false;
  let characterToUser = false;
  facts.filter(fact => needle && fact.includes(needle)).forEach(fact => {
    userToCharacter = userToCharacter || names.some(name => [
      `用户对${name}的称呼`, `用户对${name}的专属称呼`, `用户称呼${name}`, `用户叫${name}`,
      `用户把${name}叫作`, `用户给${name}的称呼`,
    ].some(cue => fact.includes(cue)));
    characterToUser = characterToUser || names.some(name => [
      `${name}对用户的称呼`, `${name}对用户的专属称呼`, `${name}称呼用户`, `${name}叫用户`,
      `${name}把用户叫作`, `${name}给用户的称呼`,
    ].some(cue => fact.includes(cue)));
  });
  if (userToCharacter === characterToUser) return '';
  return userToCharacter ? 'user_to_character' : 'character_to_user';
}

function normalizeRelationshipAgreement(value) {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const clean = (key) => String(source[key] || '').trim().slice(0, 240);
  return {
    character_to_user_address: clean('character_to_user_address') || clean('role_to_user_address'),
    user_to_character_address: clean('user_to_character_address') || clean('user_to_role_address'),
    legacy_address: clean('legacy_address') || clean('address'),
    boundary: clean('boundary'),
    contact: clean('contact'),
  };
}

function sanitizeRelationshipAgreement(characterId, value, memoryContext = null) {
  const normalized = normalizeRelationshipAgreement(value);
  const roleToUser = splitAddressField(normalized.character_to_user_address);
  const userToCharacter = splitAddressField(normalized.user_to_character_address);
  splitAddressField(normalized.legacy_address).forEach(candidate => {
    const direction = isCharacterSelfAlias(characterId, candidate)
      ? 'user_to_character'
      : addressDirectionEvidence(characterId, candidate, memoryContext);
    if (direction === 'user_to_character') userToCharacter.push(candidate);
    else roleToUser.push(candidate); // Preserve the old interpretation if evidence is absent.
  });
  const safeRoleToUser = Array.from(new Set(roleToUser.filter(item => {
    if (isCharacterSelfAlias(characterId, item)) {
      userToCharacter.push(item);
      return false;
    }
    return addressDirectionEvidence(characterId, item, memoryContext) !== 'user_to_character';
  })));
  return {
    character_to_user_address: safeRoleToUser.join('、').slice(0, 240),
    user_to_character_address: Array.from(new Set(userToCharacter)).join('、').slice(0, 240),
    boundary: normalized.boundary,
    contact: normalized.contact,
  };
}

function toApiHistory(messages, limit = 24) {
  const candidates = (Array.isArray(messages) ? messages : [])
    .filter(m => m && !m.streaming && ((m.from === 'me' || m.from === 'her') || giftContextText(m))
      && !(m.from === 'her' && (
        isLegacyGuardFallbackText(m.text)
        || m.origin === 'legacy-static-greeting'
        || isLegacyStaticGreetingText(m.text)
      )))
    .map(m => {
      const message = {
        role: m.from === 'me' || giftContextText(m) ? 'user' : 'assistant',
        origin: String(m.origin || ''),
        content: giftContextText(m) || (m.type === 'voice'
          ? `[语音消息 ${m.dur || 0}秒]${m.transcript ? ` ${String(m.transcript).trim()}` : ''}`
          : m.type === 'image'
          ? `[图片]${String(m.text || '').trim() ? ` ${String(m.text).trim()}` : ''}`
          : String(m.text || '').replace(/^\[\[sticker:(.+)\]\]$/, '[$1]').trim()),
      };
      const timestamp = Number(m.ts);
      if (Number.isFinite(timestamp) && timestamp > 0) message.ts = timestamp;
      return message;
    })
    .filter(m => m.content);
  const history = [];
  let pendingUser = null;
  candidates.forEach(message => {
    const apiMessage = {
      role: message.role,
      content: message.content,
      ...(Number.isFinite(Number(message.ts)) && Number(message.ts) > 0 ? { ts: Number(message.ts) } : {}),
      ...(message.origin ? { origin: message.origin } : {}),
    };
    if (message.role === 'user') {
      pendingUser = apiMessage;
      return;
    }
    if (message.origin === 'proactive' || message.origin === 'home-greeting' || message.origin === 'new-chat-opening') {
      // An assistant-initiated line must never masquerade as the answer to a
      // user turn whose model request failed immediately before it.
      pendingUser = null;
      history.push([apiMessage]);
      return;
    }
    if (pendingUser) {
      history.push([pendingUser, apiMessage]);
      pendingUser = null;
    } else {
      history.push([apiMessage]);
    }
  });
  const selected = [];
  let remaining = Math.max(0, Number(limit) || 0);
  for (let i = history.length - 1; i >= 0; i -= 1) {
    if (history[i].length > remaining) break;
    selected.unshift(...history[i]);
    remaining -= history[i].length;
  }
  return selected;
}

function countCompleteHistoryPairs(messages) {
  let waitingForAssistant = false;
  let count = 0;
  toApiHistory(messages, 80).forEach(message => {
    if (message.role === 'user') {
      waitingForAssistant = true;
    } else if (waitingForAssistant) {
      count += 1;
      waitingForAssistant = false;
    }
  });
  return count;
}

function normalizeCallCarryover(value) {
  return (Array.isArray(value) ? value : [])
    .filter(item => item && (item.from === 'me' || item.from === 'her') && String(item.text || '').trim())
    .map(item => ({
      from: item.from,
      text: String(item.text || '').trim().slice(0, 4000),
      ts: Number(item.ts) || Date.now(),
    }))
    .slice(-24);
}

// 新建会话时旧窗口只作为“刚才聊过”的交接上下文，不是当前窗口的历史。
// 它按真实时间排在最前，随轮次或时间过期，避免隔天旧场景被当成现在。
const WINDOW_HANDOVER_TTL_MS = 30 * 60 * 1000;
const WINDOW_HANDOVER_MAX_TURNS = 4;
const WINDOW_HANDOVER_LIMIT = 12;
function normalizeWindowHandover(value) {
  if (!value || typeof value !== 'object') return null;
  const messages = (Array.isArray(value.messages) ? value.messages : [])
    .filter(item => item && (item.from === 'me' || item.from === 'her') && String(item.text || '').trim())
    .map(item => ({
      from: item.from,
      text: String(item.text || '').trim().slice(0, 4000),
      ts: Number(item.ts) || Date.now(),
      ...(item.origin ? { origin: String(item.origin) } : {}),
      ...(item.type ? { type: String(item.type) } : {}),
      ...(item.transcript ? { transcript: String(item.transcript).slice(0, 4000) } : {}),
    }));
  if (!messages.length) return null;
  // 只保留完整问答对：历史裁剪遇到连续两条用户消息会丢掉前一条，
  // 交接里若留着“用户刚说、角色还没回”的半截消息，整段上下文反而会被一起丢掉。
  const kept = [];
  let pendingUser = null;
  messages.forEach(message => {
    if (message.from === 'me') {
      pendingUser = message;
      return;
    }
    if (pendingUser) kept.push(pendingUser, message);
    else kept.push(message);
    pendingUser = null;
  });
  if (!kept.length) return null;
  return {
    messages: kept.slice(-WINDOW_HANDOVER_LIMIT),
    createdAt: Number(value.createdAt) || Date.now(),
    turns: Math.max(0, Number(value.turns) || 0),
  };
}
function windowHandoverExpired(handover, now = Date.now()) {
  if (!handover || !handover.messages?.length) return true;
  if (now - handover.createdAt > WINDOW_HANDOVER_TTL_MS) return true;
  if (handover.turns >= WINDOW_HANDOVER_MAX_TURNS) return true;
  const lastTs = Number(handover.messages[handover.messages.length - 1]?.ts) || handover.createdAt;
  return new Date(lastTs).toDateString() !== new Date(now).toDateString();
}

function toConsolidationMessages(messages) {
  return (Array.isArray(messages) ? messages : [])
    .filter(message => message && !message.streaming && ((message.from === 'me' || message.from === 'her') || giftContextText(message))
      && !(message.from === 'her' && (
        isLegacyGuardFallbackText(message.text)
        || message.origin === 'legacy-static-greeting'
        || isLegacyStaticGreetingText(message.text)
      )))
    .map(message => ({
      from: giftContextText(message) ? 'me' : message.from,
      type: message.type || 'text',
      text: String(giftContextText(message) || message.text || '').slice(0, 4000),
      transcript: String(message.transcript || '').slice(0, 4000),
      ts: Number(message.ts) || 0,
      origin: String(message.origin || '').slice(0, 40),
    }));
}

function toConsolidationSessions(sessions) {
  return (Array.isArray(sessions) ? sessions : []).map(session => ({
    startTs: Number(session?.startTs) || null,
    endTs: Number(session?.endTs) || null,
    messages: toConsolidationMessages(session?.messages),
  }));
}

const MEMORY_CONTEXT_VERSION = 2;
const MEMORY_EVENT_TTL_MS = 72 * 60 * 60 * 1000;
// Relative-only summaries such as “今天去了……” cannot be replayed safely
// after a new day; keep only events whose text carries an absolute date.
const RELATIVE_EVENT_CUE_RE = /今天|今日|今晚|今夜|明天|明日|明早|昨天|昨日|刚刚|刚才/;

function eventDateExpiry(text) {
  const dates = [...String(text || '').matchAll(/((?:19|20)\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日|号)?/g)];
  if (!dates.length || RELATIVE_EVENT_CUE_RE.test(text)) return NaN;
  const expiries = dates.map(([, y, m, d]) => {
    const day = new Date(Number(y), Number(m) - 1, Number(d));
    if (day.getFullYear() !== Number(y) || day.getMonth() !== Number(m) - 1 || day.getDate() !== Number(d)) return NaN;
    day.setDate(day.getDate() + 1);
    return day.getTime() + MEMORY_EVENT_TTL_MS;
  });
  return Math.min(...expiries);
}
const MEMORY_SENSITIVE_CUES = [
  '情事', '性行为', '色情', '床上', '裸体', '插入', '双乳', '乳尖', '阴部',
  '小穴', '肛', '射', '淫', '操', '高潮', '失禁', '体液', '身体交付', '极尽缠绵',
  '发生了亲密关系', '发生亲密关系', '性欲', '身体很诚实', '私密部位', '下体',
  '阴茎', '精液', '口交', '性交', '做爱', '乳房', '胸部', '呻吟', '喘息',
  '快感', '创可贴贴在', '触碰我的身体', '允许他触碰', '这副模样只许', '耳垂是我的弱点',
  '交付身心', '亲密举动', '亲密时',
  '明日陪', '明天陪', '明早陪', '陪他上工', '陪我上工', '见凝光',
];
const MEMORY_TEMPORAL_CUES = [
  '今天', '今日', '今晚', '今夜', '明天', '明日', '明早', '昨天', '昨日',
  '刚刚', '刚才', '近期', '最近', '目前', '此刻', '正在', '下班', '早起', '上工', '待批', '文书',
  '行程', '安排', '计划', '稍后', '待会', '等会', '过会', '一会儿', '下次', '下回',
  '这周', '本周', '见凝光', '回来时', '见面时',
];
const MEMORY_RELATIONSHIP_CUES = [
  '称呼', '叫我', '我称', '叫作', '专属', '约定', '承诺', '答应', '契约',
  '婚姻', '婚礼', '结婚', '关系', '恋人', '伴侣', '共度余生', '唯一',
  '只许', '边界', '不会先松手',
];

function cleanMemoryText(value) {
  return String(value || '').replace(/\s+/g, ' ').replace(/^[\-•\s]+/, '').trim();
}

function completeMemoryText(value, allowTemporal = false) {
  const text = cleanMemoryText(value).slice(0, 280);
  if (!text || MEMORY_SENSITIVE_CUES.some(cue => text.includes(cue))) return '';
  if (!allowTemporal && MEMORY_TEMPORAL_CUES.some(cue => text.includes(cue))) return '';
  if (/(的|和|与|在|从|把|如果|因为|但是|还|我)$/.test(text)) return '';
  return /[。！？.!?；;：:）》)】\]]$/.test(text) ? text : `${text}。`;
}

function relationshipMemoryText(value) {
  return MEMORY_RELATIONSHIP_CUES.some(cue => String(value || '').includes(cue));
}

function canonicalStableMemoryText(value) {
  let text = completeMemoryText(value, false);
  if (!text) return '';
  if (text.startsWith('他')) text = `用户${text.slice(1)}`;
  else if (text.startsWith('她')) text = `用户${text.slice(1)}`;
  if (!text.startsWith('用户')) return '';
  if (['我爱', '我喜欢', '我的弱点', '我面对', '我认定'].some(cue => text.includes(cue))) return '';
  if (['用户说', '用户问', '用户回答', '用户表示', '用户告诉', '用户提到', '用户发',
       '用户叫', '用户纠正', '用户曾', '用户来', '用户推', '用户帮', '用户与']
      .some(prefix => text.startsWith(prefix))) return '';
  if (text.includes('我') || ROSTER.some(role => role.name && text.includes(role.name))) return '';
  if (/^用户.*?时[，,]/.test(text)) return '';
  if (['似乎', '可能', '尚未明确', '具体身份信息'].some(cue => text.includes(cue))) return '';
  return text;
}

function uniqueMemoryFacts(values, limit, allowTemporal = false) {
  const result = [];
  const seen = new Set();
  (Array.isArray(values) ? values : []).forEach(value => {
    const text = completeMemoryText(value, allowTemporal);
    if (!text || seen.has(text) || result.length >= limit) return;
    seen.add(text);
    result.push(text);
  });
  return result;
}

function migrateLegacyMemory(legacy) {
  if (typeof legacy === 'string') {
    try {
      const parsed = JSON.parse(legacy);
      if (parsed && typeof parsed === 'object' && parsed.version === MEMORY_CONTEXT_VERSION) {
        return normalizeMemoryContext(parsed, '');
      }
    } catch (e) { /* continue with old heading migration */ }
  }
  const sections = {};
  let section = 'other';
  String(legacy || '').split(/\r?\n/).forEach(rawLine => {
    const line = rawLine.trim();
    const heading = line.match(/^##\s+(.+?)\s*$/);
    if (heading) {
      section = heading[1].trim();
      sections[section] = sections[section] || [];
    } else if (/^[\-•]/.test(line)) {
      sections[section] = sections[section] || [];
      sections[section].push(line);
    }
  });
  const relationship = [];
  (sections['我们之间'] || []).forEach(line => {
    if (['约定', '承诺', '称呼', '婚姻', '纪念', '关系'].some(cue => line.includes(cue))) relationship.push(line);
  });
  return {
    version: MEMORY_CONTEXT_VERSION,
    stable_facts: uniqueMemoryFacts([...(sections['身份'] || []), ...(sections['喜好'] || [])], 16),
    relationship_facts: uniqueMemoryFacts(relationship, 12),
    recent_events: [],
    updated_at: new Date().toISOString(),
  };
}

function normalizeMemoryContext(raw, legacy = '') {
  let value = raw;
  if (typeof raw === 'string') {
    try { value = JSON.parse(raw); } catch (e) { value = null; }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) value = migrateLegacyMemory(legacy);
  const now = Date.now();
  const recent = (Array.isArray(value.recent_events) ? value.recent_events : []).map(item => {
    const source = item && typeof item === 'object' ? item : { text: item };
    const text = completeMemoryText(source.text, true);
    const captured = Number.isFinite(Date.parse(source.captured_at)) ? Date.parse(source.captured_at) : now;
    const requestedExpiry = Number.isFinite(Date.parse(source.expires_at)) ? Date.parse(source.expires_at) : captured + MEMORY_EVENT_TTL_MS;
    const expires = Math.min(requestedExpiry, captured + MEMORY_EVENT_TTL_MS, eventDateExpiry(text));
    return text && captured <= now && expires > now ? {
      text,
      captured_at: new Date(captured).toISOString(),
      expires_at: new Date(expires).toISOString(),
    } : null;
  }).filter(Boolean).slice(0, 8);
  const relationshipCandidates = Array.isArray(value.relationship_facts) ? [...value.relationship_facts] : [];
  const stable = [];
  (Array.isArray(value.stable_facts) ? value.stable_facts : []).forEach(item => {
    const clean = completeMemoryText(item, false);
    if (!clean) return;
    if (relationshipMemoryText(clean)) {
      relationshipCandidates.push(clean);
      return;
    }
    const canonical = canonicalStableMemoryText(clean);
    if (canonical && !stable.includes(canonical) && stable.length < 16) stable.push(canonical);
  });
  const normalized = {
    version: MEMORY_CONTEXT_VERSION,
    stable_facts: stable,
    relationship_facts: uniqueMemoryFacts(relationshipCandidates, 12),
    recent_events: recent,
    updated_at: typeof value.updated_at === 'string' ? value.updated_at : new Date().toISOString(),
  };
  if (!normalized.stable_facts.length && !normalized.relationship_facts.length && !normalized.recent_events.length && legacy) {
    const migrated = migrateLegacyMemory(legacy);
    if (migrated.stable_facts.length || migrated.relationship_facts.length || migrated.recent_events.length) return migrated;
  }
  return normalized;
}

function reversesCharacterAddressDirection(characterId, value) {
  const text = cleanMemoryText(value);
  const aliases = characterSelfAliases(characterId);
  if (!text || !aliases.some(alias => text.includes(alias))) return false;
  const character = Array.isArray(ROSTER) ? ROSTER.find(item => item.id === characterId) : null;
  const name = String(character?.name || aliases[0] || '角色');
  return [
    `${name}对用户的称呼`, `${name}给用户的称呼`, `${name}称呼用户`,
    `${name}称用户`, `${name}叫用户`, '角色对用户的称呼',
    '角色给用户的称呼', '角色称呼用户',
  ].some(cue => text.includes(cue));
}

function sanitizeMemoryAddressDirection(characterId, raw, legacy = '') {
  const context = normalizeMemoryContext(raw, legacy);
  const keep = value => !reversesCharacterAddressDirection(characterId, value);
  return {
    ...context,
    stable_facts: context.stable_facts.filter(keep),
    relationship_facts: context.relationship_facts.filter(keep),
    recent_events: context.recent_events.filter(event => keep(event?.text)),
  };
}

function serializeMemoryContext(context) {
  return JSON.stringify(normalizeMemoryContext(context), null, 0);
}

// ── v21 统一角色上下文：关系、经历结论与跨会话事实的唯一真源 ──
const COMPANION_CONTEXT_VERSION = 1;
const RELATIONSHIP_STAGES = ['初识', '认识', '熟悉', '信赖', '亲近', '心意相通', '关系确认', '深度伴侣', '灵魂伴侣', '终身伴侣'];
const COMPANION_CALIBRATIONS = {};
const DURABLE_COMMITMENT_CUES = Object.freeze([
  '终身', '一辈子', '余生', '白头', '永恒', '契约', '婚约', '结婚', '婚礼', '夫妻',
  '共同未来', '共同走向未来', '以后一直', '关系确认', '终身伴侣',
]);
const ONE_OFF_COMMITMENT_CUES = Object.freeze([
  '下次', '下回', '明天', '明日', '今晚', '今夜', '稍后', '待会', '等会', '见面时',
  '回来时', '发消息', '打电话', '做饭', '吃饭', '上工', '工作', '文书', '拥抱',
  '抱抱', '亲吻', '陪着说话', '还想说话',
]);

function durableCommitmentText(value, characterId) {
  let text = String(value || '').replace(/\s+/g, ' ').trim().slice(0, 280);
  if (!text || !DURABLE_COMMITMENT_CUES.some(cue => text.includes(cue))) return '';
  if ((byId(characterId)?.staleMarriage?.cues || []).some(cue => text.includes(cue))
      && ['结婚', '婚约', '婚礼', '夫妻'].some(cue => text.includes(cue))) return '';
  if (ONE_OFF_COMMITMENT_CUES.some(cue => text.includes(cue))
      && !['终身', '余生', '契约', '婚约', '结婚', '夫妻'].some(cue => text.includes(cue))) return '';
  if (!/[。！？.!?；;]$/.test(text)) text += '。';
  return text;
}

function relationshipStage(level) {
  const safe = Math.max(1, Math.min(10, Number.parseInt(level, 10) || 1));
  return RELATIONSHIP_STAGES[safe - 1];
}

function defaultCompanionContext(characterId) {
  const calibration = COMPANION_CALIBRATIONS[characterId];
  const level = calibration?.level || 1;
  const dimensions = calibration?.dimensions || [0, 0, 0, 0];
  const now = new Date().toISOString();
  return {
    version: COMPANION_CONTEXT_VERSION,
    character_id: characterId,
    relationship: {
      level,
      stage: relationshipStage(level),
      title: calibration?.title || relationshipStage(level),
      dimensions: { familiarity: dimensions[0], trust: dimensions[1], affection: dimensions[2], commitment: dimensions[3] },
      forms_of_address: [],
      user_forms_of_address: [],
      boundaries: ['过去的亲密不代表本轮永久同意；每次都尊重当下表达与边界。'],
      commitments: [...(calibration?.commitments || [])],
      confirmed_events: [...(calibration?.events || [])],
      invalidated_facts: [...(calibration?.invalidated || [])],
      updated_at: now,
    },
    experience_milestones: [],
    stable_facts: [],
    recent_events: [],
    migration: { source_version: 'v21', completed: false, processed_segments: [], migrated_at: '' },
    updated_at: now,
  };
}

function normalizeCompanionContext(raw, characterId) {
  let value = raw;
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch (e) { value = null; }
  }
  const base = defaultCompanionContext(characterId);
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || value.version !== COMPANION_CONTEXT_VERSION || value.character_id !== characterId) return base;
  const sourceRelation = value.relationship && typeof value.relationship === 'object' ? value.relationship : {};
  const sourceDimensions = sourceRelation.dimensions && typeof sourceRelation.dimensions === 'object' ? sourceRelation.dimensions : {};
  const redefined = Array.isArray(sourceRelation.confirmed_events) && sourceRelation.confirmed_events.includes('relationship_redefined');
  const clampDimension = (key) => {
    const incoming = Math.max(0, Math.min(4, Number.parseInt(sourceDimensions[key], 10) || 0));
    return redefined ? incoming : Math.max(base.relationship.dimensions[key], incoming);
  };
  const incomingLevel = Math.max(1, Math.min(10, Number.parseInt(sourceRelation.level, 10) || 1));
  const level = redefined ? incomingLevel : Math.max(base.relationship.level, incomingLevel);
  const uniqueText = (items, limit) => Array.from(new Set((Array.isArray(items) ? items : [])
    .map(item => String(item || '').replace(/\s+/g, ' ').trim()).filter(Boolean))).slice(0, limit);
  const milestones = (Array.isArray(value.experience_milestones) ? value.experience_milestones : [])
    .filter(item => item && typeof item === 'object' && typeof item.category === 'string')
    .map(item => ({
      category: item.category,
      first_at: String(item.first_at || ''),
      last_at: String(item.last_at || ''),
      frequency: ['once', 'several', 'many'].includes(item.frequency) ? item.frequency : 'once',
      evidence_ids: uniqueText(item.evidence_ids, 64),
    })).slice(0, 8);
  const migration = value.migration && typeof value.migration === 'object' ? value.migration : {};
  return {
    version: COMPANION_CONTEXT_VERSION,
    character_id: characterId,
    relationship: {
      level,
      stage: relationshipStage(level),
      title: (!redefined && COMPANION_CALIBRATIONS[characterId] && level === base.relationship.level)
        ? base.relationship.title
        : String(sourceRelation.title || relationshipStage(level)).trim().slice(0, 40),
      dimensions: {
        familiarity: clampDimension('familiarity'),
        trust: clampDimension('trust'),
        affection: clampDimension('affection'),
        commitment: clampDimension('commitment'),
      },
      forms_of_address: uniqueText(sourceRelation.forms_of_address, 12)
        .filter(item => !isCharacterSelfAlias(characterId, item)),
      user_forms_of_address: uniqueText(sourceRelation.user_forms_of_address, 12),
      boundaries: uniqueText([...base.relationship.boundaries, ...(sourceRelation.boundaries || [])], 12),
      commitments: uniqueText(redefined ? (sourceRelation.commitments || []) : [...base.relationship.commitments, ...(sourceRelation.commitments || [])], 16)
        .map(item => durableCommitmentText(item, characterId)).filter(Boolean),
      confirmed_events: uniqueText(redefined ? sourceRelation.confirmed_events : [...base.relationship.confirmed_events, ...(sourceRelation.confirmed_events || [])], 32),
      invalidated_facts: uniqueText([...base.relationship.invalidated_facts, ...(sourceRelation.invalidated_facts || [])], 16),
      updated_at: String(sourceRelation.updated_at || new Date().toISOString()),
    },
    experience_milestones: milestones,
    stable_facts: uniqueText(value.stable_facts, 24)
      .map(canonicalStableMemoryText).filter(Boolean),
    // Recent events are injected only from MemoryContextV2, which has a 72h
    // expiry.  Legacy CompanionContext strings otherwise survive forever.
    recent_events: [],
    migration: {
      source_version: 'v21',
      completed: migration.completed === true,
      processed_segments: uniqueText(migration.processed_segments, 4096),
      migrated_at: String(migration.migrated_at || ''),
    },
    updated_at: String(value.updated_at || new Date().toISOString()),
  };
}

function reconcileCompanionAddressDirections(context, characterId, agreement, memoryContext) {
  const normalized = normalizeCompanionContext(context, characterId);
  const safeAgreement = sanitizeRelationshipAgreement(characterId, agreement, memoryContext);
  const roleToUser = splitAddressField(safeAgreement.character_to_user_address);
  const userToCharacter = splitAddressField(safeAgreement.user_to_character_address);
  const relation = normalized.relationship;
  const existingRoleToUser = (Array.isArray(relation.forms_of_address) ? relation.forms_of_address : [])
    .filter(item => !isCharacterSelfAlias(characterId, item)
      && addressDirectionEvidence(characterId, item, memoryContext) !== 'user_to_character');
  const existingUserToCharacter = Array.isArray(relation.user_forms_of_address)
    ? relation.user_forms_of_address : [];
  return {
    ...normalized,
    relationship: {
      ...relation,
      forms_of_address: Array.from(new Set([...roleToUser, ...existingRoleToUser])).slice(0, 12),
      user_forms_of_address: Array.from(new Set([
        ...userToCharacter,
        ...existingUserToCharacter,
        ...(relation.forms_of_address || []).filter(item => isCharacterSelfAlias(characterId, item)
          || addressDirectionEvidence(characterId, item, memoryContext) === 'user_to_character'),
      ])).slice(0, 12),
    },
  };
}

function companionContextMetrics(context, characterId) {
  const normalized = normalizeCompanionContext(context, characterId);
  const relation = normalized.relationship;
  const dims = relation.dimensions;
  return {
    level: relation.level,
    title: relation.title,
    stage: relation.stage,
    heart: Math.min(9999, relation.level * 420 + (dims.affection + dims.commitment) * 180),
    compatibility: Math.min(99, 35 + (dims.familiarity + dims.trust + dims.affection + dims.commitment) * 4),
    dimensions: dims,
  };
}

// ── 旧数据迁移：把过去逐句记录的通话气泡(type:'call')合并成一条通话小结 ──
// 老数据没存时长/通话形式：时长用一通话内首尾时间戳估算，形式统一按语音算（旧版语音/视频
// 都写成同样的 type:'call'，无从分辨）。相邻通话气泡间隔超过 3 分钟视为两通电话，分开合并。
// 幂等：迁移后已无 type:'call'，再次运行原样返回。

async function chatFailureMessage(res) {
  if (!res) return '（后端没有回应。请确认数恋窗口没有被关掉，或重新从“启动数恋APP.bat”打开）';
  let detail = '';
  let errorCode = '';
  let requestId = '';
  try {
    const data = await res.clone().json();
    detail = typeof data?.error?.message === 'string'
      ? data.error.message
      : typeof data?.detail?.message === 'string'
        ? data.detail.message
        : typeof data?.detail === 'string'
          ? data.detail
          : '';
    errorCode = String(data?.error?.code || data?.detail?.code || '');
    requestId = String(data?.error?.request_id || '');
  } catch (e) {
    detail = '';
  }
  const diagnosticHint = requestId
    ? `（诊断编号 ${requestId}${errorCode ? ` · ${errorCode}` : ''}）`
    : '';
  if (res.status === 503 || /未配置|not configured/i.test(detail)) {
    return `（AI 密钥没有加载。请关闭数恋后，从“启动数恋APP.bat”重新打开）${diagnosticHint}`;
  }
  if (res.status === 409 || /回复生成异常|consistency/i.test(detail)) {
    return `这条回复生成异常，已停止发送。请再试一次。${diagnosticHint}`;
  }
  if (res.status === 502 || /暂时不可用|failed|upstream/i.test(detail)) {
    return `（模型服务暂时失败。后端还在运行，可以稍后再试）${diagnosticHint}`;
  }
  if (res.status === 413) return `（这次发送的内容太大了，稍微缩短一点再发）${diagnosticHint}`;
  if (res.status === 422) return `（这条消息格式没有通过检查，换个说法再发一次）${diagnosticHint}`;
  return `（信号断了…请确认后端正在运行）${diagnosticHint}`;
}

async function readChatStream(res, onStatus) {
  if (!res?.body?.getReader) throw new Error('（当前环境不支持流式回复，请更新数恋客户端后再试）');
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let reply = '';

  const consumeFrame = async (frame) => {
    if (!frame.trim()) return false;
    let eventName = 'message';
    const data = [];
    frame.split(/\r?\n/).forEach(line => {
      if (line.startsWith('event:')) eventName = line.slice(6).trim();
      if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
    });
    const payload = data.join('\n');
    if (eventName === 'error') throw new Error(payload || '（模型服务暂时失败。后端还在运行，可以稍后再试）');
    if (payload === '[DONE]') return true;
    if (!payload) return false;
    if (eventName === 'status') {
      try {
        const status = JSON.parse(payload);
        if (status && typeof status === 'object') onStatus?.(status);
      } catch (e) { /* 状态更新失败不影响已经收到的回复 */ }
      return false;
    }
    if (eventName !== 'message') return false;

    reply += payload;
    return false;
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    let boundary = buffer.search(/\r?\n\r?\n/);
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary);
      const separator = buffer.slice(boundary).match(/^\r?\n\r?\n/)[0];
      buffer = buffer.slice(boundary + separator.length);
      if (await consumeFrame(frame)) return reply;
      boundary = buffer.search(/\r?\n\r?\n/);
    }
    if (done) break;
  }
  if (buffer.trim()) await consumeFrame(buffer);
  return reply;
}

async function revealVerifiedReply(value, onText) {
  const characters = Array.from(String(value || ''));
  if (!characters.length) return;
  const delay = Math.max(4, Math.min(18, 1800 / characters.length));
  let partial = '';
  for (const character of characters) {
    partial += character;
    onText(partial);
    await new Promise(resolve => setTimeout(resolve, delay));
  }
}
function migrateCallBubbles(messages) {
  if (!Array.isArray(messages)) return messages;
  let changed = false;
  const out = [];
  let i = 0;
  while (i < messages.length) {
    const m = messages[i];
    if (m && m.type === 'call') {
      const run = [m];
      let j = i + 1;
      while (j < messages.length && messages[j] && messages[j].type === 'call'
             && (messages[j].ts || 0) - (messages[j - 1].ts || 0) <= 180000) {
        run.push(messages[j]); j++;
      }
      const firstTs = run[0].ts || 0;
      const lastTs = run[run.length - 1].ts || firstTs;
      const duration = Math.max(0, Math.round((lastTs - firstTs) / 1000));
      out.push({ from: 'system', type: 'callend', mode: 'voice', duration, ts: firstTs || Date.now() });
      changed = true;
      i = j;
    } else {
      out.push(m); i++;
    }
  }
  return changed ? out : messages;
}

function migrateLegacyGuardFallbacks(messages) {
  if (!Array.isArray(messages)) return messages;
  let changed = false;
  const migrated = messages.map(message => {
    if (!message || message.from !== 'her' || !isLegacyGuardFallbackText(message.text)) return message;
    changed = true;
    return {
      from: 'system',
      type: 'error',
      text: '此前有一条回复生成异常，已从角色对话上下文中排除。',
      ts: Number(message.ts) || Date.now(),
      migratedFrom: 'guard-fallback-v21',
    };
  });
  return changed ? migrated : messages;
}

function markLegacyStaticGreetings(messages) {
  if (!Array.isArray(messages)) return messages;
  let changed = false;
  const migrated = messages.map(message => {
    if (!message || message.from !== 'her' || message.origin
        || !isLegacyStaticGreetingText(message.text)) return message;
    changed = true;
    return { ...message, origin: 'legacy-static-greeting' };
  });
  return changed ? migrated : messages;
}

function migrateConversationMessages(messages) {
  return markLegacyStaticGreetings(migrateLegacyGuardFallbacks(migrateCallBubbles(messages)));
}

function migrateThreadsCallBubbles(threadsObj) {
  if (!threadsObj || typeof threadsObj !== 'object') return threadsObj;
  const out = {};
  for (const [id, msgs] of Object.entries(threadsObj)) out[id] = migrateConversationMessages(msgs);
  return out;
}

function migrateSessionsCallBubbles(sessionsObj) {
  if (!sessionsObj || typeof sessionsObj !== 'object') return sessionsObj;
  const out = {};
  for (const [id, sessions] of Object.entries(sessionsObj)) {
    out[id] = (Array.isArray(sessions) ? sessions : []).map(s =>
      s && Array.isArray(s.messages) ? { ...s, messages: migrateConversationMessages(s.messages) } : s);
  }
  return out;
}

const USER_PROFILE_DEFAULT = { name: '你', bio: '把喜欢的人留在身边' };
function normalizeUserProfile(value) {
  const src = value && typeof value === 'object' ? value : {};
  const bio = src.bio == null ? USER_PROFILE_DEFAULT.bio : String(src.bio);
  const img = typeof src.avatarImg === 'string' && src.avatarImg.startsWith('data:image/') && src.avatarImg.length < 600000
    ? src.avatarImg : '';
  return {
    name: String(src.name || USER_PROFILE_DEFAULT.name).trim().slice(0, 20) || USER_PROFILE_DEFAULT.name,
    bio: bio.trim().slice(0, 80),
    avatarImg: img,
  };
}

async function readAiConfigPayload(response) {
  try {
    const payload = await response.json();
    return payload && typeof payload === 'object' ? payload : {};
  } catch (e) {
    return {};
  }
}

function aiConfigErrorMessage(response, payload, action = 'check') {
  if (!response) return uiT('无法连接本机服务，请确认数恋仍在运行。');
  const detail = typeof payload?.detail === 'string'
    ? payload.detail.trim()
    : typeof payload?.detail?.message === 'string'
      ? payload.detail.message.trim()
      : '';
  if (detail && (currentUiLanguage() !== 'en' || !/[\u3400-\u9fff]/.test(detail))) return detail;
  if (response.status === 401) {
    return uiT(action === 'save'
      ? '这个 API Key 未通过验证，请检查后重新输入。'
      : '已保存的 API Key 已失效，请输入新的 Key。');
  }
  if (response.status === 503) return uiT('AI 服务暂时不可用，请稍后重试。');
  return uiT(action === 'remove' ? '暂时无法退出登录，请稍后重试。' : 'AI 服务暂时不可用，请稍后重试。');
}

function waitForWindowTransitionPaint() {
  return new Promise(resolve => {
    window.requestAnimationFrame(() => window.requestAnimationFrame(resolve));
  });
}

async function requestNativeWindowMode(mode, animate = false) {
  const method = window.pywebview?.api?.set_window_mode;
  if (typeof method !== 'function') return { ok: false, error: 'native_bridge_unavailable' };
  try {
    return await Promise.resolve(method(mode, Boolean(animate)));
  } catch (e) {
    return { ok: false, error: 'native_resize_failed' };
  }
}

const ACTIVE_UPDATE_STATUSES = new Set(['queued', 'running', 'restarting']);

async function invokeMaintenanceApi(method, ...args) {
  const invoke = window.pywebview?.api?.[method];
  if (typeof invoke !== 'function') return { ok: false, error: 'native_bridge_unavailable' };
  try {
    return await Promise.resolve(invoke(...args));
  } catch (error) {
    return { ok: false, error: 'native_bridge_failed', message: String(error?.message || error || '') };
  }
}

function useMaintenanceController() {
  const [state, setState] = useS({ loading: true, status: null, job: null, error: '' });

  const refresh = async () => {
    setState(previous => ({ ...previous, loading: true, error: '' }));
    const result = await invokeMaintenanceApi('get_maintenance_status');
    if (!result?.ok) {
      setState(previous => ({ ...previous, loading: false, error: '当前环境无法使用桌面维护功能。' }));
      return result;
    }
    setState({ loading: false, status: result, job: result.lastJob || null, error: '' });
    return result;
  };

  const refreshJob = async () => {
    const result = await invokeMaintenanceApi('get_update_job');
    if (result?.ok) setState(previous => ({ ...previous, job: result.job || null }));
    return result;
  };

  useE(() => {
    let active = true;
    const sync = () => { if (active) refresh(); };
    sync();
    window.addEventListener('pywebviewready', sync);
    return () => { active = false; window.removeEventListener('pywebviewready', sync); };
  }, []);

  useE(() => {
    if (!ACTIVE_UPDATE_STATUSES.has(state.job?.status)) return undefined;
    const timer = window.setInterval(refreshJob, 700);
    return () => window.clearInterval(timer);
  }, [state.job?.status]);

  const startUpdate = async () => {
    const sourceVersion = state.status?.sourceVersion || '新版本';
    if (!window.confirm(uiT(
      '后台构建并更新到数恋 v{version}？\n\n打包期间可以继续查看进度；切换程序时当前窗口会自动关闭并重新打开。',
      { version: sourceVersion },
    ))) {
      return { ok: false, cancelled: true };
    }
    const result = await invokeMaintenanceApi('start_source_update');
    if (result?.ok) setState(previous => ({ ...previous, job: result.job, error: '' }));
    else setState(previous => ({ ...previous, error: result?.message || uiT('无法启动后台更新。') }));
    return result;
  };

  const uninstall = async (removeUserData, confirmation) => {
    const result = await invokeMaintenanceApi('uninstall_app', Boolean(removeUserData), String(confirmation || ''));
    if (!result?.ok) setState(previous => ({ ...previous, error: result?.message || uiT('无法启动卸载助手。') }));
    return result;
  };

  const openDownloads = async () => {
    const result = await invokeMaintenanceApi('open_public_releases');
    setState(previous => ({ ...previous, error: result?.ok ? '' : uiT(result?.message || '无法打开下载页。') }));
    return result;
  };

  return { ...state, refresh, refreshJob, startUpdate, openDownloads, uninstall };
}

function WindowModeTransition({ direction }) {
  const opening = direction === 'opening';
  return (
    <main className={`window-mode-transition is-${direction}`} role="status" aria-live="polite" aria-busy="true">
      <span className="window-mode-transition-mark" aria-hidden="true"><BrandIcon size={52} /></span>
      <strong>{uiT(opening ? '正在打开数恋' : '正在返回登录')}</strong>
      <span>{uiT(opening ? '马上就好…' : '聊天和记忆都会保留')}</span>
    </main>
  );
}

function ApiKeyGate({ status, message, messageTone, onRetry, onValidate, onConnected, onRemove, maintenance }) {
  const [apiKey, setApiKey] = useS('');
  const [visible, setVisible] = useS(false);
  const [submitting, setSubmitting] = useS(false);
  const [removing, setRemoving] = useS(false);
  const [manualEntry, setManualEntry] = useS(false);
  const [success, setSuccess] = useS(false);
  const [providerLabel, setProviderLabel] = useS(uiT('自动识别'));
  const [formError, setFormError] = useS('');
  const successTimer = useR(null);

  useE(() => () => {
    if (successTimer.current) window.clearTimeout(successTimer.current);
  }, []);
  useE(() => {
    if (status !== 'error') setManualEntry(false);
  }, [status]);

  const submit = async (event) => {
    event.preventDefault();
    const candidate = apiKey.trim();
    if (!candidate) {
      setFormError(currentUiLanguage() === 'en' ? 'Enter an API key.' : '请输入 API Key。');
      return;
    }
    setSubmitting(true);
    setFormError('');
    const result = await onValidate(candidate);
    setSubmitting(false);
    if (!result?.ok) {
      setProviderLabel(uiT('自动识别'));
      setFormError(result?.message || (currentUiLanguage() === 'en' ? 'Verification failed. Please try again.' : '验证失败，请稍后重试。'));
      return;
    }
    setApiKey('');
    setProviderLabel(result.config?.provider_label || uiT('AI 服务'));
    setSuccess(true);
    successTimer.current = window.setTimeout(() => onConnected(result.config || {}), 720);
  };
  const removeStoredKey = async () => {
    const confirmed = window.confirm(currentUiLanguage() === 'en'
      ? 'Removing the saved API key will return to the sign-in screen. Chats, memories, and your profile will be kept. Continue?'
      : '清除已保存的 API Key 会返回登录界面。聊天、记忆和个人资料都会保留，继续吗？');
    if (!confirmed) return;
    setRemoving(true);
    setFormError('');
    const result = await onRemove();
    if (!result?.ok) {
      setRemoving(false);
      setFormError(result?.message || (currentUiLanguage() === 'en' ? 'Unable to remove the saved API key. Please try again later.' : '暂时无法清除已保存的 API Key，请稍后重试。'));
      setManualEntry(true);
    }
  };
  const feedbackText = formError || (success
    ? (currentUiLanguage() === 'en' ? `${providerLabel} connected. Opening Shulian…` : `${providerLabel} 已连接，正在进入数恋…`)
    : messageTone === 'error'
      ? message || ''
      : '');
  const feedbackIsError = Boolean(formError) || (!success && messageTone === 'error');
  const feedbackIsSuccess = success;
  const showRecovery = status === 'error' && !manualEntry;
  const providerState = status === 'checking'
    ? uiT('检查中')
    : submitting
      ? uiT('验证中')
      : success
        ? uiT('已连接')
        : showRecovery
          ? uiT('需处理')
          : uiT('待连接');
  return (
    <main className="api-gate-shell">
      <section className="api-gate-card" aria-label={uiT('连接 AI 服务')}>
        <div className="api-gate-brand" aria-label={uiT('数恋')}>
          <span className="api-gate-brand-mark"><BrandIcon size={30} /></span>
          <span className="api-gate-brand-copy"><strong>{uiT('数恋')}</strong></span>
        </div>

        <div className="api-gate-provider" aria-live="polite">
          <span className="api-gate-provider-mark" aria-hidden="true"><I.sparkle size={19} /></span>
          <div className="api-gate-provider-copy">
            <strong>{providerLabel}</strong>
            <span>{uiT('当前 AI 服务')}</span>
          </div>
          <span className={`api-gate-provider-state${success ? ' is-connected' : ''}`}>{providerState}</span>
        </div>

        {status === 'checking' ? (
          <div className="api-gate-state is-checking" role="status" aria-live="polite" aria-busy="true">
            <span className="api-gate-spinner" aria-hidden="true" />
            <span className="api-gate-state-copy">{uiT('正在检查 AI 服务连接…')}</span>
          </div>
        ) : showRecovery ? (
          <div className="api-gate-state" role="alert">
            <p className="api-gate-state-message">{message || uiT('AI 服务暂时不可用，请稍后重试。')}</p>
            <div className="api-gate-recovery">
              <button type="button" className="api-gate-secondary" onClick={onRetry}>{uiT('重新检查')}</button>
              <button type="button" className="api-gate-secondary" onClick={() => { setFormError(''); setManualEntry(true); }}>{uiT('切换账号')}</button>
              <button type="button" className="api-gate-secondary is-danger" disabled={removing} onClick={removeStoredKey}>{uiT(removing ? '正在清除' : '清除已保存 Key')}</button>
            </div>
          </div>
        ) : (
          <form className="api-gate-form" onSubmit={submit}>
            <span className={`api-key-input-wrap${formError ? ' is-error' : ''}`}>
              <input
                id="api-gate-key-input"
                type={visible ? 'text' : 'password'}
                value={apiKey}
                autoFocus
                autoComplete="off"
                spellCheck="false"
                placeholder={uiT('输入 API Key')}
                aria-label={uiT('AI 服务 API Key')}
                disabled={submitting || success}
                onChange={event => { setApiKey(event.target.value); setFormError(''); }}
                aria-describedby="api-key-error"
              />
              <button type="button" onClick={() => setVisible(value => !value)} disabled={submitting || success} aria-label={uiT(visible ? '隐藏 API Key' : '显示 API Key')} title={uiT(visible ? '隐藏 API Key' : '显示 API Key')}>
                {visible ? <I.eyeOff size={19} /> : <I.eye size={19} />}
              </button>
            </span>

            <div id="api-key-error" className={`api-gate-feedback${feedbackIsError ? ' is-error' : feedbackIsSuccess ? ' is-success' : ''}`} role={feedbackIsError ? 'alert' : 'status'} aria-live="polite">
              {feedbackText}
            </div>

            <button type="submit" className="api-gate-primary" disabled={submitting || success}>
              {submitting ? <><span className="api-gate-spinner is-small" aria-hidden="true" />{uiT('正在验证')}</> : uiT(success ? '连接成功' : '验证并进入')}
            </button>
          </form>
        )}
        <div className="api-gate-maintenance" aria-live="polite">
          {ACTIVE_UPDATE_STATUSES.has(maintenance?.job?.status) && (
            <div className="maintenance-progress is-compact" role="progressbar" aria-label={currentUiLanguage() === 'en' ? 'Shulian update progress' : '数恋更新进度'}
              aria-valuemin="0" aria-valuemax="100" aria-valuenow={Number(maintenance.job.percent) || 0}>
              <span style={{ width: `${Math.max(0, Math.min(100, Number(maintenance.job.percent) || 0))}%` }} />
            </div>
          )}
          {maintenance?.status?.updateMode === 'download' ? <>
            <button type="button" disabled={!maintenance.status.publicReleaseReady || maintenance?.loading}
              onClick={maintenance.openDownloads}>{uiT(maintenance.status.publicReleaseReady ? '打开公开下载页' : '下载页尚未开放')}</button>
            <p>{uiT('当前版本 v{version}', { version: maintenance.status.clientVersion || SHULIAN_APP_VERSION })}</p>
            <p>{uiT('更新前请备份角色、聊天和设置，不要先卸载。')}</p>
          </> : <button type="button" onClick={() => maintenance?.status?.updateAvailable ? maintenance.startUpdate() : maintenance?.refresh()}
            disabled={maintenance?.loading || ACTIVE_UPDATE_STATUSES.has(maintenance?.job?.status)}>
            {ACTIVE_UPDATE_STATUSES.has(maintenance?.job?.status)
              ? (currentUiLanguage() === 'en' ? `Updating in background ${Number(maintenance.job.percent) || 0}%` : `后台更新中 ${Number(maintenance.job.percent) || 0}%`)
              : maintenance?.status?.updateAvailable
                ? (currentUiLanguage() === 'en' ? `Update v${maintenance.status.sourceVersion} available` : `发现 v${maintenance.status.sourceVersion} 更新`)
                : uiT(maintenance?.loading ? '正在检查版本…' : '检查更新')}
          </button>}
          {maintenance?.error && <p role="alert">{uiT(maintenance.error)}</p>}
        </div>
      </section>
    </main>
  );
}

// Keep the wrapper component identity stable across MainApp re-renders. Defining
// this component inside MainApp remounted every settings/profile child whenever
// background status changed, which reset the selected settings category.
function DesktopPanelWrap({ wide, children, widePanel = false }) {
  return wide
    ? <div className={`desktop-panel-wrap${widePanel ? ' is-wide' : ''}`}>
        <div className="desktop-panel-surface" style={{ maxWidth: widePanel ? 980 : 680 }}>
          {children}
        </div>
      </div>
    : <React.Fragment>{children}</React.Fragment>;
}

function MainApp({ aiConfig, onAiConfigChange, onAiModelChange, onAiRemoved, onAiLoggedOut, maintenance }) {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [tab, setTab] = useS(() => sessionStorage.getItem('sl_open_custom_roles') === '1' ? 'gallery' : 'home');
  const [currentId, setCurrentId] = useS(() => {
    const stored = localStorage.getItem('sl_current_character');
    return ROSTER.some(c => c.id === stored) ? stored : (ROSTER[0]?.id || '');
  });
  const [chatId, setChatId] = useS(null);
  const [loverArchive, setLoverArchive] = useS(null); // { charId, section }
  const [chatInjection, setChatInjection] = useS(null);
  const [voiceId, setVoiceId] = useS(null);
  const [videoId, setVideoId] = useS(null);
  const [historyCharId, setHistoryCharId] = useS(null);   // 历史列表覆层
  const [profileCharId, setProfileCharId] = useS(null);   // 角色名片覆层
  const [viewingSession, setViewingSession] = useS(null); // { charId, idx } idx=-1=当前
  const [notifOpen, setNotifOpen] = useS(false);
  const [meSub, setMeSub] = useS(null); // null | 'profile' | 'settings' | 'ai-service'
  const profileDirtyRef = useR(false);
  const accountPanelTriggerRef = useR(null);
  const accountPanelKindRef = useR(null);
  const [userProfile, setUserProfile] = useS(() => normalizeUserProfile(readStoredObject('sl_user_profile')));
  // ── 桌面端检测（与 Phone 组件保持同一断点）──
  const wide = useWideLayout();
  const [notifications, setNotifications] = useS(() => {
    return readStoredArray('sl_notifications');
  });
  // ── 归档会话：从 localStorage 初始化 ──
  const [archivedSessions, setArchivedSessions] = useS(() => {
    return migrateSessionsCallBubbles(readStoredObject('sl_sessions'));
  });
  // ── 跨对话长期记忆：每角色一份摘要，新建对话也不会失忆 ──
  const [memories, setMemories] = useS(() => {
    const init = {};
    ROSTER.forEach(c => { init[c.id] = localStorage.getItem(`sl_memory_${c.id}`) || ''; });
    return init;
  });
  const memoriesRef = useR(memories);
  useE(() => { memoriesRef.current = memories; }, [memories]);
  const [memoryContexts, setMemoryContexts] = useS(() => {
    const init = {};
    ROSTER.forEach(c => {
      init[c.id] = sanitizeMemoryAddressDirection(
        c.id,
        localStorage.getItem(`sl_memory_context_${c.id}`),
        localStorage.getItem(`sl_memory_${c.id}`) || '',
      );
    });
    return init;
  });
  const memoryContextsRef = useR(memoryContexts);
  useE(() => { memoryContextsRef.current = memoryContexts; }, [memoryContexts]);
  const [companionContexts, setCompanionContexts] = useS(() => {
    const init = {};
    ROSTER.forEach(c => {
      init[c.id] = normalizeCompanionContext(
        localStorage.getItem(`sl_companion_context_${c.id}`),
        c.id,
      );
    });
    return init;
  });
  const companionContextsRef = useR(companionContexts);
  useE(() => { companionContextsRef.current = companionContexts; }, [companionContexts]);
  const legacyIntimaciesRef = useR(ROSTER.reduce((result, c) => {
    const parsed = Number.parseFloat(localStorage.getItem(`sl_intimacy_${c.id}`));
    result[c.id] = Number.isFinite(parsed) ? Math.max(1, Math.min(10, parsed)) : c.intimacy;
    return result;
  }, {}));
  const [relationshipAgreements, setRelationshipAgreements] = useS(() => {
    const init = {};
    ROSTER.forEach(c => {
      init[c.id] = sanitizeRelationshipAgreement(
        c.id,
        readStoredObject(`sl_relationship_${c.id}`),
        memoryContexts[c.id],
      );
    });
    return init;
  });
  const relationshipAgreementsRef = useR(relationshipAgreements);
  useE(() => { relationshipAgreementsRef.current = relationshipAgreements; }, [relationshipAgreements]);
  const companionForRequest = (id) => reconcileCompanionAddressDirections(
    companionContextsRef.current[id],
    id,
    relationshipAgreementsRef.current[id],
    memoryContextsRef.current[id],
  );
  const memoryForRequest = (id) => {
    const context = sanitizeMemoryAddressDirection(
      id,
      memoryContextsRef.current[id],
      memoriesRef.current[id] || '',
    );
    const agreement = sanitizeRelationshipAgreement(
      id,
      relationshipAgreementsRef.current[id],
      context,
    );
    const characterName = byId(id)?.name || id;
    const rules = [
      agreement.character_to_user_address && `- ${characterName} 对用户的称呼：${agreement.character_to_user_address}`,
      agreement.user_to_character_address && `- 用户对 ${characterName} 的称呼：${agreement.user_to_character_address}`,
      agreement.boundary && `- 相处边界：${agreement.boundary}`,
      agreement.contact && `- 主动联系：${agreement.contact}`,
    ].filter(Boolean);
    return serializeMemoryContext({
      ...context,
      relationship_facts: [...context.relationship_facts, ...rules],
    });
  };
  // ── 对话历史：从 localStorage 初始化，刷新页面不丢失 ──
  const [threads, setThreads] = useS(() => {
    return migrateThreadsCallBubbles(readStoredObject('sl_threads'));
  });
  // threads / archivedSessions 是全量聚合对象，流式回复期间每帧都在变；
  // 直接同步 JSON.stringify + 写盘会让输入和滚动逐渐发黏，所以统一走防抖写入器。
  const threadsWriter = React.useMemo(() => createDebouncedStorageWriter('sl_threads'), []);
  const sessionsWriter = React.useMemo(() => createDebouncedStorageWriter('sl_sessions'), []);
  const [typingId, setTypingId] = useS(null);
  const [toast, setToast] = useS(null);
  const [formSel, setFormSel] = useS({}); // { [charId]: formIndex }
  const [lastRead, setLastRead] = useS(() => { // { [charId]: timestamp } 上次打开聊天的时间
    return readStoredObject('sl_lastread');
  });
  const [liveStatuses, setLiveStatuses] = useS({});
  const pendingIds = useR(new Set());
  const memoryQueuesRef = useR({});
  const memorySequenceRef = useR({});
  const memoryPendingRef = useR(new Set());
  const callCarryoverRef = useR(null);
  if (callCarryoverRef.current === null) {
    callCarryoverRef.current = ROSTER.reduce((result, character) => {
      result[character.id] = normalizeCallCarryover(
        readStoredArray(`sl_call_carryover_${character.id}`),
      );
      return result;
    }, {});
  }
  const setCallCarryover = (id, turns) => {
    const normalized = normalizeCallCarryover(turns);
    callCarryoverRef.current = { ...callCarryoverRef.current, [id]: normalized };
    try { localStorage.setItem(`sl_call_carryover_${id}`, JSON.stringify(normalized)); } catch (e) { /* 临时上下文仍留在内存 */ }
    return normalized;
  };
  const clearCallCarryover = (id, expected) => {
    if (expected && callCarryoverRef.current[id] !== expected) return;
    callCarryoverRef.current = { ...callCarryoverRef.current, [id]: [] };
    try { localStorage.removeItem(`sl_call_carryover_${id}`); } catch (e) { /* 静默 */ }
  };
  // 新建窗口时旧对话尾部的交接上下文，刷新后仍可衔接，按轮次和时间过期。
  const windowHandoversRef = useR({});
  if (!windowHandoversRef.current.__ready) {
    const initial = {};
    ROSTER.forEach(character => {
      initial[character.id] = normalizeWindowHandover(readStoredObject(`sl_window_handover_${character.id}`));
    });
    initial.__ready = true;
    windowHandoversRef.current = initial;
  }
  const windowHandoverFor = (id) => {
    const handover = windowHandoversRef.current[id];
    if (!handover) return null;
    if (windowHandoverExpired(handover)) {
      windowHandoversRef.current = { ...windowHandoversRef.current, [id]: null };
      try { localStorage.removeItem(`sl_window_handover_${id}`); } catch (e) { /* 静默 */ }
      return null;
    }
    return handover;
  };
  const setWindowHandover = (id, messages) => {
    const handover = normalizeWindowHandover({ messages, createdAt: Date.now(), turns: 0 });
    windowHandoversRef.current = { ...windowHandoversRef.current, [id]: handover };
    try {
      if (handover) localStorage.setItem(`sl_window_handover_${id}`, JSON.stringify(handover));
      else localStorage.removeItem(`sl_window_handover_${id}`);
    } catch (e) { /* 容量满时仍保留内存交接 */ }
    return handover;
  };
  const consumeWindowHandover = (id) => {
    const handover = windowHandoverFor(id);
    if (!handover) return;
    const next = { ...handover, turns: handover.turns + 1 };
    windowHandoversRef.current = { ...windowHandoversRef.current, [id]: next };
    try { localStorage.setItem(`sl_window_handover_${id}`, JSON.stringify(next)); } catch (e) { /* 静默 */ }
  };
  const historyForRequest = (id, messages, limit = 24, consume = true) => {
    const handover = windowHandoverFor(id);
    const merged = [
      ...(handover ? handover.messages : []),
      ...(Array.isArray(messages) ? messages : []),
      ...(callCarryoverRef.current[id] || []),
    ].map((message, index) => ({ message, index }))
      .sort((left, right) => {
        const leftTs = Number(left.message?.ts) || 0;
        const rightTs = Number(right.message?.ts) || 0;
        if (leftTs && rightTs && leftTs !== rightTs) return leftTs - rightTs;
        return left.index - right.index;
      })
      .map(item => item.message);
    if (handover && consume) consumeWindowHandover(id);
    return toApiHistory(merged, limit);
  };
  const recordHomeGreeting = (id, key, value) => {
    const text = String(value || '').trim();
    if (!text) return;
    setThreads(prev => {
      const current = prev[id] || [];
      if (current.some(message => message?.origin === 'home-greeting' && message.greetingKey === key)) return prev;
      return {
        ...prev,
        [id]: [...current, {
          from: 'her', text, ts: Date.now(), origin: 'home-greeting', greetingKey: key,
        }],
      };
    });
  };

  // ── 亲密度：从 localStorage 初始化，每角色独立存储 ──
  const [intimacies, setIntimacies] = useS(() => {
    const init = {};
    ROSTER.forEach(c => {
      const context = normalizeCompanionContext(localStorage.getItem(`sl_companion_context_${c.id}`), c.id);
      init[c.id] = context.relationship.level;
    });
    return init;
  });
  const intimaciesRef = useR(intimacies);
  useE(() => { intimaciesRef.current = intimacies; }, [intimacies]);
  const intimacyForRequest = (id, delta = 0) => {
    // 兼容 v20 接口与旧组件：旧亲密度键只镜像 v21 关系等级，不再逐消息累加。
    return companionForRequest(id).relationship.level;
  };

  const archiveRoleLibrary = async () => {
    const results = [];
    for (const character of ROSTER) {
      const id = character.id;
      const storedStart = Number(localStorage.getItem(`sl_start_${id}`));
      const response = await fetch(`${API_BASE}/api/role-library/${encodeURIComponent(id)}/snapshots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          frontend_profile: character,
          relationship: sanitizeRelationshipAgreement(
            id,
            relationshipAgreementsRef.current[id],
            memoryContextsRef.current[id],
          ),
          memory: memoriesRef.current[id] || '',
          memory_context: memoryForRequest(id),
          intimacy: intimacyForRequest(id),
          companion_context: companionForRequest(id),
          started_at: Number.isFinite(storedStart) && storedStart > 0 ? storedStart : null,
          current_messages: threads[id] || [],
          archived_sessions: archivedSessions[id] || [],
        }),
      });
      if (!response.ok) {
        let message = `角色 ${character.name} 的档案写入失败`;
        try {
          const error = await response.json();
          if (typeof error?.detail === 'string') message = error.detail;
        } catch (e) { /* keep readable fallback */ }
        const failure = new Error(message);
        failure.completed = results;
        throw failure;
      }
      results.push(await response.json());
    }
    return {
      ok: true,
      roles: results.length,
      messages: results.reduce((sum, item) => sum + Number(item.messageCount || 0), 0),
      snapshots: results,
    };
  };

  useE(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('archive-role-library') !== '1') return undefined;
    window.__shulianArchiveRoleLibrary = archiveRoleLibrary;
    return () => { delete window.__shulianArchiveRoleLibrary; };
  }, [threads, archivedSessions, memories, memoryContexts, companionContexts, relationshipAgreements, intimacies]);

  const base = mergeForm(byId(currentId), formSel[currentId]) || { id: '', name: '', hue: 275, intimacy: 1, forms: [] };
  const currentContext = companionForRequest(currentId);
  const current = {
    ...base,
    intimacy: currentContext.relationship.level,
    companionContext: currentContext,
    relationship: currentContext.relationship,
  };
  const withCompanionContext = (character) => {
    const context = companionForRequest(character.id);
    return {
      ...character,
      intimacy: context.relationship.level,
      companionContext: context,
      relationship: context.relationship,
    };
  };

  // The visible character can differ from currentId when chat/history/profile
  // is opened from the lover list or notifications. Theme the visible role.
  const accentCharacterId =
    videoId ||
    voiceId ||
    viewingSession?.charId ||
    profileCharId ||
    historyCharId ||
    chatId ||
    loverArchive?.charId ||
    currentId;

  // ── 当前心动角色驱动强调色；Tweaks 只保留玻璃和动效参数 ──
  useE(() => {
    const root = document.documentElement.style;
    const palette = CHARACTER_ACCENTS[accentCharacterId] || { accent: 'oklch(0.72 0.18 305)', accent2: 'oklch(0.68 0.20 350)', accent3: 'oklch(0.78 0.15 265)', ink: 'oklch(0.42 0.16 320)' };
    root.setProperty('--accent', palette.accent);
    root.setProperty('--accent-2', palette.accent2);
    root.setProperty('--accent-3', palette.accent3);
    root.setProperty('--accent-ink', palette.ink);
    const g = t.glassIntensity; // 0..10
    root.setProperty('--glass-blur', (6 + g * 2.6).toFixed(1) + 'px');
    root.setProperty('--glass-tint', (0.04 + g * 0.012).toFixed(3));
    root.setProperty('--glass-tint-hi', (0.08 + g * 0.018).toFixed(3));
    root.setProperty('--glass-border', (0.10 + g * 0.018).toFixed(3));
    root.setProperty('--glass-specular', (0.18 + g * 0.055).toFixed(3));
    root.setProperty('--glass-shadow', (0.16 + g * 0.026).toFixed(3));
    root.setProperty('--aurora-play', t.aurora ? 'running' : 'paused');
  }, [accentCharacterId, t.glassIntensity, t.aurora]);

  const flash = (msg) => { setToast(msg); setTimeout(() => setToast(null), 1700); };

  const applyLiveStatus = (id, status) => {
    if (!id || !status || typeof status !== 'object') return;
    setLiveStatuses(prev => ({ ...prev, [id]: status }));
  };

  // 后端状态是权威来源；前端时间表只作为首次渲染或服务不可用时的兜底。
  useE(() => {
    let active = true;
    const refresh = async () => {
      const ids = [...new Set([currentId, chatId].filter(Boolean))];
      await Promise.all(ids.map(async id => {
        try {
          const res = await fetch(`${API_BASE}/api/characters/${encodeURIComponent(id)}/status`, { cache: 'no-store' });
          if (!res.ok) return;
          const status = await res.json();
          if (active) applyLiveStatus(id, status);
        } catch (e) { /* 保留前端兜底状态 */ }
      }));
    };
    refresh();
    const timer = setInterval(refresh, 60000);
    return () => { active = false; clearInterval(timer); };
  }, [currentId, chatId]);

  // ── 主动消息机制：角色定时发来消息，不在聊天窗口时积累为未读 ──
  const chatIdRef = useR(chatId);
  useE(() => { chatIdRef.current = chatId; }, [chatId]);

  const nudgeChar = async (id) => {
    // 如果用户正在和这个角色聊天，跳过（不打扰）
    if (chatIdRef.current === id) return;
    if (pendingIds.current.has(id) || memoryPendingRef.current.has(id)) return;
    // 检查"主动消息"开关，关闭时静默跳过
    try { const s = JSON.parse(localStorage.getItem('sl_settings') || '{}'); if (s.nudge === false) return; } catch (e) { /* 静默 */ }

    const thread = (window.__threads || {})[id] || [];
    const lastActivity = [...thread].reverse().find(message =>
      message && (message.from === 'me' || message.from === 'her') && Number(message.ts) > 0);
    if (lastActivity && Date.now() - Number(lastActivity.ts) < PROACTIVE_IDLE_MS) return;

    // 主动消息也必须服从角色当前生活状态；睡觉或共同休息时不主动打扰。
    let liveStatus = null;
    try {
      const statusRes = await fetch(`${API_BASE}/api/characters/${encodeURIComponent(id)}/status`, { cache: 'no-store' });
      if (!statusRes.ok) return;
      liveStatus = await statusRes.json();
      applyLiveStatus(id, liveStatus);
    } catch (e) {
      // 无法确认当前状态时不生成主动消息，避免拿旧状态覆盖连续性。
      return;
    }
    // A persisted shared scene means the two are already together.  A remote
    // notification in the middle of that meal/walk/rest would split one scene
    // into two incompatible channels, so proactive messaging resumes only
    // after the shared scene ends.
    if (liveStatus?.source === 'conversation' || liveStatus?.tone === 'sleep') return;

    // 主动消息只按当前窗口和通话上下文生成，不把上一个窗口的尾部当成“刚刚发生”。
    const history = historyForRequest(id, thread, 20, false);
    const nudgeContext = JSON.stringify(thread);
    try {
      const res = await fetch(`${API_BASE}/api/chat/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: (() => {
            const h = new Date().getHours();
            const period = h < 6 ? '凌晨' : h < 9 ? '清晨' : h < 12 ? '上午' : h < 14 ? '中午' : h < 18 ? '下午' : h < 22 ? '晚上' : '深夜';
            return `（这是一次主动消息。现在是${period}，请根据角色当前生活状态自然联系用户，1-2句即可。不要主动声称昨天、昨晚或上次发生过具体会面、动作或承诺；不要凭空切换到工作、公文、明早计划或与当前状态冲突的内容，不要提这是系统指令）`;
          })(),
          history,
          memory_context: memoryForRequest(id),
          intimacy: intimacyForRequest(id),
          companion_context: companionForRequest(id),
          proactive: true,
          channel: 'proactive',
        }),
      });
      if (!res.ok) return;
      const data = await res.json();
      // Discard a delayed nudge after the user starts a turn or changes sessions.
      if (chatIdRef.current === id || pendingIds.current.has(id)
        || memoryPendingRef.current.has(id)
        || (() => {
          const latest = [...((window.__threads || {})[id] || [])].reverse().find(message =>
            message && (message.from === 'me' || message.from === 'her') && Number(message.ts) > 0);
          return latest && Date.now() - Number(latest.ts) < PROACTIVE_IDLE_MS;
        })()
        || JSON.stringify((window.__threads || {})[id] || []) !== nudgeContext) return;
      applyLiveStatus(id, data.status);
      const reply = requireSafeCharacterReply(id, data.reply);
      const nudgeTs = Date.now();
      setThreads(prev => {
        const updated = {
          ...prev,
          [id]: [
            ...(prev[id] || []),
            { from: 'her', text: reply, ts: nudgeTs, origin: 'proactive' },
          ],
        };
        window.__threads = updated;
        return updated;
      });
      setNotifications(prev => [{ id: nudgeTs, charId: id, text: reply, ts: nudgeTs, read: false }, ...prev].slice(0, 50));
      flash(`💌 ${byId(id).name} 发来了消息`);
    } catch (e) { /* 静默失败 */ }
  };

  // 当前恋人变化时，取消旧计时器并为新恋人安排主动消息。
  useE(() => {
    let stopped = false;
    let timerId = null;
    const schedule = () => {
      // 在线 30~60 分钟才主动发一次消息，太频繁像强迫角色营业
      const delay = (30 + Math.random() * 30) * 60 * 1000;
      timerId = setTimeout(async () => {
        await nudgeChar(currentId);
        if (!stopped) schedule();
      }, delay);
    };
    schedule();
    return () => {
      stopped = true;
      clearTimeout(timerId);
    };
  }, [currentId]);

  // threads 更新时同步到 window（供 nudgeChar 访问，必须同步、不能防抖）；
  // 落盘走防抖，序列化推迟到真正写入那一刻，避免每帧全量 stringify。
  useE(() => {
    window.__threads = threads;
    threadsWriter.schedule(() => JSON.stringify(threads));
  }, [threads]);
  useE(() => () => { threadsWriter.flush(); sessionsWriter.flush(); }, []);

  // ── AI 今日招呼：按"角色+日期+时段+当前场景"缓存；失败时首页回落手写池 ──
  const aiGreets = useHomeGreeting({ currentId, liveStatuses, intimacies, historyForRequest, memoryForRequest, intimacyForRequest, companionForRequest, applyLiveStatus });

  useMainAppPersistence({ currentId, lastRead, archivedSessions, notifications, memories, memoryContexts, companionContexts, relationshipAgreements, sessionsWriter, memoriesRef, memoryContextsRef, relationshipAgreementsRef, setIntimacies });

  // ── 统一整理关系、经历与记忆；同一角色的请求严格串行 ──
  const { consolidateContext, updateMemory, maybePeriodicConsolidate } = createContextConsolidator({ memorySequenceRef, memoryPendingRef, memoryQueuesRef, memoryContextsRef, companionContextsRef, relationshipAgreementsRef, memoriesRef, legacyIntimaciesRef, archivedSessions, companionForRequest, flash, setThreads, setCompanionContexts, setMemoryContexts });

  // A call can end immediately before the user sends a text.  Recover any
  // temporary transcript left by a previous process and consolidate it before
  // eventually deleting the carryover key.
  useE(() => {
    Object.entries(callCarryoverRef.current).forEach(([id, turns]) => {
      if (!Array.isArray(turns) || !turns.some(item => item.from === 'me')) return;
      updateMemory(id, turns, 'call_end').then(ok => {
        if (ok) clearCallCarryover(id, turns);
      });
    });
  }, []);

  // 首次运行 v21 时扫描旧关系、当前线程和去重归档。旧键与聊天原文保留不动。
  useE(() => {
    let cancelled = false;
    (async () => {
      for (const character of ROSTER) {
        const id = character.id;
        if (cancelled || companionForRequest(id).migration.completed) continue;
        await consolidateContext(id, threads[id] || [], 'migration', true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 归档当前对话并开启新会话：窗口立即建立，记忆整理与状态刷新在后台进行。
  // 新窗口等待用户先开口，避免角色在没有明确输入时自行编造地点、计划或共同经历。
  const archiveAndNewChat = async (id) => {
    if (pendingIds.current.has(id)) {
      flash('请等她回复完再开启新对话');
      return false;
    }
    const current = threads[id] || [];
    const realMessages = current.filter(message => message
      && (message.from === 'me' || message.from === 'her')
      && message.origin !== 'legacy-static-greeting'
      && !isLegacyStaticGreetingText(message.text)
      && !isLegacyGuardFallbackText(message.text));
    if (!realMessages.length) return false;
    const hasPairs = countCompleteHistoryPairs(current) > 0;
    const now = Date.now();
    // 1) 立即建立新窗口。旧窗口尾部作为交接上下文保留，供接下来几轮继续衔接；
    //    这里不再等待模型，否则模型变慢就会表现成“点了新建没反应”。
    setArchivedSessions(prev => ({
      ...prev,
      [id]: [...(prev[id] || []), { startTs: current[0]?.ts || now, endTs: current[current.length - 1]?.ts || now, messages: current }]
    }));
    // A fixed “你来了” line can contradict an ongoing meal/rest scene and
    // must not impersonate a fresh character reply before the user has spoken.
    setThreads(prev => ({ ...prev, [id]: [] }));
    setWindowHandover(id, current);
    // 2) 记忆整理转入后台队列：失败只提示，不把已经建立的新窗口收回。
    if (hasPairs) {
      updateMemory(id, current, 'new_chat').then(consolidated => {
        if (!consolidated) flash('上一段对话的整理没有成功，稍后会继续补上');
      });
    }
    // 3) 状态刷新不阻塞用户输入；新窗口不再请求模型主动开场。
    void (async () => {
      try {
        const statusResponse = await fetch(`${API_BASE}/api/characters/${encodeURIComponent(id)}/status`, { cache: 'no-store' });
        if (statusResponse.ok) applyLiveStatus(id, await statusResponse.json());
      } catch (e) { /* 状态刷新失败不影响新窗口使用 */ }
    })();
    return true;
  };

  const openHistory = (id) => { setHistoryCharId(id); };
  const deleteArchivedSession = (id, idx) => {
    setArchivedSessions(prev => {
      const sessions = Array.isArray(prev[id]) ? prev[id] : [];
      if (!Number.isInteger(idx) || idx < 0 || idx >= sessions.length) return prev;
      return { ...prev, [id]: sessions.filter((_, sessionIdx) => sessionIdx !== idx) };
    });
    flash('历史会话已删除');
  };
  const openProfile = (id) => { setProfileCharId(id); };
  const saveCharacterMemory = (id, nextMemory) => {
    const text = String(nextMemory || '').trim();
    setMemories(prev => ({ ...prev, [id]: text }));
    const nextContext = sanitizeMemoryAddressDirection(id, migrateLegacyMemory(text));
    memoryContextsRef.current = { ...memoryContextsRef.current, [id]: nextContext };
    setMemoryContexts(prev => ({ ...prev, [id]: nextContext }));
  };
  const saveRelationshipAgreement = (id, nextAgreement) => {
    const sanitized = sanitizeRelationshipAgreement(id, nextAgreement, memoryContextsRef.current[id]);
    relationshipAgreementsRef.current = { ...relationshipAgreementsRef.current, [id]: sanitized };
    setRelationshipAgreements(prev => ({ ...prev, [id]: sanitized }));
    const reconciled = reconcileCompanionAddressDirections(
      companionContextsRef.current[id],
      id,
      sanitized,
      memoryContextsRef.current[id],
    );
    companionContextsRef.current = { ...companionContextsRef.current, [id]: reconciled };
    setCompanionContexts(prev => ({ ...prev, [id]: reconciled }));
    flash('关系约定已保存，将影响之后的互动');
  };
  const { saveUserProfile, navigateFromProfile, openAccountPanel, closeAccountPanel } = createAccountActions({ flash, profileDirtyRef, accountPanelTriggerRef, accountPanelKindRef, meSub, setMeSub, setUserProfile });

  const ensureThread = (id) => {
    setThreads(prev => Object.prototype.hasOwnProperty.call(prev, id) ? prev : { ...prev, [id]: [] });
  };
  const openChat = (id, transition = null) => {
    ensureThread(id);
    setLastRead(prev => ({ ...prev, [id]: Date.now() }));
    try { localStorage.setItem('sl_last_chat', id); } catch (e) { /* 本轮仍可正常打开 */ }
    // The frame injector is only for the horizontal message-list -> chat transition.
    // Opening a chat from the home greeting has no matching source geometry, and the
    // clip-path/glow animation causes visible flashing on lower-end WebView GPUs.
    const shouldInject = transition?.source === 'message-list';
    if (shouldInject) {
      const rawOriginY = Number(transition.originY);
      const originY = Number.isFinite(rawOriginY) ? Math.max(0.08, Math.min(0.92, rawOriginY)) : 0.18;
      const rawOriginOffsetY = Number(transition.originOffsetY);
      const originOffsetY = Number.isFinite(rawOriginOffsetY) ? Math.max(0, rawOriginOffsetY) : null;
      setChatInjection(prev => ({
        token: (prev?.token || 0) + 1,
        source: 'message-list',
        originY,
        originOffsetY,
      }));
    } else {
      setChatInjection(null);
    }
    chatIdRef.current = id;
    setChatId(id);
  };
  useE(() => {
    if (!wide || tab !== 'messages' || chatId) return;
    let rememberedId = '';
    try { rememberedId = localStorage.getItem('sl_last_chat') || ''; } catch (e) { /* 使用当前或最新会话 */ }
    const restoreId = pickDesktopConversationId(threads, rememberedId, currentId);
    if (restoreId) openChat(restoreId);
  }, [wide, tab, chatId, currentId, threads]);
  const openLoverArchive = (id, section = 'known') => {
    setChatId(null);
    setLoverArchive({ charId: id, section });
    setTab('gallery');
  };
  const openMessagesChat = (id) => {
    setLoverArchive(null);
    setTab('messages');
    openChat(id);
  };
  const openVoice = (id) => {
    if (pendingIds.current.has(id)) { flash('请等当前回复完成后再开始通话'); return; }
    setVoiceId(id);
  };
  const openVideo = (id) => {
    if (pendingIds.current.has(id)) { flash('请等当前回复完成后再开始通话'); return; }
    setVideoId(id);
  };

  const { giftHome, setCurrent, synthHerVoice, sendVoiceMessage, sendMessage, sendImageMessage } = createChatSenders({ currentId, setCurrentId, pendingIds, flash, ensureThread, threads, setThreads, setTypingId, setNotifications, historyForRequest, memoryForRequest, intimacyForRequest, companionForRequest, applyLiveStatus, maybePeriodicConsolidate, chatIdRef });

  // ── screen routing ──
  let screen;
  if (tab === 'home' && ROSTER.length) screen = <HomeScreen current={current} liveStatusOverride={liveStatuses[currentId]} aiGreet={(aiGreets[currentId] || {}).text} greetingKey={(aiGreets[currentId] || {}).key} onGreetingShown={(key, text) => recordHomeGreeting(currentId, key, text)} openMessagesChat={openMessagesChat} openVoice={openVoice} formIdx={formSel[currentId] || 0} setForm={(i) => setFormSel(p => ({ ...p, [currentId]: i }))} notifications={notifications} onBellClick={() => setNotifOpen(true)} threads={threads} onGiftHome={giftHome} openArchive={openLoverArchive} />;
  else if (tab === 'gallery' || !ROSTER.length) {
    const archiveId = loverArchive?.charId;
    screen = archiveId ? (
      <LoverArchiveScreen
        c={mergeForm(byId(archiveId), formSel[archiveId])}
        memory={memories[archiveId] || ''}
        thread={threads[archiveId] || []}
        archived={archivedSessions[archiveId] || []}
        agreements={relationshipAgreements[archiveId] || {}}
        initialSection={loverArchive.section || 'known'}
        onBack={() => setLoverArchive(null)}
        onOpenMessages={() => openMessagesChat(archiveId)}
        onOpenHistory={() => openHistory(archiveId)}
        onUpdateMemory={(nextMemory) => saveCharacterMemory(archiveId, nextMemory)}
        onSaveAgreements={(nextAgreement) => saveRelationshipAgreement(archiveId, nextAgreement)}
      />
    ) : <GalleryScreen current={current} setCurrent={setCurrent} onOpenArchive={openLoverArchive} />;
  }
  else if (tab === 'messages') screen = <MessagesScreen current={current} openChat={openChat} threads={threads} lastRead={lastRead} activeChatId={chatId} />;
  else screen = <MeScreen openProfile={() => openAccountPanel('profile', () => setMeSub('profile'))} openSettings={() => openAccountPanel('settings', () => setMeSub('settings'))} userProfile={userProfile} />;

  // 桌面端消息页使用稳定的会话列表 + 对话工作区布局。
  const isDesktopMsg = wide && tab === 'messages';

  // 面板覆层：绝对定位覆盖双栏
  const panelOverlay = meSub || notifOpen || historyCharId || viewingSession || profileCharId;
  const inOverlay = isDesktopMsg
    ? (panelOverlay || voiceId || videoId)
    : (chatId || voiceId || videoId || panelOverlay || loverArchive);

  // 通话中（语音/视频共用）：用户说一句 → 拿到 AI 回复。
  // 通话内容不再逐句写进聊天记录（真实通话也只留一条小结，见 endCallRecord）；
  // 通话过程中的上下文由 callTurns（本次通话内累积的对话）提供。
  const { callContext, callSend, endCallRecord } = createCallController({ threads, setThreads, historyForRequest, memoryForRequest, intimacyForRequest, companionForRequest, applyLiveStatus, setCallCarryover, clearCallCarryover, callCarryoverRef, updateMemory });

  // 可复用的 ChatThread 构建函数
  const makeChatThread = (id) => (
    <ChatThread
      key={id}
      c={withCompanionContext(mergeForm(byId(id), formSel[id]))}
      messages={threads[id] || []}
      typing={typingId === id}
      canSend={() => !pendingIds.current.has(id)}
      liveStatusOverride={liveStatuses[id]}
      onSend={(text) => sendMessage(id, text)}
      onBack={() => { chatIdRef.current = null; setChatId(null); }}
      onVoice={() => openVoice(id)}
      onVideo={() => openVideo(id)}
      onProfile={() => openProfile(id)}
      onVoiceMsg={(dur, transcript, audioBlob) => sendVoiceMessage(id, dur, transcript, audioBlob)}
       onNewChat={() => {
         archiveAndNewChat(id).then(opened => {
           if (opened) flash('💬 已开启新对话');
         });
       }}
      onSendImage={(imageUrl, caption) => sendImageMessage(id, imageUrl, caption)}
      injection={chatInjection}
    />
  );

  return (
    <React.Fragment>
      <Phone
        bottomBar={!inOverlay}
        activeTab={tab}
        userProfile={userProfile}
        onTab={(x) => navigateFromProfile(null, () => { accountPanelTriggerRef.current = null; accountPanelKindRef.current = null; setChatId(null); setLoverArchive(null); setHistoryCharId(null); setProfileCharId(null); setViewingSession(null); setNotifOpen(false); setMeSub(null); setTab(x); })}
        onOpenAccount={() => navigateFromProfile('profile', () => openAccountPanel('profile', () => { setChatId(null); setLoverArchive(null); setHistoryCharId(null); setProfileCharId(null); setViewingSession(null); setNotifOpen(false); setMeSub('profile'); }))}
        onOpenSettings={() => navigateFromProfile('settings', () => openAccountPanel('settings', () => { setChatId(null); setLoverArchive(null); setHistoryCharId(null); setProfileCharId(null); setViewingSession(null); setNotifOpen(false); setMeSub('settings'); }))}
      >

        {/* ══ 桌面消息双栏 ══ */}
        {isDesktopMsg && (
          <div className="desktop-messages-layout">
            <div className="msg-panel-list">
              <MessagesScreen current={current} openChat={(id, transition) => { openChat(id, transition); }} threads={threads} lastRead={lastRead} activeChatId={chatId} />
            </div>
            <div className="msg-panel-conversation">
              {chatId ? makeChatThread(chatId) : (
                <div className="desktop-chat-empty" role="status">暂无消息</div>
              )}
            </div>
          </div>
        )}

        {/* ══ 移动端 / 非消息页面 ══ */}
        {!isDesktopMsg && !chatId && !panelOverlay && screen}
        {!isDesktopMsg && chatId && !panelOverlay && <DesktopPanelWrap wide={wide}>{makeChatThread(chatId)}</DesktopPanelWrap>}

        {/* ══ 语音 / 视频通话（自带 absolute 全覆盖）══ */}
        {voiceId && <VoiceCall
          c={mergeForm(byId(voiceId), formSel[voiceId])}
          onEnd={(info) => { endCallRecord(voiceId, 'voice', info); setVoiceId(null); }}
          onContext={callTurns => callContext(voiceId, '语音', callTurns)}
          onSend={(text, callTurns) => callSend(voiceId, text, '语音', callTurns)}
        />}
        {videoId && <VideoCall
          c={mergeForm(byId(videoId), formSel[videoId])}
          onEnd={(info) => { endCallRecord(videoId, 'video', info); setVideoId(null); }}
          onContext={callTurns => callContext(videoId, '视频', callTurns)}
          onSend={(text, callTurns) => callSend(videoId, text, '视频', callTurns)}
        />}

        {/* ══ 面板覆层（用 absolute 包裹，确保覆盖双栏）══ */}
        {panelOverlay && (
          <div style={{ position: 'absolute', inset: 0, zIndex: 50, background: isDesktopMsg ? 'var(--app-background)' : undefined }}>
            <DesktopPanelWrap wide={wide} widePanel={meSub === 'settings'}>
            {meSub && (
              <MePanel
                kind={meSub}
                onBack={closeAccountPanel}
                onBackToSettings={() => {
                  setMeSub('settings');
                  requestAnimationFrame(() => document.querySelector('[data-settings-entry="ai-service"]')?.focus({ preventScroll: true }));
                }}
                onOpenAiService={() => setMeSub('ai-service')}
                aiConfig={aiConfig}
                onAiConfigChange={onAiConfigChange}
                onAiModelChange={onAiModelChange}
                onAiRemoved={onAiRemoved}
                onAiLoggedOut={onAiLoggedOut}
                maintenance={maintenance}
                userProfile={userProfile}
                onSaveProfile={saveUserProfile}
                onProfileDirtyChange={(dirty) => { profileDirtyRef.current = dirty; }}
                onArchiveRoleLibrary={archiveRoleLibrary}
                onClearData={async () => {
                  if (window.confirm(uiT('确定清除所有数恋本机数据吗？\n对话、记忆、亲密度、关系约定和个人资料都将被重置，此操作不可恢复。'))) {
                    try {
                      await window.shulianReplacePersistentState({});
                      window.location.reload();
                    } catch (e) {
                      flash(uiT('清除失败，请稍后重试'));
                    }
                  }
                }}
              />
            )}
            {profileCharId && (
              <CharacterProfilePanel
                c={withCompanionContext(mergeForm(byId(profileCharId), formSel[profileCharId]))}
                onBack={() => setProfileCharId(null)}
                onOpenChat={() => { const id = profileCharId; setProfileCharId(null); openChat(id); }}
                onOpenHistory={() => { const id = profileCharId; setProfileCharId(null); openHistory(id); }}
              />
            )}
            {notifOpen && (
              <NotifPanel
                notifications={notifications}
                onOpenChat={(charId) => {
                  setNotifOpen(false);
                  setNotifications(prev => prev.map(n => ({ ...n, read: true })));
                  openMessagesChat(charId);
                }}
                onClose={() => {
                  setNotifOpen(false);
                  setNotifications(prev => prev.map(n => ({ ...n, read: true })));
                }}
                onMarkAll={() => setNotifications(prev => prev.map(n => ({ ...n, read: true })))}
                onClearAll={() => { if (window.confirm(uiT('清空所有通知记录？'))) setNotifications([]); }}
              />
            )}
            {historyCharId && !viewingSession && (
              <ChatHistoryScreen
                c={byId(historyCharId)}
                currentThread={threads[historyCharId] || []}
                archived={archivedSessions[historyCharId] || []}
                onOpenChat={() => {
                  const id = historyCharId;
                  setHistoryCharId(null);
                  if (loverArchive?.charId) openMessagesChat(id);
                  else openChat(id);
                }}
                onViewSession={(idx) => setViewingSession({ charId: historyCharId, idx })}
                onDeleteSession={(idx) => deleteArchivedSession(historyCharId, idx)}
                onBack={() => setHistoryCharId(null)}
              />
            )}
            {viewingSession && (
              <SessionReadScreen
                c={byId(viewingSession.charId)}
                session={viewingSession.idx === -1
                  ? { messages: threads[viewingSession.charId] || [], startTs: (threads[viewingSession.charId] || [])[0]?.ts }
                  : archivedSessions[viewingSession.charId][viewingSession.idx]}
                onBack={() => setViewingSession(null)}
              />
            )}
            </DesktopPanelWrap>
          </div>
        )}

        {/* toast */}
        {toast && (
          <div style={{ position: 'absolute', top: 70, left: '50%', transform: 'translateX(-50%)', zIndex: 90 }}>
            <Glass radius={16} variant="glass-strong" className="fade-rise app-toast" style={{ padding: '10px 18px', color: 'var(--ink)', fontSize: 13.5, fontWeight: 600, whiteSpace: 'nowrap', boxShadow: '0 12px 30px rgba(0,0,0,0.4)' }}>{toast}</Glass>
          </div>
        )}
      </Phone>

      {/* ───────── Tweaks ───────── */}
      <TweaksPanel title="Tweaks">
        <TweakSection label="液态玻璃" />
        <TweakSlider label="玻璃强度" value={t.glassIntensity} min={0} max={10} step={1}
          onChange={(v) => setTweak('glassIntensity', v)} />
        <TweakToggle label="极光氛围动效" value={t.aurora}
          onChange={(v) => setTweak('aurora', v)} />

      </TweaksPanel>
    </React.Fragment>
  );
}

// ── MainApp 拆分单元 ───────────────────────────────────────────
// MainApp 原本近 1500 行。下列 hook 与工厂各自对应一块明确职责，由 MainApp 组合调用；
// 放在 MainApp 之后是因为函数声明会提升，且这些单元不依赖组件作用域的任何顺序。

// 首页 AI 招呼：按角色 + 日期 + 时段 + 当前场景缓存，失败时回落到首页手写池。
function useHomeGreeting({ currentId, liveStatuses, intimacies, historyForRequest, memoryForRequest, intimacyForRequest, companionForRequest, applyLiveStatus }) {
  const [aiGreets, setAiGreets] = useS({}); // { [id]: { key, text } } text: null=生成中 ''=失败
  useE(() => {
    const id = currentId;
    const now = new Date();
    const h = now.getHours();
    const period = h < 6 ? '凌晨' : h < 12 ? '上午' : h < 18 ? '下午' : h < 22 ? '晚上' : '深夜';
    const level = Math.floor(intimacyForRequest(id));
    const liveStatus = liveStatuses[id];
    if (!liveStatus) return; // 先等待后端权威状态，避免在睡眠状态尚未返回时抢先生成招呼。
    const sceneKey = liveStatus?.source === 'conversation'
      ? `conversation:${liveStatus.scene || 'shared'}:${liveStatus.expires_at || ''}`
      : `schedule:${liveStatus?.label || 'pending'}`;
    const key = `g${GREETING_CACHE_VERSION}|${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}|${period}|lv${level}|${sceneKey}`;
    if (
      liveStatus?.source === 'conversation'
      || liveStatus?.tone === 'sleep'
      || liveStatus?.scene === 'sleep'
    ) {
      setAiGreets(previous => ({ ...previous, [id]: { key, text: '', suppressed: true } }));
      return;
    }
    const existing = aiGreets[id];
    if (existing && existing.key === key && existing.text !== '') return; // 已生成或正在生成
    try {
      const cached = JSON.parse(localStorage.getItem(`sl_greet_${id}`) || 'null');
      if (cached && cached.key === key && cached.text
          && !startsWithCharacterSelfVocative(id, cached.text)
          && !isLegacyGuardFallbackText(cached.text)
          && !isLegacyStaticGreetingText(cached.text)) {
        setAiGreets(p => ({ ...p, [id]: cached }));
        return;
      }
    } catch (e) { /* 静默 */ }
    setAiGreets(p => ({ ...p, [id]: { key, text: null } }));
    (async () => {
      try {
        // 首页招呼只按当前窗口取历史，不消耗也不复述刚结束窗口的交接内容。
        const history = historyForRequest(id, (window.__threads || {})[id] || [], 6, false);
        const res = await fetch(`${API_BASE}/api/chat/${id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: `（用户刚打开应用来到首页。现在是${period}，请说一句见面的招呼，1-2句、40字以内，自然口语，符合你的性格和这个时段。不要主动声称昨天、昨晚或上次发生过具体会面、动作或承诺。没有已确认的用户称呼时，只能用“你”或省略称呼；绝不能把角色自己的姓名、简称或昵称用来称呼用户，也不要临时编造昵称。不要动作描写和旁白，不要提这是系统指令）`,
            history,
            memory_context: memoryForRequest(id),
            intimacy: intimacyForRequest(id),
            companion_context: companionForRequest(id),
            proactive: true,
            channel: 'home_greeting',
          }),
        });
        if (!res.ok) throw new Error('greet http ' + res.status);
        const data = await res.json();
        if (data.status) applyLiveStatus(id, data.status);
        const text = requireSafeCharacterReply(id, data.reply);
        if (isLegacyStaticGreetingText(text)) throw new Error('invalid greeting');
        setAiGreets(p => p[id]?.key === key ? ({ ...p, [id]: { key, text } }) : p);
        if (text) {
          try {
            const returnedStatus = data.status;
            const returnedSceneKey = returnedStatus?.source === 'conversation'
              ? `conversation:${returnedStatus.scene || 'shared'}:${returnedStatus.expires_at || ''}`
              : `schedule:${returnedStatus?.label || 'pending'}`;
            if (sceneKey === 'schedule:pending' || returnedSceneKey === sceneKey) {
              localStorage.setItem(`sl_greet_${id}`, JSON.stringify({ key, text }));
            }
          } catch (e) { /* 静默 */ }
        }
      } catch (e) {
        setAiGreets(p => p[id]?.key === key ? ({ ...p, [id]: { key, text: '' } }) : p);
      }
    })();
  }, [currentId, liveStatuses[currentId]?.source, liveStatuses[currentId]?.scene, liveStatuses[currentId]?.label, liveStatuses[currentId]?.expires_at, Math.floor(intimacies[currentId] ?? byId(currentId)?.intimacy ?? 1)]);
  return aiGreets;
}

// 本地持久化：记忆、关系约定、上下文、通知与已读位置随 state 落盘。
function useMainAppPersistence({ currentId, lastRead, archivedSessions, notifications, memories, memoryContexts, companionContexts, relationshipAgreements, sessionsWriter, memoriesRef, memoryContextsRef, relationshipAgreementsRef, setIntimacies }) {
  useE(() => {
    try { localStorage.setItem('sl_current_character', currentId); } catch (e) { /* 静默 */ }
  }, [currentId]);

  // lastRead 更新时持久化，刷新后未读计数仍准确
  useE(() => {
    try { localStorage.setItem('sl_lastread', JSON.stringify(lastRead)); } catch (e) { /* 静默 */ }
  }, [lastRead]);

  // 归档会话持久化（与 threads 同样防抖；序列化推迟到写入时）
  useE(() => {
    sessionsWriter.schedule(() => JSON.stringify(archivedSessions));
  }, [archivedSessions]);

  // 通知持久化
  useE(() => {
    try { localStorage.setItem('sl_notifications', JSON.stringify(notifications)); } catch (e) { /* 静默 */ }
  }, [notifications]);

  // 记忆持久化
  useE(() => {
    Object.entries(memories).forEach(([id, m]) => {
      try { localStorage.setItem(`sl_memory_${id}`, m || ''); } catch (e) { /* 静默 */ }
    });
  }, [memories]);

  // v20 结构化记忆：保留旧文本作为可恢复备份，聊天只检索与本轮话题相关的安全上下文。
  useE(() => {
    Object.entries(memoryContexts).forEach(([id, context]) => {
      try {
        if (memories[id] && !localStorage.getItem(`sl_memory_legacy_${id}`)) {
          localStorage.setItem(`sl_memory_legacy_${id}`, memories[id]);
        }
        localStorage.setItem(
          `sl_memory_context_${id}`,
          serializeMemoryContext(sanitizeMemoryAddressDirection(id, context)),
        );
      } catch (e) { /* 静默 */ }
    });
  }, [memoryContexts, memories]);

  // v21 上下文单独持久化；旧亲密度键仅镜像关系等级，供备份和旧组件读取。
  useE(() => {
    const levels = {};
    Object.entries(companionContexts).forEach(([id, rawContext]) => {
      try {
        const context = reconcileCompanionAddressDirections(
          rawContext,
          id,
          relationshipAgreementsRef.current[id],
          memoryContextsRef.current[id],
        );
        localStorage.setItem(`sl_companion_context_${id}`, JSON.stringify(context));
        localStorage.setItem(`sl_intimacy_${id}`, String(context.relationship.level));
        levels[id] = context.relationship.level;
      } catch (e) { /* 静默 */ }
    });
    if (Object.keys(levels).length) {
      setIntimacies(prev => {
        const changed = Object.entries(levels).some(([id, level]) => prev[id] !== level);
        return changed ? { ...prev, ...levels } : prev;
      });
    }
  }, [companionContexts]);

  useE(() => {
    Object.entries(relationshipAgreements).forEach(([id, agreement]) => {
      try {
        localStorage.setItem(`sl_relationship_${id}`, JSON.stringify(sanitizeRelationshipAgreement(
          id,
          agreement,
          memoryContextsRef.current[id],
        )));
      } catch (e) { /* 静默 */ }
    });
  }, [relationshipAgreements]);
}

// 记忆整理：同一角色的请求严格串行，保证先后顺序不会被后发请求覆盖。
function createContextConsolidator({ memorySequenceRef, memoryPendingRef, memoryQueuesRef, memoryContextsRef, companionContextsRef, relationshipAgreementsRef, memoriesRef, legacyIntimaciesRef, archivedSessions, companionForRequest, flash, setThreads, setCompanionContexts, setMemoryContexts }) {
  const consolidateContext = (id, msgs, reason = 'periodic', includeArchives = false) => {
    const sourceMessages = Array.isArray(msgs) ? msgs : [];
    const payload = toApiHistory(sourceMessages, 80);
    if (reason !== 'migration' && payload.length < 2) return Promise.resolve(false);
    const sequence = (memorySequenceRef.current[id] || 0) + 1;
    memorySequenceRef.current[id] = sequence;
    memoryPendingRef.current.add(id);
    const previous = memoryQueuesRef.current[id] || Promise.resolve(false);
    const queued = previous.catch(() => false).then(async () => {
      try {
        const currentContext = sanitizeMemoryAddressDirection(id, memoryContextsRef.current[id], '');
        const currentCompanion = companionForRequest(id);
        const previousLevel = currentCompanion.relationship.level;
        const res = await fetch(`${API_BASE}/api/context/${encodeURIComponent(id)}/consolidate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            companion_context: currentCompanion,
            old_memory: memoriesRef.current[id] || '',
            old_memory_context: serializeMemoryContext(currentContext),
            old_relationship: sanitizeRelationshipAgreement(
              id,
              relationshipAgreementsRef.current[id],
              currentContext,
            ),
            old_intimacy: reason === 'migration' ? legacyIntimaciesRef.current[id] : previousLevel,
            current_messages: toConsolidationMessages(sourceMessages),
            archived_sessions: includeArchives ? toConsolidationSessions(archivedSessions[id] || []) : [],
            reason,
          }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        const nextMemoryContext = sanitizeMemoryAddressDirection(
          id,
          data.memory_context || currentContext,
          '',
        );
        const nextContext = reconcileCompanionAddressDirections(
          normalizeCompanionContext(data.companion_context, id),
          id,
          relationshipAgreementsRef.current[id],
          nextMemoryContext,
        );
        // Requests are serialized per character.  Apply every successful result
        // in queue order so a call summary cannot be discarded merely because a
        // new-chat consolidation was queued behind it.
        companionContextsRef.current = { ...companionContextsRef.current, [id]: nextContext };
        memoryContextsRef.current = { ...memoryContextsRef.current, [id]: nextMemoryContext };
        setCompanionContexts(prev => ({ ...prev, [id]: nextContext }));
        setMemoryContexts(prev => ({ ...prev, [id]: nextMemoryContext }));
        if (data.stage_changed && nextContext.relationship.level > previousLevel) {
          flash(`♡ 与 ${byId(id).name} 的关系成为「${nextContext.relationship.title}」`);
          setThreads(previous => ({
            ...previous,
            [id]: [...(previous[id] || []), {
              from: 'system', type: 'levelup', level: nextContext.relationship.level,
              title: nextContext.relationship.title, ts: Date.now(),
            }],
          }));
        }
        return true;
      } catch (e) {
        return false;
      } finally {
        if (sequence === memorySequenceRef.current[id]) memoryPendingRef.current.delete(id);
      }
    });
    memoryQueuesRef.current[id] = queued;
    return queued;
  };
  const updateMemory = (id, msgs, reason = 'periodic') => consolidateContext(id, msgs, reason, false);
  const maybePeriodicConsolidate = (id, msgs) => {
    const pairCount = countCompleteHistoryPairs(msgs);
    if (pairCount > 0 && pairCount % 4 === 0) updateMemory(id, msgs, 'periodic');
  };
  return { consolidateContext, updateMemory, maybePeriodicConsolidate };
}

// 账号面板：个人资料保存、未保存拦截与焦点回位。
function createAccountActions({ flash, profileDirtyRef, accountPanelTriggerRef, accountPanelKindRef, meSub, setMeSub, setUserProfile }) {
  const saveUserProfile = (nextProfile) => {
    const normalized = normalizeUserProfile(nextProfile);
    try {
      localStorage.setItem('sl_user_profile', JSON.stringify(normalized));
      setUserProfile(normalized);
      profileDirtyRef.current = false;
      flash('个人资料已保存');
      return normalized;
    } catch (e) {
      flash('保存失败，请检查本机存储空间');
      return null;
    }
  };

  const navigateFromProfile = (target, action) => {
    const isLeavingDirtyProfile = meSub === 'profile' && target !== 'profile' && profileDirtyRef.current;
    if (isLeavingDirtyProfile && !window.confirm('资料还没有保存，确定离开吗？')) {
      requestAnimationFrame(() => document.querySelector('.account-panel-head h1')?.focus({ preventScroll: true }));
      return false;
    }
    if (target !== 'profile') profileDirtyRef.current = false;
    action();
    return true;
  };

  const openAccountPanel = (kind, action) => {
    const active = document.activeElement;
    accountPanelTriggerRef.current = active && typeof active.focus === 'function' ? active : null;
    accountPanelKindRef.current = kind;
    action();
  };

  const closeAccountPanel = () => navigateFromProfile(null, () => {
    const trigger = accountPanelTriggerRef.current;
    const kind = accountPanelKindRef.current || meSub;
    setMeSub(null);
    accountPanelTriggerRef.current = null;
    accountPanelKindRef.current = null;
    requestAnimationFrame(() => {
      const target = trigger?.isConnected ? trigger : document.querySelector(`[data-account-entry="${kind}"]`);
      if (target && typeof target.focus === 'function') target.focus({ preventScroll: true });
    });
  });
  return { saveUserProfile, navigateFromProfile, openAccountPanel, closeAccountPanel };
}

// 消息发送：文字（SSE 逐字）、语音、图片、礼物与语音合成。
function createChatSenders({ currentId, setCurrentId, pendingIds, flash, ensureThread, threads, setThreads, setTypingId, setNotifications, historyForRequest, memoryForRequest, intimacyForRequest, companionForRequest, applyLiveStatus, maybePeriodicConsolidate, chatIdRef }) {
  const giftHome = async (gift) => {
    const id = currentId;
    const char = byId(id);
    if (pendingIds.current.has(id)) {
      flash('请等她回复完再送出礼物');
      return;
    }
    pendingIds.current.add(id);
    ensureThread(id);
    const day = getGiftDay(char);
    const giftLabel = `${gift.emoji} ${gift.name}`;
    const giftMessage = { from: 'system', type: 'gift', name: char.name, gift: giftLabel, day: day ? day.label : '', ts: Date.now() };
    const prevThread = (window.__threads || {})[id] || threads[id] || [];
    setThreads(prev => ({ ...prev, [id]: [...(prev[id] || []), giftMessage] }));
    flash(`🎁 ${gift.name}已送出`);
    // 让她真的知道收到了礼物：隐藏 prompt → 以人设回应，进对话历史、进长期记忆
    try {
      const history = historyForRequest(id, prevThread, 10);
      const res = await fetch(`${API_BASE}/api/chat/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `（今天是${day ? day.label : '一个特别的日子'}，用户刚送了你一份礼物：${giftLabel}。请以你的性格回应这份心意，1-2句，自然口语，不要动作描写和旁白，不要提这是系统指令）`,
          history,
          memory_context: memoryForRequest(id),
          intimacy: intimacyForRequest(id),
          companion_context: companionForRequest(id),
          channel: 'gift',
        }),
      });
      if (!res.ok) throw new Error(await chatFailureMessage(res));
      const data = await res.json();
      if (data.status) applyLiveStatus(id, data.status);
      const reply = requireSafeCharacterReply(id, data.reply);
      const ts = Date.now();
      const herMessage = { from: 'her', text: reply, ts, origin: 'gift-response' };
      setThreads(prev => ({ ...prev, [id]: [...(prev[id] || []), herMessage] }));
      maybePeriodicConsolidate(id, [...prevThread, giftMessage, herMessage]);
      if (chatIdRef.current !== id) {
        setNotifications(prev => [{ id: ts, charId: id, text: reply, ts, read: false }, ...prev].slice(0, 50));
        flash(`💌 ${char.name} 回应了你的心意`);
      }
    } catch (e) {
      setThreads(prev => ({
        ...prev,
        [id]: [...(prev[id] || []), {
          from: 'system', type: 'error',
          text: (e && e.message) || '礼物已经保存，但她的回应暂时没有生成。',
          ts: Date.now(),
        }],
      }));
    } finally {
      pendingIds.current.delete(id);
    }
  };

  const setCurrent = (id) => {
    setCurrentId(id);
    flash(`已和 ${byId(id).name} 确认心动关系 ♡`);
  };

  // 把文本用角色克隆音色合成成可回放的语音，存到 /api/voice 以便刷新后仍能播放。失败返回 null。
  const synthHerVoice = async (id, text) => {
    const clean = String(text || '').replace(/[（(][^）)]*[）)]/g, '').replace(/[*_]/g, '').trim();
    if (!clean) return null;
    try {
      const ttsRes = await fetch(`${API_BASE}/api/tts/${id}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: clean.slice(0, 600) }),
      });
      if (!ttsRes.ok) return null;
      const blob = await ttsRes.blob();
      if (!blob || !blob.size) return null;
      let audioUrl = '';
      try {
        const up = await fetch(`${API_BASE}/api/voice`, {
          method: 'POST', headers: { 'Content-Type': blob.type || 'audio/wav' }, body: blob,
        });
        if (up.ok) audioUrl = (await up.json()).url || '';
      } catch (e) { /* 持久化失败则退回临时地址（刷新后失效） */ }
      if (!audioUrl) audioUrl = URL.createObjectURL(blob);
      return { audioUrl, dur: Math.max(1, Math.round(clean.length * 0.22)) };
    } catch (e) {
      return null;
    }
  };

  // 语音消息：保存原始录音、插入可回放气泡，再用转写文本触发角色回应。
  const sendVoiceMessage = async (id, dur, transcript, audioBlob) => {
    if (pendingIds.current.has(id)) {
      flash('请等她回复完再发送 ♡');
      return;
    }
    pendingIds.current.add(id);
    const prevThread = threads[id] || [];
    const history = historyForRequest(id, prevThread);
    let audioUrl = '';
    if (audioBlob?.size) {
      try {
        const upload = await fetch(`${API_BASE}/api/voice`, {
          method: 'POST',
          headers: { 'Content-Type': audioBlob.type || 'audio/webm' },
          body: audioBlob,
        });
        if (upload.ok) audioUrl = (await upload.json()).url || '';
        else flash('录音已发送，但保存失败，刷新后将无法回放');
      } catch (e) {
        flash('录音已发送，但保存失败，刷新后将无法回放');
      }
    }
    const userVoiceMessage = {
      from: 'me', type: 'voice', dur, transcript: transcript || '', audioUrl, ts: Date.now(),
    };
    setThreads(prev => ({
      ...prev,
      [id]: [...(prev[id] || []), userVoiceMessage],
    }));
    setTypingId(id);
    const voicePrompt = transcript && transcript.trim()
      ? `（用户给你发来了一段${dur}秒的语音。下面是转写文本，请像真实听到对方说话一样自然回应，内容要完整。）\n${transcript.trim()}`
      : `（用户给你发来了一段${dur}秒的语音，但没有得到可靠转写。请自然询问或回应，不要假装知道具体内容。）`;
    try {
      const res = await fetch(`${API_BASE}/api/chat/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: voicePrompt, history, memory_context: memoryForRequest(id), intimacy: intimacyForRequest(id), companion_context: companionForRequest(id), track_scene: true, channel: 'voice_message' }),
      });
      if (!res.ok) throw new Error(await chatFailureMessage(res));
      const data = await res.json();
      applyLiveStatus(id, data.status);
      const reply = requireSafeCharacterReply(id, data.reply);
      // 先立即显示已经校验过的文字；语音合成在后台完成后再原位升级气泡。
      // TTS 偶发缓慢或不可用时，不应让角色看起来一直不肯回复。
      const replyTs = Date.now();
      const replyId = `voice-reply-${id}-${replyTs}`;
      const herMessage = { from: 'her', text: reply, ts: replyTs, replyId };
      setThreads(prev => ({ ...prev, [id]: [...(prev[id] || []), herMessage] }));
      maybePeriodicConsolidate(id, [
        ...prevThread,
        userVoiceMessage,
        herMessage,
      ]);
      void synthHerVoice(id, reply).then(herVoice => {
        if (!herVoice) return;
        setThreads(prev => ({
          ...prev,
          [id]: (prev[id] || []).map(message => message.replyId === replyId
            ? {
                ...message,
                type: 'voice',
                transcript: reply,
                audioUrl: herVoice.audioUrl,
                dur: herVoice.dur,
              }
            : message),
        }));
      }).catch(() => {});
    } catch (e) {
      setThreads(prev => ({
        ...prev,
        [id]: [...(prev[id] || []), {
          from: 'system', type: 'error',
          text: (e && e.message) || '信号断了，请确认后端正在运行。',
          ts: Date.now(),
        }],
      }));
    } finally {
      pendingIds.current.delete(id);
      setTypingId(cur => cur === id ? null : cur);
    }
  };

  // 普通文字消息先由后端完整校验，再通过 SSE 交给界面逐字展现。
  const sendMessage = async (id, text) => {
    if (pendingIds.current.has(id)) {
      flash('请等她回复完再发送 ♡');
      return;
    }
    pendingIds.current.add(id);
    // 1) 先把用户的话显示出来
    const userMessage = { from: 'me', text, ts: Date.now() };
    setThreads(prev => ({ ...prev, [id]: [...(prev[id] || []), userMessage] }));
    setTypingId(id);

    // 2) 把之前的对话整理成后端要的历史格式（her→assistant, me→user）
    const prevThread = threads[id] || [];
    const history = historyForRequest(id, prevThread);

    // 3) 完整接收后端已校验回复，并在前端再次确认安全后才逐字显示。
    //    即使未来后端漏判，内部校验话术也不会短暂进入角色气泡。
    const streamTs = Math.max(Date.now() + 1, userMessage.ts + 1);
    const streamId = `stream-${id}-${streamTs}`;
    let streamStarted = false;
    let queuedPartial = '';
    let streamFlushTimer = null;
    const flushQueuedStream = () => {
      streamFlushTimer = null;
      if (!streamStarted || !queuedPartial) return;
      const paintedText = queuedPartial;
      setThreads(prev => ({
        ...prev,
        [id]: (prev[id] || []).map(message => message.streamId === streamId
          ? { ...message, text: paintedText, streaming: true }
          : message),
      }));
    };
    const queueStreamPaint = (partial) => {
      queuedPartial = partial;
      if (!streamStarted) {
        streamStarted = true;
        setTypingId(cur => cur === id ? null : cur);
        setThreads(prev => ({
          ...prev,
          [id]: [...(prev[id] || []), { from: 'her', text: partial, ts: streamTs, streamId, streaming: true }],
        }));
        return;
      }
      if (streamFlushTimer === null) streamFlushTimer = window.setTimeout(flushQueuedStream, 48);
    };
    try {
      const res = await fetch(`${API_BASE}/api/chat/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ message: text, history, memory_context: memoryForRequest(id), intimacy: intimacyForRequest(id), companion_context: companionForRequest(id), stream: true, track_scene: true, channel: 'text' }),
      });
      if (!res.ok) throw new Error(await chatFailureMessage(res));
      const reply = requireSafeCharacterReply(
        id,
        await readChatStream(res, status => applyLiveStatus(id, status)),
      );
      await revealVerifiedReply(reply, queueStreamPaint);
      if (streamFlushTimer !== null) {
        window.clearTimeout(streamFlushTimer);
        streamFlushTimer = null;
      }
      setThreads(prev => ({
        ...prev,
        [id]: (prev[id] || []).map(message => message.streamId === streamId
          ? { ...message, text: reply, streaming: false }
          : message),
      }));
      const completedForMemory = [
        ...prevThread,
        userMessage,
        { from: 'her', text: reply, ts: streamTs },
      ];
      maybePeriodicConsolidate(id, completedForMemory);
    } catch (e) {
      if (streamFlushTimer !== null) {
        window.clearTimeout(streamFlushTimer);
        streamFlushTimer = null;
      }
      const errorText = (e && e.message) || '（信号断了…请确认后端正在运行）';
      setThreads(prev => ({
        ...prev,
        [id]: streamStarted
          ? (prev[id] || []).map(message => message.streamId === streamId
            ? { from: 'system', type: 'error', text: errorText, ts: message.ts || streamTs }
            : message)
          : [...(prev[id] || []), { from: 'system', type: 'error', text: errorText, ts: streamTs }],
      }));
    } finally {
      if (streamFlushTimer !== null) window.clearTimeout(streamFlushTimer);
      pendingIds.current.delete(id);
      setTypingId(cur => cur === id ? null : cur);
    }
  };

  // 图片消息：图片先由中立视觉层提取事实，角色模型只接收事实与真实配文
  const sendImageMessage = async (id, imageUrl, caption = '') => {
    if (pendingIds.current.has(id)) {
      flash('请等她回复完再发送 ♡');
      return;
    }
    pendingIds.current.add(id);
    const typingStart = Date.now();
    const cleanCaption = String(caption || '').trim();
    const userImageMessage = { from: 'me', type: 'image', imageUrl, text: cleanCaption, ts: Date.now() };
    setThreads(prev => ({ ...prev, [id]: [...(prev[id] || []), userImageMessage] }));
    setTypingId(id);
    const prevThread = threads[id] || [];
    const history = historyForRequest(id, prevThread);
    try {
      const res = await fetch(`${API_BASE}/api/chat/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: cleanCaption || '用户发送了一张图片。',
          image_url: imageUrl,
          image_caption: cleanCaption,
          history, memory_context: memoryForRequest(id), intimacy: intimacyForRequest(id), companion_context: companionForRequest(id), track_scene: true, channel: 'image',
        }),
      });
      if (!res.ok) throw new Error(await chatFailureMessage(res));
      const data = await res.json();
      applyLiveStatus(id, data.status);
      const reply = requireSafeCharacterReply(id, data.reply);
      const elapsed = Date.now() - typingStart;
      const minDelay = Math.min(2200, Math.max(700, reply.length * 22));
      const wait = minDelay - elapsed;
      if (wait > 0) await new Promise(r => setTimeout(r, wait));
      const herMessage = { from: 'her', text: reply, ts: Date.now() };
      setThreads(prev => ({ ...prev, [id]: [...(prev[id] || []), herMessage] }));
      maybePeriodicConsolidate(id, [
        ...prevThread,
        userImageMessage,
        herMessage,
      ]);
    } catch (e) {
      setThreads(prev => ({
        ...prev,
        [id]: [...(prev[id] || []), {
          from: 'system', type: 'error',
          text: (e && e.message) || '信号断了，请确认后端正在运行。',
          ts: Date.now(),
        }],
      }));
    } finally {
      pendingIds.current.delete(id);
      setTypingId(cur => cur === id ? null : cur);
    }
  };
  return { giftHome, setCurrent, synthHerVoice, sendVoiceMessage, sendMessage, sendImageMessage };
}

// 豆包端到端使用 callContext；兼容模式使用 callSend 复用现有聊天模型与安全边界。
function createCallController({ threads, setThreads, historyForRequest, memoryForRequest, intimacyForRequest, companionForRequest, applyLiveStatus, setCallCarryover, clearCallCarryover, callCarryoverRef, updateMemory }) {
  const callContext = (id, kind, callTurns = []) => {
    const threadHistory = historyForRequest(id, (window.__threads || {})[id] || threads[id] || [], 16);
    const inCallHistory = (Array.isArray(callTurns) ? callTurns : [])
      .map(m => ({ role: m.from === 'me' ? 'user' : 'assistant', content: String(m.text || '').trim().slice(0, 4000), ts: m.ts }))
      .filter(m => m.content)
      .slice(-16);
    const history = [...threadHistory, ...inCallHistory].slice(-24);
    const channel = kind === '视频' ? 'video_call' : 'voice_call';
    return { message: '[实时语音通话]', history,
      memory_context: memoryForRequest(id), intimacy: intimacyForRequest(id),
      companion_context: companionForRequest(id), channel };
  };

  const callSend = async (id, text, kind, callTurns = []) => {
    const threadHistory = historyForRequest(id, (window.__threads || {})[id] || threads[id] || [], 16);
    const inCallHistory = (Array.isArray(callTurns) ? callTurns : [])
      .map(message => ({
        role: message.from === 'me' ? 'user' : 'assistant',
        content: String(message.text || '').trim().slice(0, 4000),
      }))
      .filter(message => message.content)
      .slice(-16);
    try {
      const response = await fetch(`${API_BASE}/api/chat/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: String(text || '').trim().slice(0, 4000),
          history: [...threadHistory, ...inCallHistory].slice(-24),
          memory_context: memoryForRequest(id),
          intimacy: intimacyForRequest(id),
          companion_context: companionForRequest(id),
          track_scene: true,
          proactive: false,
          channel: kind === '视频' ? 'video_call' : 'voice_call',
        }),
      });
      if (!response.ok) throw new Error(await chatFailureMessage(response));
      const data = await response.json();
      applyLiveStatus(id, data.status);
      return requireSafeCharacterReply(id, data.reply);
    } catch {
      return null;
    }
  };

  // 通话挂断：聊天里只留一条"通话小结"（时长 + 语音/视频），不展开通话内容。
  // 通话里聊到的东西折进长期记忆，下次见面她仍记得。
  const endCallRecord = (id, mode, info) => {
    if (!id) return;
    const duration = Math.max(0, Math.round((info && info.duration) || 0));
    const callTurns = info && Array.isArray(info.turns) ? info.turns : [];
    const hadConversation = callTurns.some(m => m.from === 'me');
    if (duration < 1 && !hadConversation) return; // 误触/秒挂，不记录
    const now = Date.now();
    setThreads(prev => ({
      ...prev,
      [id]: [
        ...(prev[id] || []),
        { from: 'system', type: 'callend', mode, duration, ts: now },
      ],
    }));
    if (hadConversation) {
      const carryover = setCallCarryover(id, [
        ...(callCarryoverRef.current[id] || []),
        ...callTurns,
      ]);
      updateMemory(id, carryover, 'call_end').then(ok => {
        if (ok) clearCallCarryover(id, carryover);
      });
    }
  };
  return { callContext, callSend, endCallRecord };
}

function DesktopWindowChrome({ compact = false }) {
  const [nativeReady, setNativeReady] = useS(false);
  const [maximized, setMaximized] = useS(false);
  const [controlError, setControlError] = useS('');

  useE(() => {
    const sync = () => {
      const ready = typeof window.pywebview?.api?.minimize_window === 'function';
      setNativeReady(ready);
      document.documentElement.dataset.nativeShell = ready ? 'true' : 'false';
    };
    sync();
    window.addEventListener('pywebviewready', sync);
    return () => {
      window.removeEventListener('pywebviewready', sync);
      delete document.documentElement.dataset.nativeShell;
    };
  }, []);

  if (!nativeReady) return null;
  const invoke = (method) => {
    const fn = window.pywebview?.api?.[method];
    if (typeof fn !== 'function') {
      setControlError(uiT('窗口控制暂不可用'));
      return;
    }
    Promise.resolve(fn()).then(result => {
      if (!result?.ok) {
        setControlError(uiT('窗口操作失败，请重试'));
        return;
      }
      setControlError('');
      if (method === 'toggle_maximize_window' && result?.ok) setMaximized(Boolean(result.maximized));
    }).catch(() => setControlError(uiT('窗口操作失败，请重试')));
  };

  return (
    <header className={`desktop-window-chrome${compact ? ' is-compact' : ''}`}>
      <div className="desktop-window-drag pywebview-drag-region" aria-label={uiT('拖动窗口')} onMouseDown={() => invoke('drag_window')}>
        {controlError && <span className="visually-hidden" role="status" aria-live="polite">{controlError}</span>}
      </div>
      <div className="desktop-window-actions">
        <button type="button" aria-label={uiT('最小化')} onClick={() => invoke('minimize_window')}><I.windowMinimize size={14} /></button>
        {!compact && (
          <button type="button" aria-label={uiT(maximized ? '还原' : '最大化')} onClick={() => invoke('toggle_maximize_window')}>
            {maximized ? <I.windowRestore size={13} /> : <I.windowMaximize size={13} />}
          </button>
        )}
        <button type="button" className="is-close" aria-label={uiT('关闭')} title={uiT('关闭到后台，可从系统托盘退出')} onClick={() => invoke('close_window')}><I.windowClose size={14} /></button>
      </div>
    </header>
  );
}

function App() {
  useUiLanguage();
  const [gate, setGate] = useS({ status: 'checking', message: '', messageTone: '', config: null });
  const requestSequence = useR(0);
  const windowTransitionSequence = useR(0);
  const desiredWindowMode = useR('login');
  const maintenance = useMaintenanceController();

  useE(() => {
    let active = true;
    const syncWindowMode = async () => {
      if (!active) return;
      await requestNativeWindowMode(desiredWindowMode.current, false);
    };
    syncWindowMode();
    window.addEventListener('pywebviewready', syncWindowMode);
    return () => {
      active = false;
      window.removeEventListener('pywebviewready', syncWindowMode);
    };
  }, []);

  const transitionToMain = async (config) => {
    const transition = ++windowTransitionSequence.current;
    desiredWindowMode.current = 'main';
    setGate({ status: 'entering', message: '', messageTone: '', config });
    await waitForWindowTransitionPaint();
    const reduceMotion = document.documentElement.dataset.reduceMotion === 'true'
      || Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
    await requestNativeWindowMode('main', !reduceMotion);
    await waitForWindowTransitionPaint();
    if (transition !== windowTransitionSequence.current) return;
    setGate({ status: 'ready', message: '', messageTone: '', config });
  };

  const transitionToLogin = async (message = '') => {
    const transition = ++windowTransitionSequence.current;
    desiredWindowMode.current = 'login';
    setGate({ status: 'leaving', message: '', messageTone: '', config: null });
    await waitForWindowTransitionPaint();
    const reduceMotion = document.documentElement.dataset.reduceMotion === 'true'
      || Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
    await requestNativeWindowMode('login', !reduceMotion);
    await waitForWindowTransitionPaint();
    if (transition !== windowTransitionSequence.current) return;
    setGate({ status: 'missing', message, messageTone: message ? 'success' : '', config: null });
  };

  const checkAiConfig = async () => {
    const sequence = ++requestSequence.current;
    setGate(previous => ({ ...previous, status: 'checking', message: '', messageTone: '' }));
    try {
      const response = await fetch(`${API_BASE}/api/ai-config`, { method: 'GET', cache: 'no-store' });
      const payload = await readAiConfigPayload(response);
      if (sequence !== requestSequence.current) return;
      if (response.ok && payload.ready === true) {
        await transitionToMain(payload);
        return;
      }
      if (response.ok && payload.configured === false) {
        setGate({ status: 'missing', message: '', messageTone: '', config: null });
        return;
      }
      const message = aiConfigErrorMessage(response, payload, 'check');
      setGate({ status: response.status === 401 ? 'missing' : 'error', message, messageTone: 'error', config: null });
    } catch (e) {
      if (sequence === requestSequence.current) {
        setGate({ status: 'error', message: uiT('无法连接本机服务，请确认数恋仍在运行。'), messageTone: 'error', config: null });
      }
    }
  };

  useE(() => {
    checkAiConfig();
    return () => { requestSequence.current += 1; };
  }, []);

  const validateApiKey = async (apiKey, remember = true) => {
    try {
      const response = await fetch(`${API_BASE}/api/ai-config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey, remember }),
      });
      const payload = await readAiConfigPayload(response);
      if (!response.ok) return { ok: false, message: aiConfigErrorMessage(response, payload, 'save') };
      return { ok: true, config: { ...payload, ready: true } };
    } catch (e) {
      return { ok: false, message: uiT('无法连接本机服务，请确认数恋仍在运行。') };
    }
  };

  const replaceApiKey = async (apiKey) => {
    const result = await validateApiKey(apiKey);
    if (result.ok) setGate({ status: 'ready', message: '', messageTone: '', config: result.config });
    return result;
  };

  const changeAiModel = async (model) => {
    try {
      const response = await fetch(`${API_BASE}/api/ai-config/model`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }),
      });
      const payload = await readAiConfigPayload(response);
      if (!response.ok) return { ok: false, message: aiConfigErrorMessage(response, payload, 'save') };
      const config = { ...payload, ready: true };
      setGate(previous => ({ ...previous, config }));
      return { ok: true, config };
    } catch (e) {
      return { ok: false, message: uiT('无法连接本机服务，请确认数恋仍在运行。') };
    }
  };

  const logoutApiKey = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/ai-config/logout`, { method: 'POST' });
      const payload = await readAiConfigPayload(response);
      if (!response.ok) return { ok: false, message: aiConfigErrorMessage(response, payload, 'remove') };
      requestSequence.current += 1;
      await transitionToLogin(uiT('已退出当前 AI 会话；已保存的 API Key 会在下次启动时自动连接。'));
      return { ok: true };
    } catch (e) {
      return { ok: false, message: uiT('无法连接本机服务，请确认数恋仍在运行。') };
    }
  };

  const removeApiKey = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/ai-config`, { method: 'DELETE' });
      const payload = await readAiConfigPayload(response);
      if (!response.ok) return { ok: false, message: aiConfigErrorMessage(response, payload, 'remove') };
      requestSequence.current += 1;
      await transitionToLogin(uiT('已清除保存的 API Key，本机聊天、记忆和个人资料均已保留。'));
      return { ok: true };
    } catch (e) {
      return { ok: false, message: uiT('无法连接本机服务，请确认数恋仍在运行。') };
    }
  };

  if (gate.status === 'ready') {
    return (
      <>
        <DesktopWindowChrome />
        <div className="main-app-enter">
          <MainAppWithRoleArchive
            aiConfig={gate.config || {}}
            onAiConfigChange={replaceApiKey}
            onAiModelChange={changeAiModel}
            onAiRemoved={removeApiKey}
            onAiLoggedOut={logoutApiKey}
            maintenance={maintenance}
          />
        </div>
      </>
    );
  }

  if (gate.status === 'entering' || gate.status === 'leaving') {
    return (
      <>
        <DesktopWindowChrome compact />
        <WindowModeTransition direction={gate.status === 'entering' ? 'opening' : 'closing'} />
      </>
    );
  }

  return (
    <>
      <DesktopWindowChrome compact />
      <ApiKeyGate
        status={gate.status}
        message={gate.message}
        messageTone={gate.messageTone}
        onRetry={checkAiConfig}
        onValidate={validateApiKey}
        onConnected={transitionToMain}
        onRemove={removeApiKey}
        maintenance={maintenance}
      />
    </>
  );
}

let pendingRoleArchiveRoles = [];
let roleArchiveStateSeeded = false;

// ── 本地状态契约：唯一真源是后端 SQLite ──────────────────────────────
// 真源是后端 SQLite（/api/state）。localStorage 只是启动期由 hydration 填好的
// 只读缓存副本；页面运行期间的一切写入都必须走被 installSqliteStateBridge 覆写过的
// localStorage.setItem / removeItem / clear —— 它们会在写缓存的同时把改动排进
// 待写队列推给后端。直接调用原生实现就绕过了这条链路。
//
// 因此 nativeStorageSet / nativeStorageRemove / nativeStorageClear 只允许出现在
// 这四条受控路径里（tests/test_dialogue_reliability.py 有断言兜底）：
//   1. installSqliteStateBridge    —— 覆写后仍需委托原生实现，属必需调用；
//   2. sqliteStateBridge.remember() —— 写 sl_sqlite_pending 待写标记，不是业务数据；
//   3. replaceRawPersistentState    —— 恢复数据：SQLite 已先落盘，这里同步缓存副本；
//   4. loadSqliteStateBeforeRender  —— 启动期 hydration：SQLite 为真源，这里填充缓存。
// 其它任何位置直写原生实现，都会让缓存与 SQLite 真源悄悄分叉。
const SQLITE_PENDING_KEY = 'sl_sqlite_pending';
const nativeStorageGet = Storage.prototype.getItem;
const nativeStorageSet = Storage.prototype.setItem;
const nativeStorageRemove = Storage.prototype.removeItem;
const nativeStorageClear = Storage.prototype.clear;

function isPersistentStateKey(key) {
  return typeof key === 'string'
    && key.startsWith('sl_')
    && !key.startsWith('sl_sqlite_');
}

function readRawPersistentState() {
  const data = {};
  for (let index = 0; index < localStorage.length; index++) {
    const key = localStorage.key(index);
    if (isPersistentStateKey(key)) {
      const value = nativeStorageGet.call(localStorage, key);
      if (typeof value === 'string') data[key] = value;
    }
  }
  return data;
}

function readPendingStateOperations() {
  try {
    const parsed = JSON.parse(nativeStorageGet.call(localStorage, SQLITE_PENDING_KEY) || '{}');
    const operations = new Map();
    (Array.isArray(parsed?.upsert) ? parsed.upsert : []).forEach(key => {
      if (!isPersistentStateKey(key)) return;
      const value = nativeStorageGet.call(localStorage, key);
      if (typeof value === 'string') operations.set(key, { value, deleted: false });
    });
    (Array.isArray(parsed?.deleted) ? parsed.deleted : []).forEach(key => {
      if (isPersistentStateKey(key)) operations.set(key, { value: null, deleted: true });
    });
    return operations;
  } catch (e) {
    return new Map();
  }
}

const sqliteStateBridge = {
  suspended: true,
  installed: false,
  timer: null,
  inFlight: null,
  replacement: null,
  operations: readPendingStateOperations(),

  remember() {
    const upsert = [];
    const deleted = [];
    this.operations.forEach((operation, key) => {
      (operation.deleted ? deleted : upsert).push(key);
    });
    // 受控直写（见上方本地状态契约）：这里只写待写标记，不承载业务数据。
    if (!upsert.length && !deleted.length) {
      nativeStorageRemove.call(localStorage, SQLITE_PENDING_KEY);
      return;
    }
    nativeStorageSet.call(
      localStorage,
      SQLITE_PENDING_KEY,
      JSON.stringify({ upsert: upsert.sort(), deleted: deleted.sort() }),
    );
  },

  queue(key, value, deleted = false) {
    if (!isPersistentStateKey(key) || this.suspended) return;
    this.operations.set(key, { value: deleted ? null : String(value), deleted });
    this.remember();
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.flush().catch(() => {});
    }, 80);
  },

  async flush() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.replacement) return this.replacement;
    if (this.inFlight) return this.inFlight;
    if (!this.operations.size) return { ok: true };
    this.inFlight = this.drain();
    try {
      return await this.inFlight;
    } finally {
      this.inFlight = null;
    }
  },

  async drain() {
    let result = { ok: true };
    while (this.operations.size) {
      result = await this.writeBatch();
    }
    return result;
  },

  async writeBatch() {
    const sent = new Map(this.operations);
    const items = {};
    const deletedKeys = [];
    sent.forEach((operation, key) => {
      if (operation.deleted) deletedKeys.push(key);
      else items[key] = operation.value;
    });
    const response = await fetch(`${API_BASE}/api/state`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items, deleted_keys: deletedKeys }),
      keepalive: JSON.stringify({ items, deleted_keys: deletedKeys }).length < 60_000,
    });
    if (!response.ok) throw new Error('SQLite state sync failed');
    const result = await response.json();
    sent.forEach((operation, key) => {
      if (this.operations.get(key) === operation) this.operations.delete(key);
    });
    this.remember();
    return result;
  },
};

// ── 防抖持久化 ────────────────────────────────────────────────────────────────
// localStorage.setItem 会被下面的 sqliteStateBridge 同步记入待写队列，所以防抖
// 只是把「全量序列化 + 写盘」推迟到安静期，并不会丢掉 SQLite 镜像。
const DEBOUNCED_STORAGE_DELAY_MS = 600;
const debouncedStorageWriters = new Set();

function createDebouncedStorageWriter(key, delayMs = DEBOUNCED_STORAGE_DELAY_MS) {
  let timer = null;
  let producer = null;
  const run = () => {
    timer = null;
    const current = producer;
    producer = null;
    if (!current) return;
    try {
      localStorage.setItem(key, current());
    } catch (e) { /* 容量满等情况静默，与旧行为一致 */ }
  };
  const writer = {
    // producer 是「序列化函数」而不是序列化结果：安静期之前不做任何 JSON.stringify。
    schedule(nextProducer) {
      producer = nextProducer;
      if (!timer) timer = setTimeout(run, delayMs);
    },
    flush() {
      if (timer) clearTimeout(timer);
      run();
    },
    cancel() {
      if (timer) clearTimeout(timer);
      timer = null;
      producer = null;
    },
  };
  debouncedStorageWriters.add(writer);
  return writer;
}

function flushDebouncedStorageWriters() {
  debouncedStorageWriters.forEach(writer => {
    try { writer.flush(); } catch (e) { /* 静默 */ }
  });
}

// 关窗/切后台时必须补写，否则安静期内的改动会丢在 debounce 计时器里。
if (typeof window !== 'undefined') {
  const flushOnHide = () => flushDebouncedStorageWriters();
  window.addEventListener('pagehide', flushOnHide);
  window.addEventListener('beforeunload', flushOnHide);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushOnHide();
  });
}

function installSqliteStateBridge() {
  if (sqliteStateBridge.installed) return;
  Storage.prototype.setItem = function storageSetItem(key, value) {
    const result = nativeStorageSet.call(this, key, value);
    if (this === localStorage) sqliteStateBridge.queue(String(key), String(value), false);
    return result;
  };
  Storage.prototype.removeItem = function storageRemoveItem(key) {
    const result = nativeStorageRemove.call(this, key);
    if (this === localStorage) sqliteStateBridge.queue(String(key), null, true);
    return result;
  };
  Storage.prototype.clear = function storageClear() {
    const keys = this === localStorage ? Object.keys(readRawPersistentState()) : [];
    const result = nativeStorageClear.call(this);
    keys.forEach(key => sqliteStateBridge.queue(key, null, true));
    return result;
  };
  sqliteStateBridge.installed = true;
}

function replaceRawPersistentState(data) {
  sqliteStateBridge.suspended = true;
  try {
    Object.keys(readRawPersistentState()).forEach(key => {
      nativeStorageRemove.call(localStorage, key);
    });
    Object.entries(data || {}).forEach(([key, value]) => {
      if (!isPersistentStateKey(key) || typeof value !== 'string') {
        throw new Error(`Invalid persistent state item: ${key}`);
      }
      nativeStorageSet.call(localStorage, key, value);
    });
    sqliteStateBridge.operations.clear();
    sqliteStateBridge.remember();
  } finally {
    sqliteStateBridge.suspended = false;
  }
}

function flushAllPersistentState() {
  // 顺序很重要：先把防抖里挂着的 localStorage 写入落盘（同时进入 SQLite 待写队列），
  // 再让 sqliteStateBridge 把这批改动推给后端。导出备份/恢复数据都必须走这里。
  flushDebouncedStorageWriters();
  return sqliteStateBridge.flush();
}

async function replacePersistentState(data) {
  if (sqliteStateBridge.replacement) throw new Error('已有数据恢复正在进行，请稍候');
  const pending = flushAllPersistentState();
  const replacement = (async () => {
    await pending;
    const response = await fetch(`${API_BASE}/api/state/replace`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data }),
    });
    if (!response.ok) {
      let payload = {};
      try { payload = await response.json(); } catch (e) { /* keep fallback */ }
      throw new Error(payload?.error?.message || payload?.detail || '本地数据写入失败');
    }
    const result = await response.json();
    replaceRawPersistentState(data);
    return result;
  })();
  sqliteStateBridge.replacement = replacement;
  try {
    return await replacement;
  } finally {
    sqliteStateBridge.replacement = null;
    if (sqliteStateBridge.operations.size) {
      sqliteStateBridge.timer = setTimeout(() => sqliteStateBridge.flush().catch(() => {}), 80);
    }
  }
}

async function loadSqliteStateBeforeRender() {
  installSqliteStateBridge();
  const legacyState = readRawPersistentState();
  const pendingBeforeHydrate = new Map(sqliteStateBridge.operations);
  try {
    const response = await fetch(`${API_BASE}/api/state`, { cache: 'no-store' });
    if (!response.ok) throw new Error('SQLite state load failed');
    let payload = await response.json();
    let authoritative = payload?.data && typeof payload.data === 'object' ? payload.data : {};
    if ((payload?.item_count || 0) === 0 && Object.keys(legacyState).length) {
      const imported = await fetch(`${API_BASE}/api/state/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: legacyState }),
      });
      if (!imported.ok) throw new Error('Legacy state migration failed');
      authoritative = legacyState;
    }

    sqliteStateBridge.suspended = true;
    Object.keys(readRawPersistentState()).forEach(key => {
      nativeStorageRemove.call(localStorage, key);
    });
    Object.entries(authoritative).forEach(([key, value]) => {
      if (isPersistentStateKey(key) && typeof value === 'string') {
        nativeStorageSet.call(localStorage, key, value);
      }
    });
    pendingBeforeHydrate.forEach((operation, key) => {
      if (operation.deleted) nativeStorageRemove.call(localStorage, key);
      else nativeStorageSet.call(localStorage, key, operation.value);
    });
    sqliteStateBridge.operations = pendingBeforeHydrate;
    sqliteStateBridge.remember();
  } catch (e) {
    // Keep the last local cache available. Pending writes remain queued for retry.
  } finally {
    sqliteStateBridge.suspended = false;
  }
  if (sqliteStateBridge.operations.size) {
    try { await sqliteStateBridge.flush(); } catch (e) { /* retry on the next write/start */ }
  }
}

window.shulianStorageFlush = () => flushAllPersistentState();
window.shulianReplacePersistentState = replacePersistentState;

function seedArchiveObjectState(storageKey, characterId, value) {
  if (value === undefined || value === null) return;
  let stored = {};
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) || '{}');
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) stored = parsed;
  } catch (e) { /* replace only the unreadable aggregate container */ }
  if (Object.prototype.hasOwnProperty.call(stored, characterId)) return;
  stored[characterId] = value;
  localStorage.setItem(storageKey, JSON.stringify(stored));
}

function seedArchiveScalarState(storageKey, value) {
  if (value === undefined || value === null || localStorage.getItem(storageKey) !== null) return;
  const serialized = typeof value === 'string' ? value : JSON.stringify(value);
  localStorage.setItem(storageKey, serialized);
}

function seedRoleArchiveState(role) {
  const characterId = String(role?.id || '');
  const state = role?.state;
  if (!characterId || !state || typeof state !== 'object') return;
  const markerKey = `sl_role_archive_initialized_${characterId}`;
  if (localStorage.getItem(markerKey)) return;

  seedArchiveObjectState('sl_threads', characterId, state.currentMessages || []);
  // Imported source history is stored separately and never returned here.
  seedArchiveObjectState('sl_sessions', characterId, state.archivedSessions || []);
  seedArchiveScalarState(`sl_memory_${characterId}`, state.memory || '');
  seedArchiveScalarState(`sl_memory_context_${characterId}`, state.memoryContext || {});
  seedArchiveScalarState(`sl_companion_context_${characterId}`, state.companionContext || {});
  seedArchiveScalarState(`sl_relationship_${characterId}`, state.relationship || {});
  seedArchiveScalarState(`sl_intimacy_${characterId}`, state.intimacy);
  seedArchiveScalarState(`sl_start_${characterId}`, state.startedAt);
  localStorage.setItem(markerKey, String(role.snapshotId || 'loaded'));
}

async function prepareRoleArchiveStateAfterGate() {
  if (roleArchiveStateSeeded) return;
  const needsRestore = pendingRoleArchiveRoles.some(role => {
    const characterId = String(role?.id || '');
    return characterId && !localStorage.getItem(`sl_role_archive_initialized_${characterId}`);
  });
  if (!needsRestore) {
    roleArchiveStateSeeded = true;
    return;
  }
  try {
    const response = await fetch(`${API_BASE}/api/role-library/runtime/state`, {
      method: 'GET',
      cache: 'no-store',
    });
    if (!response.ok) return;
    const payload = await response.json();
    const roles = Array.isArray(payload?.roles) ? payload.roles : [];
    roles.forEach(seedRoleArchiveState);
  } finally {
    roleArchiveStateSeeded = true;
  }
}

function MainAppWithRoleArchive({ aiConfig, onAiConfigChange, onAiModelChange, onAiRemoved, onAiLoggedOut, maintenance }) {
  const [ready, setReady] = useS(roleArchiveStateSeeded);
  useE(() => {
    let active = true;
    prepareRoleArchiveStateAfterGate().finally(() => {
      if (active) setReady(true);
    });
    return () => { active = false; };
  }, []);
  if (!ready) {
    return (
      <main className="api-gate-shell" aria-label="正在载入本地角色档案">
        <span className="api-gate-spinner" aria-hidden="true" />
      </main>
    );
  }
  return (
    <MainApp
      aiConfig={aiConfig}
      onAiConfigChange={onAiConfigChange}
      onAiModelChange={onAiModelChange}
      onAiRemoved={onAiRemoved}
      onAiLoggedOut={onAiLoggedOut}
      maintenance={maintenance}
    />
  );
}

async function loadRoleLibraryBeforeRender() {
  try {
    const response = await fetch(`${API_BASE}/api/role-library/runtime`, {
      method: 'GET',
      cache: 'no-store',
    });
    if (!response.ok) return;
    const payload = await response.json();
    const archiveRoles = Array.isArray(payload?.roles) ? payload.roles : [];
    if (!archiveRoles.length) return;

    const archiveProfiles = new Map();
    archiveRoles.forEach(role => {
      const profile = role?.frontend;
      if (profile && typeof profile === 'object' && profile.id) {
        archiveProfiles.set(profile.id, profile);
      }
    });
    if (!archiveProfiles.size) return;
    pendingRoleArchiveRoles = archiveRoles;

    const merged = [...archiveProfiles.values()].map(profile => ({
      ...profile, isCustomRole: true,
      img: profile.img || profile.face || '/custom-role-placeholder.svg',
      face: profile.face || profile.img || '/custom-role-placeholder.svg',
    }));
    merged.forEach(profile => {
      QUIZ_BANK[profile.id] = profile.quiz || [];
      if (profile.accent) CHARACTER_ACCENTS[profile.id] = profile.accent;
      CHARACTER_SELF_VOCATIVES[profile.id] = profile.aliases || [profile.name];
      if (profile.initialRelationship) COMPANION_CALIBRATIONS[profile.id] = profile.initialRelationship;
    });
    ROSTER.splice(0, ROSTER.length, ...merged);
  } catch (e) {
    console.error("Local role library could not be loaded", e);
  }
}

function renderShulianApp() {
  ReactDOM.createRoot(document.getElementById('root')).render(<App />);
  window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
    fetch(`${API_BASE}/api/diagnostics/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: 'startup.frontend_ready',
        duration_ms: Math.max(0, performance.now() - SHULIAN_PAGE_STARTED_AT),
        ok: true,
      }),
      keepalive: true,
    }).catch(() => {});
  }));
}

loadSqliteStateBeforeRender()
  .then(loadRoleLibraryBeforeRender)
  .finally(renderShulianApp);
