<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, toast, toasts } from './api'
import { ago } from './format'
import Icon from './components/Icon.vue'

const THEMES = ['system', 'light', 'dark']
const theme = ref('system')
try { theme.value = localStorage.getItem('hub-theme') || 'system' } catch {}

function applyTheme() {
  const el = document.documentElement
  if (theme.value === 'system') delete el.dataset.theme
  else el.dataset.theme = theme.value
  try { localStorage.setItem('hub-theme', theme.value) } catch {}
}
function cycleTheme() {
  theme.value = THEMES[(THEMES.indexOf(theme.value) + 1) % THEMES.length]
  applyTheme()
}
const themeLabel = computed(() => ({ system: 'Tema del sistema', light: 'Tema claro', dark: 'Tema oscuro' })[theme.value])
const themeIcon = computed(() => ({ system: 'system', light: 'sun', dark: 'moon' })[theme.value])

const overview = ref(null)
const now = ref(Date.now())
let timer
async function loadOverview() {
  try { overview.value = await api.overview({ quiet: true }) } catch { overview.value = null }
  now.value = Date.now()
}
const syncing = ref(false)
async function syncNow() {
  syncing.value = true
  try {
    await api.sync()
    toast('Sincronizando todas las fuentes…', 'info')
    setTimeout(loadOverview, 3000)
  } finally {
    setTimeout(() => (syncing.value = false), 1500)
  }
}
const syncState = computed(() => {
  const o = overview.value
  if (!o) return { cls: 'bad', text: 'Sin conexión' }
  if (o.syncer.last_error) return { cls: 'bad', text: 'Error del poller' }
  const t = o.syncer.last_tick_at
  if (!t || now.value - new Date(t).getTime() > 60000) return { cls: 'warn', text: 'Poller detenido' }
  return { cls: 'ok', text: `Al día · ${ago(t, now.value)}` }
})

onMounted(() => {
  applyTheme()
  loadOverview()
  timer = setInterval(loadOverview, 10000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <header class="topbar">
    <div class="topbar-inner">
      <RouterLink to="/" class="brand">
        <img src="/favicon.svg" alt="" width="22" height="22" />
        <span>Pipelines Hub</span>
      </RouterLink>
      <nav class="nav" aria-label="Principal">
        <RouterLink to="/" :class="{ active: $route.name === 'runs' || $route.name === 'run' }">
          Ejecuciones
          <span v-if="overview?.active" class="count">{{ overview.active }}</span>
        </RouterLink>
        <RouterLink to="/prs" :class="{ active: $route.name === 'prs' || $route.name === 'pr' }" title="Pull requests">
          <span class="lbl-long">Pull requests</span><span class="lbl-short">PRs</span>
          <span v-if="overview?.prs?.review" class="count review" :title="`${overview.prs.review} por revisar`">{{ overview.prs.review }}</span>
        </RouterLink>
        <RouterLink to="/entornos" active-class="active">Entornos</RouterLink>
        <RouterLink to="/cuentas" active-class="active">Cuentas</RouterLink>
      </nav>
      <div class="topbar-right">
        <span class="sync-state" :class="syncState.cls" :title="overview?.syncer.last_error || ''">
          <span class="dot" aria-hidden="true"></span>{{ syncState.text }}
        </span>
        <button class="btn sm" :disabled="syncing" @click="syncNow" title="Forzar sincronización de todo">
          <Icon name="refresh" :class="{ spin: syncing }" /> <span class="hide-sm">Sincronizar</span>
        </button>
        <button class="btn icon ghost" :title="themeLabel" :aria-label="themeLabel" @click="cycleTheme">
          <Icon :name="themeIcon" />
        </button>
      </div>
    </div>
  </header>

  <RouterView v-slot="{ Component, route }">
    <component :is="Component" :key="route.name === 'run' || route.name === 'pr' ? `${route.name}${route.params.id}` : route.name" @changed="loadOverview" />
  </RouterView>

  <div class="toasts" aria-live="polite">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind">{{ t.message }}</div>
  </div>
</template>

<style scoped>
.topbar {
  position: sticky; top: 0; z-index: 20;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.topbar-inner {
  max-width: 1280px; margin: 0 auto; padding: 0 24px;
  height: 54px; display: flex; align-items: center; gap: 24px;
}
.brand { display: flex; align-items: center; gap: 9px; color: var(--text); font-weight: 700; font-size: 15px; }
.brand:hover { text-decoration: none; }
.nav { display: flex; gap: 4px; height: 100%; }
.nav a {
  display: flex; align-items: center; gap: 6px; padding: 0 12px;
  color: var(--text-muted); font-weight: 550; border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.nav a:hover { color: var(--text); text-decoration: none; }
.nav a.active { color: var(--text); border-bottom-color: var(--accent); }
.count {
  min-width: 18px; height: 18px; padding: 0 5px; border-radius: 99px;
  background: var(--st-running-soft); color: var(--st-running);
  font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center;
}
.count.review { background: var(--st-waiting-soft); color: var(--st-waiting); }
.lbl-short { display: none; }
.topbar-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.sync-state { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.sync-state .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--st-queued); }
.sync-state.ok .dot { background: var(--st-success); }
.sync-state.warn .dot { background: var(--st-waiting); }
.sync-state.bad .dot { background: var(--st-failed); }
.toasts { position: fixed; right: 16px; bottom: 16px; display: grid; gap: 8px; z-index: 100; max-width: min(420px, calc(100vw - 32px)); }
.toast {
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-left: 4px solid var(--st-running); border-radius: var(--radius-sm);
  padding: 10px 14px; box-shadow: var(--shadow-lg); font-size: 13px;
}
.toast.error { border-left-color: var(--st-failed); }
@media (max-width: 820px) {
  .sync-state, .hide-sm { display: none; }
  .topbar-inner { gap: 12px; padding: 0 16px; }
  .brand span { display: none; }
}
@media (max-width: 480px) {
  .topbar-inner { gap: 4px; padding: 0 10px; }
  .brand { display: none; }
  .nav a { padding: 0 7px; font-size: 13px; }
  .nav .count { display: none; }
}
@media (max-width: 960px) {
  .lbl-long { display: none; }
  .lbl-short { display: inline; }
}
</style>
