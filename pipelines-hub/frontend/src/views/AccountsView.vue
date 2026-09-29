<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api, toast } from '../api'
import { PROVIDER_LABEL, ago, fullDate } from '../format'
import ProviderIcon from '../components/ProviderIcon.vue'
import Icon from '../components/Icon.vue'
import AccountForm from '../components/AccountForm.vue'
import SourcePicker from '../components/SourcePicker.vue'

const emit = defineEmits(['changed'])
const accounts = ref([])
const loading = ref(true)
const now = ref(Date.now())
const accountModal = ref(null) // { account } | { account: null }
const pickerFor = ref(null)
const confirming = ref('') // 'acc:1' | 'src:3'
const openRepos = reactive({}) // sourceId -> repos[]
const openSettings = reactive({}) // sourceId -> form

async function load() {
  try {
    accounts.value = await api.accounts()
  } finally {
    loading.value = false
    now.value = Date.now()
  }
}
let timer
onMounted(() => {
  load()
  timer = setInterval(() => !document.hidden && !accountModal.value && !pickerFor.value && load(), 15000)
})
onBeforeUnmount(() => clearInterval(timer))

function onAccountSaved(acc) {
  const isNew = !accountModal.value?.account
  accountModal.value = null
  load()
  emit('changed')
  if (isNew) pickerFor.value = acc
}
function onSourcesSaved() {
  pickerFor.value = null
  load()
  emit('changed')
}

async function removeAccount(a) {
  if (confirming.value !== `acc:${a.id}`) return (confirming.value = `acc:${a.id}`)
  confirming.value = ''
  await api.deleteAccount(a.id)
  toast(`Cuenta "${a.name}" eliminada`, 'info')
  load()
  emit('changed')
}
async function revalidate(a) {
  const res = await api.revalidate(a.id)
  toast(res.status === 'ok' ? 'Credencial válida' : `Sigue con error: ${res.status_detail}`, res.status === 'ok' ? 'info' : 'error')
  load()
}

async function toggleSource(src) {
  await api.updateSource(src.id, { enabled: !src.enabled })
  src.enabled = !src.enabled
  emit('changed')
}
async function removeSource(src) {
  if (confirming.value !== `src:${src.id}`) return (confirming.value = `src:${src.id}`)
  confirming.value = ''
  await api.deleteSource(src.id)
  toast(`${src.slug} quitada`, 'info')
  delete openRepos[src.id]
  load()
  emit('changed')
}
async function syncSource(src) {
  await api.sync(src.id)
  toast(`Sincronizando ${src.slug}…`, 'info')
  setTimeout(load, 4000)
}

async function toggleRepos(src) {
  if (openRepos[src.id]) return delete openRepos[src.id]
  openRepos[src.id] = 'loading'
  openRepos[src.id] = await api.sourceRepos(src.id)
}
async function patchRepo(src, repo, body) {
  const updated = await api.updateRepo(repo.id, body)
  Object.assign(repo, updated)
  emit('changed')
  setTimeout(async () => {
    if (openRepos[src.id]) openRepos[src.id] = await api.sourceRepos(src.id)
    load()
  }, 2500)
}

function toggleSettings(src) {
  if (openSettings[src.id]) return delete openSettings[src.id]
  openSettings[src.id] = { repo_filter: src.repo_filter || '', max_repos: src.max_repos, active_days: src.active_days }
}
async function saveSettings(src) {
  const f = openSettings[src.id]
  await api.updateSource(src.id, {
    repo_filter: f.repo_filter, max_repos: Number(f.max_repos), active_days: Number(f.active_days),
  })
  toast('Guardado. Recalculando qué repos se siguen…', 'info')
  delete openSettings[src.id]
  setTimeout(load, 2500)
}

const KIND = { org: 'Organización', user: 'Usuario', workspace: 'Workspace', account: 'Cuenta' }
function rate(a) {
  if (a.rate_remaining == null) return null
  return a.rate_limit ? `${a.rate_remaining.toLocaleString('es-CL')} / ${a.rate_limit.toLocaleString('es-CL')}` : a.rate_remaining.toLocaleString('es-CL')
}
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div>
        <h1>Cuentas</h1>
        <p>Conecta cuentas de GitHub, Bitbucket y Cloudflare y elige qué organizaciones, workspaces o cuentas seguir. Los tokens se guardan cifrados.</p>
      </div>
      <button class="btn primary" @click="accountModal = { account: null }"><Icon name="plus" /> Agregar cuenta</button>
    </div>

    <div v-if="loading" class="card empty">Cargando…</div>
    <div v-else-if="!accounts.length" class="card empty">
      <h2>Conecta tu primera cuenta</h2>
      <p>Con un token de GitHub o un API token de Bitbucket basta para empezar.</p>
      <button class="btn primary" @click="accountModal = { account: null }"><Icon name="plus" /> Agregar cuenta</button>
    </div>

    <section v-for="a in accounts" :key="a.id" class="card account">
      <header class="acc-head">
        <ProviderIcon :provider="a.provider" :size="22" />
        <div class="grow">
          <h2>{{ a.name }}</h2>
          <div class="acc-sub">
            <img v-if="a.avatar_url" :src="a.avatar_url" alt="" width="16" height="16" />
            <span>{{ a.login }}</span>
            <span class="faint">· {{ PROVIDER_LABEL[a.provider] }}</span>
            <span v-if="rate(a)" class="faint" title="Requests de API disponibles en la ventana actual">· API {{ rate(a) }}</span>
          </div>
        </div>
        <span v-if="a.status === 'ok'" class="badge success">Conectada</span>
        <span v-else class="badge failed" :title="a.status_detail">Error de credencial</span>
        <div class="acc-actions">
          <button v-if="a.status !== 'ok'" class="btn sm" @click="revalidate(a)">Revalidar</button>
          <button class="btn sm" @click="accountModal = { account: a }"><Icon name="key" :size="13" /> Editar</button>
          <button v-if="confirming === `acc:${a.id}`" class="btn sm danger" @click="removeAccount(a)">¿Eliminar? Sí</button>
          <button v-if="confirming === `acc:${a.id}`" class="btn sm" @click="confirming = ''">No</button>
          <button v-else class="btn sm icon ghost" title="Eliminar cuenta" aria-label="Eliminar cuenta" @click="removeAccount(a)"><Icon name="trash" :size="14" /></button>
        </div>
      </header>
      <p v-if="a.status !== 'ok' && a.status_detail" class="acc-error error-text">{{ a.status_detail }}</p>

      <div class="sources">
        <div class="sources-head">
          <h3>{{ { bitbucket: 'Workspaces', cloudflare: 'Cuentas de Cloudflare' }[a.provider] || 'Organizaciones y usuarios' }}</h3>
          <button class="btn sm" @click="pickerFor = a"><Icon name="plus" :size="13" /> Agregar</button>
        </div>
        <p v-if="!a.sources.length" class="muted none">
          Todavía no sigues ninguna. <button class="linkish" @click="pickerFor = a">Elegir {{ { bitbucket: 'workspaces', cloudflare: 'cuentas' }[a.provider] || 'organizaciones' }}</button>
        </p>
        <div v-for="s in a.sources" :key="s.id" class="source" :class="{ off: !s.enabled }">
          <div class="src-row">
            <img v-if="s.avatar_url" :src="s.avatar_url" alt="" width="28" height="28" class="src-av" />
            <span v-else class="src-av ph" aria-hidden="true">{{ s.slug[0] }}</span>
            <div class="grow">
              <div class="src-name"><strong>{{ s.display_name || s.slug }}</strong><span class="chip">{{ KIND[s.kind] }}</span></div>
              <div class="src-meta">
                <span>{{ s.tracked_count }} de {{ s.repo_count }} {{ a.provider === 'cloudflare' ? 'proyectos' : 'repos' }} seguidos</span>
                <span class="faint" :title="fullDate(s.last_synced_at)">· {{ s.last_synced_at ? `sincronizada ${ago(s.last_synced_at, now)}` : 'pendiente' }}</span>
                <span v-if="s.repo_filter" class="faint">· filtro <code>{{ s.repo_filter }}</code></span>
              </div>
              <p v-if="s.last_error" class="error-text src-err">{{ s.last_error }}</p>
            </div>
            <div class="src-actions">
              <button class="btn sm" :aria-expanded="!!openRepos[s.id]" @click="toggleRepos(s)"><Icon name="repo" :size="13" /> Repos</button>
              <button class="btn sm icon" :aria-expanded="!!openSettings[s.id]" title="Configurar" aria-label="Configurar" @click="toggleSettings(s)"><Icon name="gear" :size="14" /></button>
              <button class="btn sm icon" title="Sincronizar ahora" aria-label="Sincronizar ahora" @click="syncSource(s)"><Icon name="refresh" :size="13" /></button>
              <label class="switch" :title="s.enabled ? 'Activa' : 'Pausada'">
                <input type="checkbox" :checked="s.enabled" :aria-label="`Seguir ${s.slug}`" @change="toggleSource(s)" /><span></span>
              </label>
              <button v-if="confirming === `src:${s.id}`" class="btn sm danger" @click="removeSource(s)">¿Quitar?</button>
              <button v-else class="btn sm icon ghost" title="Quitar" aria-label="Quitar" @click="removeSource(s)"><Icon name="trash" :size="14" /></button>
            </div>
          </div>

          <form v-if="openSettings[s.id]" class="settings" @submit.prevent="saveSettings(s)">
            <label class="field filter">Filtro de repos
              <span class="hint">Globs separados por coma. <code>!</code> excluye. Ej: <code>contable-*, !*-legacy</code></span>
              <input v-model="openSettings[s.id].repo_filter" class="input mono" placeholder="(todos)" />
            </label>
            <label class="field">Máx. repos
              <span class="hint">los más activos</span>
              <input v-model="openSettings[s.id].max_repos" class="input" type="number" min="1" max="100" />
            </label>
            <label class="field">Actividad
              <span class="hint">días hacia atrás</span>
              <input v-model="openSettings[s.id].active_days" class="input" type="number" min="1" max="3650" />
            </label>
            <div class="settings-actions">
              <button type="button" class="btn sm" @click="delete openSettings[s.id]">Cancelar</button>
              <button class="btn sm primary">Guardar</button>
            </div>
          </form>

          <div v-if="openRepos[s.id]" class="repos">
            <p v-if="openRepos[s.id] === 'loading'" class="muted">Cargando…</p>
            <p v-else-if="!openRepos[s.id].length" class="muted">Aún no hay repos sincronizados.</p>
            <table v-else>
              <thead><tr><th>Repositorio</th><th>Última actividad</th><th>Estado</th><th><span class="sr-only">Acciones</span></th></tr></thead>
              <tbody>
                <tr v-for="r in openRepos[s.id]" :key="r.id" :class="{ dim: !r.tracked }">
                  <td><a :href="r.html_url" target="_blank" rel="noopener">{{ r.name }}</a>
                    <span v-if="r.last_error" class="error-text" :title="r.last_error"> · error</span></td>
                  <td class="muted" :title="fullDate(r.activity_at)">{{ ago(r.activity_at, now) }}</td>
                  <td>
                    <span v-if="r.muted" class="badge cancelled">Oculto</span>
                    <span v-else-if="r.pinned" class="badge running">Fijado</span>
                    <span v-else-if="r.tracked" class="badge success">Seguido</span>
                    <span v-else class="faint">—</span>
                  </td>
                  <td><div class="repo-actions">
                    <button class="btn sm" :class="{ on: r.pinned }" :aria-pressed="r.pinned" title="Seguir siempre, aunque no tenga actividad" @click="patchRepo(s, r, { pinned: !r.pinned })">
                      {{ r.pinned ? 'Desfijar' : 'Fijar' }}
                    </button>
                    <button class="btn sm ghost" :aria-pressed="r.muted" title="Ocultar sus ejecuciones del panel" @click="patchRepo(s, r, { muted: !r.muted })">
                      {{ r.muted ? 'Mostrar' : 'Ocultar' }}
                    </button>
                  </div></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>

    <AccountForm v-if="accountModal" :account="accountModal.account" @close="accountModal = null" @saved="onAccountSaved" />
    <SourcePicker v-if="pickerFor" :account="pickerFor" @close="pickerFor = null" @saved="onSourcesSaved" />
  </main>
</template>

<style scoped>
.account { margin-bottom: 16px; overflow: hidden; }
.acc-head { display: flex; align-items: center; gap: 12px; padding: 16px 18px; flex-wrap: wrap; }
.acc-sub { display: flex; align-items: center; gap: 5px; font-size: 12.5px; color: var(--text-muted); margin-top: 2px; flex-wrap: wrap; }
.acc-sub img { border-radius: 50%; }
.acc-actions { display: flex; gap: 6px; }
.acc-error { margin: -6px 18px 12px; }
.sources { border-top: 1px solid var(--border); background: var(--surface-2); padding: 12px 18px 16px; }
.sources-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.sources-head h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); }
.none { margin: 0; font-size: 13px; }
.linkish { border: 0; background: none; padding: 0; color: var(--accent); font: inherit; cursor: pointer; }
.linkish:hover { text-decoration: underline; }
.source { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 8px; }
.source.off .src-row { opacity: .7; }
.src-row { display: flex; align-items: center; gap: 12px; padding: 10px 12px; flex-wrap: wrap; }
.src-av { width: 28px; height: 28px; border-radius: 7px; flex: none; }
.ph { display: grid; place-items: center; background: var(--surface-2); color: var(--text-muted); font-weight: 700; text-transform: uppercase; }
.src-name { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
.src-meta { font-size: 12.5px; color: var(--text-muted); display: flex; gap: 4px; flex-wrap: wrap; margin-top: 1px; }
.src-err { margin: 4px 0 0; }
.src-actions { display: flex; align-items: center; gap: 6px; }
.settings { display: grid; grid-template-columns: minmax(0, 1fr) 120px 120px; gap: 12px; padding: 12px; border-top: 1px solid var(--border); align-items: end; }
.settings-actions { grid-column: 1 / -1; display: flex; justify-content: flex-end; gap: 8px; }
.repos { border-top: 1px solid var(--border); padding: 6px 12px 10px; max-height: 420px; overflow: auto; }
.repos table { width: 100%; border-collapse: collapse; font-size: 13px; }
.repos th { text-align: left; font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); font-weight: 600; padding: 6px 8px; }
.repos td { padding: 6px 8px; border-top: 1px solid var(--border); }
.repos tr.dim td:first-child a { color: var(--text-muted); }
.repo-actions { display: flex; gap: 4px; justify-content: flex-end; }
.repo-actions .btn.on { background: var(--accent-soft); }
@media (max-width: 720px) {
  .settings { grid-template-columns: 1fr 1fr; }
  .settings .filter { grid-column: 1 / -1; }
  .src-actions { width: 100%; justify-content: flex-end; }
}
</style>
