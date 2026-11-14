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

      <div v-if="displayGroups.length" ref="feedListRef" class="feed-list">
        <div
          v-for="group in displayGroups"
          :key="displayGroupKey(group)"
          :data-group-key="displayGroupKey(group)"
          class="feed-item"
        >
          <DateSeparator
            v-if="group.dateHeader"
            :date="group.dateHeader"
          />
          <MediaBubble
            :group="group"
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
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
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
const feedListRef = ref(null);

const viewerOpen = ref(false);
const viewerItems = ref([]);
const viewerIndex = ref(0);

const displayGroups = computed(() => {
  const sorted = [...store.mediaList].reverse();
  return mergeDisplayGroups(buildDisplayGroups(sorted));
});

let lastLoadAt = 0;
let isRestoringScroll = false;
let isAtBottom = true;
let resizeObserver = null;

function scrollToBottom() {
  const feed = feedRef.value;
  if (!feed) return;
  feed.scrollTop = feed.scrollHeight;
  requestAnimationFrame(() => {
    if (feed) feed.scrollTop = feed.scrollHeight;
  });
}

async function afterReset(promise) {
  isAtBottom = true;
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

/**
 * 参考 Telegram Web K (ScrollSaver.ts) 物理气泡锚点机制：
 * 寻找当前视口内第一条真实可见的气泡元素（.bubble），不受日期分割线增删干扰。
 * 在数据即将注入 DOM 的前一瞬间精准快照其相对于视口顶部的真实坐标。
 */
function findTopVisibleBubble() {
  const feed = feedRef.value;
  if (!feed) return null;
  const containerRect = feed.getBoundingClientRect();
  const bubbles = feed.querySelectorAll('.bubble');
  for (const el of bubbles) {
    const rect = el.getBoundingClientRect();
    if (rect.bottom > containerRect.top + 8) {
      const itemEl = el.closest('.feed-item');
      return {
        el,
        key: itemEl ? itemEl.dataset.groupKey : null,
        topOffset: rect.top - containerRect.top,
      };
    }
  }
  return null;
}

async function onScroll() {
  const feed = feedRef.value;
  if (!feed) return;

  // 距离底部 60px 以内标记为吸底状态，图片等资源后续加载展开时自动跟随贴底
  const distanceToBottom = feed.scrollHeight - feed.clientHeight - feed.scrollTop;
  isAtBottom = distanceToBottom <= 60;

  if (store.isLoading || store.isLastPage || isRestoringScroll) return;
  if (feed.scrollTop > 300) return;
  if (Date.now() - lastLoadAt < 600) return;

  lastLoadAt = Date.now();
  isRestoringScroll = true;

  try {
    let anchor = null;
    // 关键优化：在网络请求完毕、数据即将写入 Pinia 的前一瞬间记录物理锚点，
    // 杜绝网络等待期间因用户手滑产生的反向拉扯卡顿
    const loaded = await store.loadMore((data) => {
      if (data && data.length) {
        anchor = findTopVisibleBubble();
      }
    });

    if (!loaded || !anchor || !feedRef.value) return;

    await nextTick();

    // 重新测量该气泡元素在 DOM 插入后的新坐标
    let targetEl = anchor.el && anchor.el.isConnected ? anchor.el : null;
    if (!targetEl && anchor.key) {
      const itemEl = feedRef.value.querySelector(`[data-group-key="${CSS.escape(anchor.key)}"]`);
      if (itemEl) targetEl = itemEl.querySelector('.bubble');
    }

    if (targetEl) {
      const containerRect = feedRef.value.getBoundingClientRect();
      const currentRect = targetEl.getBoundingClientRect();
      const currentTop = currentRect.top - containerRect.top;
      const diff = currentTop - anchor.topOffset;
      // 浏览器 overflow-anchor: auto 会在 C++ 引擎层自动精准锚定；
      // 仅当浏览器未锚定（diff 明显超出正常滚动微动范围，如 >= 15px）时才由 JS 兜底对齐，
      // 绝不微调打断用户的自然滚轮惯性，彻底消除卡顿与闪烁。
      if (Math.abs(diff) >= 15) {
        feedRef.value.scrollTop += diff;
      }
    }
  } finally {
    setTimeout(() => {
      isRestoringScroll = false;
    }, 100);
  }
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

watch(feedListRef, (newListEl, oldListEl) => {
  if (resizeObserver && oldListEl) {
    resizeObserver.unobserve(oldListEl);
  }
  if (newListEl && typeof ResizeObserver !== 'undefined') {
    if (!resizeObserver) {
      resizeObserver = new ResizeObserver(() => {
        if (isAtBottom && !isRestoringScroll) {
          scrollToBottom();
        }
      });
    }
    resizeObserver.observe(newListEl);
  }
});

const route = useRoute();

onMounted(async () => {
  isAtBottom = true;
  if (route.query.source) {
    store.currentSourceName = String(route.query.source);
  }
  await store.refresh();
  await nextTick();
  scrollToBottom();
});

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
});
</script>

<style scoped lang="scss" src="./index.scss"></style>
