<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { ago, bytes, fullDate, uptimeText } from '../format'
import Meter from '../components/Meter.vue'
import ServerForm from '../components/ServerForm.vue'
import Icon from '../components/Icon.vue'

const router = useRouter()
const servers = ref(null)
const adding = ref(false)
const now = ref(Date.now())

async function load() {
  try { servers.value = await api.servers({ quiet: true }) } catch { servers.value = servers.value || [] }
  now.value = Date.now()
}
let timer
onMounted(() => {
  load()
  timer = setInterval(() => !document.hidden && !adding.value && load(), 20000)
})
onBeforeUnmount(() => clearInterval(timer))

function counts(s) {
  const c = { ok: 0, warn: 0, down: 0, unknown: 0 }
  for (const v of s.services) c[v.status] = (c[v.status] || 0) + 1
  return c
}
const totals = computed(() => {
  const t = { servers: 0, down: 0, services: 0, bad: 0 }
  for (const s of servers.value || []) {
    t.servers++
    if (s.status === 'error') t.down++
    for (const v of s.services) { t.services++; if (v.status === 'down' || v.status === 'warn') t.bad++ }
  }
  return t
})
function onSaved(s) {
  adding.value = false
  router.push(`/servidores/${s.id}`)
}
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div>
        <h1>Servidores</h1>
        <p>Monitoreo por SSH, sin instalar nada: recursos, puertos, actualizaciones y los servicios de cada plataforma con sus logs.</p>
      </div>
      <button class="btn primary" @click="adding = true"><Icon name="plus" /> Agregar servidor</button>
    </div>

    <p v-if="servers === null" class="card pad muted">Cargando…</p>
    <div v-else-if="!servers.length" class="card empty">
      <h2>Agrega tu primer servidor</h2>
      <p>Puedes importarlo desde tu <code>~/.ssh/config</code> y usar tus llaves locales.</p>
      <button class="btn primary" @click="adding = true"><Icon name="plus" /> Agregar servidor</button>
    </div>

    <template v-else>
      <p class="summary muted">
        {{ totals.servers }} servidores<template v-if="totals.down"> · <span class="bad">{{ totals.down }} sin conexión</span></template>
        · {{ totals.services }} servicios<template v-if="totals.bad"> · <span class="bad">{{ totals.bad }} con problemas</span></template>
      </p>
      <div class="grid">
        <RouterLink v-for="s in servers" :key="s.id" :to="`/servidores/${s.id}`" class="card srv" :class="`st-${s.status}`">
          <header>
            <span class="dot" :class="s.status" aria-hidden="true"></span>
            <div class="grow">
              <h2 class="truncate">{{ s.name }}</h2>
              <p class="faint small truncate">{{ s.username }}@{{ s.host }}<template v-if="s.environment"> · {{ s.environment }}</template></p>
            </div>
            <span v-if="s.status === 'error'" class="badge failed">Sin conexión</span>
          </header>
          <p v-if="s.status === 'error'" class="error-text small">{{ s.last_error }}</p>
          <template v-else-if="s.sample">
            <div class="m"><span>CPU</span><Meter :value="s.sample.cpu_pct" :max="100" label="CPU" /><strong>{{ s.sample.cpu_pct ?? '—' }}%</strong></div>
            <div class="m"><span>Memoria</span><Meter :value="s.sample.mem_used" :max="s.sample.mem_total" label="Memoria" /><strong>{{ bytes(s.sample.mem_used) }}</strong></div>
            <div class="m"><span>Disco</span><Meter :value="s.sample.disk_used" :max="s.sample.disk_total" :warn="0.8" :crit="0.9" label="Disco" /><strong>{{ bytes(s.sample.disk_used, 0) }}</strong></div>
          </template>
          <footer>
            <span class="svc" :title="`${counts(s).ok} ok, ${counts(s).warn} alerta, ${counts(s).down} caídos`">
              <span class="ok">● {{ counts(s).ok }}</span>
              <span v-if="counts(s).warn" class="warn">● {{ counts(s).warn }}</span>
              <span v-if="counts(s).down" class="bad">● {{ counts(s).down }}</span>
              servicios
            </span>
            <span v-if="s.flags.reboot_required" class="chip">reinicio pendiente</span>
            <span v-if="s.flags.updates" class="chip">{{ s.flags.updates }} actualizaciones</span>
            <span class="faint small up" :title="fullDate(s.last_seen_at)">{{ s.sample ? `encendido ${uptimeText(s.sample.uptime_s)}` : '' }}</span>
          </footer>
        </RouterLink>
      </div>
    </template>

    <ServerForm v-if="adding" @close="adding = false" @saved="onSaved" />
  </main>
</template>

<style scoped>
.pad { padding: 14px 16px; }
.summary { margin: -6px 0 12px; font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
.srv { display: grid; gap: 10px; padding: 14px 16px; color: var(--text); align-content: start; }
.srv:hover { border-color: var(--border-strong); text-decoration: none; }
.srv header { display: flex; align-items: center; gap: 10px; min-width: 0; }
.srv h2 { font-size: 15px; }
.small { font-size: 12px; margin: 0; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--st-queued); flex: none; }
.dot.ok { background: var(--st-success); }
.dot.error { background: var(--st-failed); }
.m { display: grid; grid-template-columns: 70px 1fr 80px; align-items: center; gap: 10px; font-size: 12.5px; color: var(--text-muted); }
.m strong { color: var(--text); text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
.srv footer { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12.5px; }
.svc { display: inline-flex; gap: 6px; color: var(--text-muted); }
.ok { color: var(--st-success); font-weight: 600; }
.warn { color: var(--st-waiting); font-weight: 600; }
.bad { color: var(--st-failed); font-weight: 600; }
.up { margin-left: auto; white-space: nowrap; }
@media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }
</style>
