<script setup>
// Medidor: el relleno lleva la severidad (normal → alerta → crítico) y la pista es un
// escalón más claro del mismo tono.
import { computed } from 'vue'

const props = defineProps({
  value: { type: Number, default: null },
  max: { type: Number, default: null },
  warn: { type: Number, default: 0.8 },
  crit: { type: Number, default: 0.92 },
  label: { type: String, default: '' },
})
const ratio = computed(() => (props.value != null && props.max ? Math.min(1, props.value / props.max) : null))
const level = computed(() => (ratio.value == null ? 'none' : ratio.value >= props.crit ? 'crit' : ratio.value >= props.warn ? 'warn' : 'ok'))
</script>

<template>
  <div class="meter" :class="level" role="meter" :aria-label="label" aria-valuemin="0" aria-valuemax="100"
       :aria-valuenow="ratio == null ? undefined : Math.round(ratio * 100)">
    <span class="fill" :style="{ width: `${(ratio ?? 0) * 100}%` }"></span>
  </div>
</template>

<style scoped>
.meter { height: 8px; border-radius: 99px; background: var(--accent-soft); overflow: hidden; }
.fill { display: block; height: 100%; border-radius: 99px; background: var(--accent); transition: width .3s; }
.warn { background: var(--st-waiting-soft); }
.warn .fill { background: var(--st-waiting); }
.crit { background: var(--st-failed-soft); }
.crit .fill { background: var(--st-failed); }
.none { background: var(--surface-2); }
</style>
