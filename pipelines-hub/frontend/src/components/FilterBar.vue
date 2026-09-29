<script setup>
// Barra común de vistas guardadas + filtros dinámicos (Ejecuciones, Pull requests, Entornos).
// v-model:filter y v-model:q; emite "ready" cuando ya resolvió la vista/URL inicial.
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, toast } from '../api'
import { PERIODS, SCOPE_FIELDS, emptyFilter, fieldLabel, isEmpty, normalize, sameFilter, valueLabel } from '../filters'
import FilterPopover from './FilterPopover.vue'
import Icon from './Icon.vue'

const props = defineProps({
  scope: { type: String, required: true },
  facets: { type: Object, default: () => ({}) },
  placeholder: { type: String, default: 'Buscar…' },
  periodLabel: { type: String, default: 'Período' },
})
const filter = defineModel('filter', { type: Object, required: true })
const q = defineModel('q', { type: String, default: '' })
const emit = defineEmits(['ready'])

const route = useRoute()
const router = useRouter()
const views = ref([])
const viewId = ref(null)
const openField = ref(null)
const addMenu = ref(false)
const naming = ref(null)
const confirmDelete = ref(false)

const fields = computed(() => SCOPE_FIELDS[props.scope])
const currentView = computed(() => views.value.find((v) => v.id === viewId.value) || null)
const dirty = computed(() => (currentView.value ? !sameFilter(currentView.value.filter, filter.value) : !isEmpty(filter.value)))
const chips = computed(() => {
  const out = []
  for (const part of ['include', 'exclude']) {
    for (const [field, values] of Object.entries(filter.value[part] || {})) if (values?.length) out.push({ field, part, values })
  }
  const order = (k) => fields.value.findIndex((f) => f.key === k)
  return out.sort((a, b) => order(a.field) - order(b.field))
})
const unused = computed(() => fields.value.filter((f) => !chips.value.some((c) => c.field === f.key)))

function syncUrl() {
  const query = { ...route.query }
  delete query.f
  delete query.view
  delete query.q
  if (viewId.value) query.view = String(viewId.value)
  if (dirty.value) query.f = JSON.stringify(normalize(filter.value))
  if (q.value) query.q = q.value
  router.replace({ query })
}
watch([filter, q], syncUrl, { deep: true })

function selectView(v) {
  viewId.value = v ? v.id : null
  filter.value = v ? normalize(v.filter) : emptyFilter()
  openField.value = null
  confirmDelete.value = false
}
async function saveView() {
  const name = naming.value?.name?.trim()
  if (!name) return
  try {
    if (naming.value.mode === 'rename') {
      const v = await api.updateView(currentView.value.id, { name, scope: props.scope, filter: currentView.value.filter })
      Object.assign(currentView.value, v)
    } else {
      const v = await api.createView({ name, scope: props.scope, filter: normalize(filter.value) })
      views.value.push(v)
      viewId.value = v.id
      toast(`Vista "${name}" guardada`, 'info')
    }
    naming.value = null
    syncUrl()
  } catch { /* toast */ }
}
async function updateCurrentView() {
  const v = await api.updateView(currentView.value.id, { name: currentView.value.name, scope: props.scope, filter: normalize(filter.value) })
  Object.assign(currentView.value, v)
  toast(`Vista "${v.name}" actualizada`, 'info')
  syncUrl()
}
async function deleteCurrentView() {
  if (!confirmDelete.value) return (confirmDelete.value = true)
  const v = currentView.value
  await api.deleteView(v.id)
  views.value = views.value.filter((x) => x.id !== v.id)
  selectView(null)
  toast(`Vista "${v.name}" eliminada`, 'info')
}
function discard() {
  filter.value = currentView.value ? normalize(currentView.value.filter) : { ...emptyFilter(), ...extras(filter.value) }
}
function extras(f) {
  return Object.fromEntries(Object.entries(f || {}).filter(([k]) => !['include', 'exclude', 'since_hours'].includes(k)))
}

function openFilter(key) {
  addMenu.value = false
  openField.value = openField.value === key ? null : key
}
function removeChip(chip) {
  const next = normalize(filter.value)
  delete next[chip.part][chip.field]
  filter.value = next
}
function setPeriod(h) {
  filter.value = { ...filter.value, since_hours: h }
}
function chipText(chip) {
  const labels = chip.values.map((v) => valueLabel(chip.field, v))
  return labels.length > 2 ? `${labels.slice(0, 2).join(', ')} +${labels.length - 2}` : labels.join(', ')
}

onMounted(async () => {
  try { views.value = await api.views({ scope: props.scope }, { quiet: true }) } catch { /* */ }
  const fromUrl = (() => { try { return route.query.f ? normalize(JSON.parse(route.query.f)) : null } catch { return null } })()
  const v = route.query.view ? views.value.find((x) => x.id === Number(route.query.view)) : null
  if (v) viewId.value = v.id
  if (fromUrl) filter.value = fromUrl
  else if (v) filter.value = normalize(v.filter)
  if (route.query.q) q.value = route.query.q
  emit('ready')
})

defineExpose({ setStatus(field, value) {
  const cur = filter.value.include?.[field] || []
  const next = normalize(filter.value)
  delete next.exclude[field]
  if (cur.length === 1 && cur[0] === value) delete next.include[field]
  else next.include[field] = [value]
  filter.value = next
} })
</script>

<template>
  <nav class="views" aria-label="Vistas">
    <button class="view-tab" :class="{ active: !viewId }" :aria-current="!viewId ? 'page' : undefined" @click="selectView(null)">Todas</button>
    <button v-for="v in views" :key="v.id" class="view-tab" :class="{ active: viewId === v.id }"
            :aria-current="viewId === v.id ? 'page' : undefined" @click="selectView(v)">
      {{ v.name }}<span v-if="viewId === v.id && dirty" class="dot" title="Cambios sin guardar" aria-label="cambios sin guardar"></span>
    </button>
    <button class="view-tab add" title="Guardar los filtros actuales como una vista nueva" @click="naming = { mode: 'new', name: '' }">
      <Icon name="plus" :size="13" /> Nueva vista
    </button>
  </nav>

  <form v-if="naming" class="naming card" @submit.prevent="saveView">
    <label class="field grow">{{ naming.mode === 'rename' ? 'Nuevo nombre' : 'Nombre de la vista' }}
      <input v-model="naming.name" class="input" maxlength="100" placeholder="Ej: Deploys a producción" autofocus />
    </label>
    <span v-if="naming.mode === 'new'" class="muted hint">Se guardan los filtros y el período que tienes puestos ahora.</span>
    <button type="button" class="btn" @click="naming = null">Cancelar</button>
    <button class="btn primary" :disabled="!naming.name.trim()">Guardar</button>
  </form>

  <slot name="summary" />

  <section class="filterbar">
    <label class="search">
      <Icon name="search" />
      <span class="sr-only">Buscar</span>
      <input v-model="q" class="input" type="search" :placeholder="placeholder" />
    </label>
    <slot name="controls" />
    <div class="segmented" role="group" :aria-label="periodLabel" :title="periodLabel">
      <button v-for="[h, l] in PERIODS" :key="l" :aria-pressed="(filter.since_hours || null) === h" @click="setPeriod(h)">{{ l }}</button>
    </div>
  </section>

  <section class="chips" aria-label="Filtros activos">
    <div v-for="chip in chips" :key="chip.field" class="fchip-wrap">
      <span class="fchip" :class="{ exclude: chip.part === 'exclude' }">
        <button class="fchip-main" data-filter-trigger :aria-expanded="openField === chip.field" @click="openFilter(chip.field)">
          <span class="fk">{{ fieldLabel(scope, chip.field) }}</span>
          <span class="op">{{ chip.part === 'exclude' ? 'no es' : chip.values.length > 1 ? 'es uno de' : 'es' }}</span>
          <span class="fv truncate" :title="chip.values.join(', ')">{{ chipText(chip) }}</span>
        </button>
        <button class="fchip-x" :aria-label="`Quitar filtro de ${fieldLabel(scope, chip.field)}`" @click="removeChip(chip)">
          <Icon name="plus" :size="12" style="transform: rotate(45deg)" />
        </button>
      </span>
      <FilterPopover v-if="openField === chip.field" :scope="scope" :field="chip.field" :filter="filter"
                     :options="facets[chip.field] || []" @update="filter = $event" @close="openField = null" />
    </div>
    <div class="fchip-wrap">
      <button class="btn sm add-filter" data-filter-trigger :aria-expanded="addMenu" @click="addMenu = !addMenu; openField = null">
        <Icon name="plus" :size="13" /> Filtro
      </button>
      <ul v-if="addMenu" class="menu card" role="menu">
        <li v-for="f in unused" :key="f.key"><button role="menuitem" @click="openFilter(f.key)">{{ f.label }}</button></li>
      </ul>
      <FilterPopover v-if="openField && !chips.some((c) => c.field === openField)" :scope="scope" :field="openField"
                     :filter="filter" :options="facets[openField] || []" @update="filter = $event" @close="openField = null" />
    </div>
    <div class="view-actions">
      <template v-if="dirty">
        <button class="linkish" @click="discard">{{ currentView ? 'Descartar cambios' : 'Limpiar' }}</button>
        <button v-if="currentView" class="btn sm" @click="updateCurrentView">Guardar en "{{ currentView.name }}"</button>
        <button class="btn sm primary" @click="naming = { mode: 'new', name: '' }">Guardar como vista</button>
      </template>
      <template v-else-if="currentView">
        <button class="btn sm ghost" @click="naming = { mode: 'rename', name: currentView.name }">Renombrar</button>
        <button class="btn sm ghost danger" @click="deleteCurrentView">{{ confirmDelete ? '¿Eliminar vista? Sí' : 'Eliminar vista' }}</button>
        <button v-if="confirmDelete" class="btn sm ghost" @click="confirmDelete = false">No</button>
      </template>
    </div>
  </section>
</template>

<style scoped>
.views { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 14px; overflow-x: auto; }
.view-tab {
  display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; margin-bottom: -1px;
  border: 0; border-bottom: 2px solid transparent; background: none; color: var(--text-muted);
  font: inherit; font-weight: 600; cursor: pointer; white-space: nowrap;
}
.view-tab:hover { color: var(--text); }
.view-tab.active { color: var(--text); border-bottom-color: var(--accent); }
.view-tab.add { color: var(--accent); font-weight: 550; }
.view-tab .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--st-waiting); }
.naming { display: flex; align-items: flex-end; gap: 10px; padding: 12px 14px; margin-bottom: 14px; flex-wrap: wrap; }
.naming .hint { font-size: 12.5px; flex-basis: 100%; order: 3; }
.filterbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.search { position: relative; flex: 1 1 260px; display: flex; }
.search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-faint); pointer-events: none; }
.search .input { width: 100%; padding-left: 32px; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; min-height: 30px; }
.fchip-wrap { position: relative; }
.fchip { display: inline-flex; align-items: stretch; height: 28px; border: 1px solid var(--border-strong); border-radius: 99px; background: var(--surface); overflow: hidden; max-width: 420px; }
.fchip.exclude { border-style: dashed; }
.fchip-main { display: inline-flex; align-items: center; gap: 5px; padding: 0 4px 0 11px; border: 0; background: none; color: var(--text); font: 12.5px var(--font); cursor: pointer; min-width: 0; }
.fchip-main:hover, .fchip-x:hover { background: var(--surface-hover); }
.fk { font-weight: 650; white-space: nowrap; }
.op { color: var(--text-muted); white-space: nowrap; }
.fchip.exclude .op { color: var(--st-failed); font-weight: 600; }
.fv { font-weight: 550; }
.fchip-x { display: inline-flex; align-items: center; padding: 0 8px 0 5px; border: 0; background: none; color: var(--text-muted); cursor: pointer; }
.add-filter { border-radius: 99px; border-style: dashed; height: 28px; }
.menu { position: absolute; top: calc(100% + 6px); left: 0; z-index: 30; list-style: none; margin: 0; padding: 4px; min-width: 200px; box-shadow: var(--shadow-lg); }
.menu button { width: 100%; text-align: left; padding: 7px 10px; border: 0; background: none; color: var(--text); font: 13px var(--font); border-radius: var(--radius-sm); cursor: pointer; }
.menu button:hover { background: var(--surface-hover); }
.view-actions { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.linkish { border: 0; background: none; padding: 0; color: var(--accent); font: 13px var(--font); cursor: pointer; }
.linkish:hover { text-decoration: underline; }
@media (max-width: 720px) {
  .view-actions { margin-left: 0; width: 100%; flex-wrap: wrap; }
  .fchip { max-width: calc(100vw - 32px); }
}
</style>
