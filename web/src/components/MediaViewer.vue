<template>
  <Teleport to="body">
    <div v-if="modelValue && current" class="modal open" @click.self="close">
      <div class="modal-body">
        <div class="modal-left">
          <button class="modal-close" @click="close">×</button>
          <button v-if="index > 0" class="modal-nav prev" @click="$emit('update:index', index - 1)">‹</button>
          <button
            v-if="index < items.length - 1"
            class="modal-nav next"
            @click="$emit('update:index', index + 1)"
          >
            ›
          </button>
          <div class="modal-counter">
            {{ items.length > 1 ? `${index + 1} / ${items.length}` : '' }}
          </div>
          <div class="modal-media">
            <template v-if="current.media_type === 'video'">
              <video
                v-if="!videoError"
                :key="`video-${current.id}`"
                ref="videoEl"
                controls
                autoplay
                preload="metadata"
                :src="mediaUrl(current)"
                @loadedmetadata="applyVideoProgress"
                @timeupdate="onTimeUpdate"
                @error="onVideoError"
              />
              <div v-if="decodeWarning" class="video-codec-tip">
                <div class="video-codec-tip-text">
                  ⚠️ 画面未能正常解码（仅音频在播放）：该视频采用 HEVC (H.265) 编码，当前浏览器内核不具备原生解码器。
                </div>
                <div class="video-codec-tip-actions">
                  <button class="btn btn-small" @click="copyFilePath">复制本地文件名</button>
                  <button class="btn btn-small" @click="copyLink">复制播放链接</button>
                </div>
              </div>
              <div v-else-if="videoError" class="video-error-overlay">
                <div class="video-error-icon">⚠️</div>
                <div class="video-error-title">该视频无法在网页中直接播放</div>
                <div class="video-error-desc">
                  该视频多为 HEVC (H.265) 编码或特殊音轨，当前浏览器内核不具备原生解码器。
                </div>
                <div class="video-error-desc">
                  媒体文件已完整归档在本地磁盘，建议使用 VLC、IINA 或 PotPlayer 打开播放：
                </div>
                <div class="video-error-path">{{ current.filename }}</div>
              </div>
            </template>
            <img v-else :key="`image-${current.id}`" :src="mediaUrl(current)" alt="" />
          </div>
        </div>

        <div class="modal-right">
          <div class="modal-caption" v-html="highlightedCaption" />
          <div class="modal-meta">
            <template v-for="(row, i) in metaRows" :key="`${row.label}-${i}`">
              <div v-if="row.divider" class="meta-divider" />
              <div v-else class="meta-item">
                <span class="meta-label">{{ row.label }}: </span>
                <a
                  v-if="row.href"
                  :href="row.href"
                  target="_blank"
                  rel="noopener"
                  style="color: var(--accent)"
                >
                  {{ row.value }}
                </a>
                <span v-else>{{ row.value }}</span>
              </div>
            </template>

            <div class="meta-toggle" @click="showExtra = !showExtra">
              其他信息 {{ showExtra ? '▾' : '▸' }}
            </div>
            <div v-show="showExtra" class="meta-hidden">
              <div v-for="row in extraRows" :key="row.label" class="meta-item">
                <span class="meta-label">{{ row.label }}: </span>
                <span>{{ row.value }}</span>
              </div>
            </div>
          </div>

          <div class="modal-actions">
            <button class="btn btn-cancel" @click="toggleFavorite">
              {{ current.favorite ? '★ 已收藏' : '☆ 收藏' }}
            </button>
            <button class="btn btn-cancel" @click="editTags">标签</button>
            <button class="btn btn-cancel" @click="editRemark">备注</button>
            <button class="btn btn-cancel" @click="copyLink">复制链接</button>
            <button class="btn btn-danger modal-delete-btn" @click="$emit('delete', current)">
              <svg
                viewBox="0 0 24 24"
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M3 6h18" />
                <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                <path d="M10 11v6" />
                <path d="M14 11v6" />
              </svg>
              删除
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useMediaStore } from '@/store/media';
import { updateMediaMeta } from '@/api/media';
import {
  buildPrivateMessageLink,
  formatTime,
  mediaUrl,
  sourceTypeLabel,
} from '@/lib/media';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  items: { type: Array, default: () => [] },
  index: { type: Number, default: 0 },
});
const emit = defineEmits(['update:modelValue', 'update:index', 'delete']);

const showExtra = ref(false);
const videoError = ref(false);
const decodeWarning = ref(false);
const videoEl = ref(null);

function onVideoError() {
  videoError.value = true;
}
const store = useMediaStore();
const current = computed(() => props.items[props.index] || null);

function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

const highlightedCaption = computed(() => {
  const caption = (current.value && current.value.caption) || '';
  const terms = (store.currentSearch || '').trim().split(/\s+/).filter(Boolean);
  const safeCaption = escapeHtml(caption);
  if (!terms.length) return safeCaption;
  const pattern = new RegExp(`(${terms.map((term) => escapeRegExp(escapeHtml(term))).join('|')})`, 'gi');
  return safeCaption.replace(pattern, '<mark>$1</mark>');
});

function tagsText(value) {
  return String(value || '').split(',').filter(Boolean).join('、');
}

async function toggleFavorite() {
  const item = current.value;
  if (!item) return;
  try {
    const res = await updateMediaMeta(item.id, { favorite: !item.favorite });
    const data = res && res.data;
    item.favorite = Boolean(data && data.favorite);
    ElMessage.success(item.favorite ? '已收藏' : '已取消收藏');
  } catch {
    // 错误由 request.js 统一提示
  }
}

async function editTags() {
  const item = current.value;
  if (!item) return;
  let value;
  try {
    const result = await ElMessageBox.prompt('多个标签用逗号分隔', '编辑标签', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: tagsText(item.tags).replace(/、/g, '，'),
    });
    value = result.value;
  } catch {
    return;
  }
  try {
    const res = await updateMediaMeta(item.id, { tags: value });
    const data = res && res.data;
    item.tags = (data && data.tags) || '';
    ElMessage.success('标签已更新');
  } catch {
    // 错误由 request.js 统一提示
  }
}

async function editRemark() {
  const item = current.value;
  if (!item) return;
  let value;
  try {
    const result = await ElMessageBox.prompt('为这条媒体添加备注（留空则清除）', '编辑备注', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: item.remark || '',
    });
    value = result.value;
  } catch {
    return;
  }
  try {
    const res = await updateMediaMeta(item.id, { remark: value });
    const data = res && res.data;
    item.remark = (data && data.remark) || '';
    ElMessage.success('备注已更新');
  } catch {
    // 错误由 request.js 统一提示
  }
}

watch(
  () => [props.modelValue, props.index],
  () => {
    showExtra.value = false;
    videoError.value = false;
    decodeWarning.value = false;
    nextTick(() => {
      if (videoEl.value) applyVideoProgress();
    });
  },
);

const metaRows = computed(() => {
  const item = current.value;
  if (!item) return [];

  const rows = [];
  rows.push({ label: '文件', value: item.filename || '' });
  rows.push({ label: '类型', value: item.media_type || '' });
  if (item.width && item.height) {
    rows.push({ label: '尺寸', value: `${item.width} × ${item.height}` });
  }
  rows.push({ divider: true });

  if (item.source_name) rows.push({ label: '来源名称', value: item.source_name });
  if (item.favorite) rows.push({ label: '收藏', value: '是' });
  if (item.tags) rows.push({ label: '标签', value: tagsText(item.tags) });
  if (item.remark) rows.push({ label: '备注', value: item.remark });
  const typeLabel = item.source_type ? sourceTypeLabel(item.source_type) : '';
  if (typeLabel) rows.push({ label: '来源类型', value: typeLabel });
  if (item.source_id) rows.push({ label: '来源 ID', value: item.source_id });
  if (item.source_username) {
    rows.push({ label: '来源用户名', value: item.source_username });
  } else if (item.source_name) {
    rows.push({ label: '来源用户名', value: '-' });
  }

  const link1 = item.source_link1 ||
    (item.source_username && item.message_id !== null && item.message_id !== undefined
      ? `https://t.me/${item.source_username}/${item.message_id}`
      : '');
  if (link1) {
    const isPrivateLink = link1.includes('t.me/c/');
    rows.push({
      label: isPrivateLink ? '数字链接（需已加入）' : '公开链接',
      value: link1,
      href: link1,
    });
    // 公开频道额外提供数字链接兜底；频道改名后用户名链接可能失效
    if (!isPrivateLink && item.source_type === 'channel' && item.source_id) {
      const msgId = item.original_message_id ?? item.message_id;
      const privateLink = msgId !== null && msgId !== undefined
        ? buildPrivateMessageLink(item.source_id, msgId)
        : '';
      if (privateLink && privateLink !== link1) {
        rows.push({
          label: '数字链接（需已加入）',
          value: privateLink,
          href: privateLink,
        });
      }
    }
  }

  rows.push({ divider: true });
  if (item.user_id !== null && item.user_id !== undefined) {
    rows.push({ label: '用户 ID', value: item.user_id });
  }
  if (item.user_name) rows.push({ label: '用户名', value: item.user_name });

  rows.push({ divider: true });
  if (item.media_group_id) rows.push({ label: '媒体组 ID', value: item.media_group_id });
  if (item.message_id !== null && item.message_id !== undefined) {
    rows.push({ label: '消息 ID', value: item.message_id });
  }
  if (item.message_time) rows.push({ label: '消息时间', value: formatTime(item.message_time) });
  if (item.datetime) rows.push({ label: '储存时间', value: formatTime(item.datetime) });
  return rows;
});

const extraRows = computed(() => {
  const item = current.value;
  if (!item) return [];
  const rows = [];
  if (item.current_message_id !== null && item.current_message_id !== undefined) {
    rows.push({ label: '当前会话消息 ID', value: item.current_message_id });
  }
  if (item.original_message_id !== null && item.original_message_id !== undefined) {
    rows.push({ label: '原始来源消息 ID', value: item.original_message_id });
  }
  if (item.file_id) rows.push({ label: 'File ID', value: item.file_id });
  rows.push({ label: 'Unique ID', value: item.file_unique_id || '' });
  return rows;
});

function close() {
  emit('update:modelValue', false);
}

function prev() {
  if (props.index > 0) emit('update:index', props.index - 1);
}

function next() {
  if (props.index < props.items.length - 1) emit('update:index', props.index + 1);
}

function videoKey(item) {
  return item ? `telegrabber-video-pos:${item.file_unique_id || item.id}` : '';
}

function applyVideoProgress() {
  const video = videoEl.value;
  const item = current.value;
  if (!video || !item || item.media_type !== 'video') return;
  const saved = Number(localStorage.getItem(videoKey(item)) || 0);
  if (saved > 0 && Number.isFinite(saved) && saved < (video.duration || Infinity)) {
    video.currentTime = saved;
  }
}

function saveVideoProgress() {
  const video = videoEl.value;
  const item = current.value;
  if (!video || !item || item.media_type !== 'video') return;
  if (!video.currentTime || video.currentTime < 3) return;
  localStorage.setItem(videoKey(item), String(video.currentTime));
}

function onTimeUpdate() {
  saveVideoProgress();
  if (!decodeWarning.value) {
    const video = videoEl.value;
    if (video && video.currentTime > 0.5 && !video.paused) {
      if (typeof video.getVideoPlaybackQuality === 'function') {
        const q = video.getVideoPlaybackQuality();
        if (q && q.totalVideoFrames === 0) {
          decodeWarning.value = true;
        }
      } else if (typeof video.webkitDecodedFrameCount === 'number') {
        if (video.webkitDecodedFrameCount === 0) {
          decodeWarning.value = true;
        }
      }
    }
  }
}

async function copyFilePath() {
  const item = current.value;
  if (!item || !item.filename) return;
  try {
    await navigator.clipboard.writeText(item.filename);
    ElMessage.success('文件名已复制');
  } catch {
    ElMessage.warning('复制失败');
  }
}

async function copyLink() {
  const item = current.value;
  if (!item) return;
  const url = new URL(mediaUrl(item), window.location.origin).href;
  try {
    await navigator.clipboard.writeText(url);
    ElMessage.success('链接已复制');
  } catch {
    ElMessage.warning('复制失败，请手动复制地址');
  }
}

function toggleVideo() {
  const video = videoEl.value;
  if (!video) return;
  if (video.paused) video.play();
  else video.pause();
}

function onKeydown(event) {
  if (!props.modelValue) return;
  const tag = event.target && event.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;
  if (event.key === 'Escape') close();
  else if (event.key === 'ArrowLeft') prev();
  else if (event.key === 'ArrowRight') next();
  else if (event.key === ' ' && current.value && current.value.media_type === 'video') {
    event.preventDefault();
    toggleVideo();
  }
}

onMounted(() => document.addEventListener('keydown', onKeydown));
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown));
</script>

<style scoped lang="scss" src="./MediaViewer.scss"></style>
