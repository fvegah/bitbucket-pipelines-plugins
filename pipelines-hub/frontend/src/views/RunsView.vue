<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { ago, cleanBranch, duration, elapsed, fullDate, shortSha } from '../format'
import { emptyFilter, isEmpty, toParam } from '../filters'
import StatusIcon from '../components/StatusIcon.vue'
import ProviderIcon from '../components/ProviderIcon.vue'
import FilterBar from '../components/FilterBar.vue'
import Icon from '../components/Icon.vue'

const bar = ref(null)
const ready = ref(false)
const filter = ref(emptyFilter())
const q = ref('')
const facets = ref({})
const runs = ref([])
const stats = ref(null)
const overview = ref(null)
const loading = ref(true)
const loadingMore = ref(false)
const exhausted = ref(false)
const now = ref(Date.now())
const PAGE = 60

const hasAccounts = computed(() => (overview.value?.accounts ?? 1) > 0)
const summary = computed(() => {
  const s = stats.value?.last_24h || {}
  return {
    active: stats.value?.active ?? 0, waiting: stats.value?.waiting ?? 0,
    failed: s.failed || 0, success: s.success || 0, repos: stats.value?.repos ?? 0,
  }
})
const statusOn = (v) => { const s = filter.value.include?.status || []; return s.length === 1 && s[0] === v }

let seq = 0
async function load({ quiet = false } = {}) {
  const my = ++seq
  if (!quiet) loading.value = true
  const params = { filter: toParam(filter.value), q: q.value || undefined }
  try {
    const [list, st, ov] = await Promise.all([
      api.runs({ ...params, limit: PAGE }, { quiet }),
      api.runStats(params, { quiet: true }),
      api.overview({ quiet: true }),
    ])
    if (my !== seq) return
    if (quiet && runs.value.length > PAGE) {
      const fresh = new Map(list.map((r) => [r.id, r]))
      const minId = Math.min(...list.map((x) => x.id))
      runs.value = [...list, ...runs.value.filter((r) => !fresh.has(r.id) && r.id < minId)]
    } else {
      runs.value = list
      exhausted.value = list.length < PAGE
    }
    stats.value = st
    overview.value = ov
  } catch {
    /* toast */
  } finally {
    if (my === seq) loading.value = false
    now.value = Date.now()
  }
}
async function loadFacets() {
  try { facets.value = await api.runFacets({ filter: toParam(filter.value) }, { quiet: true }) } catch { /* */ }
}
async function loadMore() {
  if (!runs.value.length) return
  loadingMore.value = true
  try {
    const last = runs.value[runs.value.length - 1]
    const more = await api.runs({ filter: toParam(filter.value), q: q.value || undefined, limit: PAGE, before_id: last.id })
    runs.value = [...runs.value, ...more.filter((r) => !runs.value.some((x) => x.id === r.id))]
    exhausted.value = more.length < PAGE
  } finally {
    loadingMore.value = false
  }
}

let debounce
watch([filter, q], () => {
  if (!ready.value) return
  clearTimeout(debounce)
  debounce = setTimeout(() => { load(); loadFacets() }, 200)
}, { deep: true })
function onReady() {
  ready.value = true
  load()
  loadFacets()
}

let timer
const tick = setInterval(() => (now.value = Date.now()), 1000)
onMounted(() => {
  timer = setInterval(() => { if (ready.value && !document.hidden) load({ quiet: true }) }, 8000)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  clearInterval(tick)
  clearTimeout(debounce)
})

function runDuration(run) {
  if (run.status === 'running') return duration(elapsed(run.started_at, null, now.value))
  return duration(run.duration_s)
}
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div>
        <h1>Ejecuciones</h1>
        <p>Pipelines de GitHub Actions, Bitbucket y Cloudflare. Arma vistas con los filtros que te importan.</p>
      </div>
    </div>

    <FilterBar ref="bar" v-model:filter="filter" v-model:q="q" scope="runs" :facets="facets"
               placeholder="Buscar commit, workflow, autor, SHA…" @ready="onReady">
      <template #summary>
        <section class="stats" aria-label="Resumen">
          <button class="stat" :class="{ on: statusOn('active') }" @click="bar.setStatus('status', 'active')">
            <span class="stat-n running">{{ summary.active }}</span><span class="stat-l">en curso</span>
          </button>
          <button class="stat" :class="{ on: statusOn('waiting') }" title="Esperando que alguien lance un step manual" @click="bar.setStatus('status', 'waiting')">
            <span class="stat-n waiting">{{ summary.waiting }}</span><span class="stat-l">en pausa</span>
          </button>
          <button class="stat" :class="{ on: statusOn('failed') }" @click="bar.setStatus('status', 'failed')">
            <span class="stat-n failed">{{ summary.failed }}</span><span class="stat-l">fallidas · 24 h</span>
          </button>
          <button class="stat" :class="{ on: statusOn('success') }" @click="bar.setStatus('status', 'success')">
            <span class="stat-n success">{{ summary.success }}</span><span class="stat-l">exitosas · 24 h</span>
          </button>
          <div class="stat static">
            <span class="stat-n">{{ summary.repos }}</span><span class="stat-l">repos en esta vista</span>
          </div>
        </section>
      </template>
    </FilterBar>

    <div class="card list">
      <div v-if="loading && !runs.length" class="empty">Cargando…</div>
      <div v-else-if="!hasAccounts" class="empty">
        <h2>Todavía no hay cuentas</h2>
        <p>Agrega una cuenta de GitHub o Bitbucket y elige qué organizaciones seguir.</p>
        <RouterLink to="/cuentas" class="btn primary"><Icon name="plus" /> Agregar cuenta</RouterLink>
      </div>
      <div v-else-if="!runs.length" class="empty">
        <h2>Sin ejecuciones</h2>
        <p v-if="!isEmpty(filter) || q">Nada calza con los filtros.</p>
        <p v-else>La primera sincronización puede tardar unos segundos.</p>
      </div>
      <RouterLink v-for="run in runs" :key="run.id" :to="`/runs/${run.id}`" class="run" :class="run.status">
        <StatusIcon :status="run.status" :size="18" class="run-status" />
        <div class="run-main">
          <div class="run-title truncate" :title="run.title">{{ run.title || run.workflow || 'Sin título' }}</div>
          <div class="run-meta">
            <span class="repo"><ProviderIcon :provider="run.provider" :size="13" /><span class="truncate">{{ run.repo.full_name }}</span></span>
            <template v-if="run.workflow && run.workflow !== run.title">
              <span class="sep hide-sm" aria-hidden="true">·</span>
              <span class="truncate wf hide-sm">{{ run.workflow }}</span>
            </template>
            <span v-if="run.number" class="faint num hide-sm">#{{ run.number }}</span>
          </div>
        </div>
        <div class="run-side">
          <span v-if="run.branch" class="chip branch" :title="run.branch"><Icon name="branch" />
            <span class="truncate">{{ cleanBranch(run.branch) }}</span></span>
          <span v-if="run.sha" class="chip mono hide-md">{{ shortSha(run.sha) }}</span>
        </div>
        <div class="run-when">
          <span :title="fullDate(run.created_at)">{{ ago(run.created_at, now) }}</span>
          <span class="faint"><Icon name="clock" :size="12" /> {{ runDuration(run) }}</span>
        </div>
        <div class="run-actor hide-md" :title="run.actor">
          <img v-if="run.actor_avatar" :src="run.actor_avatar" alt="" width="20" height="20" loading="lazy" />
          <span class="truncate">{{ run.actor }}</span>
        </div>
      </RouterLink>
      <div v-if="runs.length && !exhausted" class="more">
        <button class="btn" :disabled="loadingMore" @click="loadMore">{{ loadingMore ? 'Cargando…' : 'Cargar más' }}</button>
      </div>
    </div>
  </main>
</template>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.stat {
  display: flex; align-items: baseline; gap: 8px; padding: 14px 16px;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow); color: var(--text); font: inherit; text-align: left; cursor: pointer;
}
.stat:hover { border-color: var(--border-strong); text-decoration: none; }
.stat.on { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.stat-n { font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; }
.stat-n.running { color: var(--st-running); }
.stat-n.failed { color: var(--st-failed); }
.stat-n.waiting { color: var(--st-waiting); }
.stat-n.success { color: var(--st-success); }
.stat-l { color: var(--text-muted); font-size: 13px; }

.stat.static { cursor: default; }
.stat.static:hover { border-color: var(--border); }

.list { overflow: hidden; }
.run {
  display: grid; grid-template-columns: 22px minmax(0, 1fr) minmax(0, 220px) 104px 150px;
  align-items: center; gap: 14px; padding: 11px 16px;
  border-bottom: 1px solid var(--border); color: var(--text);
}
.run:last-of-type { border-bottom: 0; }
.run:hover { background: var(--surface-hover); text-decoration: none; }
.run-main { min-width: 0; }
.run-title { font-weight: 600; }
.run-meta { display: flex; align-items: center; gap: 6px; margin-top: 2px; font-size: 12.5px; color: var(--text-muted); min-width: 0; }
.repo { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; font-weight: 550; min-width: 0; flex: 0 1 auto; }
.repo svg { flex: none; }
.num { white-space: nowrap; }
.wf { min-width: 0; }
.run-side { display: flex; gap: 6px; justify-content: flex-end; min-width: 0; }
.branch { max-width: 170px; }
.run-when { display: grid; justify-items: end; font-size: 12.5px; color: var(--text-muted); white-space: nowrap; }
.run-when .faint { display: inline-flex; align-items: center; gap: 4px; font-variant-numeric: tabular-nums; }
.run-actor { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-muted); min-width: 0; }
.run-actor img { border-radius: 50%; flex: none; }
.more { display: flex; justify-content: center; padding: 14px; border-top: 1px solid var(--border); }

@media (max-width: 1020px) {
  .run { grid-template-columns: 22px minmax(0, 1fr) minmax(0, 170px) 96px; }
  .hide-md { display: none !important; }
}
@media (max-width: 720px) {
  .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stat.static { grid-column: 1 / -1; }
  .run { grid-template-columns: 20px minmax(0, 1fr) 84px; gap: 10px; padding: 10px 12px; }
  .run-side { display: none; }
  .hide-sm { display: none !important; }
}
</style>
