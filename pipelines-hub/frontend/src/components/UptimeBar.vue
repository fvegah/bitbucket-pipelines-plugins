<script setup>
// Historial de chequeos: celdas por intervalo con tooltip (estado + hora); el estado va
// también como texto en el tooltip, no solo por color.
import { computed } from 'vue'

const props = defineProps({ checks: { type: Array, default: () => [] }, buckets: { type: Number, default: 48 } })
const LABEL = { ok: 'OK', warn: 'Alerta', down: 'Caído', unknown: 'Sin dato' }
const RANK = { down: 3, warn: 2, unknown: 1, ok: 0 }
const cells = computed(() => {
  if (!props.checks.length) return []
  const end = Date.now()
  const start = end - 24 * 3600 * 1000
  const size = (end - start) / props.buckets
  const out = Array.from({ length: props.buckets }, (_, i) => ({ from: start + i * size, status: null, n: 0 }))
  for (const c of props.checks) {
    const i = Math.floor((new Date(c.ts).getTime() - start) / size)
    if (i < 0 || i >= props.buckets) continue
    const cell = out[i]
    cell.n++
    if (cell.status === null || RANK[c.status] > RANK[cell.status]) cell.status = c.status
  }
  return out
})
const uptime = computed(() => {
  const n = props.checks.filter((c) => c.status !== 'unknown').length
  if (!n) return null
  return (props.checks.filter((c) => c.status === 'ok').length / n) * 100
})
const hour = (t) => new Date(t).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })
</script>

<template>
  <div class="uptime">
    <div class="cells" role="img" :aria-label="uptime == null ? 'Sin historial' : `Disponibilidad 24 h: ${uptime.toFixed(1)}%`">
      <span v-for="(c, i) in cells" :key="i" class="cell" :class="c.status || 'nodata'"
            :title="c.status ? `${hour(c.from)} · ${LABEL[c.status]} (${c.n} chequeos)` : `${hour(c.from)} · sin chequeos`"></span>
    </div>
    <span class="pct faint">{{ uptime == null ? '—' : `${uptime.toFixed(uptime === 100 ? 0 : 1)}%` }}</span>
  </div>
</template>

<style scoped>
.uptime { display: flex; align-items: center; gap: 8px; }
.cells { display: flex; gap: 2px; flex: 1; min-width: 0; height: 18px; }
.cell { flex: 1; border-radius: 2px; background: var(--surface-2); min-width: 2px; }
.cell.ok { background: var(--st-success); }
.cell.warn { background: var(--st-waiting); }
.cell.down { background: var(--st-failed); }
.cell.unknown { background: var(--border-strong); }
.pct { font-size: 12px; width: 44px; text-align: right; font-variant-numeric: tabular-nums; }
</style>
