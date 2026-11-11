<template>
  <ElDrawer
    :model-value="modelValue"
    title="任务详情"
    size="420px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
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
      <div class="detail-row">
        <span>Unique ID</span><span class="detail-break">{{ detail.file_unique_id || '-' }}</span>
      </div>
      <div class="detail-row" v-if="detail.source_link1">
        <span>{{ detail.source_link1.includes('t.me/c/') ? '数字链接' : '公开链接' }}</span>
        <a :href="detail.source_link1" target="_blank" rel="noopener">{{ detail.source_link1 }}</a>
      </div>
      <div class="detail-row" v-if="privateLink">
        <span>数字链接</span>
        <a :href="privateLink" target="_blank" rel="noopener">{{ privateLink }}</a>
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
</template>

<script setup>
import { ElDrawer } from 'element-plus';
import { formatTime } from '@/lib/media';
import { sizeLabel, statusLabel } from '../taskUtils';

defineProps({
  modelValue: { type: Boolean, default: false },
  detail: { type: Object, default: null },
  privateLink: { type: String, default: '' },
});

defineEmits(['update:modelValue']);
</script>

<style scoped lang="scss" src="./TaskDetailDrawer.scss"></style>
