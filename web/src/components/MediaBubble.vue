<template>
  <div class="message" :data-group-id="groupId || undefined">
    <div
      v-if="publisher"
      class="msg-avatar"
      :style="avatarStyle(publisher)"
      :title="publisher"
    >
      {{ avatarInitial(publisher) }}
    </div>

    <div class="bubble" :style="bubbleStyle">
      <div
        class="msg-name-row"
        :class="{ 'msg-name-row--empty': !publisher && !sourceType }"
      >
        <div class="msg-name-main">
          <span
            v-if="sourceType"
            :class="['source-badge', sourceTypeClass(sourceType)]"
          >
            {{ sourceTypeLabel(sourceType) }}
          </span>
          <span v-if="publisher" class="msg-name">{{ publisher }}</span>
        </div>

        <button
          class="bubble-del"
          type="button"
          title="删除"
          aria-label="删除"
          @click.stop="onDelete"
        >
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
        </button>
      </div>

      <AlbumGrid
        v-if="isMulti"
        :items="items"
        @open="(index) => $emit('open', items, index)"
      />

      <template v-else>
        <div
          class="media-grid g1"
          :class="{ 'video-fallback': isVideo && (!thumb || posterFailed) }"
          :style="singleMediaStyle"
          @click="$emit('open', items, 0)"
        >
          <template v-if="isVideo">
            <img
              v-if="thumb && !posterFailed"
              class="single-media video-poster"
              :src="thumb"
              loading="lazy"
              decoding="async"
              @error="posterFailed = true"
            />
            <span v-if="isAnimation" class="gif-badge">GIF</span>
            <div v-else class="play-badge">
              <svg viewBox="0 0 24 24" width="48" height="48">
                <circle cx="12" cy="12" r="11" fill="rgba(0,0,0,0.6)" />
                <polygon points="9.5,7 9.5,17 18,12" fill="white" />
              </svg>
            </div>
          </template>
          <img
            v-else
            class="single-media"
            :src="thumb || originalUrl"
            loading="lazy"
            decoding="async"
            @error="onImageError"
          />
        </div>

        <div v-if="caption" class="caption">{{ caption }}</div>
      </template>

      <div v-if="isMulti && caption" class="caption">{{ caption }}</div>

      <div class="bubble-footer">
        <div class="timestamp">
          <template v-if="refItem.message_time && refItem.datetime">
            <div v-if="refItem.message_time">消息时间: {{ formatTime(refItem.message_time) }}</div>
            <div v-if="refItem.datetime">储存时间: {{ formatTime(refItem.datetime) }}</div>
          </template>
          <template v-else>
            <div>时间: {{ formatTime(refItem.message_time) || formatTime(refItem.datetime) || '-' }}</div>
          </template>
          <div v-if="extra" class="timestamp-count">{{ extra }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';
import AlbumGrid from './AlbumGrid.vue';
import {
  avatarInitial,
  avatarStyle,
  formatTime,
  isAnimation as checkIsAnimation,
  isVideo as checkIsVideo,
  mediaUrl,
  sourceTypeClass,
  sourceTypeLabel,
  thumbUrl,
} from '@/lib/media';

const props = defineProps({
  group: { type: Object, required: true },
});
const emit = defineEmits(['open', 'delete']);

const items = computed(() => props.group.items || []);
const isGroup = computed(() => props.group.type === 'media-group');
const groupId = computed(() => (isGroup.value ? props.group.groupId : null));
const isMulti = computed(() => isGroup.value && items.value.length > 1);
const refItem = computed(() => items.value[0] || {});
const publisher = computed(() => refItem.value.source_name || refItem.value.user_name || '');
const sourceType = computed(() => refItem.value.source_type || '');
const isVideo = computed(() => checkIsVideo(refItem.value));
const isAnimation = computed(() => checkIsAnimation(refItem.value));
const thumb = computed(() => thumbUrl(refItem.value));
const originalUrl = computed(() => mediaUrl(refItem.value));
const posterFailed = ref(false);

const mediaDimensions = computed(() => {
  const w = Number(refItem.value.width);
  const h = Number(refItem.value.height);
  if (w > 0 && h > 0) {
    // 对齐 Telegram 消息流布局：钳位纵横比在舒适范围内，设置最小宽度保护，防止极细长竖屏视频塌陷为过窄立柱
    const maxW = 400;
    const maxH = 400;
    const minW = 280;
    const minRatio = 0.7;
    const maxRatio = 1.85;

    const rawRatio = w / h;
    const clampedRatio = Math.max(minRatio, Math.min(maxRatio, rawRatio));

    let boxW;
    let boxH;
    if (clampedRatio <= 1) {
      boxH = Math.min(Math.max(h, 240), maxH);
      boxW = Math.round(boxH * clampedRatio);
      if (boxW < minW) {
        boxW = minW;
        boxH = Math.min(maxH, Math.round(boxW / clampedRatio));
      }
    } else {
      boxW = Math.min(Math.max(w, minW), maxW);
      boxH = Math.round(boxW / clampedRatio);
      if (boxH > maxH) {
        boxH = maxH;
        boxW = Math.min(maxW, Math.round(boxH * clampedRatio));
      }
    }

    return { boxW, boxH };
  }
  return { boxW: 320, boxH: 240 };
});

const bubbleStyle = computed(() => {
  if (isMulti.value) return {};
  const { boxW } = mediaDimensions.value;
  return {
    width: `${boxW}px`,
  };
});

const singleMediaStyle = computed(() => {
  const { boxW, boxH } = mediaDimensions.value;
  return {
    width: '100%',
    height: `${boxH}px`,
    aspectRatio: `${boxW} / ${boxH}`,
  };
});

const caption = computed(() => {
  if (isMulti.value) {
    const withCaption = items.value.find((item) => item.caption);
    return withCaption ? withCaption.caption : '';
  }
  return refItem.value.caption || '';
});

const extra = computed(() => {
  let text = '';
  const msgId = refItem.value.original_message_id ?? refItem.value.current_message_id;
  if (msgId !== null && msgId !== undefined) {
    text += `#${msgId}`;
  }
  if (isGroup.value && items.value.length > 4) text += ` · ${items.value.length} 项`;
  return text.trim();
});

function onImageError(event) {
  const img = event.target;
  img.onerror = null;
  img.src = originalUrl.value;
}

function onDelete() {
  if (isGroup.value && groupId.value) {
    emit('delete', { group: true, groupId: groupId.value });
  } else {
    emit('delete', { group: false, id: refItem.value.id });
  }
}
</script>

<style scoped lang="scss" src="./MediaBubble.scss"></style>
