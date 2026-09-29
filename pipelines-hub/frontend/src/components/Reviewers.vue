<script setup>
import { REVIEW_LABEL } from '../format'

defineProps({ reviewers: { type: Array, default: () => [] }, max: { type: Number, default: 4 } })
</script>

<template>
  <span class="reviewers">
    <span v-for="r in reviewers.slice(0, max)" :key="r.id" class="rv" :class="r.state" :title="`${r.name}: ${REVIEW_LABEL[r.state]}`">
      <img v-if="r.avatar" :src="r.avatar" alt="" width="20" height="20" loading="lazy" />
      <span v-else class="ph">{{ r.name[0] }}</span>
      <span class="mark" aria-hidden="true">
        <svg v-if="r.state === 'approved'" viewBox="0 0 10 10"><path d="M2.5 5.2l1.6 1.6 3.4-3.6" /></svg>
        <svg v-else-if="r.state === 'changes_requested'" viewBox="0 0 10 10"><path d="M3 5h4" /></svg>
        <svg v-else-if="r.state === 'pending'" viewBox="0 0 10 10"><circle cx="5" cy="5" r="1" /></svg>
      </span>
      <span class="sr-only">{{ r.name }}: {{ REVIEW_LABEL[r.state] }}</span>
    </span>
    <span v-if="reviewers.length > max" class="more">+{{ reviewers.length - max }}</span>
  </span>
</template>

<style scoped>
.reviewers { display: inline-flex; align-items: center; }
.rv { position: relative; width: 22px; height: 22px; margin-left: -4px; }
.rv:first-child { margin-left: 0; }
.rv img, .ph { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--surface); display: block; }
.ph { display: grid; place-items: center; background: var(--surface-2); color: var(--text-muted); font-size: 10px; font-weight: 700; text-transform: uppercase; }
.mark { position: absolute; right: -3px; bottom: -3px; width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid var(--surface); display: grid; place-items: center; }
.mark:empty { display: none; }
.mark svg { width: 10px; height: 10px; fill: none; stroke: #fff; stroke-width: 1.6; stroke-linecap: round; }
.approved .mark { background: var(--st-success); }
.changes_requested .mark { background: var(--st-failed); }
.pending .mark { background: var(--st-waiting); }
.pending .mark svg { fill: #fff; }
.commented .mark { display: none; }
.more { margin-left: 4px; font-size: 12px; color: var(--text-muted); font-weight: 600; }
:root[data-theme='dark'] .mark svg { stroke: var(--surface); }
@media (prefers-color-scheme: dark) { :root:not([data-theme='light']) .mark svg { stroke: var(--surface); } }
</style>
