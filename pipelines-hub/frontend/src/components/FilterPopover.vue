<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { fieldLabel, SCOPE_FIELDS, valueLabel } from '../filters'

const props = defineProps({
  field: { type: String, required: true },
  scope: { type: String, default: 'runs' },
  filter: { type: Object, required: true },
  options: { type: Array, default: () => [] }, // [{ value, count }]
})
const emit = defineEmits(['update', 'close'])

const spec = computed(() => SCOPE_FIELDS[props.scope].find((f) => f.key === props.field) || {})
const label = computed(() => fieldLabel(props.scope, props.field))
const root = ref(null)
const search = ref(null)
const q = ref('')
const pattern = ref('')

// el modo vive en el popover: elegir "No es" antes de marcar valores no debe perderse
const mode = ref(props.filter.exclude?.[props.field]?.length ? 'exclude' : 'include')
const selected = computed(() => new Set(props.filter[mode.value]?.[props.field] || []))
const patterns = computed(() => [...selected.value].filter((v) => v.includes('*')))

const options = computed(() => {
  const term = q.value.trim().toLowerCase()
  let list = props.options
  const specials = (spec.value.specials || []).filter((v) => !list.some((o) => o.value === v))
  list = [...specials.map((value) => ({ value, count: null })), ...list]
  // mostrar arriba lo marcado aunque ya no tenga ejecuciones
  const extra = [...selected.value].filter((v) => !v.includes('*') && !list.some((o) => o.value === v))
    .map((value) => ({ value, count: 0 }))
  list = [...extra, ...list]
  return term ? list.filter((o) => String(valueLabel(props.field, o.value)).toLowerCase().includes(term)) : list
})

function commit(values, m = mode.value) {
  const next = {
    ...props.filter,
    include: { ...props.filter.include },
    exclude: { ...props.filter.exclude },
  }
  delete next.include[props.field]
  delete next.exclude[props.field]
  if (values.length) next[m][props.field] = values
  emit('update', next)
}
function toggle(value) {
  const set = new Set(selected.value)
  set.has(value) ? set.delete(value) : set.add(value)
  commit([...set])
}
function setMode(m) {
  const values = [...selected.value]
  mode.value = m
  if (values.length) commit(values, m)
}
function addPattern() {
  const p = pattern.value.trim()
  if (!p) return
  commit([...new Set([...selected.value, p.includes('*') ? p : `*${p}*`])])
  pattern.value = ''
}
function onlyThis(value) {
  commit([value])
}

function outside(e) {
  if (root.value && !root.value.contains(e.target) && !e.target.closest?.('[data-filter-trigger]')) emit('close')
}
function onKey(e) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => {
  setTimeout(() => document.addEventListener('mousedown', outside), 0)
  document.addEventListener('keydown', onKey)
  search.value?.focus()
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', outside)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="pop card" role="dialog" :aria-label="`Filtro de ${label}`">
    <div class="pop-head">
      <strong>{{ label }}</strong>
      <div class="segmented sm" role="group" aria-label="Modo">
        <button :aria-pressed="mode === 'include'" @click="setMode('include')">Es</button>
        <button :aria-pressed="mode === 'exclude'" @click="setMode('exclude')">No es</button>
      </div>
    </div>
    <input ref="search" v-model="q" class="input" :placeholder="`Buscar ${label.toLowerCase()}…`" :aria-label="`Buscar ${label}`" />
    <ul class="opts">
      <li v-for="p in patterns" :key="p">
        <label><input type="checkbox" checked @change="toggle(p)" /><code class="grow truncate">{{ p }}</code><span class="faint">patrón</span></label>
      </li>
      <li v-for="o in options" :key="o.value">
        <label :title="o.value">
          <input type="checkbox" :checked="selected.has(o.value)" @change="toggle(o.value)" />
          <span class="grow truncate">{{ valueLabel(field, o.value) }}</span>
          <button type="button" class="only" title="Solo este" @click.prevent="onlyThis(o.value)">solo</button>
          <span v-if="o.count !== null" class="faint num">{{ o.count }}</span>
        </label>
      </li>
      <li v-if="!options.length && !patterns.length" class="muted none">Sin valores en los últimos 30 días.</li>
    </ul>
    <form v-if="!spec.noPattern" class="pattern" @submit.prevent="addPattern">
      <input v-model="pattern" class="input" placeholder="Patrón, ej: deploy* o *-prod" aria-label="Agregar patrón" />
      <button class="btn sm" :disabled="!pattern.trim()">Agregar</button>
    </form>
    <div class="pop-foot">
      <button class="linkish" :disabled="!selected.size" @click="commit([])">Limpiar</button>
      <button class="btn sm primary" @click="emit('close')">Listo</button>
    </div>
  </div>
</template>

<style scoped>
.pop { position: absolute; top: calc(100% + 6px); left: 0; z-index: 30; width: 320px; padding: 12px; display: grid; gap: 10px; box-shadow: var(--shadow-lg); }
.pop-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.segmented.sm button { height: 26px; padding: 0 9px; font-size: 12px; }
.opts { list-style: none; margin: 0; padding: 0; max-height: 280px; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius-sm); }
.opts li + li { border-top: 1px solid var(--border); }
.opts label { display: flex; align-items: center; gap: 8px; padding: 6px 10px; font-size: 13px; cursor: pointer; min-width: 0; }
.opts label:hover { background: var(--surface-hover); }
.opts input { accent-color: var(--accent); width: 15px; height: 15px; flex: none; }
.num { font-variant-numeric: tabular-nums; font-size: 12px; }
.only { visibility: hidden; border: 0; background: none; color: var(--accent); font: 12px var(--font); cursor: pointer; padding: 0 2px; }
.opts label:hover .only, .only:focus-visible { visibility: visible; }
.none { padding: 10px; font-size: 13px; }
.pattern { display: flex; gap: 6px; }
.pattern .input { flex: 1; height: 28px; font-size: 12.5px; }
.pop-foot { display: flex; justify-content: space-between; align-items: center; }
.linkish { border: 0; background: none; padding: 0; color: var(--accent); font: 13px var(--font); cursor: pointer; }
.linkish:disabled { color: var(--text-faint); cursor: default; }
@media (max-width: 720px) {
  .pop { position: fixed; left: 16px; right: 16px; top: 120px; width: auto; }
}
</style>
