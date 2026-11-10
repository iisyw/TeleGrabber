<template>
  <SourceSidebar
    @select-source="onSelectSource"
    @select-type="onSelectType"
  />

  <main id="mainArea">
    <ChatHeader @search="onSearch" @sort="onSort" @filter="onFilter" />

    <div id="chatFeed" ref="feedRef" class="chat-feed" @scroll="onScroll">
      <div
        v-if="store.isLoading && store.mediaList.length"
        id="feedLoader"
        class="feed-loader feed-loader-top"
      >
        <div class="mini-loader" />
        <span>加载更早的消息...</span>
      </div>

      <div
        v-if="displayGroups.length"
        class="feed-virtual"
        :style="{ height: `${totalSize}px` }"
      >
        <div
          v-for="virtualRow in virtualRows"
          :key="virtualRow.key"
          :ref="measureElement"
          :data-index="virtualRow.index"
          class="feed-virtual-item"
          :style="{ transform: `translateY(${virtualRow.start}px)` }"
        >
          <DateSeparator
            v-if="virtualRow.group.type === 'date'"
            :date="virtualRow.group.date"
          />
          <MediaBubble
            v-else
            :group="virtualRow.group"
            @open="openViewer"
            @delete="onDelete"
          />
        </div>
      </div>

      <div
        v-if="store.isLoading && !store.mediaList.length"
        class="loader-container"
      >
        <div class="loader" />
      </div>
      <div
        v-else-if="!store.mediaList.length"
        class="empty-state"
      >
        <div class="empty-icon">📭</div>
        <div>{{ store.error || '暂无媒体' }}</div>
      </div>
    </div>
  </main>

  <MediaViewer
    v-model="viewerOpen"
    v-model:index="viewerIndex"
    :items="viewerItems"
    @delete="onViewerDelete"
  />
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue';
import { useVirtualizer } from '@tanstack/vue-virtual';
import { ElMessage, ElMessageBox } from 'element-plus';
import SourceSidebar from '@/components/SourceSidebar.vue';
import ChatHeader from '@/components/ChatHeader.vue';
import DateSeparator from '@/components/DateSeparator.vue';
import MediaBubble from '@/components/MediaBubble.vue';
import MediaViewer from '@/components/MediaViewer.vue';
import { useMediaStore } from '@/store/media';
import {
  buildDisplayGroups,
  displayGroupKey,
  mergeDisplayGroups,
} from '@/lib/media';

const store = useMediaStore();
const feedRef = ref(null);

const viewerOpen = ref(false);
const viewerItems = ref([]);
const viewerIndex = ref(0);

const displayGroups = computed(() => {
  const sorted = [...store.mediaList].reverse();
  return mergeDisplayGroups(buildDisplayGroups(sorted));
});

const virtualizer = useVirtualizer(computed(() => ({
  count: displayGroups.value.length,
  getScrollElement: () => feedRef.value,
  estimateSize: () => 360,
  overscan: 6,
  getItemKey: (index) => {
    const group = displayGroups.value[index];
    return group ? displayGroupKey(group) : index;
  },
})));

const virtualItems = computed(() => virtualizer.value.getVirtualItems());
const totalSize = computed(() => virtualizer.value.getTotalSize());
const virtualRows = computed(() => virtualItems.value
  .map((row) => ({ ...row, group: displayGroups.value[row.index] }))
  .filter((row) => row.group));

let lastLoadAt = 0;

function measureElement(el) {
  if (el) virtualizer.value.measureElement(el);
}

function scrollToBottom() {
  const count = displayGroups.value.length;
  if (!count) return;
  virtualizer.value.scrollToIndex(count - 1, { align: 'end' });
  setTimeout(() => {
    if (displayGroups.value.length) {
      virtualizer.value.scrollToIndex(displayGroups.value.length - 1, { align: 'end' });
    }
  }, 60);
}

async function afterReset(promise) {
  await promise;
  await nextTick();
  scrollToBottom();
}

function onSelectSource(sourceName) {
  afterReset(store.selectSource(sourceName));
}

function onSelectType(type) {
  afterReset(store.selectSourceType(type));
}

function onSearch(value) {
  afterReset(store.setSearch(value));
}

function onSort(sort) {
  afterReset(store.setSort(sort));
}

function onFilter(filters) {
  afterReset(store.setFilters(filters));
}

async function onScroll() {
  const feed = feedRef.value;
  if (!feed || store.isLoading || store.isLastPage) return;
  if (feed.scrollTop > 300) return;
  if (Date.now() - lastLoadAt < 600) return;

  lastLoadAt = Date.now();
  const oldHeight = feed.scrollHeight;
  const loaded = await store.loadMore();
  if (!loaded) return;

  await nextTick();
  // 保持底部视口位置：把新插入到顶部的旧消息高度补回滚动偏移
  requestAnimationFrame(() => {
    if (!feedRef.value) return;
    const delta = feedRef.value.scrollHeight - oldHeight;
    if (delta > 0) feedRef.value.scrollTop += delta;
  });
}

function openViewer(items, index) {
  viewerItems.value = items;
  viewerIndex.value = index;
  viewerOpen.value = true;
}

function closeViewer() {
  viewerOpen.value = false;
}

async function onDelete(target) {
  const isGroup = target.group;
  const message = isGroup
    ? '确定要删除整个媒体组吗？\n此操作将删除该组下所有文件，不可恢复。'
    : '确定要删除这个媒体吗？\n此操作不可恢复。';
  const title = isGroup ? '删除媒体组' : '删除媒体';

  try {
    await ElMessageBox.confirm(message, title, {
      confirmButtonText: isGroup ? '删除整组' : '彻底删除',
      cancelButtonText: '取消',
      type: 'warning',
    });
  } catch {
    return;
  }

  try {
    if (isGroup) {
      await store.deleteGroup(target.groupId);
      ElMessage.success('媒体组已删除');
    } else {
      await store.deleteItem(target.id);
      ElMessage.success('已删除');
    }
    if (viewerOpen.value) closeViewer();
  } catch {
    // 错误提示由 request.js 拦截器统一负责，这里只做流程控制
  }
}

function onViewerDelete(item) {
  onDelete({ group: false, id: item.id });
}

onMounted(async () => {
  await store.refresh();
  await nextTick();
  scrollToBottom();
});
</script>

<style scoped lang="scss" src="./index.scss"></style>
