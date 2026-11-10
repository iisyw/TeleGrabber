<template>
  <div class="date-separator" :data-date="date || ''">
    <span class="date-label">{{ dateLabel(date) }}</span>
  </div>
</template>

<script setup>
import { dateLabel } from '@/lib/media';

defineProps({
  date: { type: String, default: '' },
});
</script>

<style scoped lang="scss" src="./DateSeparator.scss"></style>
