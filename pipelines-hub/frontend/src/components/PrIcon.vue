<script setup>
import { computed } from 'vue'
import { PR_STATE_LABEL } from '../format'

const props = defineProps({
  state: { type: String, required: true },
  draft: { type: Boolean, default: false },
  size: { type: Number, default: 16 },
  decorative: { type: Boolean, default: false },
})
const kind = computed(() => (props.state === 'open' && props.draft ? 'draft' : props.state))
</script>

<template>
  <svg class="pr-icon" :class="kind" :width="size" :height="size" viewBox="0 0 16 16" fill="none"
       stroke="currentColor" stroke-width="1.5" stroke-linecap="round" :role="decorative ? undefined : 'img'"
       :aria-hidden="decorative ? 'true' : undefined" :aria-label="decorative ? undefined : PR_STATE_LABEL[kind]">
    <title v-if="!decorative">{{ PR_STATE_LABEL[kind] }}</title>
    <template v-if="kind === 'merged'">
      <circle cx="4.5" cy="3.5" r="1.6" /><circle cx="4.5" cy="12.5" r="1.6" /><circle cx="11.5" cy="8.5" r="1.6" />
      <path d="M4.5 5.1v5.8M4.5 5.5c0 2.5 2.5 3 5.4 3" />
    </template>
    <template v-else>
      <circle cx="4.5" cy="3.5" r="1.6" /><circle cx="4.5" cy="12.5" r="1.6" /><circle cx="11.5" cy="12.5" r="1.6" />
      <path d="M4.5 5.1v5.8" />
      <path v-if="kind === 'closed'" d="M9.8 3l3.4 3.4M13.2 3L9.8 6.4" />
      <path v-else-if="kind === 'draft'" d="M11.5 9v.01M11.5 6.2v.01M11.5 3.4v.01" stroke-width="1.8" />
      <path v-else d="M11.5 10.9V6a2 2 0 0 0-2-2H7.5M8.8 2.6 7.3 4l1.5 1.4" />
    </template>
  </svg>
</template>

<style scoped>
.pr-icon { flex: none; }
.open { color: var(--st-success); }
.merged { color: var(--st-merged); }
.closed { color: var(--st-failed); }
.draft { color: var(--st-queued); }
</style>
