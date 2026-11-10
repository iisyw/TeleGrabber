<template>
  <div class="top-bar">
    <div class="chat-info">
      <div id="chatAvatar" :class="['chat-avatar', 'badge', avatarClass]">
        {{ avatarLabel }}
      </div>
      <div>
        <div id="chatName" class="chat-name">{{ title }}</div>
        <div id="chatCount" class="chat-count">{{ countText }}</div>
      </div>
    </div>

    <div class="top-bar-actions">
      <div class="sort-group">
        <span class="sort-label">排序</span>
        <div class="sort-buttons">
          <button
            class="sort-btn"
            :class="{ active: store.sortBy === 'message_time' }"
            @click="$emit('sort', 'message_time')"
          >
            消息时间
          </button>
          <button
            class="sort-btn"
            :class="{ active: store.sortBy === 'datetime' }"
            @click="$emit('sort', 'datetime')"
          >
            下载时间
          </button>
        </div>
      </div>

      <div id="searchBox" class="search-box">
        <svg class="search-icon" viewBox="0 0 24 24" width="18" height="18">
          <path
            fill="currentColor"
            d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"
          />
        </svg>
        <input
          v-model="searchInput"
          type="text"
          placeholder="搜索媒体..."
          @input="onInput"
          @focus="historyOpen = true"
          @blur="onSearchBlur"
          @keydown.enter="applyNow"
        />
        <button
          v-if="searchInput"
          class="search-clear"
          aria-label="清除搜索"
          @click="clearSearch"
        >
          ×
        </button>
      </div>

      <button
        class="theme-toggle filter-toggle"
        :class="{ active: filterActive }"
        type="button"
        title="筛选"
        aria-label="筛选"
        @click="showFilters = !showFilters"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M4 6h16M7 12h10M10 18h4" />
        </svg>
      </button>

    </div>

    <div v-if="historyOpen && searchHistory.length" class="search-history">
      <span class="search-history-label">最近搜索</span>
      <button
        v-for="item in searchHistory"
        :key="item"
        class="search-history-item"
        @mousedown.prevent
        @click="applyHistory(item)"
      >
        {{ item }}
      </button>
    </div>

    <div v-if="activeChips.length" class="active-filters">
      <span v-for="chip in activeChips" :key="chip.key" class="filter-chip">
        {{ chip.label }}
        <button type="button" aria-label="移除筛选" @click="removeChip(chip)">×</button>
      </span>
      <button type="button" class="filter-chip-clear" @click="clearFilters">清除全部</button>
    </div>

    <div v-if="showFilters" class="filter-panel">
      <label>
        类型
        <select v-model="filterType">
          <option value="">全部</option>
          <option value="photo">图片</option>
          <option value="video">视频</option>
          <option value="document">文档</option>
          <option value="animation">动画</option>
          <option value="audio">音频</option>
        </select>
      </label>
      <label>
        从
        <input v-model="filterFrom" type="date" />
      </label>
      <label>
        到
        <input v-model="filterTo" type="date" />
      </label>
      <label>
        标签
        <input v-model="filterTag" type="text" placeholder="标签" />
      </label>
      <label class="filter-check">
        <input v-model="filterFavorite" type="checkbox" />
        仅看收藏
      </label>
      <div class="filter-actions">
        <button class="btn" @click="applyFilters">应用</button>
        <button class="btn btn-cancel" @click="clearFilters">清除</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useMediaStore } from '@/store/media';
import { sourceTypeLabel, sourceTypeClass } from '@/lib/media';

const emit = defineEmits(['search', 'sort', 'filter']);
const store = useMediaStore();
const searchInput = ref(store.currentSearch || '');
const showFilters = ref(false);
const filterType = ref(store.mediaType || '');
const filterFrom = ref(store.dateFrom || '');
const filterTo = ref(store.dateTo || '');
const filterFavorite = ref(Boolean(store.favorite));
const filterTag = ref(store.tag || '');
const historyOpen = ref(false);
const searchHistory = ref(loadSearchHistory());
let debounceTimer = null;

const MEDIA_TYPE_LABELS = {
  photo: '图片',
  video: '视频',
  document: '文档',
  animation: '动画',
  audio: '音频',
};

function loadSearchHistory() {
  try {
    const raw = localStorage.getItem('telegrabber-search-history');
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((item) => typeof item === 'string').slice(0, 8) : [];
  } catch {
    return [];
  }
}

function pushSearchHistory(value) {
  const text = (value || '').trim();
  if (!text) return;
  const next = [text, ...searchHistory.value.filter((item) => item !== text)].slice(0, 8);
  searchHistory.value = next;
  localStorage.setItem('telegrabber-search-history', JSON.stringify(next));
}

function applyHistory(value) {
  searchInput.value = value;
  historyOpen.value = false;
  pushSearchHistory(value);
  emit('search', value);
}

function onSearchBlur() {
  setTimeout(() => { historyOpen.value = false; }, 150);
}

const activeChips = computed(() => {
  const chips = [];
  if (store.mediaType) {
    chips.push({ key: 'type', label: `类型：${MEDIA_TYPE_LABELS[store.mediaType] || store.mediaType}` });
  }
  if (store.favorite) chips.push({ key: 'favorite', label: '仅看收藏' });
  if (store.tag) chips.push({ key: 'tag', label: `标签：${store.tag}` });
  if (store.dateFrom) chips.push({ key: 'from', label: `从 ${store.dateFrom}` });
  if (store.dateTo) chips.push({ key: 'to', label: `到 ${store.dateTo}` });
  return chips;
});

function removeChip(chip) {
  const next = {
    media_type: store.mediaType,
    date_from: store.dateFrom,
    date_to: store.dateTo,
    favorite: store.favorite,
    tag: store.tag,
  };
  if (chip.key === 'type') next.media_type = '';
  if (chip.key === 'favorite') next.favorite = false;
  if (chip.key === 'tag') next.tag = '';
  if (chip.key === 'from') next.date_from = '';
  if (chip.key === 'to') next.date_to = '';
  emit('filter', next);
}

const filterActive = computed(() => Boolean(
  store.mediaType || store.dateFrom || store.dateTo || store.favorite || store.tag,
));

watch(
  () => [store.mediaType, store.dateFrom, store.dateTo, store.favorite, store.tag],
  ([type, from, to, favorite, tag]) => {
    filterType.value = type || '';
    filterFrom.value = from || '';
    filterTo.value = to || '';
    filterFavorite.value = Boolean(favorite);
    filterTag.value = tag || '';
  },
);

function applyFilters() {
  emit('filter', {
    media_type: filterType.value,
    date_from: filterFrom.value,
    date_to: filterTo.value,
    favorite: filterFavorite.value,
    tag: filterTag.value,
  });
  showFilters.value = false;
}

function clearFilters() {
  filterType.value = '';
  filterFrom.value = '';
  filterTo.value = '';
  filterFavorite.value = false;
  filterTag.value = '';
  applyFilters();
}

watch(
  () => store.currentSearch,
  (value) => { searchInput.value = value || ''; },
);

const title = computed(() => store.currentSourceName || '全部消息');

const countText = computed(() => {
  const stats = store.stats;
  if (!stats) return '-';
  return `${stats.message_count ?? 0} 个消息, ${stats.total_count ?? 0} 个媒体`;
});

const avatarLabel = computed(() => {
  if (store.currentSourceName) {
    const source = store.sources.find((s) => s.source_name === store.currentSourceName);
    return sourceTypeLabel(source ? source.source_type : '');
  }
  if (!store.currentSourceType) return '全部';
  return sourceTypeLabel(store.currentSourceType);
});

const avatarClass = computed(() => {
  if (store.currentSourceName) {
    const source = store.sources.find((s) => s.source_name === store.currentSourceName);
    return sourceTypeClass(source ? source.source_type : '');
  }
  return store.currentSourceType ? sourceTypeClass(store.currentSourceType) : 'all';
});

function onInput() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    emit('search', searchInput.value);
  }, 300);
}

function applyNow() {
  if (debounceTimer) clearTimeout(debounceTimer);
  pushSearchHistory(searchInput.value);
  historyOpen.value = false;
  emit('search', searchInput.value);
}

function clearSearch() {
  searchInput.value = '';
  if (debounceTimer) clearTimeout(debounceTimer);
  emit('search', '');
}

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
});
</script>

<style scoped lang="scss" src="./ChatHeader.scss"></style>
