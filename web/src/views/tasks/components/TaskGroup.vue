<template>
  <div class="task-group">
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
          <button class="btn btn-small btn-cancel" @click="$emit('toggle', entry.key)">
            {{ expanded ? '收起' : `展开 ${entry.tasks.length}` }}
          </button>
          <button
            v-if="entry.failed"
            class="btn btn-small"
            :disabled="busy"
            @click="$emit('retry-group', entry)"
          >
            重试失败
          </button>
        </div>
      </div>
    </div>

    <div v-if="expanded" class="task-group-items">
      <TaskItem
        v-for="task in entry.tasks"
        :key="task.id"
        :task="task"
        compact
        :busy="busy"
        @open="$emit('open', $event)"
        @retry="(taskItem, priority) => $emit('retry', taskItem, priority)"
        @pause="$emit('pause', $event)"
        @resume="$emit('resume', $event)"
        @cancel="$emit('cancel', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { formatBytes, formatTime } from '@/lib/media';
import TaskItem from './TaskItem.vue';
import { statusLabel } from '../taskUtils';

defineProps({
  entry: { type: Object, required: true },
  expanded: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
});

defineEmits(['toggle', 'retry-group', 'open', 'retry', 'pause', 'resume', 'cancel']);
</script>

<style scoped lang="scss" src="./TaskGroup.scss"></style>
