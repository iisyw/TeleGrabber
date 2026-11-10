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

    <div class="bubble">
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
          @click="$emit('open', items, 0)"
        >
          <template v-if="isVideo">
            <img
              v-if="thumb && !posterFailed"
              class="single-media video-poster"
              :src="thumb"
              :width="refItem.width || undefined"
              :height="refItem.height || undefined"
              loading="lazy"
              decoding="async"
              @error="posterFailed = true"
            />
            <div class="play-badge">
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
            :width="refItem.width || undefined"
            :height="refItem.height || undefined"
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
const isVideo = computed(() => refItem.value.media_type === 'video');
const thumb = computed(() => thumbUrl(refItem.value));
const originalUrl = computed(() => mediaUrl(refItem.value));
const posterFailed = ref(false);

const caption = computed(() => {
  if (isMulti.value) {
    const withCaption = items.value.find((item) => item.caption);
    return withCaption ? withCaption.caption : '';
  }
  return refItem.value.caption || '';
});

const extra = computed(() => {
  let text = '';
  if (refItem.value.message_id !== null && refItem.value.message_id !== undefined) {
    text += `#${refItem.value.message_id}`;
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
