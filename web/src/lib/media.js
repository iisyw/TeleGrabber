export function mediaUrl(item) {
  if (!item) return '';
  let path;
  if (!item.source_name) {
    path = `unsorted/${item.filename}`;
  } else if (['user', 'private_user', 'unknown_forward'].includes(item.source_type)) {
    path = `direct_messages/${item.source_name}/${item.filename}`;
  } else {
    path = `${item.source_name}/${item.filename}`;
  }
  return `/media/${path.split('/').map(encodeURIComponent).join('/')}`;
}

export function thumbUrl(item) {
  return item && item.thumb_url ? item.thumb_url : '';
}

export function datePart(dt) {
  if (!dt) return '';
  return dt.split('T')[0];
}

export function dateLabel(dt) {
  if (!dt) return '';
  const p = dt.split('T')[0].split('-');
  if (p.length !== 3) return dt;
  const [y, m, d] = p;
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const yd = new Date(now);
  yd.setDate(yd.getDate() - 1);
  const yest = `${yd.getFullYear()}-${pad(yd.getMonth() + 1)}-${pad(yd.getDate())}`;
  const dp = `${y}-${m}-${d}`;
  if (dp === today) return '今天';
  if (dp === yest) return '昨天';
  if (y === String(now.getFullYear())) return `${parseInt(m, 10)}月${parseInt(d, 10)}日`;
  return `${y}年${parseInt(m, 10)}月${parseInt(d, 10)}日`;
}

export function formatTime(t) {
  return t ? t.replace('T', ' ').split('.')[0] : '';
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) return '-';
  let value = Number(bytes);
  if (value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  const size = value / 1024 ** index;
  return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
}

export function sourceTypeLabel(st) {
  if (st === 'bot') return '机器人';
  if (st === 'private_user' || st === 'user') return '用户';
  if (st === 'group') return '群组';
  if (st === 'channel') return '频道';
  if (st === 'all') return '全部';
  if (!st) return '-';
  return st.substring(0, 2);
}

export function isVideo(item) {
  if (!item) return false;
  if (item.media_type === 'video') return true;
  if (item.media_type === 'animation') {
    const fn = (item.filename || '').toLowerCase();
    return !fn.endsWith('.gif');
  }
  return false;
}

export function isAnimation(item) {
  return Boolean(item && item.media_type === 'animation');
}

export function mediaTypeLabel(type) {
  const map = {
    photo: '图片',
    video: '视频',
    animation: '动画',
    document: '文档',
    audio: '音频',
  };
  return map[type] || type || '-';
}

export function sourceTypeClass(st) {
  if (st === 'bot') return 'bot';
  if (st === 'private_user' || st === 'user') return 'private';
  if (st === 'group') return 'group';
  if (st === 'channel') return 'channel';
  return 'all';
}

const AVATAR_COLORS = [
  ['#FF845E', '#D45246'],
  ['#FEBB5B', '#F68136'],
  ['#B694F9', '#6C61DF'],
  ['#9AD164', '#46BA43'],
  ['#53edd6', '#28c9b7'],
  ['#5CAFFA', '#408ACF'],
  ['#FF8AAC', '#D95574'],
];

export function avatarStyle(name) {
  let h = 0;
  const text = name || '';
  for (let i = 0; i < text.length; i++) h = ((h << 5) - h) + text.charCodeAt(i);
  const c = AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
  return `background:linear-gradient(135deg,${c[0]},${c[1]})`;
}

export function avatarInitial(name) {
  return (name || '?').charAt(0).toUpperCase();
}

/** 把 -100 前缀的频道 ID 归一化为 t.me/c 可用的正数 ID。 */
export function telegramInternalChatId(chatId) {
  if (chatId === null || chatId === undefined || chatId === '') return '';
  const raw = String(chatId);
  let text = raw.startsWith('-') ? raw.slice(1) : raw;
  if (text.startsWith('100') && text.length > 3) text = text.slice(3);
  return text;
}

export function buildPrivateMessageLink(chatId, messageId) {
  const internal = telegramInternalChatId(chatId);
  if (!internal) return '';
  return messageId === null || messageId === undefined
    ? `https://t.me/c/${internal}`
    : `https://t.me/c/${internal}/${messageId}`;
}

/** 把 API 返回的 newest-first 列表按聊天顺序分组（旧消息在上）。 */
export function buildDisplayGroups(items) {
  const groups = [];
  let curDate = null;

  items.forEach((item) => {
    const d = datePart(item.message_time || item.datetime);
    let dateHeader = null;
    if (d !== curDate) {
      curDate = d;
      dateHeader = d;
    }
    const gid = (item.media_group_id || '').trim();
    const isGrouped = Boolean(gid);

    if (isGrouped) {
      const last = groups.length > 0 ? groups[groups.length - 1] : null;
      if (last && last.type === 'media-group' && last.groupId === gid) {
        last.items.push(item);
      } else {
        groups.push({ type: 'media-group', groupId: gid, items: [item], dateHeader });
      }
    } else {
      groups.push({ type: 'single', items: [item], dateHeader });
    }
  });

  groups.forEach((g) => {
    if (g.type === 'media-group') {
      g.items.sort((a, b) =>
        (a.filename || '').localeCompare(b.filename || '', undefined, { numeric: true }),
      );
    }
  });

  return groups;
}

/** 合并跨分页被拆开的媒体组。 */
export function mergeDisplayGroups(groups) {
  const merged = [];
  const groupIdx = {};
  for (const group of groups) {
    if (group.type === 'media-group') {
      if (groupIdx[group.groupId] !== undefined) {
        const existing = merged[groupIdx[group.groupId]];
        existing.items = existing.items.concat(group.items);
        existing.items.sort((a, b) =>
          (a.filename || '').localeCompare(b.filename || '', undefined, { numeric: true }),
        );
      } else {
        groupIdx[group.groupId] = merged.length;
        merged.push(group);
      }
    } else {
      merged.push(group);
    }
  }
  return merged;
}

export function displayGroupKey(group) {
  if (group.type === 'media-group') return `group:${group.groupId}`;
  return `single:${group.items[0] && group.items[0].id}`;
}
