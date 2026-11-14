<template>
  <main class="welcome-page">
    <div class="welcome-container">
      <!-- 1. Hero 品牌与运行状态 -->
      <header class="welcome-hero">
        <div class="welcome-brand">
          <div class="welcome-logo-wrap">
            <span class="welcome-logo" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="32" height="32">
                <path
                  fill="currentColor"
                  d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.43-5.95c.74-.28 1.38.18 1.11 1.3l-2.62 12.34c-.19.9-.74 1.12-1.5.7l-4.13-3.05-1.99 1.93c-.23.23-.42.43-.83.43z"
                />
              </svg>
            </span>
          </div>
          <div class="welcome-title-group">
            <div class="welcome-title-row">
              <h1 class="welcome-title">TeleGrabber</h1>
              <span class="welcome-badge">Private Archive</span>
            </div>
            <p class="welcome-subtitle">Telegram 媒体私有化归档与资产管理工作台</p>
          </div>
        </div>

        <div class="welcome-status-pill" :title="statusTooltip">
          <span class="status-dot" :class="botRunning ? 'ok' : 'idle'" />
          <span class="status-text">{{ botRunning ? 'Bot 运行中' : (botConfigured ? 'Bot 已配置' : 'Bot 未配置') }}</span>
          <span class="status-divider">·</span>
          <span class="status-subtext">{{ userApiConnected ? 'User API 已连通' : 'User API 待机' }}</span>
        </div>
      </header>

      <!-- 2. 核心大盘概览指标 -->
      <section class="welcome-stats-grid">
        <div class="stat-card">
          <div class="stat-header">
            <span class="stat-label">归档媒体总量</span>
            <span class="stat-icon-badge">📦</span>
          </div>
          <div class="stat-value">
            {{ totalMediaCount }}
            <span v-if="totalMediaCount !== '-'" class="stat-unit">项</span>
          </div>
          <div class="stat-sub">
            <template v-if="photoCount || videoCount">
              <span>📷 {{ photoCount }} 照片</span>
              <span class="stat-dot-sep">·</span>
              <span>🎬 {{ videoCount }} 视频</span>
            </template>
            <template v-else>
              已归档媒体文件总计
            </template>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-header">
            <span class="stat-label">归档存储占用</span>
            <span class="stat-icon-badge">💾</span>
          </div>
          <div class="stat-value">
            {{ formatBytes(totalMediaBytes) }}
          </div>
          <div class="stat-sub">
            <span>磁盘剩余可用 {{ formatBytes(diskFree) }}</span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-header">
            <span class="stat-label">归档来源会话</span>
            <span class="stat-icon-badge">💬</span>
          </div>
          <div class="stat-value">
            {{ sourcesCount }}
            <span v-if="sourcesCount !== '-'" class="stat-unit">个来源</span>
          </div>
          <div class="stat-sub">
            <span>涵盖频道、群组与个人私聊</span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-header">
            <span class="stat-label">系统运行健康</span>
            <span class="stat-icon-badge">⚡</span>
          </div>
          <div class="stat-value" :class="healthStatusClass">
            {{ healthStatusText }}
          </div>
          <div class="stat-sub">
            <span>{{ healthSubText }}</span>
          </div>
        </div>
      </section>

      <!-- 3. 核心功能入口卡片 -->
      <section class="welcome-hub-grid">
        <router-link to="/feed" class="hub-card hub-card--primary">
          <div class="hub-card-top">
            <div class="hub-icon-wrap primary">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9.5 9.5 0 0 1-3.5-.7L3 21l1.8-4.5A8.4 8.4 0 1 1 21 11.5z" />
              </svg>
            </div>
            <span class="hub-badge primary">核心入口</span>
          </div>
          <div class="hub-card-body">
            <h2 class="hub-title">消息流浏览</h2>
            <p class="hub-desc">
              以 Telegram 原生会话瀑布流展现归档媒体，支持按来源多维筛选、原画灯箱全屏播放、抽帧封面与秒级全文检索。
            </p>
          </div>
          <div class="hub-card-footer">
            <span class="hub-btn primary">
              进入消息流
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </span>
          </div>
        </router-link>

        <router-link to="/storage" class="hub-card">
          <div class="hub-card-top">
            <div class="hub-icon-wrap storage">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <ellipse cx="12" cy="5" rx="8" ry="3" />
                <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
                <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
              </svg>
            </div>
            <span class="hub-badge">资产分析</span>
          </div>
          <div class="hub-card-body">
            <h2 class="hub-title">存储与去重</h2>
            <p class="hub-desc">
              可视化查看各来源与媒体类型的空间占用分布，自动捕获拦截重复转存与孤立媒体，精细管控磁盘空间健康。
            </p>
          </div>
          <div class="hub-card-footer">
            <span class="hub-btn">
              存储管理
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 18l6-6-6-6" />
              </svg>
            </span>
          </div>
        </router-link>

        <router-link to="/status" class="hub-card">
          <div class="hub-card-top">
            <div class="hub-icon-wrap status">
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 3l8 4v5c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V7l8-4z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
            </div>
            <span class="hub-badge">健康监控</span>
          </div>
          <div class="hub-card-body">
            <h2 class="hub-title">系统与网关</h2>
            <p class="hub-desc">
              监控 Telegram Bot 连通性、User API 大文件下载管道与代理隧道状态，提供全自动健康巡检诊断与故障自愈。
            </p>
          </div>
          <div class="hub-card-footer">
            <span class="hub-btn">
              系统状态
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 18l6-6-6-6" />
              </svg>
            </span>
          </div>
        </router-link>
      </section>

      <!-- 4. 活跃归档来源快捷通道 (仅在有来源数据时展示) -->
      <section v-if="topSources.length" class="welcome-sources-section">
        <div class="sources-section-head">
          <div class="sources-head-left">
            <span class="sources-title">活跃归档来源</span>
            <span class="sources-subtitle">点击直达对应会话</span>
          </div>
          <router-link to="/feed" class="sources-all-link">
            全部 {{ sourcesCount }} 个来源
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </router-link>
        </div>
        <div class="sources-chips-grid">
          <router-link
            v-for="s in topSources"
            :key="`${s.source_name}-${s.source_type}`"
            :to="`/feed?source=${encodeURIComponent(s.source_name)}`"
            class="source-chip"
          >
            <span :class="['source-badge', sourceTypeClass(s.source_type)]">
              {{ sourceTypeLabel(s.source_type) }}
            </span>
            <span class="source-chip-name" :title="s.source_name">{{ s.source_name || '未命名来源' }}</span>
            <span class="source-chip-count">{{ s.count }} 项</span>
          </router-link>
        </div>
      </section>

      <!-- 5. 底部特性指南 -->
      <footer class="welcome-guide-grid">
        <div class="guide-item">
          <span class="guide-icon-box">📥</span>
          <div class="guide-content">
            <div class="guide-title">转发即归档</div>
            <div class="guide-desc">单条媒体或多图专辑转发给机器人，后台自动多线程分片入库</div>
          </div>
        </div>
        <div class="guide-item">
          <span class="guide-icon-box">🛡️</span>
          <div class="guide-content">
            <div class="guide-title">大文件与防转发穿透</div>
            <div class="guide-desc">使用 /link 指令直连 User API，抓取超 20MB 大文件及限制转发内容</div>
          </div>
        </div>
        <div class="guide-item">
          <span class="guide-icon-box">🔍</span>
          <div class="guide-content">
            <div class="guide-title">元数据与原链溯源</div>
            <div class="guide-desc">保留消息原始时间戳、公开/数字私有直达链接及高清抽帧缩略图</div>
          </div>
        </div>
      </footer>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchStorageSummary } from '@/api/storage';
import { fetchSystemStatus } from '@/api/status';
import { formatBytes, sourceTypeLabel, sourceTypeClass } from '@/lib/media';

const summary = ref(null);
const status = ref(null);
const loading = ref(true);

const totalMediaCount = computed(() => {
  if (summary.value && summary.value.total_count !== undefined) {
    return summary.value.total_count;
  }
  if (status.value?.storage?.media_count !== undefined) {
    return status.value.storage.media_count;
  }
  return '-';
});

const totalMediaBytes = computed(() => {
  return summary.value?.total_bytes ?? status.value?.storage?.media_bytes ?? 0;
});

const diskFree = computed(() => {
  return summary.value?.disk?.free ?? status.value?.storage?.disk_free ?? 0;
});

const typeCounts = computed(() => {
  if (!summary.value?.by_type) return null;
  const photo = summary.value.by_type.find((t) => t.media_type === 'photo')?.count ?? 0;
  const video = summary.value.by_type.find((t) => t.media_type === 'video')?.count ?? 0;
  return { photo, video };
});

const photoCount = computed(() => typeCounts.value?.photo ?? 0);
const videoCount = computed(() => typeCounts.value?.video ?? 0);

const sourcesCount = computed(() => {
  if (summary.value?.by_source) return summary.value.by_source.length;
  return '-';
});

const topSources = computed(() => {
  if (!summary.value?.by_source) return [];
  return summary.value.by_source
    .filter((s) => s.source_name && s.count > 0)
    .slice(0, 8);
});

const botRunning = computed(() => Boolean(status.value?.runtime?.bot_running));
const botConfigured = computed(() => Boolean(status.value?.telegram?.bot_configured));
const userApiConnected = computed(() => Boolean(status.value?.user_api?.connected));

const healthStatusClass = computed(() => {
  const issues = status.value?.health?.missing_files ?? 0;
  if (issues > 0) return 'text-warn';
  return 'text-ok';
});

const healthStatusText = computed(() => {
  if (!status.value?.health) return '就绪';
  const missing = status.value.health.missing_files || 0;
  return missing > 0 ? `${missing} 处异常` : '健康';
});

const healthSubText = computed(() => {
  const missing = status.value?.health?.missing_files || 0;
  if (missing > 0) return '发现缺失文件，可在系统状态中修复';
  const botUser = status.value?.telegram?.bot_username;
  return botUser ? `@${botUser} 已连接` : '本地服务运转正常';
});

const statusTooltip = computed(() => {
  const parts = [];
  parts.push(botRunning.value ? 'Telegram Bot: 运行中' : 'Telegram Bot: 未运行');
  parts.push(userApiConnected.value ? 'User API: 已连接' : 'User API: 未连接');
  return parts.join(' | ');
});

async function loadData() {
  loading.value = true;
  try {
    const [summaryRes, statusRes] = await Promise.allSettled([
      fetchStorageSummary(),
      fetchSystemStatus(),
    ]);
    if (summaryRes.status === 'fulfilled') {
      summary.value = summaryRes.value;
    }
    if (statusRes.status === 'fulfilled') {
      status.value = statusRes.value;
    }
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadData();
});
</script>

<style scoped lang="scss" src="./index.scss"></style>
