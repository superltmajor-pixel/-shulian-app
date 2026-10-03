const SHULIAN_APP_VERSION = '0.26.0';

// Compatibility for already saved replies: hide machine labels at render
// time without modifying the user's stored conversation.
function stripHistoryLabels(value) {
  return String(value || '').replace(/[【\[]\s*(?:消息时间\s*[:：]\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?:\s*[；;]\s*来源\s*[:：]\s*(?:主动消息|首页问候|新对话开场))?|来源\s*[:：]\s*(?:主动消息|首页问候|新对话开场)|消息编号\s*[:：]\s*\d+)\s*[】\]]/g, '').trim();
}

const CATS = ['全部', '奇幻', '校园', '我的角色'];

const LIVE_STATUS_TONES = {
  sleep: '#8b97c9',
  warm: '#f5b76a',
  study: '#73d6ff',
  meal: '#7ee0a4',
  idle: '#d39bf7',
  walk: '#f79ad2',
};

function useLiveClockTick(intervalMs = 60000) {
  const [tick, setTick] = React.useState(() => Date.now());
  React.useEffect(() => {
    setTick(Date.now());
    const timer = setInterval(() => setTick(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return tick;
}

// 首次渲染与后端不可用时的日程兜底；正常运行时以后端会话状态为准。
function getLiveStatus(c, now = new Date()) {
  const hour = now.getHours();
  const day = now.getDay();
  const weekend = day === 0 || day === 6;
  const isStudent = c?.cat === '校园' || /高中|学生|校园|学年/.test(String(c?.profileIntro || '') + String(c?.persona || ''));
  const afterSchool = hour >= 17 && hour < 20;

  let status;
  const schedule = c?.schedule?.[weekend ? 1 : 0]?.[hour];
  if (schedule) {
    status = { ...schedule };
  } else if (hour < 6) {
    status = { label: '睡觉中', detail: '被窝里，暂时不想被打扰', tone: 'sleep' };
  } else if (hour < 8) {
    status = { label: '起床洗漱', detail: '刚醒，正在收拾自己', tone: 'warm' };
  } else if (hour < 12) {
    status = weekend
      ? { label: '睡懒觉', detail: '周末补觉中', tone: 'sleep' }
      : (isStudent
        ? { label: '上课中', detail: '正在听课，手机先静音', tone: 'study' }
        : { label: '学习中', detail: '上午在处理重要的事情', tone: 'study' });
  } else if (hour < 13) {
    status = { label: '吃饭中', detail: '午饭时间，可能在慢慢吃', tone: 'meal' };
  } else if (hour < 17) {
    status = weekend
      ? { label: '无聊中', detail: '下午有点空，正在发呆', tone: 'idle' }
      : (isStudent
        ? { label: '自习中', detail: '在写作业或者补笔记', tone: 'study' }
        : { label: '忙碌中', detail: '下午还在忙，回消息会慢一点', tone: 'study' });
  } else if (afterSchool) {
    status = isStudent
      ? { label: '放学路上', detail: '刚下课，正在回家的路上', tone: 'walk' }
      : { label: '下班途中', detail: '刚结束白天的安排，正在回去', tone: 'walk' };
  } else if (hour < 22) {
    status = weekend
      ? { label: '自由时间', detail: '晚上在做自己喜欢的事，慢慢放松', tone: 'idle' }
      : (isStudent
        ? { label: '写作业', detail: '晚些时候再休息', tone: 'study' }
        : { label: '整理中', detail: '在收尾今天剩下的事情', tone: 'study' });
  } else {
    status = { label: '准备睡了', detail: '夜深了，快要关灯休息', tone: 'sleep' };
  }

  if (c?.online === false && hour >= 22) {
    status = { label: '离线休息', detail: '已经睡下了', tone: 'sleep' };
  }

  return {
    ...status,
    color: LIVE_STATUS_TONES[status.tone] || '#7ee0a4',
  };
}

// ── 送礼日子：节日 / 角色生日 / 纪念日，平时送礼入口不出现 ──
// 农历节日按 2026 年公历日期硬编码，往后年份需更新
const FESTIVALS = {
  '1-1': '元旦', '2-14': '情人节', '2-17': '春节', '3-14': '白色情人节',
  '5-20': '520', '6-19': '端午节', '8-19': '七夕', '9-25': '中秋节',
  '12-24': '平安夜', '12-25': '圣诞节', '12-31': '跨年夜',
};
function getGiftDay(c, now = new Date()) {
  const md = `${now.getMonth() + 1}-${now.getDate()}`;
  if (FESTIVALS[md]) return { label: FESTIVALS[md], kind: 'festival' };
  if (c && c.birthday === md) return { label: `${c.name}的生日`, kind: 'birthday' };
  if (c) {
    const v = localStorage.getItem(`sl_start_${c.id}`);
    if (v) {
      const days = Math.max(1, Math.floor((now.getTime() - parseInt(v)) / 86400000));
      if (days === 100) return { label: '在一起 100 天纪念日', kind: 'anniversary' };
      if (days >= 365 && days % 365 === 0) return { label: `在一起 ${days / 365} 周年纪念日`, kind: 'anniversary' };
    }
  }
  return null;
}

// Personal character content is supplied by the local role-library API.
const ROSTER = [];
const QUIZ_BANK = {};

const byId = (id) => ROSTER.find(c => c.id === id) || ROSTER[0];

// 按选中的形象合并出生效角色（图片/persona 覆盖基础设定）
const mergeForm = (c, idx) => {
  if (!c || !c.forms || idx == null || !c.forms[idx]) return c;
  return { ...c, ...c.forms[idx] };
};

Object.assign(window, { CATS, ROSTER, byId, mergeForm, getLiveStatus, useLiveClockTick, LIVE_STATUS_TONES, FESTIVALS, getGiftDay, QUIZ_BANK });
