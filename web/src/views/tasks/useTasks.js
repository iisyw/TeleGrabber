import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import {
  cancelTask, fetchTaskDetail, fetchTasks, pauseTask, resumeTask,
  retryFailedTasks, retryTask,
} from '@/api/tasks';
import { buildTaskEntries, detailPrivateLink as buildDetailPrivateLink } from './taskUtils';

const PAGE_SIZE = 50;

export function useTasks() {
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
  const taskEntries = computed(() => buildTaskEntries(tasks.value));
  const detailPrivateLink = computed(() => buildDetailPrivateLink(detail.value));

  let timer = null;
  let prevFailed = null;
  let prevSuccess = null;

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
      const nextTasks = (data && data.tasks) || [];
      if (tasks.value.length <= limit) {
        tasks.value = nextTasks;
      } else {
        // 用户已展开加载超过 200 条长列表时，增量合并更新已有状态，避免长列表被自动截断缩回
        const nextMap = new Map(nextTasks.map((t) => [t.id, t]));
        tasks.value = tasks.value.map((t) => nextMap.get(t.id) || t);
      }
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

  function selectStatus(value) {
    if (status.value === value) return;
    status.value = value;
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

  function toggleGroup(key) {
    expandedGroups.value = {
      ...expandedGroups.value,
      [key]: !expandedGroups.value[key],
    };
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

  onMounted(() => {
    load(false);
    timer = setInterval(refresh, 3000);
  });

  onBeforeUnmount(() => {
    if (timer) clearInterval(timer);
  });

  return {
    tasks, counts, total, status, loading, error, busy,
    detailOpen, detail, filterSource, filterGroup, expandedGroups,
    notifyEnabled, hasMore, taskEntries, detailPrivateLink,
    load, refresh, applyFilters, clearFilters, selectStatus,
    openDetail, toggleGroup, toggleNotify,
    retryOne, retryGroup, pauseOne, resumeOne, retryAllFailed, cancelOne,
  };
}
