<template>
  <AppSidebar />
  <div class="app-body">
    <router-view />
  </div>
  <div v-if="showWelcome" class="app-welcome">
    <div>
      <div class="app-welcome-title">欢迎使用 TeleGrabber</div>
      <div class="app-welcome-sub">消息流、下载任务与存储管理都在左侧栏，打开即可使用。</div>
    </div>
    <button type="button" aria-label="关闭欢迎提示" @click="dismissWelcome">×</button>
  </div>
  <div v-if="diskWarning" class="app-alert">
    磁盘剩余 {{ formatBytes(diskFree) }}，低于配置的最小可用空间 {{ minFreeMb }} MB，请及时清理或扩容
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue';
import AppSidebar from '@/components/AppSidebar.vue';
import { fetchSystemStatus } from '@/api/status';
import { formatBytes } from '@/lib/media';

const showWelcome = ref(localStorage.getItem('telegrabber-welcome-seen') !== '1');
const diskFree = ref(0);
const minFreeMb = ref(0);
const diskWarning = ref(false);
let timer = null;

function dismissWelcome() {
  showWelcome.value = false;
  localStorage.setItem('telegrabber-welcome-seen', '1');
}

async function loadStatus() {
  try {
    const data = await fetchSystemStatus();
    const storage = (data && data.storage) || {};
    diskFree.value = storage.disk_free || 0;
    minFreeMb.value = storage.min_free_mb || 0;
    diskWarning.value = Boolean(
      minFreeMb.value && diskFree.value < minFreeMb.value * 1024 * 1024,
    );
  } catch {
    // 状态轮询失败不打扰用户
  }
}

onMounted(() => {
  loadStatus();
  timer = setInterval(loadStatus, 60000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<style lang="scss" src="./assets/scss/reset.scss"></style>
<style lang="scss" src="./assets/scss/global.scss"></style>
<style lang="scss" src="./assets/scss/media.scss"></style>
