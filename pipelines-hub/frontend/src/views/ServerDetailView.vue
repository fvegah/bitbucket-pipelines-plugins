<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, toast } from '../api'
import { ago, bytes, fullDate, uptimeText } from '../format'
import Sparkline from '../components/Sparkline.vue'
import Meter from '../components/Meter.vue'
import UptimeBar from '../components/UptimeBar.vue'
import LogViewer from '../components/LogViewer.vue'
import ServerForm from '../components/ServerForm.vue'
import ServiceForm from '../components/ServiceForm.vue'
import Icon from '../components/Icon.vue'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()

const srv = ref(null)
const samples = ref([])
const hours = ref(24)
const history = ref({})
const tab = ref('services')
const busy = ref('')
const editing = ref(false)
const serviceForm = ref(null) // { service } | { preset }
const suggestions = ref(null)
const logFor = ref(null)
const logOpts = ref({ lines: 500, grep: '', follow: false })
const confirm = ref('')
const now = ref(Date.now())

const snap = computed(() => srv.value?.snapshot)
const s = computed(() => srv.value?.sample)
const platforms = computed(() => [...new Set((srv.value?.services || []).map((v) => v.platform).filter(Boolean))])
const groups = computed(() => {
  const g = {}
  for (const v of srv.value?.services || []) (g[v.platform || 'Sin plataforma'] ||= []).push(v)
  return Object.entries(g).sort(([a], [b]) => (a === 'Sin plataforma') - (b === 'Sin plataforma') || a.localeCompare(b))
})

async function load() {
  try {
    srv.value = await api.server(props.id, { quiet: true })
    const [sm, ...hs] = await Promise.all([
      api.serverSamples(props.id, hours.value, { quiet: true }),
      ...srv.value.services.map((v) => api.serviceHistory(v.id, { quiet: true })),
    ])
    samples.value = sm
    history.value = Object.fromEntries(srv.value.services.map((v, i) => [v.id, hs[i]]))
  } catch (e) {
    if (!srv.value) toast(e.message)
  }
  now.value = Date.now()
}
watch(hours, load)
let timer
onMounted(async () => {
  await load()
  if (srv.value && !srv.value.snapshot) refreshSnapshot()
  timer = setInterval(() => !document.hidden && !serviceForm.value && !editing.value && load(), 30000)
})
onBeforeUnmount(() => clearInterval(timer))

async function refreshSnapshot() {
  busy.value = 'snap'
  try {
    await api.serverSnapshot(props.id)
    await load()
  } catch { /* toast */ } finally { busy.value = '' }
}
async function pollNow() {
  busy.value = 'poll'
  try { srv.value = await api.pollServer(props.id); await load() } catch { /* */ } finally { busy.value = '' }
}
async function detect() {
  busy.value = 'detect'
  try { suggestions.value = await api.serverSuggestions(props.id) } catch { /* */ } finally { busy.value = '' }
}
async function checkNow(v) {
  busy.value = `chk${v.id}`
  try { Object.assign(v, await api.checkService(v.id)) } catch { /* */ } finally { busy.value = '' }
}
async function removeService(v) {
  if (confirm.value !== `svc${v.id}`) return (confirm.value = `svc${v.id}`)
  confirm.value = ''
  await api.deleteService(v.id)
  if (logFor.value?.id === v.id) logFor.value = null
  load()
}
async function removeServer() {
  if (confirm.value !== 'server') return (confirm.value = 'server')
  await api.deleteServer(props.id)
  toast('Servidor eliminado', 'info')
  router.push('/servidores')
}
function onServiceSaved() {
  serviceForm.value = null
  if (suggestions.value) detect()
  load()
}
function openLog(v) {
  logFor.value = v
  logOpts.value = { lines: 500, grep: '', follow: false }
}
const logLoader = async (cursor) => api.serviceLog(logFor.value.id, {
  lines: logOpts.value.lines, grep: logOpts.value.grep || undefined, cursor: cursor || undefined,
}, { quiet: true })
const logKey = computed(() => logFor.value ? `${logFor.value.id}/${logOpts.value.lines}/${logOpts.value.grep}` : '')
const grepDraft = ref('')

const series = (key, fn = (x) => x) => samples.value.map((x) => ({ ts: x.ts, value: x[key] == null ? null : fn(x[key], x) }))
const memPct = (v, x) => (x.mem_total ? (v / x.mem_total) * 100 : null)
const diskPct = (v, x) => (x.disk_total ? (v / x.disk_total) * 100 : null)
const pct = (a, b) => (a != null && b ? `${Math.round((a / b) * 100)}%` : '—')
const KIND = { systemd: 'systemd', docker: 'docker', redis: 'Redis', postgres: 'Postgres', sidekiq: 'Sidekiq', rabbitmq: 'RabbitMQ', http: 'HTTP', tcp: 'TCP', process: 'proceso', log: 'log' }
const ST = { ok: 'OK', warn: 'Alerta', down: 'Caído', unknown: 'Sin dato' }
const EXPO = { all: 'todas las interfaces', public: 'IP pública', private: 'red privada', tailscale: 'Tailscale', local: 'solo local' }
const logSourceText = (l) => ({ journal: `journalctl -u ${l.unit}`, file: l.path, docker: `docker logs ${l.container}` }[l.type] || '')
</script>

<template>
  <main class="page wide">
    <RouterLink to="/servidores" class="back"><Icon name="chevron" :size="13" style="transform: rotate(180deg)" /> Servidores</RouterLink>
    <p v-if="!srv" class="card pad muted">Cargando…</p>

    <template v-else>
      <section class="card head">
        <div class="head-top">
          <span class="dot" :class="srv.status" aria-hidden="true"></span>
          <div class="grow">
            <h1>{{ srv.name }} <span v-if="srv.environment" class="chip">{{ srv.environment }}</span></h1>
            <p class="muted sub">
              {{ srv.username }}@{{ srv.host }}:{{ srv.port }}
              <template v-if="snap"> · {{ snap.os }} · kernel {{ snap.kernel }}</template>
              <template v-if="s"> · encendido hace {{ uptimeText(s.uptime_s) }}</template>
            </p>
          </div>
          <div class="acts">
            <button class="btn sm" :disabled="!!busy" @click="pollNow"><Icon name="refresh" :size="13" :class="{ spin: busy === 'poll' }" /> Medir ahora</button>
            <button class="btn sm" @click="editing = true"><Icon name="key" :size="13" /> Editar</button>
            <button v-if="confirm === 'server'" class="btn sm danger" @click="removeServer">¿Eliminar? Sí</button>
            <button v-else class="btn sm icon ghost" aria-label="Eliminar servidor" title="Eliminar servidor" @click="removeServer"><Icon name="trash" :size="14" /></button>
          </div>
        </div>
        <p v-if="srv.status === 'error'" class="error-text">{{ srv.last_error }}</p>
        <div class="flags">
          <span v-if="snap?.reboot_required" class="badge waiting">Reinicio pendiente</span>
          <span v-if="snap?.updates" class="badge waiting">{{ snap.updates }} actualizaciones<template v-if="snap.security_updates"> ({{ snap.security_updates }} de seguridad)</template></span>
          <span v-if="snap?.ssh_failed_24h" class="badge" :class="snap.ssh_failed_24h > 100 ? 'failed' : 'queued'">{{ snap.ssh_failed_24h }} intentos SSH fallidos en 24 h</span>
          <span v-if="snap" class="badge" :class="snap.ufw?.active ? 'success' : 'failed'">ufw {{ snap.ufw?.active ? 'activo' : 'inactivo o sin permiso' }}</span>
          <span v-if="snap?.failed_units?.length" class="badge failed">{{ snap.failed_units.length }} unidades fallidas</span>
          <span v-if="snap?.tailscale_ip" class="badge queued">Tailscale {{ snap.tailscale_ip }}</span>
          <span v-if="snap && !snap.sudo" class="badge queued">sin sudo: algunas lecturas quedan limitadas</span>
          <span class="faint small">huella <code>{{ srv.host_key }}</code> · foto del sistema {{ srv.snapshot_at ? ago(srv.snapshot_at, now) : 'pendiente' }}</span>
          <button class="linkish small" :disabled="busy === 'snap'" @click="refreshSnapshot">{{ busy === 'snap' ? 'actualizando…' : 'actualizar' }}</button>
        </div>
      </section>

      <section class="metrics">
        <div class="card tile">
          <div class="t-head"><span>CPU</span><strong>{{ s?.cpu_pct ?? '—' }}%</strong></div>
          <Sparkline :points="series('cpu_pct')" :max="100" :format="(v) => `${v.toFixed(1)}%`" label="CPU" />
        </div>
        <div class="card tile">
          <div class="t-head"><span>Carga (1 min)</span><strong>{{ s?.load1 ?? '—' }}<span class="faint"> / {{ s?.cores }} núcleos</span></strong></div>
          <Sparkline :points="series('load1')" :format="(v) => v.toFixed(2)" label="Carga" />
        </div>
        <div class="card tile">
          <div class="t-head"><span>Memoria</span><strong>{{ bytes(s?.mem_used) }} <span class="faint">/ {{ bytes(s?.mem_total) }}</span></strong></div>
          <Sparkline :points="series('mem_used', memPct)" :max="100" :format="(v) => `${v.toFixed(0)}%`" label="Memoria" />
          <div class="swap faint small">swap {{ bytes(s?.swap_used) }} / {{ bytes(s?.swap_total) }}</div>
        </div>
        <div class="card tile">
          <div class="t-head"><span>Disco /</span><strong>{{ pct(s?.disk_used, s?.disk_total) }} <span class="faint">· {{ bytes((s?.disk_total || 0) - (s?.disk_used || 0), 0) }} libres</span></strong></div>
          <Sparkline :points="series('disk_used', diskPct)" :max="100" :format="(v) => `${v.toFixed(1)}%`" label="Disco" />
        </div>
      </section>
      <div class="range">
        <div class="segmented" role="group" aria-label="Rango">
          <button v-for="h in [6, 24, 72, 168]" :key="h" :aria-pressed="hours === h" @click="hours = h">{{ h < 48 ? `${h} h` : `${h / 24} días` }}</button>
        </div>
        <span class="faint small">{{ samples.length }} muestras · cada minuto</span>
      </div>

      <nav class="tabs">
        <button v-for="[k, l, n] in [['services', 'Servicios', srv.services.length], ['ports', 'Puertos', snap?.ports?.length], ['procs', 'Procesos'], ['disks', 'Discos'], ['containers', 'Contenedores', snap?.containers?.length], ['system', 'Sistema']]"
                :key="k" :class="{ active: tab === k }" @click="tab = k">{{ l }}<span v-if="n" class="n">{{ n }}</span></button>
      </nav>

      <template v-if="tab === 'services'">
        <div class="svc-bar">
          <button class="btn sm primary" @click="serviceForm = { }"><Icon name="plus" :size="13" /> Agregar servicio</button>
          <button class="btn sm" :disabled="busy === 'detect'" @click="detect">{{ busy === 'detect' ? 'Buscando…' : 'Detectar servicios' }}</button>
        </div>
        <section v-if="suggestions" class="card sugg">
          <header><h3>Detectados en el servidor</h3><button class="btn icon sm ghost" aria-label="Cerrar" @click="suggestions = null"><Icon name="plus" :size="13" style="transform: rotate(45deg)" /></button></header>
          <p v-if="!suggestions.length" class="muted small">No hay servicios nuevos: todo lo que corre ya está agregado.</p>
          <ul>
            <li v-for="x in suggestions" :key="x.kind + x.name">
              <span class="chip">{{ KIND[x.kind] }}</span><strong class="grow">{{ x.name }}</strong>
              <span class="faint small">{{ x.log?.type !== 'none' ? logSourceText(x.log) : '' }}</span>
              <button class="btn sm" @click="serviceForm = { preset: x }">Agregar…</button>
            </li>
          </ul>
        </section>

        <p v-if="!srv.services.length && !suggestions" class="card pad muted">Sin servicios todavía. Usa "Detectar servicios" para ver lo que corre en el servidor.</p>
        <section v-for="[platform, items] in groups" :key="platform" class="card group">
          <h3 class="g-title">{{ platform }} <span class="faint">{{ items.length }}</span></h3>
          <div v-for="v in items" :key="v.id" class="svc" :class="v.status">
            <div class="svc-main">
              <span class="st" :class="v.status">{{ ST[v.status] }}</span>
              <div class="grow">
                <div class="svc-name"><strong>{{ v.name }}</strong> <span class="chip">{{ KIND[v.kind] }}</span></div>
                <div class="svc-sum small" :title="v.summary">{{ v.summary || '—' }}</div>
                <div v-if="v.kind === 'sidekiq' && v.detail?.queues" class="small faint">colas: {{ Object.entries(v.detail.queues).map(([q, n]) => `${q} ${n}`).join(' · ') || 'vacías' }}</div>
                <div v-if="v.kind === 'rabbitmq' && v.detail?.stuck?.length" class="small bad">sin consumidor: {{ v.detail.stuck.map((q) => `${q.name} (${q.messages})`).join(', ') }}</div>
                <div v-if="v.kind === 'postgres' && v.detail?.databases" class="small faint">{{ v.detail.databases.map((d) => `${d.db} ${bytes(d.size)}`).join(' · ') }}</div>
                <div v-if="v.kind === 'systemd' && v.detail?.memory" class="small faint">memoria {{ bytes(v.detail.memory) }} · {{ v.detail.restarts }} reinicios</div>
              </div>
              <div class="svc-acts">
                <button v-if="v.log?.type && v.log.type !== 'none'" class="btn sm" @click="openLog(v)">Ver log</button>
                <button class="btn sm icon ghost" :title="`Chequear ahora`" :aria-label="`Chequear ${v.name}`" :disabled="busy === `chk${v.id}`" @click="checkNow(v)"><Icon name="refresh" :size="13" :class="{ spin: busy === `chk${v.id}` }" /></button>
                <button class="btn sm icon ghost" :aria-label="`Editar ${v.name}`" title="Editar" @click="serviceForm = { service: v }"><Icon name="gear" :size="13" /></button>
                <button v-if="confirm === `svc${v.id}`" class="btn sm danger" @click="removeService(v)">¿Quitar?</button>
                <button v-else class="btn sm icon ghost" :aria-label="`Quitar ${v.name}`" title="Quitar" @click="removeService(v)"><Icon name="trash" :size="13" /></button>
              </div>
            </div>
            <div class="svc-hist">
              <UptimeBar :checks="history[v.id] || []" />
              <span class="faint small" :title="fullDate(v.checked_at)">{{ v.checked_at ? ago(v.checked_at, now) : '' }}</span>
            </div>
          </div>
        </section>
      </template>

      <section v-else-if="tab === 'ports'" class="card tbl-wrap">
        <p v-if="!snap" class="pad muted">Falta la foto del sistema.</p>
        <table v-else class="tbl">
          <caption v-if="snap.exposure_checked_from" class="cap faint small">"Desde internet" se verificó conectando desde otro servidor ({{ snap.exposure_checked_from }}), así que considera también firewalls del proveedor.</caption>
          <thead><tr><th>Puerto</th><th>Proceso</th><th>Escucha en</th><th>Desde internet</th></tr></thead>
          <tbody>
            <tr v-for="(p, i) in snap.ports" :key="i">
              <td class="mono">{{ p.port }}/{{ p.proto }}</td>
              <td>{{ p.process || '—' }}</td>
              <td class="small">{{ EXPO[p.exposure] }} <span class="faint mono">{{ p.address }}</span></td>
              <td>
                <span v-if="p.internet" class="badge waiting">{{ p.verified === 'open' ? 'Abierto (verificado)' : 'Abierto' }}</span>
                <span v-else-if="p.verified === 'filtered'" class="faint small">no: lo corta un firewall externo</span>
                <span v-else class="faint small">{{ p.exposure === 'all' || p.exposure === 'public' ? 'filtrado por ufw' : 'no' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-else-if="tab === 'procs'" class="card tbl-wrap">
        <table v-if="snap" class="tbl">
          <thead><tr><th>PID</th><th>Usuario</th><th>Comando</th><th class="r">CPU</th><th class="r">Memoria</th><th class="r">Tiempo</th></tr></thead>
          <tbody>
            <tr v-for="p in snap.processes" :key="p.pid">
              <td class="mono small">{{ p.pid }}</td><td class="small">{{ p.user }}</td><td class="mono small">{{ p.command }}</td>
              <td class="r">{{ p.cpu }}%</td><td class="r">{{ bytes(p.rss) }}</td><td class="r faint">{{ uptimeText(p.elapsed_s) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="pad faint small">Los 15 que más memoria usan, según la última foto del sistema.</p>
      </section>

      <section v-else-if="tab === 'disks'" class="card tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Montaje</th><th>Dispositivo</th><th class="w">Uso</th><th class="r">Usado</th><th class="r">Total</th></tr></thead>
          <tbody>
            <tr v-for="d in s?.disks || []" :key="d.mount">
              <td class="mono">{{ d.mount }}</td><td class="mono small faint">{{ d.fs }}</td>
              <td><Meter :value="d.used" :max="d.total" :warn="0.8" :crit="0.9" :label="`Disco ${d.mount}`" /></td>
              <td class="r">{{ bytes(d.used) }} <span class="faint">({{ pct(d.used, d.total) }})</span></td><td class="r">{{ bytes(d.total) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-else-if="tab === 'containers'" class="card tbl-wrap">
        <p v-if="!snap?.containers?.length" class="pad muted">Sin contenedores (o Docker no está instalado).</p>
        <table v-else class="tbl">
          <thead><tr><th>Contenedor</th><th>Imagen</th><th>Estado</th><th>Puertos</th></tr></thead>
          <tbody>
            <tr v-for="c in snap.containers" :key="c.name">
              <td>{{ c.name }}</td><td class="mono small">{{ c.image }}</td>
              <td><span class="badge" :class="c.state === 'running' ? 'success' : 'failed'">{{ c.status }}</span></td><td class="mono small">{{ c.ports }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-else-if="tab === 'system'" class="card pad sys">
        <template v-if="snap">
          <dl class="facts">
            <div><dt>Sistema</dt><dd>{{ snap.os }} ({{ snap.os_id }} {{ snap.os_version }})</dd></div>
            <div><dt>Kernel</dt><dd class="mono">{{ snap.kernel }}</dd></div>
            <div><dt>Hostname</dt><dd class="mono">{{ snap.hostname }}</dd></div>
            <div><dt>Sesiones abiertas</dt><dd>{{ snap.sessions.length }}</dd></div>
          </dl>
          <h3>Unidades fallidas</h3>
          <p v-if="!snap.failed_units.length" class="muted small">Ninguna.</p>
          <ul v-else class="mono small"><li v-for="u in snap.failed_units" :key="u">{{ u }}</li></ul>
          <h3>Firewall (ufw)</h3>
          <pre class="pre">{{ snap.ufw?.rules || 'Sin datos (ufw no instalado o sin sudo).' }}</pre>
        </template>
      </section>
    </template>

    <div v-if="logFor" class="backdrop" @click.self="logFor = null">
      <aside class="panel" role="dialog" :aria-label="`Log de ${logFor.name}`">
        <header class="p-head">
          <div class="grow"><h2>{{ logFor.name }}</h2><p class="muted small mono">{{ logSourceText(logFor.log) }}</p></div>
          <button class="btn icon ghost" aria-label="Cerrar" @click="logFor = null"><Icon name="plus" style="transform: rotate(45deg)" /></button>
        </header>
        <div class="log-opts">
          <label class="field inline">Líneas
            <select v-model.number="logOpts.lines" class="select"><option :value="200">200</option><option :value="500">500</option><option :value="2000">2.000</option><option :value="5000">5.000</option></select>
          </label>
          <form class="field inline grepf" @submit.prevent="logOpts.grep = grepDraft.trim()">
            <span>Filtrar en el servidor</span>
            <span class="row"><input v-model="grepDraft" class="input" placeholder="ERROR, timeout, un RUT…" /><button class="btn sm">Buscar</button>
              <button v-if="logOpts.grep" type="button" class="btn sm ghost" @click="grepDraft = ''; logOpts.grep = ''">Limpiar</button></span>
          </form>
          <label class="check"><input v-model="logOpts.follow" type="checkbox" /> Seguir en vivo</label>
        </div>
        <LogViewer class="plog" :loader="logLoader" :loader-key="logKey" :live="logOpts.follow" :title="logFor.name"
                   :subtitle="logOpts.grep ? `filtrado: ${logOpts.grep}` : `últimas ${logOpts.lines} líneas`" :file-name="logFor.name" :interval="5000" />
      </aside>
    </div>

    <ServerForm v-if="editing" :server="srv" @close="editing = false" @saved="editing = false; load()" />
    <ServiceForm v-if="serviceForm" :server-id="Number(id)" :service="serviceForm.service" :preset="serviceForm.preset"
                 :platforms="platforms" @close="serviceForm = null" @saved="onServiceSaved" />
  </main>
</template>

<style scoped>
.wide { max-width: 1360px; }
.back { display: inline-flex; align-items: center; gap: 4px; color: var(--text-muted); font-size: 13px; font-weight: 550; margin-bottom: 12px; }
.back:hover { color: var(--text); }
.pad { padding: 14px 16px; margin: 0; }
.small { font-size: 12px; }
.mono { font-family: var(--mono); }
.head { padding: 16px 20px; margin-bottom: 14px; }
.head-top { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.head h1 { font-size: 19px; display: flex; align-items: center; gap: 8px; }
.sub { margin: 4px 0 0; font-size: 13px; }
.acts { display: flex; gap: 6px; }
.dot { width: 12px; height: 12px; border-radius: 50%; background: var(--st-queued); margin-top: 6px; flex: none; }
.dot.ok { background: var(--st-success); }
.dot.error { background: var(--st-failed); }
.flags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 12px; }
.flags code { font-size: 11px; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.tile { padding: 12px 14px 10px; display: grid; gap: 8px; }
.t-head { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; color: var(--text-muted); }
.t-head strong { color: var(--text); font-variant-numeric: tabular-nums; }
.swap { margin-top: -4px; }
.range { display: flex; align-items: center; gap: 12px; margin: 10px 0 16px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 12px; overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; padding: 8px 11px; margin-bottom: -1px; border: 0; border-bottom: 2px solid transparent; background: none; color: var(--text-muted); font: inherit; font-weight: 600; cursor: pointer; white-space: nowrap; }
.tabs button:hover { color: var(--text); }
.tabs button.active { color: var(--text); border-bottom-color: var(--accent); }
.n { min-width: 18px; height: 18px; padding: 0 5px; border-radius: 99px; background: var(--surface-2); border: 1px solid var(--border); font-size: 11px; display: inline-flex; align-items: center; justify-content: center; }
.svc-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.sugg { padding: 12px 16px; margin-bottom: 12px; }
.sugg header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.sugg h3 { font-size: 13px; }
.sugg ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.sugg li { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-top: 1px solid var(--border); font-size: 13px; }
.group { margin-bottom: 12px; overflow: hidden; }
.g-title { padding: 10px 16px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); border-bottom: 1px solid var(--border); background: var(--surface-2); }
.svc { padding: 12px 16px; border-bottom: 1px solid var(--border); display: grid; gap: 8px; }
.svc:last-child { border-bottom: 0; }
.svc-main { display: flex; gap: 12px; align-items: flex-start; }
.st { flex: none; min-width: 64px; text-align: center; padding: 3px 8px; border-radius: 99px; font-size: 12px; font-weight: 700; background: var(--st-neutral-soft); color: var(--st-queued); }
.st.ok { background: var(--st-success-soft); color: var(--st-success); }
.st.warn { background: var(--st-waiting-soft); color: var(--st-waiting); }
.st.down { background: var(--st-failed-soft); color: var(--st-failed); }
.svc-name { display: flex; align-items: center; gap: 8px; }
.svc-sum { color: var(--text-muted); margin-top: 2px; overflow-wrap: anywhere; }
.svc-acts { display: flex; gap: 4px; align-items: center; }
.svc-hist { display: grid; grid-template-columns: minmax(0, 1fr) 110px; align-items: center; gap: 10px; padding-left: 76px; }
.svc-hist > span { text-align: right; }
.bad { color: var(--st-failed); font-weight: 600; }
.tbl-wrap { overflow-x: auto; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th { text-align: left; font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); font-weight: 600; padding: 8px 12px; border-bottom: 1px solid var(--border); }
.tbl td { padding: 7px 12px; border-bottom: 1px solid var(--border); }
.tbl tr:last-child td { border-bottom: 0; }
.r { text-align: right; font-variant-numeric: tabular-nums; }
.cap { caption-side: bottom; text-align: left; padding: 8px 12px; }
.w { width: 200px; }
.sys h3 { font-size: 13px; margin: 16px 0 6px; }
.facts { display: flex; flex-wrap: wrap; gap: 10px 28px; margin: 0; }
.facts div { display: grid; gap: 2px; }
.facts dt { font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); font-weight: 600; }
.facts dd { margin: 0; font-size: 13px; }
.pre { margin: 0; padding: 10px 12px; background: var(--log-bg); color: var(--log-text); border: 1px solid var(--border); border-radius: var(--radius-sm); font: 12px/1.5 var(--mono); overflow: auto; }
.linkish { border: 0; background: none; padding: 0; color: var(--accent); font: inherit; cursor: pointer; }
.linkish:hover { text-decoration: underline; }
.backdrop { position: fixed; inset: 0; z-index: 50; background: rgb(8 10 14 / 45%); display: flex; justify-content: flex-end; }
.panel { width: min(1000px, 100vw); height: 100%; background: var(--bg); border-left: 1px solid var(--border); display: flex; flex-direction: column; box-shadow: var(--shadow-lg); }
.p-head { display: flex; gap: 12px; align-items: flex-start; padding: 16px 20px 8px; background: var(--surface); }
.p-head h2 { font-size: 17px; }
.p-head p { margin: 4px 0 0; overflow-wrap: anywhere; }
.log-opts { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; padding: 10px 20px 12px; background: var(--surface); border-bottom: 1px solid var(--border); }
.field.inline { display: grid; gap: 4px; font-size: 12px; font-weight: 550; }
.grepf .row { display: flex; gap: 6px; }
.grepf .input { width: 240px; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.check input { accent-color: var(--accent); }
.plog { flex: 1; min-height: 0; margin: 12px 20px 20px; }
@media (max-width: 960px) {
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .svc-hist { padding-left: 0; grid-template-columns: minmax(0, 1fr) 90px; }
  .svc-main { flex-wrap: wrap; }
}
@media (max-width: 560px) { .metrics { grid-template-columns: 1fr; } .grepf .input { width: 150px; } }
</style>
