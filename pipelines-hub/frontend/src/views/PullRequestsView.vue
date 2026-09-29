<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { STATUS_LABEL, ago, fullDate } from '../format'
import { emptyFilter, toParam } from '../filters'
import PrIcon from '../components/PrIcon.vue'
import ProviderIcon from '../components/ProviderIcon.vue'
import StatusIcon from '../components/StatusIcon.vue'
import Reviewers from '../components/Reviewers.vue'
import FilterBar from '../components/FilterBar.vue'

const TABS = [
  ['review', 'Por revisar', 'Te pidieron revisión y todavía no respondes.'],
  ['mine', 'Míos', 'Tus PR abiertos: aprobaciones, cambios pedidos y CI.'],
  ['open', 'Abiertos', 'Todos los PR abiertos de los repos seguidos.'],
  ['closed', 'Cerrados', 'Mergeados o cerrados en los últimos 7 días.'],
]
const filter = ref(emptyFilter())
const q = ref('')
const ready = ref(false)
const facets = ref({})
const data = ref(null)
const loading = ref(true)
const now = ref(Date.now())

const bucket = computed(() => filter.value.bucket || 'review')
function setBucket(key) {
  filter.value = { ...filter.value, bucket: key }
}

let seq = 0
async function load(quiet = false) {
  const my = ++seq
  if (!quiet) loading.value = true
  try {
    const res = await api.prs({ view: bucket.value, filter: toParam(filter.value), q: q.value || undefined }, { quiet })
    if (my === seq) data.value = res
  } catch {
    /* toast */
  } finally {
    if (my === seq) loading.value = false
    now.value = Date.now()
  }
}
async function loadFacets() {
  try { facets.value = await api.prFacets({ filter: toParam(filter.value) }, { quiet: true }) } catch { /* */ }
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
onMounted(() => {
  timer = setInterval(() => ready.value && !document.hidden && load(true), 20000)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  clearTimeout(debounce)
})

const tabInfo = computed(() => TABS.find((t) => t[0] === bucket.value) || TABS[0])
const items = computed(() => data.value?.items || [])
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div>
        <h1>Pull requests</h1>
        <p>{{ tabInfo[2] }}</p>
      </div>
    </div>

    <FilterBar v-model:filter="filter" v-model:q="q" scope="prs" :facets="facets"
               placeholder="Título, autor, rama o repo" period-label="Actualizados en" @ready="onReady">
      <template #summary>
        <nav class="tabs" aria-label="Bandejas">
          <button v-for="[key, label] in TABS" :key="key" :aria-current="bucket === key ? 'page' : undefined"
                  :class="{ active: bucket === key }" @click="setBucket(key)">
            {{ label }}
            <span v-if="data" class="n" :class="{ hot: key === 'review' && data.counts.review }">{{ data.counts[key] }}</span>
          </button>
        </nav>
      </template>
    </FilterBar>

    <div class="card list">
      <div v-if="loading && !data" class="empty">Cargando…</div>
      <div v-else-if="!items.length" class="empty">
        <template v-if="bucket === 'review'"><h2>Nada por revisar</h2><p>Nadie te está esperando. 🎉</p></template>
        <template v-else-if="bucket === 'mine'"><h2>No tienes PR abiertos</h2></template>
        <template v-else><h2>Sin pull requests</h2><p v-if="q">Nada calza con la búsqueda.</p></template>
      </div>
      <RouterLink v-for="pr in items" :key="pr.id" :to="`/prs/${pr.id}`" class="pr">
        <PrIcon :state="pr.state" :draft="pr.draft" :size="18" class="pr-state" />
        <div class="pr-main">
          <div class="pr-title">
            <span class="truncate" :title="pr.title">{{ pr.title }}</span>
            <span v-if="pr.draft" class="badge draft">Borrador</span>
            <span v-if="pr.ready" class="badge success">Lista para mergear</span>
            <span v-else-if="pr.changes_requested" class="badge failed">Cambios pedidos</span>
            <span v-if="pr.state === 'merged'" class="badge merged">Mergeado</span>
            <span v-else-if="pr.state === 'closed'" class="badge closed">Cerrado</span>
          </div>
          <div class="pr-meta">
            <span class="repo"><ProviderIcon :provider="pr.provider" :size="13" /><span class="truncate">{{ pr.repo.full_name }}</span></span>
            <span class="faint num">#{{ pr.number }}</span>
            <span class="sep hide-sm" aria-hidden="true">·</span>
            <span class="author hide-sm"><img v-if="pr.author_avatar" :src="pr.author_avatar" alt="" width="16" height="16" loading="lazy" />{{ pr.author }}</span>
            <span class="branches hide-md" :title="`${pr.source_branch} → ${pr.target_branch}`">
              <span class="chip"><span class="truncate">{{ pr.source_branch }}</span></span>
              <span aria-hidden="true">→</span>
              <span class="chip">{{ pr.target_branch }}</span>
            </span>
          </div>
        </div>
        <div class="pr-ci">
          <span v-if="pr.ci" class="ci" :title="pr.ci.runs.map((r) => `${r.workflow}: ${STATUS_LABEL[r.status]}`).join('\n')">
            <StatusIcon :status="pr.ci.status" />
            <span class="hide-md">{{ STATUS_LABEL[pr.ci.status] }}</span>
          </span>
        </div>
        <div class="pr-rev hide-sm"><Reviewers :reviewers="pr.reviewers" /></div>
        <div class="pr-when">
          <span :title="fullDate(pr.updated_at)">{{ ago(pr.state === 'open' ? pr.updated_at : pr.closed_at || pr.updated_at, now) }}</span>
          <span v-if="pr.comment_count" class="faint comments" :title="`${pr.comment_count} comentarios`">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z" stroke-linejoin="round" /></svg>
            {{ pr.comment_count }}
          </span>
        </div>
      </RouterLink>
    </div>
  </main>
</template>

<style scoped>
.tabs { display: flex; gap: 6px; margin-bottom: 12px; overflow-x: auto; }
.tabs button {
  display: inline-flex; align-items: center; gap: 7px; height: 32px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: 99px; background: var(--surface); color: var(--text-muted);
  font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap;
}
.tabs button:hover { color: var(--text); border-color: var(--border-strong); }
.tabs button.active { color: var(--text); background: var(--accent-soft); border-color: var(--accent); }
.n { min-width: 20px; height: 20px; padding: 0 6px; border-radius: 99px; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-muted); font-size: 11.5px; display: inline-flex; align-items: center; justify-content: center; }
.n.hot { background: var(--st-waiting-soft); border-color: transparent; color: var(--st-waiting); }

.list { overflow: hidden; }
.pr {
  display: grid; grid-template-columns: 22px minmax(0, 1fr) 110px 110px 100px;
  align-items: center; gap: 14px; padding: 11px 16px; border-bottom: 1px solid var(--border); color: var(--text);
}
.pr:last-of-type { border-bottom: 0; }
.pr:hover { background: var(--surface-hover); text-decoration: none; }
.pr-main { min-width: 0; }
.pr-title { display: flex; align-items: center; gap: 8px; font-weight: 600; min-width: 0; }
.pr-meta { display: flex; align-items: center; gap: 6px; margin-top: 3px; font-size: 12.5px; color: var(--text-muted); min-width: 0; }
.repo { display: inline-flex; align-items: center; gap: 5px; font-weight: 550; min-width: 0; flex: 0 1 auto; white-space: nowrap; }
.repo svg { flex: none; }
.num { white-space: nowrap; }
.author { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.author img { border-radius: 50%; }
.branches { display: inline-flex; align-items: center; gap: 4px; min-width: 0; margin-left: 4px; }
.branches .chip:first-child { max-width: 220px; }
.pr-ci .ci { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-muted); }
.pr-rev { display: flex; justify-content: flex-start; }
.pr-when { display: grid; justify-items: end; font-size: 12.5px; color: var(--text-muted); white-space: nowrap; }
.comments { display: inline-flex; align-items: center; gap: 4px; }
@media (max-width: 1020px) {
  .pr { grid-template-columns: 22px minmax(0, 1fr) 32px 100px 90px; }
  .hide-md { display: none !important; }
}
@media (max-width: 720px) {
  .pr { grid-template-columns: 20px minmax(0, 1fr) 24px 80px; gap: 10px; padding: 10px 12px; }
  .hide-sm { display: none !important; }
        .pr-title .badge { display: none; }
}
</style>
