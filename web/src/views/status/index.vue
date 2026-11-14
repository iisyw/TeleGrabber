<template>
  <div class="manage-page">
    <div class="manage-header">
      <div>
        <div class="manage-title">系统状态</div>
        <div class="manage-subtitle">Bot、User API、存储与任务运行情况</div>
      </div>
      <div class="manage-actions">
        <button
          class="btn btn-cancel status-auto-toggle"
          :class="{ active: autoRefresh }"
          @click="toggleAutoRefresh"
        >
          自动刷新 {{ autoRefresh ? '开' : '关' }}
        </button>
        <button class="btn" @click="load">刷新</button>
      </div>
    </div>

    <div class="status-meta-row">
      <span v-if="lastChecked" class="status-checked">
        最后检查 {{ formatTime(lastChecked) }}
      </span>
      <span v-if="error" class="status-stale">{{ error }}</span>
    </div>

    <div v-if="status" class="status-grid">
      <div class="status-card">
        <div class="status-card-head">
          <span>Telegram Bot</span>
          <span :class="['status-dot', status.runtime.bot_running ? 'ok' : 'bad']" />
        </div>
        <div class="status-card-value">{{ status.runtime.bot_running ? '运行中' : '未运行' }}</div>
        <div class="status-card-sub">
          {{ status.telegram.bot_configured ? 'Token 已配置' : 'Token 未配置' }}
        </div>
        <div v-if="status.telegram.bot_username" class="status-card-sub">
          机器人账号：@{{ status.telegram.bot_username }}
        </div>
        <div v-else-if="status.telegram.bot_id" class="status-card-sub">
          机器人 ID：{{ status.telegram.bot_id }}
        </div>
        <div v-else-if="status.telegram.bot_configured" class="status-card-sub">
          等待 Bot 连接后显示机器人账号
        </div>
        <div v-if="status.runtime.started_at" class="status-card-sub">
          启动于 {{ formatTime(status.runtime.started_at) }}
        </div>
      </div>

      <div class="status-card">
        <div class="status-card-head">
          <span>User API 账号</span>
          <span :class="['status-dot', status.user_api.connected ? 'ok' : (status.user_api.enabled ? 'warn' : 'bad')]" />
        </div>
        <div class="status-card-value">
          {{ status.user_api.connected ? '已连接' : (status.user_api.enabled ? '未连接' : '未配置') }}
        </div>
        <div class="status-card-sub">
          {{ status.user_api.username ? `登录用户：@${status.user_api.username}` : `登录用户 ID：${status.user_api.user_id || '-'}` }}
        </div>
        <div
          class="status-card-sub"
          title="这些会话开启了内容保护或禁止转发，机器人无法把其中的消息转发到下载会话，只能尝试由 User API 直接下载"
        >
          禁止转发会话：{{ status.user_api.protected_chat_count }}
        </div>
      </div>

      <div class="status-card">
        <div class="status-card-head">
          <span>磁盘空间（全盘）</span>
          <span :class="['status-dot', freePercent > 15 ? 'ok' : 'warn']" />
        </div>
        <div class="status-card-value">{{ formatBytes(status.storage.disk_free) }} 可用</div>
        <div class="status-card-sub">
          全盘已用 {{ formatBytes(status.storage.disk_used) }} / {{ formatBytes(status.storage.disk_total) }}
        </div>
        <div class="status-card-sub">数据库 {{ formatBytes(status.storage.db_size) }}</div>
      </div>
    </div>

    <div v-if="status" class="storage-section">
      <div class="storage-section-title">检查清单</div>
      <div class="check-list">
        <div v-for="item in checklist" :key="item.label" class="check-item">
          <span :class="['status-dot', item.ok ? 'ok' : 'warn']" />
          <span class="check-label">{{ item.label }}</span>
          <span class="check-hint">{{ item.hint }}</span>
        </div>
      </div>
    </div>

    <div v-if="status" class="storage-section">
      <div class="storage-section-title">存储构成</div>
      <div class="status-metrics">
        <div class="status-metric">
          <span>原始媒体数量</span>
          <strong>{{ status.storage.media_count }}</strong>
        </div>
        <div class="status-metric">
          <span>原始媒体占用</span>
          <strong>{{ formatBytes(status.storage.media_bytes) }}</strong>
        </div>
        <div class="status-metric" title="由原始媒体生成，删除后访问时会重新生成；执行健康检查后更新">
          <span>缩略图占用</span>
          <strong>{{ formatBytes(status.storage.thumb_bytes) }}</strong>
        </div>
        <div class="status-metric" title="原文件 + 缩略图；执行健康检查后更新">
          <span>媒体总占用</span>
          <strong>{{ formatBytes(status.storage.media_total_bytes) }}</strong>
        </div>
        <div class="status-metric">
          <span>数据库</span>
          <strong>{{ formatBytes(status.storage.db_size) }}</strong>
        </div>
        <div class="status-metric">
          <span>重复文件组</span>
          <strong>{{ status.storage.duplicate_groups }}</strong>
        </div>
        <div class="status-metric">
          <span>重复浪费</span>
          <strong>{{ formatBytes(status.storage.duplicate_wasted_bytes) }}</strong>
        </div>
      </div>
    </div>

    <div v-if="status" class="storage-section">
      <div class="storage-section-title storage-section-title--actions">
        <span>
          数据健康
          <span v-if="status.health" class="health-checked">检查于 {{ formatTime(status.health.checked_at) }}</span>
        </span>
        <div class="health-actions-group">
          <button
            v-if="status.health && (status.health.missing_thumbs || status.health.missing_dimensions)"
            class="btn btn-small"
            :disabled="quickRepairing"
            @click="handleQuickRepair"
          >
            {{ quickRepairing ? '修复中...' : '一键全部修复' }}
          </button>
          <button
            class="btn btn-small btn-cancel"
            :disabled="healthLoading"
            @click="runHealth"
          >
            {{ healthLoading ? '检查中...' : (status.health ? '重新检查' : '执行健康检查') }}
          </button>
        </div>
      </div>
      <div v-if="!status.health" class="health-empty">
        {{ healthLoading ? '正在执行首次健康检查，请稍候...' : '尚未执行健康检查。检查会扫描数据库记录、磁盘文件和缩略图目录，媒体较多时可能需要一点时间。' }}
      </div>
      <template v-else>
        <div class="status-metrics">
          <div
            :class="['status-metric', status.health.missing_files ? 'bad status-metric--clickable' : '']"
            @click="status.health.missing_files ? openIssuesDrawer('missing_files') : null"
            :title="status.health.missing_files ? '点击查看原文件丢失的媒体列表' : ''"
          >
            <span>缺失文件</span>
            <strong>{{ status.health.missing_files }}</strong>
            <span v-if="status.health.missing_files" class="metric-link-hint">查看列表 &rsaquo;</span>
          </div>
          <div
            :class="['status-metric', status.health.missing_thumbs ? 'warn status-metric--clickable' : '']"
            @click="status.health.missing_thumbs ? openIssuesDrawer('missing_thumbs') : null"
            :title="status.health.missing_thumbs ? '点击查看缺失缩略图的媒体列表并修复' : ''"
          >
            <span>缺失缩略图</span>
            <strong>{{ status.health.missing_thumbs }}</strong>
            <span v-if="status.health.missing_thumbs" class="metric-link-hint">查看 & 修复 &rsaquo;</span>
          </div>
          <div
            :class="['status-metric', status.health.missing_dimensions ? 'warn status-metric--clickable' : '']"
            @click="status.health.missing_dimensions ? openIssuesDrawer('missing_dimensions') : null"
            :title="status.health.missing_dimensions ? '点击查看缺少尺寸大小的媒体列表并修复' : ''"
          >
            <span>缺少尺寸/大小</span>
            <strong>{{ status.health.missing_dimensions }}</strong>
            <span v-if="status.health.missing_dimensions" class="metric-link-hint">查看 & 修复 &rsaquo;</span>
          </div>
          <div class="status-metric">
            <span>记录总数</span>
            <strong>{{ status.health.total }}</strong>
          </div>
        </div>
        <div class="health-hint">
          点击异常指标可查看问题媒体清单，缺失缩略图与尺寸大小支持一键自动修复补全。
        </div>
      </template>
    </div>

    <div v-if="status" class="storage-section">
      <div class="storage-section-title">最近错误</div>
      <div v-if="status.runtime.last_error" class="error-block">
        <div class="error-meta">
          {{ status.runtime.last_error_source || 'runtime' }} ·
          {{ formatTime(status.runtime.last_error_at) || '-' }}
        </div>
        <pre>{{ status.runtime.last_error }}</pre>
      </div>
      <div v-else class="manage-empty">暂无运行错误</div>
    </div>

    <div v-if="status" class="storage-section">
      <div class="storage-section-title">运行配置</div>
      <div class="status-kv">
        <span>Web 监听</span><span>{{ status.config.web_host }}:{{ status.config.web_port }}</span>
        <span>代理</span><span>{{ status.telegram.proxy || '未配置' }}</span>
        <span>下载目录</span><span>{{ status.storage.save_dir }}</span>
        <span>数据目录</span><span>{{ status.storage.data_dir }}</span>
        <span>下载超时</span><span>{{ status.config.download_timeout }} 秒</span>
        <span>卡死判定</span><span>{{ status.config.download_stall_timeout }} 秒</span>
        <span>下载重试</span><span>{{ status.config.download_retries }} 次</span>
        <span>允许用户</span><span>{{ status.config.allowed_users ? `${status.config.allowed_users} 人` : '不限制' }}</span>
        <span>最小剩余空间</span><span>{{ status.storage.min_free_mb }} MB</span>
      </div>
    </div>

    <div v-if="!status && error" class="manage-empty">{{ error }}</div>

    <HealthIssuesDrawer
      v-model="drawerOpen"
      :initial-type="drawerType"
      @repaired="onRepaired"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { fetchSystemStatus, runHealthCheck, repairHealthIssues } from '@/api/status';
import { formatBytes, formatTime } from '@/lib/media';
import HealthIssuesDrawer from './components/HealthIssuesDrawer.vue';

const status = ref(null);
const error = ref('');
const autoRefresh = ref(false);
const healthLoading = ref(false);
const quickRepairing = ref(false);
const lastChecked = ref('');
const drawerOpen = ref(false);
const drawerType = ref('all');
let timer = null;

const freePercent = computed(() => {
  const storage = status.value && status.value.storage;
  if (!storage || !storage.disk_total) return 100;
  return (storage.disk_free / storage.disk_total) * 100;
});

const checklist = computed(() => {
  if (!status.value) return [];
  const data = status.value;
  return [
    {
      label: 'Bot Token',
      ok: data.telegram.bot_configured,
      hint: data.telegram.bot_configured ? '已配置' : '请在 conf/config.toml 填写 bot_token',
    },
    {
      label: 'User API',
      ok: data.user_api.connected,
      hint: data.user_api.connected ? '已连接，可下载大文件' : '未连接，>20MB 文件不可下载',
    },
    {
      label: '磁盘余量',
      ok: freePercent.value > 15,
      hint: `剩余 ${formatBytes(data.storage.disk_free)}`,
    },
  ];
});

function localIsoString(date) {
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

async function load() {
  try {
    status.value = await fetchSystemStatus();
    error.value = '';
    if (status.value && !status.value.health && !healthLoading.value) {
      runHealth();
    }
  } catch {
    error.value = '刷新失败，当前显示的是上一次成功获取的数据';
  } finally {
    lastChecked.value = localIsoString(new Date());
  }
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value;
}

async function runHealth() {
  if (healthLoading.value) return;
  healthLoading.value = true;
  try {
    await runHealthCheck();
    await load();
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    healthLoading.value = false;
  }
}

function openIssuesDrawer(type = 'all') {
  drawerType.value = type;
  drawerOpen.value = true;
}

async function handleQuickRepair() {
  if (quickRepairing.value) return;
  quickRepairing.value = true;
  try {
    const res = await repairHealthIssues('all');
    const thumbs = (res && res.repaired_thumbs) || 0;
    const dims = (res && res.repaired_dimensions) || 0;
    ElMessage.success(`修复完成：补齐 ${thumbs} 个缩略图，${dims} 条尺寸数据`);
    await load();
  } catch {
    // 错误由 request.js 统一提示
  } finally {
    quickRepairing.value = false;
  }
}

function onRepaired() {
  load();
}

onMounted(() => {
  load();
  timer = setInterval(() => {
    if (autoRefresh.value) load();
  }, 30000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<style scoped lang="scss" src="./index.scss"></style>
