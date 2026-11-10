<template>
  <div
    class="media-grid"
    :style="{ position: 'relative', width: cw + 'px', height: ch + 'px' }"
  >
    <div
      v-for="(item, index) in items"
      :key="item.id"
      class="gi"
      :class="{ 'video-fallback': isVideo(item) && posterFailed[item.id] }"
      :data-id="item.id"
      :style="tileStyle(index)"
      @click="$emit('open', index)"
    >
      <template v-if="isVideo(item)">
        <img
          v-if="thumbUrl(item) && !posterFailed[item.id]"
          :src="thumbUrl(item)"
          loading="lazy"
          decoding="async"
          @error="markPosterFailed(item)"
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
        :src="thumbUrl(item) || mediaUrl(item)"
        loading="lazy"
        decoding="async"
        @error="onImageError($event, item)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import {
  computeAlbumLayout,
  RectPart,
} from '@/lib/album-layout';
import { mediaUrl, thumbUrl } from '@/lib/media';

const props = defineProps({
  items: { type: Array, required: true },
});
defineEmits(['open']);

const feedWidth = ref(480);
const posterFailed = ref({});
let resizeObserver = null;

function measure() {
  const feed = document.getElementById('chatFeed');
  const feedW = feed ? feed.clientWidth - 32 : 480;
  // 气泡最大宽度 420，媒体区域不再额外留内边距
  feedWidth.value = Math.min(420, Math.max(100, feedW));
}

onMounted(() => {
  measure();
  const feed = document.getElementById('chatFeed');
  if (feed && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(measure);
    resizeObserver.observe(feed);
  } else {
    window.addEventListener('resize', measure);
  }
});

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect();
  else window.removeEventListener('resize', measure);
});

const layout = computed(() => computeAlbumLayout(props.items, feedWidth.value));

const cw = computed(() => {
  const right = layout.value.find((l) => l.sides & RectPart.Right);
  return right ? right.geometry.x + right.geometry.width : feedWidth.value;
});

const ch = computed(() => {
  const bottom = layout.value.find((l) => l.sides & RectPart.Bottom);
  return bottom ? bottom.geometry.y + bottom.geometry.height : feedWidth.value;
});

function isVideo(item) {
  return item.media_type === 'video';
}

function markPosterFailed(item) {
  posterFailed.value = { ...posterFailed.value, [item.id]: true };
}

function onImageError(event, item) {
  const img = event.target;
  img.onerror = null;
  img.src = mediaUrl(item);
}

function tileStyle(index) {
  const l = layout.value[index];
  if (!l) return {};
  const style = {
    position: 'absolute',
    left: `${(l.geometry.x / cw.value) * 100}%`,
    top: `${(l.geometry.y / ch.value) * 100}%`,
    width: `${(l.geometry.width / cw.value) * 100}%`,
    height: `${(l.geometry.height / ch.value) * 100}%`,
  };
  return style;
}
</script>
