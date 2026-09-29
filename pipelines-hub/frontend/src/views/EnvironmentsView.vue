<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { STATUS_LABEL, ago, cleanBranch, fullDate, shortSha } from '../format'
import { emptyFilter, isEmpty, toParam } from '../filters'
import StatusIcon from '../components/StatusIcon.vue'
import ProviderIcon from '../components/ProviderIcon.vue'
import FilterBar from '../components/FilterBar.vue'
import Icon from '../components/Icon.vue'

const groups = ref([])
const loading = ref(true)
const filter = ref(emptyFilter())
const q = ref('')
const ready = ref(false)
const facets = ref({})
const now = ref(Date.now())

let seq = 0
async function load(quiet = false) {
  const my = ++seq
  try {
    const res = await api.deployments({ filter: toParam(filter.value), q: q.value || undefined }, { quiet })
    if (my === seq) groups.value = res
  } finally {
    if (my === seq) loading.value = false
    now.value = Date.now()
  }
}
async function loadFacets() {
  try { facets.value = await api.deploymentFacets({ filter: toParam(filter.value) }, { quiet: true }) } catch { /* */ }
}

function envKind(e) {
  const t = (e.env_type || e.environment || '').toLowerCase()
  if (t.includes('prod')) return 'prod'
  if (t.includes('stag')) return 'staging'
  return 'test'
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
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div>
        <h1>Entornos</h1>
        <p>Qué quedó desplegado en cada entorno, según GitHub, Bitbucket y Cloudflare.</p>
      </div>
    </div>

    <FilterBar v-model:filter="filter" v-model:q="q" scope="deployments" :facets="facets"
               placeholder="Repo, entorno, autor o SHA" period-label="Desplegados en" @ready="onReady" />

    <div v-if="loading" class="card empty">Cargando…</div>
    <div v-else-if="!groups.length && (!isEmpty(filter) || q)" class="card empty"><p>Nada calza con los filtros.</p></div>
    <div v-else-if="!groups.length" class="card empty">
      <h2>Sin despliegues registrados</h2>
      <p>Aparecen los repos que usan <em>environments</em> (GitHub) o <em>deployments</em> (Bitbucket).
        Se refrescan cada 30 minutos y cuando termina una ejecución.</p>
    </div>

    <div v-else class="grid">
      <article v-for="g in groups" :key="g.repo.id" class="card env-card">
        <header>
          <ProviderIcon :provider="g.repo.provider" />
          <a :href="g.repo.html_url" target="_blank" rel="noopener" class="truncate repo">{{ g.repo.full_name }}</a>
        </header>
        <ul>
          <li v-for="e in g.environments" :key="e.environment" class="env">
            <div class="env-top">
              <span class="env-name" :class="envKind(e)">{{ e.environment }}</span>
              <span class="badge" :class="e.status"><StatusIcon :status="e.status" :size="12" />{{ STATUS_LABEL[e.status] }}</span>
            </div>
            <div class="env-meta">
              <span v-if="e.ref" class="chip" :title="e.ref"><Icon name="branch" />{{ cleanBranch(e.ref) }}</span>
              <span v-if="e.sha" class="chip mono">{{ shortSha(e.sha) }}</span>
              <span class="faint" :title="fullDate(e.deployed_at)">{{ ago(e.deployed_at, now) }}</span>
              <span v-if="e.actor" class="faint truncate">· {{ e.actor }}</span>
            </div>
            <div v-if="e.title" class="env-title truncate" :title="e.title">{{ e.title }}</div>
            <div class="env-links">
              <RouterLink v-if="e.run_id" :to="`/runs/${e.run_id}`">Ver ejecución<template v-if="e.run_number"> #{{ e.run_number }}</template></RouterLink>
              <a v-if="e.url" :href="e.url" target="_blank" rel="noopener">Abrir <Icon name="external" :size="12" /></a>
            </div>
          </li>
        </ul>
      </article>
    </div>
  </main>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
.env-card header { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); }
.repo { color: var(--text); font-weight: 650; }
.env-card ul { list-style: none; margin: 0; padding: 0; }
.env { padding: 12px 16px; border-bottom: 1px solid var(--border); display: grid; gap: 6px; }
.env:last-child { border-bottom: 0; }
.env-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.env-name { font-weight: 650; font-size: 13.5px; padding-left: 10px; border-left: 3px solid var(--env-test); }
.env-name.prod { border-left-color: var(--env-prod); }
.env-name.staging { border-left-color: var(--env-staging); }
.env-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12.5px; min-width: 0; }
.env-title { font-size: 12.5px; color: var(--text-muted); }
.env-links { display: flex; gap: 14px; font-size: 12.5px; font-weight: 550; }
.env-links a { display: inline-flex; align-items: center; gap: 3px; }
@media (max-width: 720px) {
  .grid { grid-template-columns: 1fr; }
    }
</style>
