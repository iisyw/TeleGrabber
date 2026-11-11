<template>
  <div class="manage-page">
    <div class="manage-header">
      <div>
        <div class="manage-title">存储管理</div>
        <div class="manage-subtitle">查看媒体占用与来源分布</div>
      </div>
      <div class="manage-actions">
        <button class="btn" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="summary" class="storage-cards">
      <div class="storage-card">
        <div class="storage-card-label">媒体总数</div>
        <div class="storage-card-value">{{ summary.total_count ?? '-' }}</div>
      </div>
      <div class="storage-card">
        <div class="storage-card-label">媒体占用</div>
        <div class="storage-card-value">{{ formatBytes(summary.total_bytes) }}</div>
      </div>
      <div class="storage-card">
        <div class="storage-card-label">磁盘已用</div>
        <div class="storage-card-value">{{ formatBytes(summary.disk && summary.disk.used) }}</div>
      </div>
      <div class="storage-card">
        <div class="storage-card-label">磁盘剩余</div>
        <div class="storage-card-value">{{ formatBytes(summary.disk && summary.disk.free) }}</div>
      </div>
    </div>

    <div v-if="summary" class="storage-section">
      <div class="storage-section-title">按来源</div>
      <div class="storage-table">
        <div class="storage-row storage-head">
          <span>来源</span><span>类型</span><span>数量</span><span>占用</span>
        </div>
        <div v-for="row in summary.by_source" :key="`${row.source_name}-${row.source_type}`" class="storage-row">
          <span class="storage-source">{{ row.source_name || '未分类' }}</span>
          <span>{{ row.source_type || '-' }}</span>
          <span>{{ row.count }}</span>
          <span>{{ formatBytes(row.bytes) }}</span>
        </div>
      </div>
    </div>

    <div class="storage-section">
      <div class="storage-section-title">重复拦截记录</div>
      <div v-if="!duplicates.length" class="manage-empty">暂无重复拦截记录</div>
      <div v-else class="duplicate-list">
        <div v-for="group in duplicates" :key="group.file_unique_id" class="duplicate-item">
          <div class="duplicate-main">
            <div class="duplicate-title">
              {{ group.count > 1 ? `${group.count} 次拦截` : '已拦截' }} · {{ formatBytes(group.total_bytes) }}
            </div>
            <div class="duplicate-files">{{ (group.filenames && group.filenames.length ? group.filenames.join(' / ') : group.file_unique_id) }}</div>
          </div>
          <div class="duplicate-sources">{{ (group.sources && group.sources.length ? group.sources.join(' / ') : '未知来源') }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { fetchDuplicates, fetchStorageSummary } from '@/api/storage';
import { formatBytes } from '@/lib/media';

const summary = ref(null);
const duplicates = ref([]);

async function load() {
  try {
    const [summaryData, duplicateData] = await Promise.all([
      fetchStorageSummary(),
      fetchDuplicates(),
    ]);
    summary.value = summaryData;
    duplicates.value = duplicateData || [];
  } catch {
    // 错误由 request.js 统一提示
  }
}

onMounted(load);
</script>

<style scoped lang="scss" src="./index.scss"></style>
