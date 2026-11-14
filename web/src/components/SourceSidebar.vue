<template>
  <aside id="sidebar">
    <div class="sidebar-header">
      <svg class="brand-icon" viewBox="0 0 24 24" width="22" height="22">
        <path
          fill="currentColor"
          d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.43-5.95c.74-.28 1.38.18 1.11 1.3l-2.62 12.34c-.19.9-.74 1.12-1.5.7l-4.13-3.05-1.99 1.93c-.23.23-.42.43-.83.43z"
        />
      </svg>
      <span>TeleGrabber</span>
    </div>

    <div id="sourceTypeTabs" class="source-type-tabs">
      <button
        v-for="tab in typeTabs"
        :key="tab.value"
        class="source-type-tab"
        :class="{ active: store.currentSourceType === tab.value }"
        @click="$emit('select-type', tab.value)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div id="sourceList" class="source-list">
      <div
        v-for="item in sourceItems"
        :key="item.value || '__all__'"
        class="source-item"
        :class="{ active: store.currentSourceName === item.value }"
        @click="$emit('select-source', item.value)"
      >
        <div class="source-info">
          <div class="source-name" :title="item.remark ? `${item.name}（${item.remark}）` : item.name">
            <span v-if="item.badge" :class="['source-badge', item.badgeClass]">{{ item.badge }}</span>
            <span v-if="item.pinned" class="source-pin" title="已置顶">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor">
                <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5v6l1 1 1-1v-6h5v-2l-2-2z" />
              </svg>
            </span>
            <span class="source-name-text">{{ item.displayName }}</span>
            <span v-if="item.protected" class="source-tag-protected" title="该会话禁止转发/内容保护，机器人无法转发，只能由 User API 尝试下载">禁转</span>
          </div>
          <div class="source-sub">
            {{ item.messages }} 个消息, {{ item.media }} 个媒体
            <span v-if="item.failedCount" class="source-failed" :title="`${item.failedCount} 个失败下载任务`">
              · 失败 {{ item.failedCount }}
            </span>
            <span v-if="item.lastSynced" :title="`最近同步 ${formatTime(item.lastSynced)}`">
              · {{ formatTime(item.lastSynced).slice(5, 10) }}
            </span>
          </div>
        </div>
        <div v-if="item.value" class="source-actions" @click.stop>
          <button
            v-if="item.failedCount"
            type="button"
            class="source-action danger"
            title="重试该来源的失败任务"
            @click="retryFailed(item)"
          >
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-1.19" />
            </svg>
          </button>
          <button
            type="button"
            class="source-action"
            :class="{ active: item.pinned }"
            :title="item.pinned ? '取消置顶' : '置顶'"
            @click="togglePin(item)"
          >
            <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
              <path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5v6l1 1 1-1v-6h5v-2l-2-2z" />
            </svg>
          </button>
          <button
            type="button"
            class="source-action"
            :class="{ active: item.hidden }"
            :title="item.hidden ? '取消隐藏' : '隐藏来源'"
            @click="toggleHide(item)"
          >
            <svg v-if="item.hidden" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24M1 1l22 22" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
          <button
            type="button"
            class="source-action"
            title="修改备注"
            @click="rename(item)"
          >
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <button
      v-if="hiddenCount"
      type="button"
      class="source-visible-toggle"
      @click="showHidden = !showHidden"
    >
      {{ showHidden ? '隐藏已隐藏来源' : `显示已隐藏来源 (${hiddenCount})` }}
    </button>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useMediaStore } from '@/store/media';
import { retryFailedTasks } from '@/api/tasks';
import { sourceTypeLabel, formatTime } from '@/lib/media';

const store = useMediaStore();
const emit = defineEmits(['select-source', 'select-type']);
const showHidden = ref(false);

const typeTabs = [
  { value: '', label: '全部' },
  { value: 'channel', label: '频道' },
  { value: 'bot', label: '机器人' },
  { value: 'group', label: '群组' },
  { value: 'private_user', label: '用户' },
];

function badgeClassFor(sourceType) {
  if (!sourceType) return '';
  if (sourceType === 'private_user' || sourceType === 'user') return 'private';
  if (['bot', 'group', 'channel', 'all'].includes(sourceType)) return sourceType;
  return '';
}

const hiddenCount = computed(
  () => (store.sources || []).filter((source) => source.hidden).length,
);

const sourceItems = computed(() => {
  const counts = store.sourceCounts || {};
  const all = counts[''] || { messages: 0, media: 0 };
  const items = [{
    value: '',
    badge: '',
    badgeClass: 'all',
    name: '全部消息',
    displayName: '全部消息',
    messages: all.messages,
    media: all.media,
  }];

  (store.sources || []).forEach((source) => {
    if (source.hidden && !showHidden.value) return;
    const count = counts[source.source_name] || { messages: 0, media: 0 };
    const displayName = source.remark || source.source_name;
    items.push({
      value: source.source_name,
      badge: sourceTypeLabel(source.source_type),
      badgeClass: badgeClassFor(source.source_type),
      name: source.source_name,
      displayName,
      pinned: Boolean(source.pinned),
      hidden: Boolean(source.hidden),
      remark: source.remark || '',
      lastSynced: source.last_synced_at || '',
      protected: Boolean(source.protected),
      failedCount: source.failed_count || 0,
      messages: count.messages,
      media: count.media,
    });
  });

  return items;
});

async function togglePin(item) {
  try {
    await store.setSourceMeta(item.value, { pinned: !item.pinned });
  } catch {
    // 错误由 request.js 统一提示
  }
}

async function toggleHide(item) {
  try {
    await store.setSourceMeta(item.value, { hidden: !item.hidden });
    if (!item.hidden && store.currentSourceName === item.value) {
      emit('select-source', '');
    }
  } catch {
    // 错误由 request.js 统一提示
  }
}

async function retryFailed(item) {
  try {
    const res = await retryFailedTasks(20, item.value);
    const started = (res && res.data && res.data.started) || [];
    ElMessage.success(`已加入 ${started.length} 个重试任务`);
    await store.loadSources();
  } catch {
    // 错误由 request.js 统一提示
  }
}

async function rename(item) {  let value;
  try {
    const result = await ElMessageBox.prompt('设置来源备注（留空则恢复原名）', item.name, {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: item.remark,
    });
    value = result.value;
  } catch {
    return;
  }
  try {
    await store.setSourceMeta(item.value, { remark: value.trim() });
    ElMessage.success('备注已更新');
  } catch {
    // 错误由 request.js 统一提示
  }
}
</script>

<style scoped lang="scss" src="./SourceSidebar.scss"></style>
