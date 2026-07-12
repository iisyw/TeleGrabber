let state = {
  sources: [],
  sourceCounts: {},
  currentSourceName: '',
  currentSearch: '',
  currentSourceType: '',  // '' = 全部, 'bot', 'private_user', 'group', 'channel'
  mediaList: [],
  offset: 0,
  limit: 30,
  isLoading: false,
  isLastPage: false,
  currentMediaId: null,
  currentUserId: null,  // 用户 ID（用于判断私聊）
  modalItems: [],
  modalIndex: 0,
  sortBy: 'message_time',  // 'message_time' 或 'datetime'
};

let authHeader = null;

/* Preserve sentinel while clearing feed, creating it if needed */
function sentinelPreserve(feed) {
  let sentinel = document.getElementById('feedSentinel');
  if (!sentinel) {
    sentinel = document.createElement('div');
    sentinel.id = 'feedSentinel';
    sentinel.className = 'feed-sentinel';
  }
  while (feed.firstChild) feed.removeChild(feed.firstChild);
  feed.appendChild(sentinel);
}

/* Set exact pixel dimensions on media element (tweb setAttachmentSize pattern) */
function setExactSize(el, w, h) {
  const feedEl = document.getElementById('chatFeed');
  if (!feedEl) return;
  /* Bubble inner width = min(468, feed.clientWidth - feedPad(32) - msgPad(8) - avatar(40) - gap(8) - bubblePad(12)) */
  const maxW = Math.min(468, Math.max(100, feedEl.clientWidth - 156));
  const ar = w / h;
  let dw = maxW;
  let dh = dw / ar;
  if (dh > 400) { dh = 400; dw = dh * ar; }
  el.style.width = Math.round(dw) + 'px';
  el.style.height = Math.round(dh) + 'px';
}

function escape(val) {
  if (val == null) return '';
  return String(val).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function qs(sel) { return document.querySelector(sel); }
function qsa(sel) { return document.querySelectorAll(sel); }

function authFetch(url, opts) {
  const o = { ...opts };
  if (authHeader) o.headers = { ...(o.headers || {}), Authorization: authHeader };
  return fetch(url, o);
}

async function authedWrite(url, opts) {
  let r = await authFetch(url, opts);
  if (r.status === 401) {
    const u = prompt('用户名:');
    if (u == null) return null;
    const p = prompt('密码:');
    if (p == null) return null;
    authHeader = 'Basic ' + btoa(u + ':' + p);
    r = await authFetch(url, opts);
    if (r.status === 401) { authHeader = null; showToast('用户名或密码错误', 'error'); return null; }
  }
  return r;
}

/* ─── Toast ─── */
function showToast(msg, type, dur) {
  type = type || 'success'; dur = dur || 2500;
  const c = document.getElementById('toastContainer');
  if (!c) return;
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => {
    t.classList.add('fade-out');
    t.addEventListener('animationend', () => t.remove());
  }, dur);
}

/* ─── Confirm Dialog ─── */
function confirmDialog(msg, opts) {
  opts = opts || {};
  return new Promise(resolve => {
    const overlay = document.getElementById('confirmDialog');
    document.getElementById('confirmTitle').textContent = opts.title || '确认操作';
    document.getElementById('confirmMessage').textContent = msg;
    document.getElementById('confirmOk').textContent = opts.okText || '确认';

    function cleanup(res) {
      overlay.classList.remove('show');
      document.getElementById('confirmOk').onclick = null;
      document.getElementById('confirmCancel').onclick = null;
      document.removeEventListener('keydown', onKey);
      resolve(res);
    }
    function onKey(e) {
      if (e.key === 'Escape') cleanup(false);
      else if (e.key === 'Enter') cleanup(true);
    }
    document.getElementById('confirmOk').onclick = () => cleanup(true);
    document.getElementById('confirmCancel').onclick = () => cleanup(false);
    document.addEventListener('keydown', onKey);
    overlay.classList.add('show');
  });
}

/* ─── Media URL ─── */
function mediaUrl(item) {
  let path;
  if (!item.source_name) {
    path = 'unsorted/' + item.filename;
  } else if (['user','private_user','unknown_forward'].includes(item.source_type)) {
    path = 'direct_messages/' + item.source_name + '/' + item.filename;
  } else {
    path = item.source_name + '/' + item.filename;
  }
  return '/media/' + path.split('/').map(encodeURIComponent).join('/');
}

/* ─── Date Helpers ─── */
function datePart(dt) {
  if (!dt) return '';
  return dt.split('T')[0];
}

function timePart(dt) {
  if (!dt) return '';
  const t = dt.split('T')[1];
  if (!t) return '';
  return t.split('.')[0].substring(0, 5);
}

function dateLabel(dt) {
  if (!dt) return '';
  const p = dt.split('T')[0].split('-');
  if (p.length !== 3) return dt;
  const [y, m, d] = p;
  const now = new Date();
  const today = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
  const yd = new Date(now); yd.setDate(yd.getDate()-1);
  const yest = yd.getFullYear() + '-' + String(yd.getMonth()+1).padStart(2,'0') + '-' + String(yd.getDate()).padStart(2,'0');
  const dp = y + '-' + m + '-' + d;
  if (dp === today) return '今天';
  if (dp === yest) return '昨天';
  if (y === String(now.getFullYear())) return parseInt(m) + '月' + parseInt(d) + '日';
  return y + '年' + parseInt(m) + '月' + parseInt(d) + '日';
}

function sourceTypeLabel(st) {
  if (st === 'bot') return '机器人';
  if (st === 'private_user' || st === 'user') return '用户';
  if (st === 'group') return '群组';
  if (st === 'channel') return '频道';
  if (st === 'all' || !st) return '全部';
  return st ? st.substring(0, 2) : '';
}

/* ─── API Helpers ─── */
async function loadSources() {
  try {
    let url = '/api/sources';
    if (state.currentSourceType) url += '?source_type=' + encodeURIComponent(state.currentSourceType);
    const resp = await fetch(url);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    state.sources = await resp.json();  // [{source_name, source_type}, ...]

    const totalUrl = '/api/stats' + (state.currentSourceType ? '?source_type=' + encodeURIComponent(state.currentSourceType) : '');
    const totalResp = await fetch(totalUrl);
    const totalData = await totalResp.json();
    state.sourceCounts = { '': { media: totalData.total_count, messages: totalData.message_count } };

    const promises = state.sources.map(async s => {
      try {
        let url = '/api/stats?source_name=' + encodeURIComponent(s.source_name);
        if (state.currentSourceType) url += '&source_type=' + encodeURIComponent(state.currentSourceType);
        const r = await fetch(url);
        const d = await r.json();
        state.sourceCounts[s.source_name] = { media: d.total_count, messages: d.message_count };
      } catch { state.sourceCounts[s.source_name] = { media: 0, messages: 0 }; }
    });
    await Promise.all(promises);
    renderSources();
  } catch (e) {
    console.error('loadSources failed', e);
  }
}

function renderSources() {
  const list = document.getElementById('sourceList');
  list.innerHTML = '';

  const c = state.sourceCounts[''] || { media: 0, messages: 0 };
  const allItem = createSourceItem('', '全部', 'all', '全部消息', c.messages, c.media, state.currentSourceName === '');
  list.appendChild(allItem);

  state.sources.forEach(s => {
    const badge = sourceTypeLabel(s.source_type);
    const sc = state.sourceCounts[s.source_name] || { media: 0, messages: 0 };
    const item = createSourceItem(s.source_name, badge, s.source_type, s.source_name, sc.messages, sc.media, state.currentSourceName === s.source_name);
    list.appendChild(item);
  });
}

function createSourceItem(source, badge, sourceType, name, msgCount, mediaCount, active) {
  const div = document.createElement('div');
  div.className = 'source-item' + (active ? ' active' : '');
  const st = sourceType || '';
  let badgeClass = 'source-badge';
  if (st === 'all') badgeClass += ' all';
  else if (st === 'bot') badgeClass += ' bot';
  else if (st === 'private_user') badgeClass += ' private';
  else if (st === 'group') badgeClass += ' group';
  else if (st === 'channel') badgeClass += ' channel';
  div.innerHTML = '<div class="source-icon badge"><span class="' + badgeClass + '">' + escape(badge) + '</span></div><div class="source-info"><div class="source-name">' + escape(name) + '</div><div class="source-sub">' + msgCount + ' 个消息, ' + mediaCount + ' 个媒体</div></div>';
  div.addEventListener('click', () => selectSource(source));
  return div;
}

function selectSource(source) {
  if (state.currentSourceName === source) return;
  state.currentSourceName = source;
  state.mediaList = [];
  state.offset = 0;
  state.isLastPage = false;
  qsa('.source-item').forEach(el => el.classList.remove('active'));
  const items = qsa('.source-item');
  if (source === '') {
    if (items[0]) items[0].classList.add('active');
  } else {
    const idx = state.sources.findIndex(s => s.source_name === source);
    if (idx >= 0 && items[idx + 1]) items[idx + 1].classList.add('active');
  }
  updateChatHeader();
  loadStats();
  loadMedia(true);
}

function selectSourceType(type) {
  if (state.currentSourceType === type) return;
  state.currentSourceType = type;
  qsa('.source-type-tab').forEach(el => el.classList.toggle('active', el.dataset.type === type));
  state.currentSourceName = '';
  state.mediaList = [];
  state.offset = 0;
  state.isLastPage = false;
  loadSources();
  updateChatHeader();
  loadStats();
  loadMedia(true);
}

function updateChatHeader() {
  const name = state.currentSourceName || '全部消息';
  document.getElementById('chatName').textContent = name;

  const av = document.getElementById('chatAvatar');
  let label = '全部';
  let typeClass = 'all';
  if (state.currentSourceName) {
    const src = state.sources.find(s => s.source_name === state.currentSourceName);
    const st = src ? src.source_type : '';
    label = sourceTypeLabel(st);
    if (st === 'bot') typeClass = 'bot';
    else if (st === 'private_user') typeClass = 'private';
    else if (st === 'group') typeClass = 'group';
    else if (st === 'channel') typeClass = 'channel';
  } else if (state.currentSourceType) {
    label = sourceTypeLabel(state.currentSourceType);
    typeClass = state.currentSourceType;
  }
  av.textContent = label;
  av.className = 'chat-avatar badge ' + typeClass;
}

async function loadStats() {
  try {
    let url = '/api/stats';
    const q = [];
    if (state.currentSearch) q.push('search=' + encodeURIComponent(state.currentSearch));
    if (state.currentSourceName) q.push('source_name=' + encodeURIComponent(state.currentSourceName));
    if (state.currentSourceType) q.push('source_type=' + encodeURIComponent(state.currentSourceType));
    if (q.length) url += '?' + q.join('&');
    const r = await fetch(url);
    const d = await r.json();
    document.getElementById('chatCount').textContent = d.message_count + ' 个消息, ' + d.total_count + ' 个媒体';
  } catch {
    document.getElementById('chatCount').textContent = '';
  }
}

/* ─── Media Loading ─── */
async function loadMedia(reset) {
  if (state.isLoading || state.isLastPage) return;
  state.isLoading = true;

  const feed = document.getElementById('chatFeed');

  if (reset) {
    sentinelPreserve(feed);
    const loader = document.createElement('div');
    loader.className = 'feed-loader';
    loader.innerHTML = '<div class="mini-loader"></div><span>加载中...</span>';
    feed.appendChild(loader);
  } else {
    const loader = document.createElement('div');
    loader.className = 'feed-loader';
    loader.id = 'feedLoader';
    loader.innerHTML = '<div class="mini-loader"></div><span>加载更多...</span>';
    feed.appendChild(loader);
  }

  try {
    let url = '/api/media?limit=' + state.limit + '&offset=' + state.offset + '&sort=' + state.sortBy;
    if (state.currentSearch) url += '&search=' + encodeURIComponent(state.currentSearch);
    if (state.currentSourceName) url += '&source_name=' + encodeURIComponent(state.currentSourceName);
    if (state.currentSourceType) url += '&source_type=' + encodeURIComponent(state.currentSourceType);

    const resp = await fetch(url);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();

    if (data.length < state.limit) state.isLastPage = true;
    state.offset += data.length;

    if (reset) {
      state.mediaList = data;
      renderFeed(true);
      feed.scrollTop = feed.scrollHeight;
    } else {
      /* Remove feedLoader first so anchor doesn't include its height */
      const existingLoader = document.getElementById('feedLoader');
      if (existingLoader) existingLoader.remove();
      /* Append older items to end (keep DESC order), then reverse gives chronological */
      const anchor = feed.scrollHeight - feed.scrollTop;
      state.mediaList = state.mediaList.concat(data);
      renderFeed(false);
      feed.scrollTop = feed.scrollHeight - anchor;
    }
  } catch (e) {
    console.error('loadMedia failed', e);
    if (reset) {
      sentinelPreserve(feed);
      const err = document.createElement('div');
      err.className = 'empty-state';
      err.innerHTML = '<div class="empty-icon">📭</div><div>加载失败: ' + escape(e.message) + '</div>';
      feed.appendChild(err);
    }
  } finally {
    state.isLoading = false;
    const fl = document.getElementById('feedLoader');
    if (fl) fl.remove();
  }
}

/* ─── Rendering ─── */
function renderFeed(reset) {
  const feed = document.getElementById('chatFeed');

  sentinelPreserve(feed);

  if (state.mediaList.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = '<div class="empty-icon">📭</div><div>暂无媒体</div>';
    feed.appendChild(empty);
    return;
  }

  /* API returns newest-first (ORDER BY id DESC); reverse for oldest-at-top chat order */
  const sorted = [...state.mediaList].reverse();
  const groups = buildDisplayGroups(sorted);
  /* Merge media groups split across pagination */
  const merged = [];
  const groupIdx = {};
  for (const g of groups) {
    if (g.type === 'media-group') {
      if (groupIdx[g.groupId] !== undefined) {
        merged[groupIdx[g.groupId]].items = merged[groupIdx[g.groupId]].items.concat(g.items);
        merged[groupIdx[g.groupId]].items.sort((a, b) => (a.filename || '').localeCompare(b.filename || '', undefined, { numeric: true }));
      } else {
        groupIdx[g.groupId] = merged.length;
        merged.push(g);
      }
    } else {
      merged.push(g);
    }
  }
  merged.forEach(g => feed.appendChild(renderGroup(g)));
}

function buildDisplayGroups(items) {
  const groups = [];
  let curDate = null;

  items.forEach(item => {
    const d = datePart(item.message_time || item.datetime);
    if (d !== curDate) {
      curDate = d;
      groups.push({ type: 'date', date: d, items: [] });
    }
    const gid = item.media_group_id;
    const isGrouped = gid && gid !== 'single' && gid !== '' && gid !== null;

    if (isGrouped) {
      const last = groups.length > 0 ? groups[groups.length - 1] : null;
      if (last && last.type === 'media-group' && last.groupId === gid) {
        last.items.push(item);
      } else {
        groups.push({ type: 'media-group', groupId: gid, items: [item] });
      }
    } else {
      groups.push({ type: 'single', items: [item] });
    }
  });

  /* Sort items within each media group by filename */
  groups.forEach(g => {
    if (g.type === 'media-group') {
      g.items.sort((a, b) => (a.filename || '').localeCompare(b.filename || '', undefined, { numeric: true }));
    }
  });

  return groups;
}

function renderGroup(group) {
  if (group.type === 'date') {
    return createDateSep(group.date);
  }
  if (group.type === 'media-group') {
    return createBubble(group.items, true);
  }
  return createBubble(group.items, false);
}

function createDateSep(dateStr) {
  const div = document.createElement('div');
  div.className = 'date-separator';
  div.innerHTML = '<span class="date-label">' + escape(dateLabel(dateStr)) + '</span>';
  return div;
}

/* ─── Album Layout ─── */
/* Ported from Telegram WebK groupedLayout.ts / tdesktop (GPL-2.0) */
const GAP = 2;

const RectPart = { None: 0, Top: 1, Right: 2, Bottom: 4, Left: 8 };

function _sum(arr) { return arr.reduce((s, v) => s + v, 0); }
function _clamp(v, lo, hi) { return Math.min(Math.max(v, lo), hi); }

class Layouter {
  constructor(sizes, maxWidth, minWidth, spacing, maxHeight) {
    this.maxWidth = maxWidth;
    this.minWidth = minWidth;
    this.spacing = spacing;
    this.maxHeight = maxHeight || maxWidth;
    this.sizes = sizes;
    this.count = sizes.length;
    this.ratios = sizes.map(s => s.w / s.h);
    this.proportions = this.ratios.map(r => r > 1.2 ? 'w' : r < 0.8 ? 'n' : 'q').join('');
    this.averageRatio = _sum(this.ratios) / this.count;
    this.maxSizeRatio = maxWidth / this.maxHeight;
  }

  layout() {
    if (!this.count) return [];
    if (this.count === 1) return this._layoutOne();
    if (this.count >= 5 || this.ratios.some(r => r > 2))
      return new ComplexLayouter(this.ratios, this.averageRatio, this.maxWidth, this.minWidth, this.spacing).layout();
    if (this.count === 2) return this._layoutTwo();
    if (this.count === 3) return this._layoutThree();
    return this._layoutFour();
  }

  _layoutOne() {
    const width = this.maxWidth;
    const height = Math.round((this.sizes[0].h * width) / this.sizes[0].w);
    return [{ geometry: { x: 0, y: 0, width, height }, sides: RectPart.Left | RectPart.Top | RectPart.Right | RectPart.Bottom }];
  }

  _layoutTwo() {
    if (this.proportions === 'ww' && this.averageRatio > 1.4 * this.maxSizeRatio && this.ratios[1] - this.ratios[0] < 0.2) return this._layoutTwoTopBottom();
    if (this.proportions === 'ww' || this.proportions === 'qq') return this._layoutTwoLeftRightEqual();
    return this._layoutTwoLeftRight();
  }

  _layoutTwoTopBottom() {
    const w = this.maxWidth;
    const h = Math.round(Math.min(w / this.ratios[0], w / this.ratios[1], (this.maxHeight - this.spacing) / 2));
    return [
      { geometry: { x: 0, y: 0, width: w, height: h }, sides: RectPart.Left | RectPart.Top | RectPart.Right },
      { geometry: { x: 0, y: h + this.spacing, width: w, height: h }, sides: RectPart.Left | RectPart.Bottom | RectPart.Right }
    ];
  }

  _layoutTwoLeftRightEqual() {
    const w = Math.round((this.maxWidth - this.spacing) / 2);
    const h = Math.round(Math.min(w / this.ratios[0], w / this.ratios[1], this.maxHeight));
    return [
      { geometry: { x: 0, y: 0, width: w, height: h }, sides: RectPart.Top | RectPart.Left | RectPart.Bottom },
      { geometry: { x: w + this.spacing, y: 0, width: w, height: h }, sides: RectPart.Top | RectPart.Right | RectPart.Bottom }
    ];
  }

  _layoutTwoLeftRight() {
    const minW = Math.round(this.minWidth * 1.5);
    const sw = Math.min(Math.round(Math.max(0.4 * (this.maxWidth - this.spacing), (this.maxWidth - this.spacing) / this.ratios[0] / (1 / this.ratios[0] + 1 / this.ratios[1]))), this.maxWidth - this.spacing - minW);
    const fw = this.maxWidth - sw - this.spacing;
    const h = Math.min(this.maxHeight, Math.round(Math.min(fw / this.ratios[0], sw / this.ratios[1])));
    return [
      { geometry: { x: 0, y: 0, width: fw, height: h }, sides: RectPart.Top | RectPart.Left | RectPart.Bottom },
      { geometry: { x: fw + this.spacing, y: 0, width: sw, height: h }, sides: RectPart.Top | RectPart.Right | RectPart.Bottom }
    ];
  }

  _layoutThree() {
    if (this.proportions[0] === 'n') return this._layoutThreeLeftAndOther();
    return this._layoutThreeTopAndOther();
  }

  _layoutThreeLeftAndOther() {
    const fh = this.maxHeight;
    const th = Math.round(Math.min((this.maxHeight - this.spacing) / 2, (this.ratios[1] * (this.maxWidth - this.spacing) / (this.ratios[2] + this.ratios[1]))));
    const sh = fh - th - this.spacing;
    const rw = Math.max(this.minWidth, Math.round(Math.min((this.maxWidth - this.spacing) / 2, Math.min(th * this.ratios[2], sh * this.ratios[1]))));
    const lw = Math.min(Math.round(fh * this.ratios[0]), this.maxWidth - this.spacing - rw);
    return [
      { geometry: { x: 0, y: 0, width: lw, height: fh }, sides: RectPart.Top | RectPart.Left | RectPart.Bottom },
      { geometry: { x: lw + this.spacing, y: 0, width: rw, height: sh }, sides: RectPart.Top | RectPart.Right },
      { geometry: { x: lw + this.spacing, y: sh + this.spacing, width: rw, height: th }, sides: RectPart.Bottom | RectPart.Right }
    ];
  }

  _layoutThreeTopAndOther() {
    const fw = this.maxWidth;
    const fh = Math.round(Math.min(fw / this.ratios[0], (this.maxHeight - this.spacing) * 0.66));
    const sw = Math.round((this.maxWidth - this.spacing) / 2);
    const sh = Math.min(this.maxHeight - fh - this.spacing, Math.round(Math.min(sw / this.ratios[1], sw / this.ratios[2])));
    const tw = fw - sw - this.spacing;
    return [
      { geometry: { x: 0, y: 0, width: fw, height: fh }, sides: RectPart.Left | RectPart.Top | RectPart.Right },
      { geometry: { x: 0, y: fh + this.spacing, width: sw, height: sh }, sides: RectPart.Bottom | RectPart.Left },
      { geometry: { x: sw + this.spacing, y: fh + this.spacing, width: tw, height: sh }, sides: RectPart.Bottom | RectPart.Right }
    ];
  }

  _layoutFour() {
    if (this.proportions[0] === 'w') return this._layoutFourTopAndOther();
    return this._layoutFourLeftAndOther();
  }

  _layoutFourTopAndOther() {
    const w = this.maxWidth;
    const h0 = Math.round(Math.min(w / this.ratios[0], (this.maxHeight - this.spacing) * 0.66));
    const h = Math.round((this.maxWidth - 2 * this.spacing) / (this.ratios[1] + this.ratios[2] + this.ratios[3]));
    const w0 = Math.max(this.minWidth, Math.round(Math.min((this.maxWidth - 2 * this.spacing) * 0.4, h * this.ratios[1])));
    const w2 = Math.round(Math.max(Math.max(this.minWidth, (this.maxWidth - 2 * this.spacing) * 0.33), h * this.ratios[3]));
    const w1 = w - w0 - w2 - 2 * this.spacing;
    const h1 = Math.min(this.maxHeight - h0 - this.spacing, h);
    return [
      { geometry: { x: 0, y: 0, width: w, height: h0 }, sides: RectPart.Left | RectPart.Top | RectPart.Right },
      { geometry: { x: 0, y: h0 + this.spacing, width: w0, height: h1 }, sides: RectPart.Bottom | RectPart.Left },
      { geometry: { x: w0 + this.spacing, y: h0 + this.spacing, width: w1, height: h1 }, sides: RectPart.Bottom },
      { geometry: { x: w0 + this.spacing + w1 + this.spacing, y: h0 + this.spacing, width: w2, height: h1 }, sides: RectPart.Right | RectPart.Bottom }
    ];
  }

  _layoutFourLeftAndOther() {
    const h = this.maxHeight;
    const w0 = Math.round(Math.min(h * this.ratios[0], (this.maxWidth - this.spacing) * 0.6));
    const w = Math.round((this.maxHeight - 2 * this.spacing) / (1 / this.ratios[1] + 1 / this.ratios[2] + 1 / this.ratios[3]));
    const h0 = Math.round(w / this.ratios[1]);
    const h1 = Math.round(w / this.ratios[2]);
    const h2 = h - h0 - h1 - 2 * this.spacing;
    const w1 = Math.max(this.minWidth, Math.min(this.maxWidth - w0 - this.spacing, w));
    return [
      { geometry: { x: 0, y: 0, width: w0, height: h }, sides: RectPart.Top | RectPart.Left | RectPart.Bottom },
      { geometry: { x: w0 + this.spacing, y: 0, width: w1, height: h0 }, sides: RectPart.Top | RectPart.Right },
      { geometry: { x: w0 + this.spacing, y: h0 + this.spacing, width: w1, height: h1 }, sides: RectPart.Right },
      { geometry: { x: w0 + this.spacing, y: h0 + h1 + 2 * this.spacing, width: w1, height: h2 }, sides: RectPart.Bottom | RectPart.Right }
    ];
  }
}

class ComplexLayouter {
  constructor(ratios, averageRatio, maxWidth, minWidth, spacing, maxHeight) {
    this.ratios = ComplexLayouter._cropRatios(ratios, averageRatio);
    this.averageRatio = averageRatio;
    this.count = ratios.length;
    this.maxWidth = maxWidth;
    this.minWidth = minWidth;
    this.spacing = spacing;
    this.maxHeight = maxHeight || maxWidth * 4 / 3;
  }

  static _cropRatios(ratios, averageRatio) {
    const kMax = 2.75, kMin = 0.6667;
    return ratios.map(r => averageRatio > 1.1 ? _clamp(r, 1, kMax) : _clamp(r, kMin, 1));
  }

  layout() {
    const result = new Array(this.count);
    const attempts = [];

    const multiHeight = (offset, count) => {
      const ratios = this.ratios.slice(offset, offset + count);
      return (this.maxWidth - (count - 1) * this.spacing) / _sum(ratios);
    };

    const pushAttempt = (lineCounts) => {
      const heights = [];
      let offset = 0;
      for (const cnt of lineCounts) { heights.push(multiHeight(offset, cnt)); offset += cnt; }
      attempts.push({ lineCounts, heights });
    };

    for (let first = 1; first < this.count; ++first) {
      const second = this.count - first;
      if (first > 3 || second > 3) continue;
      pushAttempt([first, second]);
    }
    for (let first = 1; first < this.count - 1; ++first) {
      for (let second = 1; second < this.count - first; ++second) {
        const third = this.count - first - second;
        if (first > 3 || second > (this.averageRatio < 0.85 ? 4 : 3) || third > 3) continue;
        pushAttempt([first, second, third]);
      }
    }
    for (let first = 1; first < this.count - 1; ++first) {
      for (let second = 1; second < this.count - first; ++second) {
        for (let third = 1; third < this.count - first - second; ++third) {
          const fourth = this.count - first - second - third;
          if (first > 3 || second > 3 || third > 3 || fourth > 3) continue;
          pushAttempt([first, second, third, fourth]);
        }
      }
    }

    let optimalAttempt = null, optimalDiff = 0;
    for (const attempt of attempts) {
      const { heights, lineCounts: counts } = attempt;
      const lineCount = counts.length;
      const totalHeight = _sum(heights) + this.spacing * (lineCount - 1);
      const minLineHeight = Math.min(...heights);
      const bad1 = minLineHeight < this.minWidth ? 1.5 : 1;
      let bad2 = 1;
      for (let line = 1; line < lineCount; ++line)
        if (counts[line - 1] > counts[line]) { bad2 = 1.5; break; }
      const diff = Math.abs(totalHeight - this.maxHeight) * bad1 * bad2;
      if (!optimalAttempt || diff < optimalDiff) { optimalAttempt = attempt; optimalDiff = diff; }
    }

    const optimalCounts = optimalAttempt.lineCounts;
    const optimalHeights = optimalAttempt.heights;
    const rowCount = optimalCounts.length;
    let index = 0, y = 0;
    for (let row = 0; row < rowCount; ++row) {
      const colCount = optimalCounts[row];
      const height = Math.round(optimalHeights[row]);
      let x = 0;
      for (let col = 0; col < colCount; ++col) {
        const sides = (row === 0 ? RectPart.Top : 0) | (row === rowCount - 1 ? RectPart.Bottom : 0) |
                      (col === 0 ? RectPart.Left : 0) | (col === colCount - 1 ? RectPart.Right : 0);
        const width = col === colCount - 1 ? (this.maxWidth - x) : Math.round(this.ratios[index] * optimalHeights[row]);
        result[index] = { geometry: { x, y, width, height }, sides };
        x += width + this.spacing;
        ++index;
      }
      y += height + this.spacing;
    }
    return result;
  }
}

function computeAlbumLayout(items, maxWidth) {
  const sizes = items.map(it => ({ w: it.w || 1, h: it.h || 1 }));
  return new Layouter(sizes, maxWidth, 70, GAP).layout();
}

/* Avatar colors matching Telegram WebK palette */
const AVATAR_COLORS = [
  ['#FF845E','#D45246'], ['#FEBB5B','#F68136'], ['#B694F9','#6C61DF'],
  ['#9AD164','#46BA43'], ['#53edd6','#28c9b7'], ['#5CAFFA','#408ACF'],
  ['#FF8AAC','#D95574']
];

function avatarStyle(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = ((h << 5) - h) + name.charCodeAt(i);
  const c = AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
  return 'background:linear-gradient(135deg,' + c[0] + ',' + c[1] + ')';
}

function avatarInitial(name) {
  return (name || '?').charAt(0).toUpperCase();
}

function createBubble(items, isGroup) {
  const msg = document.createElement('div');
  msg.className = 'message';

  const refItem = items[0];
  const publisher = refItem.source_name || refItem.user_name || '';

  if (publisher) {
    const av = document.createElement('div');
    av.className = 'msg-avatar';
    av.style.cssText = avatarStyle(publisher);
    av.textContent = avatarInitial(publisher);
    av.title = publisher;
    msg.appendChild(av);
  }

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  const nameRow = document.createElement('div');
  nameRow.className = 'msg-name-row';

  const sourceType = refItem.source_type || '';
  if (sourceType === 'bot') {
    const b = document.createElement('span');
    b.className = 'source-badge bot';
    b.textContent = '机器人';
    nameRow.appendChild(b);
  } else if (sourceType === 'private_user') {
    const b = document.createElement('span');
    b.className = 'source-badge private';
    b.textContent = '用户';
    nameRow.appendChild(b);
  } else if (sourceType === 'group') {
    const b = document.createElement('span');
    b.className = 'source-badge group';
    b.textContent = '群组';
    nameRow.appendChild(b);
  } else if (sourceType === 'channel') {
    const b = document.createElement('span');
    b.className = 'source-badge channel';
    b.textContent = '频道';
    nameRow.appendChild(b);
  }

  if (publisher) {
    const nameEl = document.createElement('span');
    nameEl.className = 'msg-name';
    nameEl.textContent = publisher;
    nameRow.appendChild(nameEl);
  }

  if (nameRow.children.length > 0) {
    bubble.appendChild(nameRow);
  }

  const G = GAP;
  const n = items.length;

  if (isGroup && n > 1) {
    const gid = refItem.media_group_id;
    if (gid) msg.dataset.groupId = gid;

    const feedEl = document.getElementById('chatFeed');
    const feedW = feedEl ? feedEl.clientWidth - 32 : 480;
    const W = Math.min(480, Math.max(100, feedW)) - 12;

    const layout = computeAlbumLayout(items, W);
    const widthItem = layout.find(l => l.sides & RectPart.Right);
    const heightItem = layout.find(l => l.sides & RectPart.Bottom);
    const cw = widthItem.geometry.x + widthItem.geometry.width;
    const ch = heightItem.geometry.y + heightItem.geometry.height;

    const grid = document.createElement('div');
    grid.className = 'media-grid';
    grid.style.cssText = 'position:relative;width:' + cw + 'px;height:' + ch + 'px';

    for (let i = 0; i < n; i++) {
      const gi = createGridItem(items[i], items, i);
      const l = layout[i];
      gi.style.position = 'absolute';
      gi.style.left = (l.geometry.x / cw * 100) + '%';
      gi.style.top = (l.geometry.y / ch * 100) + '%';
      gi.style.width = (l.geometry.width / cw * 100) + '%';
      gi.style.height = (l.geometry.height / ch * 100) + '%';

      const s = l.sides, sp = GAP;
      if (s & RectPart.Left && s & RectPart.Top)
        gi.style.borderStartStartRadius = 'calc(var(--bubble-radius) - ' + sp + 'px)';
      if (s & RectPart.Left && s & RectPart.Bottom)
        gi.style.borderEndStartRadius = 'calc(var(--bubble-radius) - ' + sp + 'px)';
      if (s & RectPart.Right && s & RectPart.Top)
        gi.style.borderStartEndRadius = 'calc(var(--bubble-radius) - ' + sp + 'px)';
      if (s & RectPart.Right && s & RectPart.Bottom)
        gi.style.borderEndEndRadius = 'calc(var(--bubble-radius) - ' + sp + 'px)';

      grid.appendChild(gi);
    }
    bubble.appendChild(grid);

    const caption = items.find(it => it.caption)?.caption;
    if (caption) {
      const capDiv = document.createElement('div');
      capDiv.className = 'caption';
      capDiv.textContent = caption;
      bubble.appendChild(capDiv);
    }
  } else {
    const item = items[0];
    const url = mediaUrl(item);
    const isVideo = item.media_type === 'video';
    const wrapper = document.createElement('div');
    wrapper.className = 'media-grid g1';

    if (isVideo) {
      const vid = document.createElement('video');
      vid.muted = true;
      vid.preload = 'metadata';
      if (item.w && item.h) setExactSize(vid, item.w, item.h);
      vid.src = url;
      vid.className = 'single-media';
      wrapper.appendChild(vid);
      const badge = document.createElement('div');
      badge.className = 'play-badge';
      badge.innerHTML = '<svg viewBox="0 0 24 24" width="48" height="48"><circle cx="12" cy="12" r="11" fill="rgba(0,0,0,0.6)"/><polygon points="9.5,7 9.5,17 18,12" fill="white"/></svg>';
      wrapper.appendChild(badge);
    } else {
      const img = document.createElement('img');
      img.loading = 'lazy';
      if (item.w && item.h) setExactSize(img, item.w, item.h);
      img.src = url;
      img.className = 'single-media';
      wrapper.appendChild(img);
    }

    wrapper.addEventListener('click', e => {
      e.stopPropagation();
      openModal(items, 0);
    });

    bubble.appendChild(wrapper);

    if (item.caption) {
      const capDiv = document.createElement('div');
      capDiv.className = 'caption';
      capDiv.textContent = item.caption;
      bubble.appendChild(capDiv);
    }
  }

  /* Delete button */
  const delBtn = document.createElement('button');
  delBtn.className = 'bubble-del';
  delBtn.textContent = '🗑️';
  delBtn.addEventListener('click', e => {
    e.stopPropagation();
    if (isGroup && n > 1) {
      deleteMediaGroup(refItem.media_group_id);
    } else {
      deleteMedia(refItem.id);
    }
  });
  bubble.appendChild(delBtn);

  /* Timestamp – two lines: message time and save time */
  const ts = document.createElement('div');
  ts.className = 'timestamp';
  const fmtTime = (t) => t ? t.replace('T',' ').split('.')[0] : '';

  if (refItem.message_time && refItem.datetime) {
    const mt = fmtTime(refItem.message_time);
    const dt = fmtTime(refItem.datetime);
    ts.innerHTML = mt ? '<div>消息时间: ' + mt + '</div>' : '';
    ts.innerHTML += dt ? '<div>储存时间: ' + dt + '</div>' : '';
    if (mt || dt) {
      bubble.appendChild(ts);
    }
  } else {
    const t = fmtTime(refItem.message_time) || fmtTime(refItem.datetime) || '-';
    ts.innerHTML = '<div>时间: ' + t + '</div>';
    bubble.appendChild(ts);
  }

  if (isGroup && n > 4) {
    ts.innerHTML += '<div class="timestamp-count">· ' + n + ' 项</div>';
  }

  bubble.appendChild(ts);
  msg.appendChild(bubble);
  return msg;
}

function createGridItem(item, contextItems, index) {
  const gi = document.createElement('div');
  gi.className = 'gi';
  gi.dataset.id = item.id;

  const url = mediaUrl(item);
  const isVideo = item.media_type === 'video';

  if (isVideo) {
    const vid = document.createElement('video');
    vid.muted = true;
    vid.preload = 'metadata';
    vid.src = url;
    gi.appendChild(vid);
    const badge = document.createElement('div');
    badge.className = 'play-badge';
    badge.innerHTML = '<svg viewBox="0 0 24 24" width="48" height="48"><circle cx="12" cy="12" r="11" fill="rgba(0,0,0,0.6)"/><polygon points="9.5,7 9.5,17 18,12" fill="white"/></svg>';
    gi.appendChild(badge);
  } else {
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.src = url;
    gi.appendChild(img);
  }

  gi.addEventListener('click', e => {
    e.stopPropagation();
    openModal(contextItems, index);
  });

  return gi;
}

/* ─── Modal ─── */
function openModal(contextItems, index) {
  state.modalItems = contextItems || [contextItems[0]];
  state.modalIndex = index || 0;
  renderModalItem();
  document.getElementById('modal').classList.add('open');
}

function renderModalItem() {
  const items = state.modalItems;
  if (!items || items.length === 0) return;
  const idx = state.modalIndex;
  const item = items[idx];
  if (!item) return;

  state.currentMediaId = item.id;
  const media = document.getElementById('modalMedia');
  const url = mediaUrl(item);

  const oldVid = media.querySelector('video');
  if (oldVid) { oldVid.pause(); oldVid.src = ''; oldVid.load(); }
  media.innerHTML = '';

  if (item.media_type === 'video') {
    media.innerHTML = '<video controls autoplay src="' + escape(url) + '"></video>';
  } else {
    media.innerHTML = '<img src="' + escape(url) + '" alt="">';
  }

  document.getElementById('modalCaption').textContent = item.caption || '';

  const meta = document.getElementById('modalMeta');
  const esc = escape;
  const fmt = (t) => t ? t.replace('T',' ').split('.')[0] : '';
  const stLabel = item.source_type ? sourceTypeLabel(item.source_type) : '';

  let html = '';

  /* 文件名 */
  html += '<div class="meta-item"><span class="meta-label">文件: </span>' + esc(item.filename || '') + '</div>';

  /* 类型 */
  html += '<div class="meta-item"><span class="meta-label">类型: </span>' + esc(item.media_type || '') + '</div>';

  if (item.source_name) {
    let srcTxt = esc(item.source_name);
    if (item.source_link) {
      srcTxt += ' <a href="' + esc(item.source_link) + '" target="_blank" rel="noopener" style="color:var(--accent)">原消息</a>';
    }
    html += '<div class="meta-item"><span class="meta-label">来源: </span>' + srcTxt + '</div>';
  }

  /* 来源类型 */
  if (stLabel) {
    html += '<div class="meta-item"><span class="meta-label">来源类型: </span>' + esc(stLabel) + '</div>';
  }

  /* 来源 ID */
  if (item.source_id) {
    html += '<div class="meta-item"><span class="meta-label">来源 ID: </span>' + esc(item.source_id) + '</div>';
  }

  /* 用户 */
  if (item.user_name) {
    html += '<div class="meta-item"><span class="meta-label">用户: </span>' + esc(item.user_name) + '</div>';
  }
  if (item.user_id != null) {
    html += '<div class="meta-item"><span class="meta-label">用户 ID: </span>' + item.user_id + '</div>';
  }

  /* 消息时间 */
  if (item.message_time) {
    html += '<div class="meta-item"><span class="meta-label">消息时间: </span>' + esc(fmt(item.message_time)) + '</div>';
  }

  /* 储存时间 */
  if (item.datetime) {
    html += '<div class="meta-item"><span class="meta-label">储存时间: </span>' + esc(fmt(item.datetime)) + '</div>';
  }

  /* 媒体组 */
  if (item.media_group_id) {
    html += '<div class="meta-item"><span class="meta-label">媒体组: </span>' + esc(item.media_group_id) + '</div>';
  }

  /* 消息 ID */
  if (item.message_id != null) {
    html += '<div class="meta-item"><span class="meta-label">消息 ID: </span>' + item.message_id + '</div>';
  }

  /* file_id / file_unique_id */
  if (item.file_id) {
    html += '<div class="meta-item"><span class="meta-label">File ID: </span>' + esc(item.file_id) + '</div>';
  }
  html += '<div class="meta-item"><span class="meta-label">Unique ID: </span>' + esc(item.file_unique_id || '') + '</div>';

  meta.innerHTML = html;

  const countEl = document.getElementById('modalCount');
  if (countEl) {
    countEl.textContent = items.length > 1 ? (idx + 1) + ' / ' + items.length : '';
  }

  const prevBtn = document.getElementById('modalPrev');
  const nextBtn = document.getElementById('modalNext');
  if (prevBtn) { prevBtn.style.display = idx > 0 ? 'flex' : 'none'; }
  if (nextBtn) { nextBtn.style.display = idx < items.length - 1 ? 'flex' : 'none'; }
}

function prevModal() {
  if (state.modalIndex > 0) {
    state.modalIndex--;
    renderModalItem();
  }
}

function nextModal() {
  if (state.modalIndex < state.modalItems.length - 1) {
    state.modalIndex++;
    renderModalItem();
  }
}

function closeModal() {
  const vid = document.querySelector('#modalMedia video');
  if (vid) { vid.pause(); vid.src = ''; vid.load(); }
  document.getElementById('modalMedia').innerHTML = '';
  document.getElementById('modal').classList.remove('open');
}

/* ─── Delete ─── */
async function deleteMedia(id) {
  const ok = await confirmDialog('确定要删除这个媒体吗？\n此操作不可恢复。', { title: '删除媒体', okText: '彻底删除' });
  if (!ok) return;
  const r = await authedWrite('/api/media/' + id, { method: 'DELETE' });
  if (!r) return;
  if (r.ok) {
    closeModal();
    removeItem(id);
    loadStats();
    showToast('已删除', 'success');
  } else {
    const err = await r.json().catch(() => ({}));
    showToast('删除失败: ' + (err.detail || '未知错误'), 'error');
  }
}

async function deleteMediaGroup(groupId) {
  const ok = await confirmDialog('确定要删除整个媒体组吗？\n此操作将删除该组下所有文件，不可恢复。', { title: '删除媒体组', okText: '删除整组' });
  if (!ok) return;
  const r = await authedWrite('/api/media_group/' + encodeURIComponent(groupId), { method: 'DELETE' });
  if (!r) return;
  if (r.ok) {
    removeGroup(groupId);
    loadStats();
    showToast('媒体组已删除', 'success');
  } else {
    const err = await r.json().catch(() => ({}));
    showToast('删除失败: ' + (err.detail || '未知错误'), 'error');
  }
}

function removeItem(id) {
  state.mediaList = state.mediaList.filter(m => String(m.id) !== String(id));
  const gi = document.querySelector('.gi[data-id="' + CSS.escape(String(id)) + '"]');
  if (gi) {
    const grid = gi.closest('.media-grid');
    gi.remove();
    if (grid && grid.querySelectorAll('.gi').length === 0) {
      const bubble = grid.closest('.bubble');
      if (bubble) {
        const msg = bubble.closest('.message');
        if (msg) msg.remove();
      }
    }
  }
  if (state.mediaList.length === 0) {
    const feed = document.getElementById('chatFeed');
    sentinelPreserve(feed);
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = '<div class="empty-icon">📭</div><div>暂无媒体</div>';
    feed.appendChild(empty);
  }
}

function removeGroup(groupId) {
  state.mediaList = state.mediaList.filter(m => m.media_group_id !== groupId);
  const selector = '[data-group-id="' + CSS.escape(groupId) + '"]';
  document.querySelectorAll(selector).forEach(el => el.remove());
  if (state.mediaList.length === 0) {
    const feed = document.getElementById('chatFeed');
    sentinelPreserve(feed);
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = '<div class="empty-icon">📭</div><div>暂无媒体</div>';
    feed.appendChild(empty);
  }
}

/* ─── Search ─── */
function doSearch() {
  const val = document.getElementById('searchInput').value.trim();
  state.currentSearch = val;
  state.mediaList = [];
  state.offset = 0;
  state.isLastPage = false;
  document.getElementById('searchClearBtn').style.display = state.currentSearch ? 'block' : 'none';
  loadStats();
  loadMedia(true);
}

function clearSearch() {
  document.getElementById('searchInput').value = '';
  document.getElementById('searchClearBtn').style.display = 'none';
  if (state.currentSearch) {
    state.currentSearch = '';
    state.mediaList = [];
    state.offset = 0;
    state.isLastPage = false;
loadStats();
  // 获取当前用户 ID（用于判断私聊）
  fetch('/api/stats').then(r => r.json()).then(d => {
    state.currentUserId = d.current_user_id || null;
  }).catch(() => {});
  loadMedia(true);
  }
}

function switchSort() {
  state.sortBy = state.sortBy === 'message_time' ? 'datetime' : 'message_time';
  state.mediaList = [];
  state.offset = 0;
  state.isLastPage = false;
  const btn = document.getElementById('sortToggle');
  btn.textContent = state.sortBy === 'message_time' ? '消息时间' : '下载时间';
  btn.classList.toggle('active', state.sortBy !== 'message_time');
  loadMedia(true);
}

/* ─── Init ─── */
function init() {
  loadSources();
  updateChatHeader();
  loadStats();
  loadMedia(true);

  /* Source type tabs */
  qsa('.source-type-tab').forEach(tab => {
    tab.addEventListener('click', () => selectSourceType(tab.dataset.type));
  });

  const sentinel = document.getElementById('feedSentinel');
  const observer = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting && !state.isLoading && !state.isLastPage) {
      loadMedia(false);
    }
  }, { threshold: 0.1, rootMargin: '200px' });
  observer.observe(sentinel);

  document.getElementById('searchInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
  });

  document.getElementById('searchClearBtn').addEventListener('click', clearSearch);

  const sortBtn = document.getElementById('sortToggle');
  if (sortBtn) sortBtn.addEventListener('click', switchSort);

  document.getElementById('searchInput').addEventListener('input', () => {
    document.getElementById('searchClearBtn').style.display = document.getElementById('searchInput').value ? 'block' : 'none';
  });

  document.getElementById('modalClose').addEventListener('click', closeModal);
  document.getElementById('modalPrev').addEventListener('click', prevModal);
  document.getElementById('modalNext').addEventListener('click', nextModal);
  document.getElementById('modal').addEventListener('click', e => {
    if (e.target === document.getElementById('modal')) closeModal();
  });
  document.addEventListener('keydown', e => {
    if (!document.getElementById('modal').classList.contains('open')) return;
    if (e.key === 'Escape') closeModal();
    else if (e.key === 'ArrowLeft') prevModal();
    else if (e.key === 'ArrowRight') nextModal();
  });

  document.getElementById('modalDeleteBtn').addEventListener('click', () => {
    if (state.currentMediaId != null) deleteMedia(state.currentMediaId);
  });
}

document.addEventListener('DOMContentLoaded', init);
