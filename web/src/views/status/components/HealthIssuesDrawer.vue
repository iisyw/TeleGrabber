<template>
  <ElDrawer
    :model-value="modelValue"
    title="数据健康问题清单"
    size="580px"
    class="health-issues-drawer"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="health-drawer-container">
      <!-- 顶部过滤与统计 -->
      <div class="health-drawer-header">
        <div class="health-type-tabs">
          <button
            v-for="tab in typeTabs"
            :key="tab.value"
            type="button"
            class="health-tab-btn"
            :class="{ active: currentType === tab.value }"
            @click="switchType(tab.value)"
          >
            {{ tab.label }}
          </button>
        </div>

        <div class="health-drawer-actions">
          <button
            v-if="currentType === 'missing_thumbs'"
            class="btn btn-small"
            :disabled="busy"
            @click="handleRepair('thumbs')"
          >
            {{ repairing ? '修复中...' : '补齐缩略图' }}
          </button>
          <button
            v-else-if="currentType === 'missing_dimensions'"
            class="btn btn-small"
            :disabled="busy"
            @click="handleRepair('dimensions')"
          >
            {{ repairing ? '修复中...' : '补齐尺寸大小' }}
          </button>
          <button
            v-else-if="currentType === 'missing_files'"
            class="btn btn-small btn-danger"
            :disabled="busy || !items.length"
            @click="handleCleanMissing"
          >
            {{ cleaning ? '清理中...' : '清理已丢失记录' }}
          </button>
          <template v-else>
            <button
              class="btn btn-small"
              :disabled="busy"
              @click="handleRepair('all')"
            >
              {{ repairing ? '修复中...' : '全部自动修复' }}
            </button>
          </template>
        </div>
      </div>

      <!-- 列表内容 -->
      <div v-if="loading && !items.length" class="health-drawer-empty">
        加载中...
      </div>
      <div v-else-if="!items.length" class="health-drawer-empty">
        当前分类暂无异常记录，数据健康良好。
      </div>
      <div v-else class="health-issue-list">
        <div
          v-for="item in items"
          :key="item.id"
          class="health-issue-card"
        >
          <div class="issue-card-thumb">
            <img
              v-if="item.thumb_url"
              :src="item.thumb_url"
              alt="thumb"
              class="issue-thumb-img"
              loading="lazy"
            />
            <div v-else class="issue-thumb-placeholder">
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <polyline points="21 15 16 10 5 21" />
              </svg>
            </div>
          </div>

          <div class="issue-card-info">
            <div class="issue-card-top">
              <span class="issue-filename" :title="item.filename">{{ item.filename }}</span>
              <span class="issue-id">ID #{{ item.id }}</span>
            </div>

            <div class="issue-card-meta">
              <span class="issue-source" :title="`来源: ${item.source_name}`">{{ item.source_name }}</span>
              <span class="issue-time">{{ formatTime(item.datetime) }}</span>
              <span class="issue-type">{{ item.media_type }}</span>
            </div>

            <div class="issue-card-stats">
              <span>尺寸: {{ item.width && item.height ? `${item.width} × ${item.height}` : '未知' }}</span>
              <span>大小: {{ formatBytes(item.file_size) }}</span>
            </div>

            <div class="issue-card-tags">
              <span
                v-if="item.issues.includes('missing_files')"
                class="issue-tag tag-danger"
              >
                原文件缺失
              </span>
              <span
                v-if="item.issues.includes('missing_thumbs')"
                class="issue-tag tag-warn"
              >
                缺失缩略图
              </span>
              <span
                v-if="item.issues.includes('missing_dimensions')"
                class="issue-tag tag-info"
              >
                缺少尺寸大小
              </span>
            </div>
          </div>
        </div>

        <div v-if="hasMore" class="health-drawer-more">
          <button
            class="btn btn-small btn-cancel"
            :disabled="loading"
            @click="loadMore"
          >
            {{ loading ? '加载中...' : `加载更多 (${items.length}/${total})` }}
          </button>
        </div>
      </div>
    </div>
  </ElDrawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { ElDrawer, ElMessage, ElMessageBox } from 'element-plus';
import { fetchHealthIssues, repairHealthIssues, cleanMissingHealthFiles } from '@/api/status';
import { formatBytes, formatTime } from '@/lib/media';

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  initialType: {
    type: String,
    default: 'all',
  },
});

const emit = defineEmits(['update:modelValue', 'repaired']);

const currentType = ref('all');
const items = ref([]);
const total = ref(0);
const loading = ref(false);
const repairing = ref(false);
const cleaning = ref(false);

const busy = computed(() => loading.value || repairing.value || cleaning.value);
const hasMore = computed(() => items.value.length < total.value);

const typeTabs = [
  { value: 'all', label: '全部异常' },
  { value: 'missing_thumbs', label: '缺失缩略图' },
  { value: 'missing_dimensions', label: '缺少尺寸' },
  { value: 'missing_files', label: '缺失文件' },
];

async function loadData(append = false) {
  if (loading.value) return;
  loading.value = true;
  try {
    const offset = append ? items.value.length : 0;
    const res = await fetchHealthIssues({
      type: currentType.value,
      limit: 50,
      offset,
    });
    const nextItems = (res && res.items) || [];
    total.value = (res && res.total) || 0;
    items.value = append ? items.value.concat(nextItems) : nextItems;
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    loading.value = false;
  }
}

function loadMore() {
  loadData(true);
}

function switchType(type) {
  currentType.value = type;
  items.value = [];
  total.value = 0;
  loadData(false);
}

async function handleRepair(action) {
  if (repairing.value) return;
  repairing.value = true;
  try {
    const res = await repairHealthIssues(action);
    const thumbs = (res && res.repaired_thumbs) || 0;
    const dims = (res && res.repaired_dimensions) || 0;
    ElMessage.success(`修复完成：补齐 ${thumbs} 个缩略图，${dims} 条尺寸数据`);
    emit('repaired');
    loadData(false);
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    repairing.value = false;
  }
}

async function handleCleanMissing() {
  try {
    await ElMessageBox.confirm(
      '确定要清理这些在磁盘上已不存在的无效记录吗？删除后不可恢复。',
      '清理丢失记录',
      {
        confirmButtonText: '确定清理',
        cancelButtonText: '取消',
        type: 'warning',
      },
    );
  } catch {
    return;
  }

  cleaning.value = true;
  try {
    const res = await cleanMissingHealthFiles();
    const count = (res && res.deleted_count) || 0;
    ElMessage.success(`已清理 ${count} 条丢失媒体记录`);
    emit('repaired');
    loadData(false);
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    cleaning.value = false;
  }
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      currentType.value = props.initialType || 'all';
      items.value = [];
      total.value = 0;
      loadData(false);
    }
  },
);

watch(
  () => props.initialType,
  (val) => {
    if (props.modelValue && val) {
      currentType.value = val;
      loadData(false);
    }
  },
);
</script>

<style scoped lang="scss" src="./HealthIssuesDrawer.scss"></style>
