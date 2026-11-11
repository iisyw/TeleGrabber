<template>
  <div class="task-actions">
    <button class="btn btn-small btn-cancel" @click="$emit('open')">详情</button>
    <button
      v-if="canRetry(task)"
      class="btn btn-small"
      :disabled="busy"
      @click="$emit('retry', 0)"
    >
      重试
    </button>
    <button
      v-if="canRetry(task)"
      class="btn btn-small btn-cancel"
      :disabled="busy"
      title="插队到重试队列前面"
      @click="$emit('retry', 1)"
    >
      优先
    </button>
    <button
      v-if="task.status === 'queued' && task.can_pause"
      class="btn btn-small btn-cancel"
      :disabled="busy"
      title="暂停重试队列中尚未开始的任务"
      @click="$emit('pause')"
    >
      暂停
    </button>
    <button
      v-if="task.status === 'paused'"
      class="btn btn-small"
      :disabled="busy"
      @click="$emit('resume')"
    >
      继续
    </button>
    <button
      v-if="canCancel(task)"
      class="btn btn-small btn-cancel"
      :disabled="busy"
      :title="task.status === 'downloading' ? '取消将在当前下载步骤结束后生效' : '取消排队任务'"
      @click="$emit('cancel')"
    >
      取消
    </button>
  </div>
</template>

<script setup>
import { canCancel, canRetry } from '../taskUtils';

defineProps({
  task: { type: Object, required: true },
  busy: { type: Boolean, default: false },
});

defineEmits(['open', 'retry', 'pause', 'resume', 'cancel']);
</script>

<style scoped lang="scss" src="./TaskActions.scss"></style>
