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
        <button class="btn" @click="load(false)">刷新</button>
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
    <div v-else-if="!taskEntries.length" class="manage-empty">{{ error || '暂无任务' }}</div>

    <div v-else class="task-list">
      <template v-for="entry in taskEntries">
        <TaskItem
          v-if="entry.type === 'single'"
          :key="`single-${entry.key}`"
          :task="entry.task"
          :busy="busy"
          @open="openDetail"
          @retry="retryOne"
          @pause="pauseOne"
          @resume="resumeOne"
          @cancel="cancelOne"
        />
        <TaskGroup
          v-else
          :key="`group-${entry.key}`"
          :entry="entry"
          :expanded="!!expandedGroups[entry.key]"
          :busy="busy"
          @toggle="toggleGroup"
          @retry-group="retryGroup"
          @open="openDetail"
          @retry="retryOne"
          @pause="pauseOne"
          @resume="resumeOne"
          @cancel="cancelOne"
        />
      </template>
    </div>

    <div v-if="hasMore" class="task-more">
      <button class="btn" :disabled="loading" @click="load(true)">加载更多</button>
    </div>

    <TaskDetailDrawer
      v-model="detailOpen"
      :detail="detail"
      :private-link="detailPrivateLink"
    />
  </div>
</template>

<script setup>
import TaskDetailDrawer from './components/TaskDetailDrawer.vue';
import TaskGroup from './components/TaskGroup.vue';
import TaskItem from './components/TaskItem.vue';
import { useTasks } from './useTasks';

const tabs = [
  { value: '', label: '全部' },
  { value: 'downloading', label: '下载中' },
  { value: 'queued', label: '排队' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'paused', label: '暂停' },
  { value: 'cancelled', label: '已取消' },
];

const {
  tasks, counts, total, status, loading, error, busy, detailOpen, detail,
  filterSource, filterGroup, expandedGroups, notifyEnabled, hasMore,
  taskEntries, detailPrivateLink,
  load, applyFilters, clearFilters, selectStatus, openDetail, toggleGroup,
  toggleNotify, retryOne, retryGroup, pauseOne, resumeOne, retryAllFailed, cancelOne,
} = useTasks();
</script>

<style scoped lang="scss" src="./index.scss"></style>
