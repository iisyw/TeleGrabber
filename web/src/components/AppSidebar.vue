<template>
  <aside class="app-sidebar">
    <router-link to="/" class="app-sidebar-brand" title="TeleGrabber">
      <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
        <path
          fill="currentColor"
          d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.43-5.95c.74-.28 1.38.18 1.11 1.3l-2.62 12.34c-.19.9-.74 1.12-1.5.7l-4.13-3.05-1.99 1.93c-.23.23-.42.43-.83.43z"
        />
      </svg>
    </router-link>

    <nav class="app-sidebar-nav">
      <router-link
        to="/"
        class="app-sidebar-item"
        :class="{ active: $route.path === '/' }"
        title="消息流"
      >
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9.5 9.5 0 0 1-3.5-.7L3 21l1.8-4.5A8.4 8.4 0 1 1 21 11.5z" />
        </svg>
        <span>消息流</span>
      </router-link>

      <router-link
        to="/tasks"
        class="app-sidebar-item"
        :class="{ active: $route.path === '/tasks' }"
        title="下载任务"
      >
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 3v12" />
          <path d="m7 10 5 5 5-5" />
          <path d="M5 21h14" />
        </svg>
        <span>下载任务</span>
        <span v-if="failedCount" class="app-sidebar-badge">{{ failedCount > 99 ? '99+' : failedCount }}</span>
        <span v-else-if="downloadingCount" class="app-sidebar-dot" />
      </router-link>

      <router-link
        to="/storage"
        class="app-sidebar-item"
        :class="{ active: $route.path === '/storage' }"
        title="存储管理"
      >
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <ellipse cx="12" cy="5" rx="8" ry="3" />
          <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
          <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
        </svg>
        <span>存储管理</span>
      </router-link>

      <router-link
        to="/status"
        class="app-sidebar-item"
        :class="{ active: $route.path === '/status' }"
        title="系统状态"
      >
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 3l8 4v5c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V7l8-4z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
        <span>系统状态</span>
      </router-link>
    </nav>

    <button
      class="theme-toggle app-sidebar-theme"
      type="button"
      :title="theme === 'dark' ? '切换到白天模式' : '切换到夜间模式'"
      :aria-label="theme === 'dark' ? '切换到白天模式' : '切换到夜间模式'"
      @click="toggleTheme"
    >
      <svg
        v-if="theme === 'dark'"
        viewBox="0 0 24 24"
        width="18"
        height="18"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
      >
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
      </svg>
      <svg
        v-else
        viewBox="0 0 24 24"
        width="18"
        height="18"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
      </svg>
    </button>
  </aside>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { theme, toggleTheme } from '@/lib/theme';
import { fetchTasks } from '@/api/tasks';

const failedCount = ref(0);
const downloadingCount = ref(0);
let timer = null;

async function loadTaskCounts() {
  try {
    const data = await fetchTasks({ limit: 1 }, { silent: true });
    const counts = (data && data.counts) || {};
    failedCount.value = counts.failed || 0;
    downloadingCount.value = (counts.downloading || 0) + (counts.queued || 0);
  } catch {
    // 状态轮询失败不打扰用户
  }
}

onMounted(() => {
  loadTaskCounts();
  timer = setInterval(loadTaskCounts, 15000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<style scoped lang="scss" src="./AppSidebar.scss"></style>
