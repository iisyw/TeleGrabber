<template>
  <div class="manage-page">
    <div class="manage-header">
      <div>
        <div class="manage-title">下载任务</div>
        <div class="manage-subtitle">
          共 {{ total }} 条任务
          <span v-if="counts.downloading"> · 下载中 {{ counts.downloading }}</span>
          <span v-if="counts.failed"> · 失败 {{ counts.failed }}</span>
        </div>
      </div>
      <div class="manage-actions">
        <button
          class="btn btn-cancel"
          :class="{ active: notifyEnabled }"
          @click="toggleNotify"
        >
          {{ notifyEnabled ? '通知已开启' : '开启通知' }}
        </button>
        <button class="btn" @click="load">刷新</button>
        <button
          v-if="counts.failed"
          class="btn"
          :disabled="busy"
          @click="retryAllFailed"
        >
          重试全部失败
        </button>
      </div>
    </div>

    <div class="manage-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        class="manage-tab"
        :class="{ active: status === tab.value }"
        @click="selectStatus(tab.value)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="task-filters">
      <input
        v-model="filterSource"
        type="text"
        placeholder="按来源筛选"
        @keydown.enter="applyFilters"
      />
      <input
        v-model="filterGroup"
        type="text"
        placeholder="按媒体组 ID 筛选"
        @keydown.enter="applyFilters"
      />
      <button class="btn btn-small" @click="applyFilters">筛选</button>
      <button class="btn btn-small btn-cancel" @click="clearFilters">清除</button>
    </div>

    <div v-if="loading && !tasks.length" class="manage-empty">加载中...</div>
    <div v-else-if="!tasks.length" class="manage-empty">{{ error || '暂无任务' }}</div>

    <div v-else class="task-list">
      <template v-for="entry in taskEntries" :key="entry.key">
        <div v-if="entry.type === 'single'" class="task-card">
          <div class="task-main">
            <div class="task-title-row">
              <span :class="['task-status', entry.task.status]">{{ statusLabel(entry.task.status) }}</span>
              <span class="task-filename">{{ entry.task.filename || entry.task.file_unique_id || '-' }}</span>
            </div>
            <div class="task-meta">
              <span>{{ sourceLabel(entry.task) }}</span>
              <span v-if="entry.task.media_type">· {{ entry.task.media_type }}</span>
              <span v-if="entry.task.download_method">· {{ entry.task.download_method === 'user_api' ? 'User API' : 'Bot API' }}</span>
              <span v-if="entry.task.total_bytes || entry.task.downloaded_bytes">
                · {{ sizeLabel(entry.task) }}
              </span>
            </div>
            <div v-if="entry.task.status === 'downloading'" class="task-progress">
              <div class="task-progress-bar" :style="{ width: `${entry.task.progress || 0}%` }" />
            </div>
            <div v-if="entry.task.error" class="task-error">{{ entry.task.error }}</div>
          </div>
          <div class="task-side">
            <div class="task-time">
              <div>创建 {{ formatTime(entry.task.created_at) }}</div>
              <div v-if="entry.task.finished_at" class="task-finished">完成 {{ formatTime(entry.task.finished_at) }}</div>
            </div>
            <div class="task-actions">
              <button class="btn btn-small btn-cancel" @click="openDetail(entry.task)">详情</button>
              <button
                v-if="canRetry(entry.task)"
                class="btn btn-small"
                :disabled="busy"
                @click="retryOne(entry.task)"
              >
                重试
              </button>
              <button
                v-if="canRetry(entry.task)"
                class="btn btn-small btn-cancel"
                :disabled="busy"
                title="插队到重试队列前面"
                @click="retryOne(entry.task, 1)"
              >
                优先
              </button>
              <button
                v-if="entry.task.status === 'queued' && entry.task.can_pause"
                class="btn btn-small btn-cancel"
                :disabled="busy"
                title="暂停重试队列中尚未开始的任务"
                @click="pauseOne(entry.task)"
              >
                暂停
              </button>
              <button
                v-if="entry.task.status === 'paused'"
                class="btn btn-small"
                :disabled="busy"
                @click="resumeOne(entry.task)"
              >
                继续
              </button>
              <button
                v-if="canCancel(entry.task)"
                class="btn btn-small btn-cancel"
                :disabled="busy"
                :title="entry.task.status === 'downloading' ? '取消将在当前下载步骤结束后生效' : '取消排队任务'"
                @click="cancelOne(entry.task)"
              >
                取消
              </button>
            </div>
          </div>
        </div>

        <div v-else class="task-group">
          <div class="task-card task-card--group">
            <div class="task-main">
              <div class="task-title-row">
                <span :class="['task-status', entry.status]">{{ statusLabel(entry.status) }}</span>
                <span class="task-group-badge">媒体组</span>
                <span class="task-filename">{{ entry.sourceName }}</span>
              </div>
              <div class="task-meta">
                <span>{{ entry.tasks.length }} 个文件</span>
                <span>· 成功 {{ entry.success }}</span>
                <span v-if="entry.failed">· 失败 {{ entry.failed }}</span>
                <span v-if="entry.running">· 进行中 {{ entry.running }}</span>
                <span v-if="entry.totalBytes">· {{ formatBytes(entry.totalBytes) }}</span>
              </div>
              <div class="task-meta">
                <span :title="entry.groupId">组 ID {{ entry.groupId.slice(-8) }}</span>
                <span v-if="entry.batchId && entry.batchId !== entry.groupId">
                  · 批次 {{ entry.batchId.slice(-6) }}
                </span>
              </div>
            </div>
            <div class="task-side">
              <div class="task-time">
                <div>开始 {{ formatTime(entry.createdAt) }}</div>
                <div class="task-finished">更新 {{ formatTime(entry.updatedAt) }}</div>
              </div>
              <div class="task-actions">
                <button class="btn btn-small btn-cancel" @click="toggleGroup(entry.key)">
                  {{ expandedGroups[entry.key] ? '收起' : `展开 ${entry.tasks.length}` }}
                </button>
                <button
                  v-if="entry.failed"
                  class="btn btn-small"
                  :disabled="busy"
                  @click="retryGroup(entry)"
                >
                  重试失败
                </button>
              </div>
            </div>
          </div>

          <div v-if="expandedGroups[entry.key]" class="task-group-items">
            <div v-for="task in entry.tasks" :key="task.id" class="task-subitem">
              <div class="task-subitem-main">
                <div class="task-title-row">
                  <span :class="['task-status', task.status]">{{ statusLabel(task.status) }}</span>
                  <span v-if="task.item_index" class="task-group-badge">#{{ task.item_index }}</span>
                  <span class="task-filename">{{ task.filename || task.file_unique_id || '-' }}</span>
                </div>
                <div class="task-meta">
                  <span v-if="task.media_type">{{ task.media_type }}</span>
                  <span v-if="task.download_method">· {{ task.download_method === 'user_api' ? 'User API' : 'Bot API' }}</span>
                  <span v-if="task.total_bytes || task.downloaded_bytes">· {{ sizeLabel(task) }}</span>
                </div>
                <div v-if="task.error" class="task-error">{{ task.error }}</div>
              </div>
              <div class="task-actions task-actions--wrap">
                <button class="btn btn-small btn-cancel" @click="openDetail(task)">详情</button>
                <button v-if="canRetry(task)" class="btn btn-small" :disabled="busy" @click="retryOne(task)">重试</button>
                <button v-if="canRetry(task)" class="btn btn-small btn-cancel" :disabled="busy" @click="retryOne(task, 1)">优先</button>
                <button v-if="task.status === 'queued' && task.can_pause" class="btn btn-small btn-cancel" :disabled="busy" @click="pauseOne(task)">暂停</button>
                <button v-if="task.status === 'paused'" class="btn btn-small" :disabled="busy" @click="resumeOne(task)">继续</button>
                <button v-if="canCancel(task)" class="btn btn-small btn-cancel" :disabled="busy" @click="cancelOne(task)">取消</button>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
    <div v-if="hasMore" class="task-more">
      <button class="btn" :disabled="loading" @click="load(true)">加载更多</button>
    </div>

    <ElDrawer v-model="detailOpen" title="任务详情" size="420px">
      <div v-if="detail" class="task-detail">
        <div class="detail-row"><span>状态</span><span>{{ statusLabel(detail.status) }}</span></div>
        <div class="detail-row"><span>文件名</span><span>{{ detail.filename || '-' }}</span></div>
        <div class="detail-row"><span>来源</span><span>{{ detail.source_name || '-' }}</span></div>
        <div class="detail-row"><span>媒体类型</span><span>{{ detail.media_type || '-' }}</span></div>
        <div class="detail-row"><span>下载方式</span><span>{{ detail.download_method || '-' }}</span></div>
        <div class="detail-row"><span>进度</span><span>{{ detail.progress || 0 }}%</span></div>
        <div class="detail-row"><span>大小</span><span>{{ sizeLabel(detail) }}</span></div>
        <div class="detail-row"><span>媒体组</span><span>{{ detail.media_group_id || '-' }}</span></div>
        <div class="detail-row"><span>下载批次</span><span>{{ detail.batch_id || '-' }}</span></div>
        <div class="detail-row"><span>组内序号</span><span>{{ detail.item_index ?? '-' }}</span></div>
        <div class="detail-row"><span>聊天 ID</span><span>{{ detail.chat_id ?? '-' }}</span></div>
        <div class="detail-row"><span>消息 ID</span><span>{{ detail.message_id ?? '-' }}</span></div>
        <div class="detail-row"><span>Unique ID</span><span class="detail-break">{{ detail.file_unique_id || '-' }}</span></div>
        <div class="detail-row" v-if="detail.source_link1">
          <span>{{ detail.source_link1.includes('t.me/c/') ? '数字链接' : '公开链接' }}</span>
          <a :href="detail.source_link1" target="_blank" rel="noopener">{{ detail.source_link1 }}</a>
        </div>
        <div class="detail-row" v-if="detailPrivateLink">
          <span>数字链接</span>
          <a :href="detailPrivateLink" target="_blank" rel="noopener">{{ detailPrivateLink }}</a>
        </div>
        <div class="detail-row"><span>原始消息 ID</span><span>{{ detail.original_message_id ?? '-' }}</span></div>
        <div class="detail-row"><span>创建时间</span><span>{{ formatTime(detail.created_at) || '-' }}</span></div>
        <div class="detail-row"><span>更新时间</span><span>{{ formatTime(detail.updated_at) || '-' }}</span></div>
        <div class="detail-row"><span>完成时间</span><span>{{ formatTime(detail.finished_at) || '-' }}</span></div>
        <div class="detail-row detail-error"><span>错误</span><span>{{ detail.error || '-' }}</span></div>
        <div v-if="!detail.has_retry_context" class="detail-warning">
          该任务没有保存重试上下文，无法直接重试。请重新发送原消息或链接生成新任务。
        </div>
      </div>
    </ElDrawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElDrawer, ElMessage } from 'element-plus';
import { cancelTask, fetchTaskDetail, fetchTasks, pauseTask, resumeTask, retryFailedTasks, retryTask } from '@/api/tasks';
import { buildPrivateMessageLink, formatBytes, formatTime } from '@/lib/media';

const tabs = [
  { value: '', label: '全部' },
  { value: 'downloading', label: '下载中' },
  { value: 'queued', label: '排队' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'paused', label: '暂停' },
  { value: 'cancelled', label: '已取消' },
];

const tasks = ref([]);
const counts = ref({});
const total = ref(0);
const status = ref('');
const loading = ref(false);
const error = ref('');
const busy = ref(false);
const detailOpen = ref(false);
const detail = ref(null);
const filterSource = ref('');
const filterGroup = ref('');
const appliedSource = ref('');
const appliedGroup = ref('');
const expandedGroups = ref({});
const notifyEnabled = ref(localStorage.getItem('telegrabber-task-notify') === '1');
const hasMore = computed(() => tasks.value.length < total.value);
const detailPrivateLink = computed(() => {
  const data = detail.value;
  if (
    !data || data.source_type !== 'channel' || !data.source_id ||
    !data.source_link1 || data.source_link1.includes('t.me/c/')
  ) return '';
  const msgId = data.original_message_id ?? data.message_id;
  if (msgId === null || msgId === undefined) return '';
  return buildPrivateMessageLink(data.source_id, msgId);
});
const PAGE_SIZE = 50;
let timer = null;
let prevFailed = null;
let prevSuccess = null;

function statusLabel(value) {
  return {
    queued: '排队',
    downloading: '下载中',
    success: '成功',
    failed: '失败',
    skipped: '跳过',
    paused: '暂停',
    cancelled: '已取消',
  }[value] || value || '-';
}

function sourceLabel(task) {
  return task.source_name || task.user_name || '-';
}

function canRetry(task) {
  return ['failed', 'cancelled'].includes(task.status);
}

function canCancel(task) {
  return ['queued', 'downloading'].includes(task.status);
}

function groupStatus(list) {
  if (list.some((task) => task.status === 'downloading')) return 'downloading';
  if (list.some((task) => task.status === 'queued')) return 'queued';
  if (list.some((task) => task.status === 'paused')) return 'paused';
  if (list.some((task) => task.status === 'failed')) return 'failed';
  if (list.some((task) => task.status === 'cancelled')) return 'cancelled';
  return 'success';
}

const taskEntries = computed(() => {
  const entries = [];
  const groups = new Map();
  for (const task of tasks.value) {
    if (!task.media_group_id) {
      entries.push({ type: 'single', key: `task-${task.id}`, task });
      continue;
    }
    const batchKey = task.batch_id || task.media_group_id;
    let entry = groups.get(batchKey);
    if (!entry) {
      entry = {
        type: 'group',
        key: `group-${batchKey}`,
        groupId: task.media_group_id,
        batchId: task.batch_id || '',
        tasks: [],
      };
      groups.set(batchKey, entry);
      entries.push(entry);
    }
    entry.tasks.push(task);
  }

  for (const entry of entries) {
    if (entry.type !== 'group') continue;
    const list = entry.tasks;
    entry.sourceName = list.find((task) => task.source_name)?.source_name || '未命名来源';
    entry.success = list.filter((task) => task.status === 'success').length;
    entry.failed = list.filter((task) => task.status === 'failed').length;
    entry.running = list.filter((task) => ['downloading', 'queued', 'paused'].includes(task.status)).length;
    entry.totalBytes = list.reduce((sum, task) => sum + (task.total_bytes || 0), 0);
    entry.createdAt = list[list.length - 1]?.created_at || '';
    entry.updatedAt = list[0]?.updated_at || '';
    entry.status = groupStatus(list);
  }
  return entries;
});

function toggleGroup(key) {
  expandedGroups.value = {
    ...expandedGroups.value,
    [key]: !expandedGroups.value[key],
  };
}

function displayDownloaded(task) {
  const downloaded = task.downloaded_bytes || 0;
  if (task.status === 'success' && !downloaded) return task.total_bytes || 0;
  return downloaded;
}

function sizeLabel(task) {
  return `${formatBytes(displayDownloaded(task))} / ${formatBytes(task.total_bytes)}`;
}

function notify(title, body) {
  if (!notifyEnabled.value || typeof Notification === 'undefined') return;
  if (Notification.permission !== 'granted') return;
  new Notification(title, { body });
}

function applyCounts(nextCounts) {
  const failed = nextCounts.failed || 0;
  const success = nextCounts.success || 0;
  if (prevFailed !== null && failed > prevFailed) {
    notify('下载任务失败', `新增 ${failed - prevFailed} 个失败任务`);
  }
  if (prevSuccess !== null && success > prevSuccess) {
    notify('下载任务完成', `新增 ${success - prevSuccess} 个成功任务`);
  }
  prevFailed = failed;
  prevSuccess = success;
  counts.value = nextCounts;
}

function taskParams() {
  return {
    status: status.value || undefined,
    source_name: appliedSource.value || undefined,
    media_group_id: appliedGroup.value || undefined,
  };
}

async function load(append = false) {
  loading.value = true;
  try {
    const offset = append ? tasks.value.length : 0;
    const data = await fetchTasks({
      ...taskParams(),
      limit: PAGE_SIZE,
      offset,
    });
    const nextTasks = (data && data.tasks) || [];
    tasks.value = append ? tasks.value.concat(nextTasks) : nextTasks;
    applyCounts((data && data.counts) || {});
    total.value = (data && data.total) || 0;
    error.value = '';
  } catch {
    error.value = '加载失败';
  } finally {
    loading.value = false;
  }
}

async function refresh() {
  if (!tasks.value.length) return load(false);
  try {
    const limit = Math.min(Math.max(tasks.value.length, PAGE_SIZE), 200);
    const data = await fetchTasks({
      ...taskParams(),
      limit,
      offset: 0,
    });
    tasks.value = (data && data.tasks) || [];
    applyCounts((data && data.counts) || {});
    total.value = (data && data.total) || 0;
    error.value = '';
  } catch {
    // 定时刷新失败不覆盖当前列表
  }
}

function applyFilters() {
  appliedSource.value = filterSource.value.trim();
  appliedGroup.value = filterGroup.value.trim();
  load(false);
}

function clearFilters() {
  filterSource.value = '';
  filterGroup.value = '';
  appliedSource.value = '';
  appliedGroup.value = '';
  load(false);
}

async function openDetail(task) {
  detailOpen.value = true;
  detail.value = null;
  try {
    detail.value = await fetchTaskDetail(task.id);
  } catch {
    detailOpen.value = false;
  }
}

async function toggleNotify() {
  if (notifyEnabled.value) {
    notifyEnabled.value = false;
    localStorage.removeItem('telegrabber-task-notify');
    return;
  }
  if (typeof Notification === 'undefined') {
    ElMessage.warning('当前浏览器不支持桌面通知');
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    ElMessage.warning('未获得通知权限');
    return;
  }
  notifyEnabled.value = true;
  localStorage.setItem('telegrabber-task-notify', '1');
}

async function retryOne(task, priority = 0) {
  busy.value = true;
  try {
    await retryTask(task.id, priority);
    ElMessage.success(priority ? '已优先加入重试队列' : '已加入重试队列');
    await refresh();
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    busy.value = false;
  }
}

async function retryGroup(entry) {
  busy.value = true;
  try {
    const res = await retryFailedTasks(100, '', entry.groupId, entry.batchId);
    const started = (res && res.data && res.data.started) || [];
    ElMessage.success(`媒体组已加入 ${started.length} 个重试任务`);
    expandedGroups.value = { ...expandedGroups.value, [entry.key]: true };
    await refresh();
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    busy.value = false;
  }
}

async function pauseOne(task) {
  busy.value = true;
  try {
    await pauseTask(task.id);
    ElMessage.success('已暂停');
    await refresh();
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    busy.value = false;
  }
}

async function resumeOne(task) {
  busy.value = true;
  try {
    await resumeTask(task.id);
    ElMessage.success('已继续');
    await refresh();
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    busy.value = false;
  }
}

async function retryAllFailed() {
  busy.value = true;
  try {
    const res = await retryFailedTasks(20);
    const started = (res && res.data && res.data.started) || [];
    ElMessage.success(`已加入 ${started.length} 个重试任务`);
    await refresh();
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    busy.value = false;
  }
}

async function cancelOne(task) {
  busy.value = true;
  try {
    await cancelTask(task.id);
    ElMessage.success(task.status === 'downloading' ? '已请求取消，将在当前下载步骤结束后生效' : '已取消');
    await refresh();
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    busy.value = false;
  }
}

function selectStatus(value) {
  if (status.value === value) return;
  status.value = value;
  load(false);
}

onMounted(() => {
  load(false);
  timer = setInterval(refresh, 3000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<style scoped lang="scss" src="./index.scss"></style>
