<script setup>
import { STATUS_LABEL } from '../format'

defineProps({
  status: { type: String, required: true },
  size: { type: Number, default: 16 },
})
</script>

<template>
  <span class="status-icon" :class="status" :title="STATUS_LABEL[status] || status" role="img"
        :aria-label="STATUS_LABEL[status] || status" :style="{ width: size + 'px', height: size + 'px' }">
    <svg viewBox="0 0 16 16" :width="size" :height="size" aria-hidden="true">
      <template v-if="status === 'success'">
        <circle cx="8" cy="8" r="7.25" fill="currentColor" />
        <path d="M4.8 8.3l2.1 2.1 4.3-4.6" fill="none" stroke="var(--surface)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      </template>
      <template v-else-if="status === 'failed'">
        <circle cx="8" cy="8" r="7.25" fill="currentColor" />
        <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="var(--surface)" stroke-width="1.8" stroke-linecap="round" />
      </template>
      <template v-else-if="status === 'running'">
        <circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" stroke-opacity=".28" stroke-width="2" />
        <path class="spin" d="M8 1.75a6.25 6.25 0 0 1 6.25 6.25" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </template>
      <template v-else-if="status === 'waiting'">
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1.6" />
        <path d="M6.3 5.3v5.4M9.7 5.3v5.4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
      </template>
      <template v-else-if="status === 'queued'">
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="2.6 2.1" />
      </template>
      <template v-else-if="status === 'cancelled'">
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1.6" />
        <path d="M3.6 12.4l8.8-8.8" stroke="currentColor" stroke-width="1.6" />
      </template>
      <template v-else>
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1.6" />
        <path d="M5 8h6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
      </template>
    </svg>
  </span>
</template>

<style scoped>
.status-icon { display: inline-flex; flex: none; }
.success { color: var(--st-success); }
.failed { color: var(--st-failed); }
.running { color: var(--st-running); }
.waiting { color: var(--st-waiting); }
.queued, .cancelled, .skipped { color: var(--st-queued); }
</style>
