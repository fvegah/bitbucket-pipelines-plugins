<script setup>
// Serie única (sin leyenda: el título de la tarjeta la nombra), línea de 2px con área tenue
// y tooltip con crosshair al pasar el mouse.
import { computed, ref } from 'vue'

const props = defineProps({
  points: { type: Array, default: () => [] }, // [{ ts, value }]
  max: { type: Number, default: null },
  format: { type: Function, default: (v) => String(v) },
  label: { type: String, default: '' },
  height: { type: Number, default: 44 },
})
const W = 240
const hover = ref(null)
const valid = computed(() => props.points.filter((p) => p.value !== null && p.value !== undefined))
const top = computed(() => props.max ?? Math.max(1e-9, ...valid.value.map((p) => p.value)) * 1.1)
const coords = computed(() => {
  const n = valid.value.length
  return valid.value.map((p, i) => ({
    ...p,
    x: n > 1 ? (i / (n - 1)) * W : W / 2,
    y: props.height - 2 - (Math.min(p.value, top.value) / top.value) * (props.height - 6),
  }))
})
const line = computed(() => coords.value.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' '))
const area = computed(() => coords.value.length
  ? `0,${props.height} ${line.value} ${W},${props.height}` : '')

function move(e) {
  if (!coords.value.length) return
  const rect = e.currentTarget.getBoundingClientRect()
  const x = ((e.clientX - rect.left) / rect.width) * W
  let best = coords.value[0]
  for (const c of coords.value) if (Math.abs(c.x - x) < Math.abs(best.x - x)) best = c
  hover.value = { ...best, left: (best.x / W) * 100 }
}
const time = (ts) => new Date(ts).toLocaleString('es-CL', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
</script>

<template>
  <div class="spark" @mousemove="move" @mouseleave="hover = null">
    <svg :viewBox="`0 0 ${W} ${height}`" preserveAspectRatio="none" :height="height" role="img"
         :aria-label="`${label}: ${valid.length ? format(valid[valid.length - 1].value) : 'sin datos'}`">
      <polygon v-if="area" :points="area" class="area" />
      <polyline v-if="line" :points="line" class="line" vector-effect="non-scaling-stroke" />
      <line v-if="hover" :x1="hover.x" :x2="hover.x" y1="0" :y2="height" class="cross" vector-effect="non-scaling-stroke" />
    </svg>
    <div v-if="hover" class="tip" :style="{ left: `clamp(0px, calc(${hover.left}% - 60px), calc(100% - 120px))` }">
      <strong>{{ format(hover.value) }}</strong><span>{{ time(hover.ts) }}</span>
    </div>
    <p v-if="!valid.length" class="empty-s">Sin muestras todavía</p>
  </div>
</template>

<style scoped>
.spark { position: relative; width: 100%; }
svg { display: block; width: 100%; }
.line { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.area { fill: var(--accent); opacity: .12; }
.cross { stroke: var(--text-faint); stroke-width: 1; stroke-dasharray: 2 2; }
.tip {
  position: absolute; top: -34px; width: 120px; pointer-events: none; z-index: 5;
  display: grid; gap: 1px; padding: 4px 8px; border-radius: var(--radius-sm);
  background: var(--text); color: var(--bg); font-size: 11px; box-shadow: var(--shadow-lg);
}
.tip strong { font-size: 12px; font-variant-numeric: tabular-nums; }
.empty-s { margin: 0; font-size: 12px; color: var(--text-faint); position: absolute; inset: 0; display: grid; place-items: center; }
</style>
