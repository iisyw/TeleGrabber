<template>
  <div :class="compact ? 'task-subitem' : 'task-card'">
    <div :class="compact ? 'task-subitem-main' : 'task-main'">
      <div class="task-title-row">
        <span :class="['task-status', task.status]">{{ statusLabel(task.status) }}</span>
        <span v-if="compact && task.item_index" class="task-group-badge">#{{ task.item_index }}</span>
        <span class="task-filename">{{ task.filename || task.file_unique_id || '-' }}</span>
      </div>
      <div class="task-meta">
        <template v-if="compact">
          <span v-if="task.media_type">{{ task.media_type }}</span>
          <span v-if="task.download_method">
            · {{ task.download_method === 'user_api' ? 'User API' : 'Bot API' }}
          </span>
          <span v-if="task.total_bytes || task.downloaded_bytes">· {{ sizeLabel(task) }}</span>
        </template>
        <template v-else>
          <span>{{ sourceLabel(task) }}</span>
          <span v-if="task.media_type">· {{ task.media_type }}</span>
          <span v-if="task.download_method">
            · {{ task.download_method === 'user_api' ? 'User API' : 'Bot API' }}
          </span>
          <span v-if="task.total_bytes || task.downloaded_bytes">· {{ sizeLabel(task) }}</span>
        </template>
      </div>
      <div v-if="!compact && task.status === 'downloading'" class="task-progress">
        <div class="task-progress-bar" :style="{ width: `${task.progress || 0}%` }" />
      </div>
      <div v-if="task.error" class="task-error">{{ task.error }}</div>
    </div>

    <div v-if="!compact" class="task-side">
      <div class="task-time">
        <div>创建 {{ formatTime(task.created_at) }}</div>
        <div v-if="task.finished_at" class="task-finished">完成 {{ formatTime(task.finished_at) }}</div>
      </div>
      <TaskActions
        :task="task"
        :busy="busy"
        @open="$emit('open', task)"
        @retry="(priority) => $emit('retry', task, priority)"
        @pause="$emit('pause', task)"
        @resume="$emit('resume', task)"
        @cancel="$emit('cancel', task)"
      />
    </div>
    <TaskActions
      v-else
      class="task-actions--wrap"
      :task="task"
      :busy="busy"
      @open="$emit('open', task)"
      @retry="(priority) => $emit('retry', task, priority)"
      @pause="$emit('pause', task)"
      @resume="$emit('resume', task)"
      @cancel="$emit('cancel', task)"
    />
  </div>
</template>

<script setup>
import { formatTime } from '@/lib/media';
import TaskActions from './TaskActions.vue';
import { sizeLabel, sourceLabel, statusLabel } from '../taskUtils';

defineProps({
  task: { type: Object, required: true },
  compact: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
});

defineEmits(['open', 'retry', 'pause', 'resume', 'cancel']);
</script>

<style scoped lang="scss" src="./TaskItem.scss"></style>
