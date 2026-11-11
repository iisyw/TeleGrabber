import { buildPrivateMessageLink, formatBytes } from '@/lib/media';

export function statusLabel(value) {
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

export function sourceLabel(task) {
  return task.source_name || task.user_name || '-';
}

export function canRetry(task) {
  return ['failed', 'cancelled'].includes(task.status);
}

export function canCancel(task) {
  return ['queued', 'downloading'].includes(task.status);
}

export function groupStatus(list) {
  if (list.some((task) => task.status === 'downloading')) return 'downloading';
  if (list.some((task) => task.status === 'queued')) return 'queued';
  if (list.some((task) => task.status === 'paused')) return 'paused';
  if (list.some((task) => task.status === 'failed')) return 'failed';
  if (list.some((task) => task.status === 'cancelled')) return 'cancelled';
  return 'success';
}

export function displayDownloaded(task) {
  const downloaded = task.downloaded_bytes || 0;
  if (task.status === 'success' && !downloaded) return task.total_bytes || 0;
  return downloaded;
}

export function sizeLabel(task) {
  return `${formatBytes(displayDownloaded(task))} / ${formatBytes(task.total_bytes)}`;
}

/** 将任务列表按 batch_id（缺失时回退 media_group_id）聚合成单条或媒体组。 */
export function buildTaskEntries(tasks) {
  const entries = [];
  const groups = new Map();
  for (const task of tasks) {
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
}

/** 公开频道有公开链接时，补充可用的数字链接（t.me/c/...）。 */
export function detailPrivateLink(data) {
  if (
    !data || data.source_type !== 'channel' || !data.source_id ||
    !data.source_link1 || data.source_link1.includes('t.me/c/')
  ) return '';
  const msgId = data.original_message_id ?? data.message_id;
  if (msgId === null || msgId === undefined) return '';
  return buildPrivateMessageLink(data.source_id, msgId);
}
