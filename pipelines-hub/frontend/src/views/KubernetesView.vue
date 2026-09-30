<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, toast } from '../api'
import { ago, bytes, cores, fullDate } from '../format'
import K8sPanel from '../components/K8sPanel.vue'
import Meter from '../components/Meter.vue'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()
const TABS = [
  ['overview', 'Resumen'], ['pods', 'Pods'], ['deployments', 'Deployments'], ['cronjobs', 'CronJobs'],
  ['jobs', 'Jobs'], ['others', 'StatefulSets y DaemonSets'], ['network', 'Red'], ['config', 'Config'],
  ['nodes', 'Nodos'], ['events', 'Eventos'],
]

const clusters = ref([])
const contexts = ref(null)
const clusterId = ref(null)
const tab = ref(route.query.tab || 'overview')
const namespace = ref(route.query.ns || '')
const q = ref('')
const onlyProblems = ref(route.query.problems === '1')
const overview = ref(null)
const rows = ref(null)
const loading = ref(false)
const error = ref('')
const panel = ref(null)
const updatedAt = ref(null)

const namespaces = computed(() => (overview.value?.namespaces || []).map((n) => n.name).sort())

async function loadClusters() {
  clusters.value = await api.k8sClusters({ quiet: true })
  if (!clusters.value.length) contexts.value = await api.k8sContexts({ quiet: true })
  const wanted = Number(route.query.cluster)
  clusterId.value = clusters.value.find((c) => c.id === wanted)?.id ?? clusters.value[0]?.id ?? null
}

async function addCluster(ctx) {
  try {
    await api.k8sAddCluster({ context: ctx.name, name: ctx.name.split('/').pop() })
    toast('Cluster agregado', 'info')
    await loadClusters()
    load()
  } catch { /* toast */ }
}

let seq = 0
async function load(quiet = false) {
  if (!clusterId.value) return
  const my = ++seq
  if (!quiet) loading.value = true
  error.value = ''
  const ns = namespace.value || undefined
  try {
    if (!overview.value || tab.value === 'overview' || !quiet) {
      if (tab.value === 'overview' || !overview.value) overview.value = await api.k8s(clusterId.value, 'overview', {}, { quiet: true })
    }
    let data = null
    if (tab.value === 'pods') data = await api.k8s(clusterId.value, 'pods', { namespace: ns }, { quiet: true })
    else if (['deployments', 'cronjobs', 'jobs'].includes(tab.value)) data = await api.k8s(clusterId.value, `workloads/${tab.value}`, { namespace: ns }, { quiet: true })
    else if (tab.value === 'others') {
      const [a, b] = await Promise.all([
        api.k8s(clusterId.value, 'workloads/statefulsets', { namespace: ns }, { quiet: true }),
        api.k8s(clusterId.value, 'workloads/daemonsets', { namespace: ns }, { quiet: true }),
      ])
      data = [...a, ...b]
    } else if (tab.value === 'network') data = await api.k8s(clusterId.value, 'network', { namespace: ns }, { quiet: true })
    else if (tab.value === 'config') data = await api.k8s(clusterId.value, 'config', { namespace: ns }, { quiet: true })
    else if (tab.value === 'nodes') data = await api.k8s(clusterId.value, 'nodes', {}, { quiet: true })
    else if (tab.value === 'events') data = await api.k8s(clusterId.value, 'events', { namespace: ns }, { quiet: true })
    if (my === seq) {
      rows.value = data
      updatedAt.value = new Date().toISOString()
    }
  } catch (e) {
    if (my === seq) error.value = e.message
  } finally {
    if (my === seq) loading.value = false
  }
}

watch([tab, namespace, clusterId, onlyProblems], () => {
  rows.value = null
  router.replace({ query: { ...route.query, tab: tab.value, ns: namespace.value || undefined, cluster: clusterId.value || undefined, problems: onlyProblems.value ? '1' : undefined } })
  load()
})

let timer
onMounted(async () => {
  try { await loadClusters() } catch { /* */ }
  load()
  timer = setInterval(() => !document.hidden && !panel.value && load(true), 20000)
})
onBeforeUnmount(() => clearInterval(timer))

function match(...fields) {
  const t = q.value.trim().toLowerCase()
  return !t || fields.some((f) => String(f ?? '').toLowerCase().includes(t))
}
const list = computed(() => {
  const r = rows.value
  if (!Array.isArray(r)) return []
  return r.filter((x) => (!onlyProblems.value || x.problem || x.type === 'Warning')
    && match(x.name, x.namespace, x.reason, x.object, x.message, (x.images || []).join(' ')))
})
const svcList = computed(() => (rows.value?.services || []).filter((x) => match(x.name, x.namespace, x.type, (x.external || []).join(' '))))
const ingList = computed(() => (rows.value?.ingresses || []).filter((x) => match(x.name, x.namespace, x.rules.map((r) => r.host).join(' '))))
const cmList = computed(() => (rows.value?.configmaps || []).filter((x) => match(x.name, x.namespace, x.keys.join(' '))))
const secList = computed(() => (rows.value?.secrets || []).filter((x) => match(x.name, x.namespace, x.type, x.keys.join(' '))))

function open(kind, obj) {
  panel.value = { kind, namespace: obj.namespace, name: obj.name }
}
function goNamespace(ns) {
  namespace.value = ns
  tab.value = 'pods'
}
const pct = (a, b) => (a != null && b ? `${Math.round((a / b) * 100)}%` : '—')
const tag = (img) => (img || '').split('/').pop()
const JOB = { failed: 'Falló', success: 'OK', running: 'Corriendo', queued: 'En cola' }
</script>

<template>
  <main class="page wide">
    <div class="page-head">
      <div>
        <h1>Kubernetes</h1>
        <p>Visor de solo lectura con tu kubeconfig local. Los Secrets se muestran sin sus valores.</p>
      </div>
      <div v-if="clusters.length" class="row head-ctrls">
        <select v-if="clusters.length > 1" v-model="clusterId" class="select" aria-label="Cluster">
          <option v-for="c in clusters" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <span v-else class="chip">{{ clusters[0].name }}</span>
        <span class="faint small" :title="fullDate(updatedAt)">{{ updatedAt ? `actualizado ${ago(updatedAt)}` : '' }}</span>
        <button class="btn sm" :disabled="loading" @click="load()"><Icon name="refresh" :class="{ spin: loading }" /> Refrescar</button>
      </div>
    </div>

    <div v-if="!clusters.length" class="card setup">
      <h2>Conecta un cluster</h2>
      <p v-if="contexts && !contexts.available" class="error-text">{{ contexts.message }}</p>
      <template v-else-if="contexts">
        <p class="muted">Contextos de <code>{{ contexts.path }}</code>. Se usan tus credenciales locales (para EKS, las de AWS montadas en el contenedor).</p>
        <ul class="ctx">
          <li v-for="c in contexts.contexts" :key="c.name">
            <div class="grow"><strong class="truncate">{{ c.name }}</strong><div class="faint small truncate">{{ c.server }}</div></div>
            <button class="btn primary sm" @click="addCluster(c)"><Icon name="plus" :size="13" /> Agregar</button>
          </li>
        </ul>
      </template>
      <p v-else class="muted">Cargando…</p>
    </div>

    <template v-else>
      <nav class="tabs" aria-label="Secciones">
        <button v-for="[k, l] in TABS" :key="k" :class="{ active: tab === k }" :aria-current="tab === k ? 'page' : undefined" @click="tab = k">
          {{ l }}
          <span v-if="k === 'pods' && overview?.problems.pods.length" class="n bad">{{ overview.problems.pods.length }}</span>
          <span v-if="k === 'deployments' && overview?.problems.deployments.length" class="n bad">{{ overview.problems.deployments.length }}</span>
          <span v-if="k === 'cronjobs' && overview?.problems.cronjobs.length" class="n bad">{{ overview.problems.cronjobs.length }}</span>
        </button>
      </nav>

      <section v-if="tab !== 'overview'" class="filters">
        <label class="search">
          <Icon name="search" /><span class="sr-only">Buscar</span>
          <input v-model="q" class="input" type="search" placeholder="Buscar por nombre, imagen, motivo…" />
        </label>
        <select v-if="tab !== 'nodes'" v-model="namespace" class="select" aria-label="Namespace">
          <option value="">Todos los namespaces</option>
          <option v-for="n in namespaces" :key="n" :value="n">{{ n }}</option>
        </select>
        <label v-if="!['network', 'config'].includes(tab)" class="check"><input v-model="onlyProblems" type="checkbox" /> Solo con problemas</label>
      </section>

      <p v-if="error" class="card pad error-text">{{ error }}</p>

      <!-- Resumen -->
      <template v-if="tab === 'overview'">
        <p v-if="!overview" class="card pad muted">Cargando el cluster…</p>
        <template v-else>
          <section class="stats">
            <div class="stat"><span class="stat-n">{{ overview.totals.nodes_ready }}/{{ overview.totals.nodes }}</span><span class="stat-l">nodos listos</span></div>
            <button class="stat" @click="onlyProblems = true; tab = 'pods'"><span class="stat-n" :class="{ failed: overview.problems.pods.length }">{{ overview.problems.pods.length }}</span><span class="stat-l">pods con problemas</span></button>
            <button class="stat" @click="onlyProblems = true; tab = 'deployments'"><span class="stat-n" :class="{ failed: overview.problems.deployments.length }">{{ overview.problems.deployments.length }}</span><span class="stat-l">deployments incompletos</span></button>
            <button class="stat" @click="onlyProblems = true; tab = 'cronjobs'"><span class="stat-n" :class="{ failed: overview.problems.cronjobs.length }">{{ overview.problems.cronjobs.length }}</span><span class="stat-l">cronjobs cuyo último job falló</span></button>
          </section>
          <section class="card usage">
            <div>
              <div class="u-head"><strong>CPU</strong><span class="muted">{{ cores(overview.totals.cpu_used) }} de {{ cores(overview.totals.cpu_alloc) }} núcleos · {{ pct(overview.totals.cpu_used, overview.totals.cpu_alloc) }}</span></div>
              <Meter :value="overview.totals.cpu_used" :max="overview.totals.cpu_alloc" label="CPU del cluster" />
            </div>
            <div>
              <div class="u-head"><strong>Memoria</strong><span class="muted">{{ bytes(overview.totals.mem_used) }} de {{ bytes(overview.totals.mem_alloc) }} · {{ pct(overview.totals.mem_used, overview.totals.mem_alloc) }}</span></div>
              <Meter :value="overview.totals.mem_used" :max="overview.totals.mem_alloc" label="Memoria del cluster" />
            </div>
            <p class="faint small">{{ overview.totals.pods_running }} pods corriendo de {{ overview.totals.pods }} · {{ overview.totals.deployments }} deployments · {{ overview.totals.cronjobs }} cronjobs<template v-if="!overview.totals.has_metrics"> · sin metrics-server: no hay uso real</template></p>
          </section>

          <div class="grid2">
            <section class="card">
              <h3 class="c-title">Lo que requiere atención</h3>
              <ul class="plist">
                <li v-for="n in overview.problems.nodes" :key="'n' + n.name" class="row-link" @click="open('nodes', n)">
                  <span class="badge failed">Nodo</span><span class="grow truncate">{{ n.name }}</span><span class="faint">{{ n.ready ? n.pressure.join(', ') : 'NotReady' }}</span>
                </li>
                <li v-for="p in overview.problems.pods" :key="'p' + p.namespace + p.name" class="row-link" @click="open('pods', p)">
                  <span class="badge failed">{{ p.reason || p.phase }}</span>
                  <span class="grow truncate"><span class="faint">{{ p.namespace }}/</span>{{ p.name }}</span>
                  <span class="faint">↻{{ p.restarts }}</span>
                </li>
                <li v-for="d in overview.problems.deployments" :key="'d' + d.namespace + d.name" class="row-link" @click="open('deployments', d)">
                  <span class="badge waiting">{{ d.ready }}/{{ d.desired }}</span><span class="grow truncate"><span class="faint">{{ d.namespace }}/</span>{{ d.name }}</span><span class="faint">deployment</span>
                </li>
                <li v-for="c in overview.problems.cronjobs" :key="'c' + c.namespace + c.name" class="row-link" @click="open('cronjobs', c)">
                  <span class="badge failed">cron</span><span class="grow truncate"><span class="faint">{{ c.namespace }}/</span>{{ c.name }}</span><span class="faint">{{ ago(c.last_job?.started_at) }}</span>
                </li>
                <li v-if="!overview.problems.pods.length && !overview.problems.deployments.length && !overview.problems.cronjobs.length && !overview.problems.nodes.length" class="muted">Todo en orden. 🎉</li>
              </ul>
            </section>
            <section class="card">
              <h3 class="c-title">Más reinicios</h3>
              <ul class="plist">
                <li v-for="p in overview.problems.restarts" :key="p.namespace + p.name" class="row-link" @click="open('pods', p)">
                  <span class="restarts">↻ {{ p.restarts }}</span><span class="grow truncate"><span class="faint">{{ p.namespace }}/</span>{{ p.name }}</span>
                  <span class="faint">{{ p.last_termination?.reason || p.reason || '' }}</span>
                </li>
                <li v-if="!overview.problems.restarts.length" class="muted">Ningún pod con 3 o más reinicios.</li>
              </ul>
            </section>
          </div>

          <div class="grid2">
            <section class="card">
              <h3 class="c-title">Namespaces</h3>
              <table class="tbl">
                <thead><tr><th>Namespace</th><th class="r">Pods</th><th class="r">Problemas</th><th class="r">CPU</th><th class="r">Memoria</th></tr></thead>
                <tbody>
                  <tr v-for="n in overview.namespaces" :key="n.name" class="row-link" @click="goNamespace(n.name)">
                    <td>{{ n.name }}</td><td class="r">{{ n.pods }}</td>
                    <td class="r"><span v-if="n.problems" class="bad">{{ n.problems }}</span><span v-else class="faint">0</span></td>
                    <td class="r">{{ cores(n.cpu) }}</td><td class="r">{{ bytes(n.memory) }}</td>
                  </tr>
                </tbody>
              </table>
            </section>
            <section class="card">
              <h3 class="c-title">Eventos Warning recientes</h3>
              <ul class="plist">
                <li v-for="(e, i) in overview.warnings.slice(0, 20)" :key="i" class="ev">
                  <div><strong>{{ e.reason }}</strong> <span class="faint">· {{ e.namespace }}/{{ e.object }} · {{ ago(e.last_seen) }}<template v-if="e.count > 1"> · ×{{ e.count }}</template></span></div>
                  <div class="small truncate" :title="e.message">{{ e.message }}</div>
                </li>
              </ul>
            </section>
          </div>
        </template>
      </template>

      <div v-else-if="rows === null && !error" class="card pad muted">Cargando…</div>

      <!-- Pods -->
      <section v-else-if="tab === 'pods'" class="card tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Pod</th><th>Estado</th><th class="r">Listos</th><th class="r">Reinicios</th><th class="r">CPU</th><th class="r">Memoria</th><th>Nodo</th><th class="r">Edad</th></tr></thead>
          <tbody>
            <tr v-for="p in list.slice(0, 500)" :key="p.namespace + p.name" class="row-link" @click="open('pods', p)">
              <td class="name"><span class="faint">{{ p.namespace }}/</span>{{ p.name }}</td>
              <td><span class="badge" :class="p.problem ? 'failed' : p.phase === 'Running' ? 'success' : p.phase === 'Succeeded' ? 'queued' : 'waiting'">{{ p.reason || p.phase }}</span></td>
              <td class="r">{{ p.ready }}</td>
              <td class="r" :class="{ bad: p.restarts >= 5 }" :title="p.last_termination ? `Último término: ${p.last_termination.reason}` : ''">{{ p.restarts }}</td>
              <td class="r">{{ cores(p.cpu) }}</td>
              <td class="r">{{ bytes(p.memory) }}<span v-if="p.mem_limit" class="faint"> / {{ bytes(p.mem_limit, 0) }}</span></td>
              <td class="faint small truncate node">{{ p.node }}</td>
              <td class="r faint" :title="fullDate(p.started_at || p.created_at)">{{ ago(p.started_at || p.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="list.length > 500" class="pad faint small">Mostrando 500 de {{ list.length }}; filtra por namespace o búsqueda.</p>
        <p v-if="!list.length" class="pad muted">Nada que mostrar.</p>
      </section>

      <!-- Deployments / StatefulSets / DaemonSets -->
      <section v-else-if="tab === 'deployments' || tab === 'others'" class="card tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Nombre</th><th v-if="tab === 'others'">Tipo</th><th class="r">Listos</th><th>Imagen</th><th class="r">Edad</th></tr></thead>
          <tbody>
            <tr v-for="d in list" :key="d.kind + d.namespace + d.name" class="row-link" @click="open(d.kind === 'StatefulSet' ? 'statefulsets' : d.kind === 'DaemonSet' ? 'daemonsets' : 'deployments', d)">
              <td class="name"><span class="faint">{{ d.namespace }}/</span>{{ d.name }}</td>
              <td v-if="tab === 'others'">{{ d.kind }}</td>
              <td class="r"><span :class="{ bad: d.problem }">{{ d.ready }}/{{ d.desired }}</span></td>
              <td class="mono small truncate img" :title="d.images.join(', ')">{{ d.images.map(tag).join(', ') }}</td>
              <td class="r faint">{{ ago(d.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!list.length" class="pad muted">Nada que mostrar.</p>
      </section>

      <!-- CronJobs -->
      <section v-else-if="tab === 'cronjobs'" class="card tbl-wrap">
        <table class="tbl">
          <thead><tr><th>CronJob</th><th>Horario</th><th>Último job</th><th class="r">Última corrida</th><th class="r">Último éxito</th><th>Imagen</th></tr></thead>
          <tbody>
            <tr v-for="c in list" :key="c.namespace + c.name" class="row-link" @click="open('cronjobs', c)">
              <td class="name"><span class="faint">{{ c.namespace }}/</span>{{ c.name }} <span v-if="c.suspended" class="chip">suspendido</span></td>
              <td class="mono small">{{ c.schedule }}<span v-if="c.timezone" class="faint"> {{ c.timezone }}</span></td>
              <td><span v-if="c.last_job" class="badge" :class="{ failed: 'failed', success: 'success', running: 'running', queued: 'queued' }[c.last_job.status]">{{ JOB[c.last_job.status] }}</span><span v-else class="faint">—</span></td>
              <td class="r faint" :title="fullDate(c.last_schedule)">{{ ago(c.last_schedule) }}</td>
              <td class="r faint" :title="fullDate(c.last_success)">{{ ago(c.last_success) }}</td>
              <td class="mono small truncate img" :title="c.images.join(', ')">{{ c.images.map(tag).join(', ') }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!list.length" class="pad muted">Nada que mostrar.</p>
      </section>

      <!-- Jobs -->
      <section v-else-if="tab === 'jobs'" class="card tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Job</th><th>Estado</th><th>CronJob</th><th class="r">Inicio</th><th class="r">Fin</th></tr></thead>
          <tbody>
            <tr v-for="j in list.slice(0, 500)" :key="j.namespace + j.name" class="row-link" @click="open('jobs', j)">
              <td class="name"><span class="faint">{{ j.namespace }}/</span>{{ j.name }}</td>
              <td><span class="badge" :class="{ failed: 'failed', success: 'success', running: 'running', queued: 'queued' }[j.status]">{{ JOB[j.status] }}</span><span v-if="j.reason" class="faint small"> {{ j.reason }}</span></td>
              <td class="small">{{ j.cronjob || '—' }}</td>
              <td class="r faint" :title="fullDate(j.started_at)">{{ ago(j.started_at) }}</td>
              <td class="r faint" :title="fullDate(j.finished_at)">{{ ago(j.finished_at) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!list.length" class="pad muted">Nada que mostrar.</p>
      </section>

      <!-- Red -->
      <template v-else-if="tab === 'network'">
        <section class="card tbl-wrap">
          <h3 class="c-title">Ingress <span class="faint">{{ ingList.length }}</span></h3>
          <table class="tbl">
            <thead><tr><th>Ingress</th><th>Hosts y rutas</th><th>Destino</th><th>TLS</th></tr></thead>
            <tbody>
              <tr v-for="i in ingList" :key="i.namespace + i.name" class="row-link" @click="open('ingresses', i)">
                <td class="name"><span class="faint">{{ i.namespace }}/</span>{{ i.name }}</td>
                <td class="small"><div v-for="(r, k) in i.rules.slice(0, 4)" :key="k" class="truncate">{{ r.host }}{{ r.path }}</div><span v-if="i.rules.length > 4" class="faint">+{{ i.rules.length - 4 }}</span></td>
                <td class="small"><div v-for="(r, k) in i.rules.slice(0, 4)" :key="k" class="truncate">{{ r.service }}:{{ r.port }}</div></td>
                <td class="small">{{ i.tls.length ? '🔒' : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section class="card tbl-wrap">
          <h3 class="c-title">Services <span class="faint">{{ svcList.length }}</span></h3>
          <table class="tbl">
            <thead><tr><th>Service</th><th>Tipo</th><th>Puertos</th><th>Externo</th></tr></thead>
            <tbody>
              <tr v-for="s in svcList" :key="s.namespace + s.name" class="row-link" @click="open('services', s)">
                <td class="name"><span class="faint">{{ s.namespace }}/</span>{{ s.name }}</td>
                <td class="small">{{ s.type }}</td>
                <td class="mono small">{{ s.ports.join(', ') }}</td>
                <td class="small truncate">{{ s.external.join(', ') || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>

      <!-- Config -->
      <template v-else-if="tab === 'config'">
        <section class="card tbl-wrap">
          <h3 class="c-title">Secrets <span class="faint">{{ secList.length }} · solo nombres de claves</span></h3>
          <table class="tbl">
            <thead><tr><th>Secret</th><th>Tipo</th><th>Claves</th><th class="r">Edad</th></tr></thead>
            <tbody>
              <tr v-for="s in secList" :key="s.namespace + s.name" class="row-link" @click="open('secrets', s)">
                <td class="name"><span class="faint">{{ s.namespace }}/</span>{{ s.name }}</td>
                <td class="small faint">{{ s.type }}</td>
                <td class="mono small truncate img" :title="s.keys.join(', ')">{{ s.keys.join(', ') || '—' }}</td>
                <td class="r faint">{{ ago(s.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section class="card tbl-wrap">
          <h3 class="c-title">ConfigMaps <span class="faint">{{ cmList.length }}</span></h3>
          <table class="tbl">
            <thead><tr><th>ConfigMap</th><th>Claves</th><th class="r">Edad</th></tr></thead>
            <tbody>
              <tr v-for="c in cmList" :key="c.namespace + c.name" class="row-link" @click="open('configmaps', c)">
                <td class="name"><span class="faint">{{ c.namespace }}/</span>{{ c.name }}</td>
                <td class="mono small truncate img" :title="c.keys.join(', ')">{{ c.keys.join(', ') || '—' }}</td>
                <td class="r faint">{{ ago(c.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>

      <!-- Nodos -->
      <section v-else-if="tab === 'nodes'" class="card tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Nodo</th><th>Estado</th><th>Tipo</th><th class="w">CPU</th><th class="w">Memoria</th><th class="r">Pods</th><th class="r">Edad</th></tr></thead>
          <tbody>
            <tr v-for="n in list" :key="n.name" class="row-link" @click="open('nodes', n)">
              <td class="name mono small">{{ n.name }}</td>
              <td><span class="badge" :class="n.problem ? 'failed' : 'success'">{{ n.ready ? (n.pressure.join(', ') || 'Ready') : 'NotReady' }}</span></td>
              <td class="small">{{ n.instance_type }}<span v-if="n.capacity_type" class="faint"> · {{ n.capacity_type.toLowerCase() }}</span><div class="faint">{{ n.zone }}</div></td>
              <td><Meter :value="n.cpu_used" :max="n.cpu_alloc" :label="`CPU de ${n.name}`" /><span class="small faint">{{ cores(n.cpu_used) }} / {{ cores(n.cpu_alloc) }}</span></td>
              <td><Meter :value="n.mem_used" :max="n.mem_alloc" :label="`Memoria de ${n.name}`" /><span class="small faint">{{ bytes(n.mem_used) }} / {{ bytes(n.mem_alloc) }}</span></td>
              <td class="r">{{ n.pods }}/{{ n.pods_alloc }}</td>
              <td class="r faint">{{ ago(n.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!list.length" class="pad muted">{{ onlyProblems ? 'Ningún nodo con problemas.' : 'Sin nodos.' }}</p>
      </section>

      <!-- Eventos -->
      <section v-else-if="tab === 'events'" class="card tbl-wrap">
        <table class="tbl">
          <thead><tr><th>Cuándo</th><th>Tipo</th><th>Motivo</th><th>Objeto</th><th>Mensaje</th></tr></thead>
          <tbody>
            <tr v-for="(e, i) in list.slice(0, 300)" :key="i">
              <td class="faint small nowrap" :title="fullDate(e.last_seen)">{{ ago(e.last_seen) }}<template v-if="e.count > 1"> ×{{ e.count }}</template></td>
              <td><span :class="e.type === 'Warning' ? 'bad' : 'faint'">{{ e.type }}</span></td>
              <td class="small"><strong>{{ e.reason }}</strong></td>
              <td class="small truncate obj"><span class="faint">{{ e.namespace }}/</span>{{ e.kind }} {{ e.object }}</td>
              <td class="small msg">{{ e.message }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!list.length" class="pad muted">Sin eventos.</p>
      </section>
    </template>

    <K8sPanel v-if="panel" :cluster-id="clusterId" :target="panel" @close="panel = null" @open="panel = $event" />
  </main>
</template>

<style scoped>
.wide { max-width: 1440px; }
.head-ctrls { gap: 10px; }
.small { font-size: 12px; }
.setup { padding: 20px; max-width: 760px; }
.setup h2 { margin-bottom: 6px; }
.ctx { list-style: none; margin: 14px 0 0; padding: 0; display: grid; gap: 8px; }
.ctx li { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius); min-width: 0; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 14px; overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; padding: 8px 11px; margin-bottom: -1px; border: 0; border-bottom: 2px solid transparent; background: none; color: var(--text-muted); font: inherit; font-weight: 600; cursor: pointer; white-space: nowrap; }
.tabs button:hover { color: var(--text); }
.tabs button.active { color: var(--text); border-bottom-color: var(--accent); }
.n { min-width: 18px; height: 18px; padding: 0 5px; border-radius: 99px; font-size: 11px; display: inline-flex; align-items: center; justify-content: center; }
.n.bad { background: var(--st-failed-soft); color: var(--st-failed); }
.filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
.search { position: relative; flex: 1 1 260px; display: flex; }
.search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-faint); pointer-events: none; }
.search .input { width: 100%; padding-left: 32px; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.check input { accent-color: var(--accent); }
.pad { padding: 14px 16px; margin: 0; }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }
.stat { display: flex; align-items: baseline; gap: 8px; padding: 14px 16px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); color: var(--text); font: inherit; text-align: left; }
button.stat { cursor: pointer; }
button.stat:hover { border-color: var(--border-strong); }
.stat-n { font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; }
.stat-n.failed { color: var(--st-failed); }
.stat-l { color: var(--text-muted); font-size: 13px; }
.usage { padding: 14px 16px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px 24px; margin-bottom: 12px; }
.usage p { grid-column: 1 / -1; margin: 0; }
.u-head { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; margin-bottom: 6px; flex-wrap: wrap; }
.grid2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; margin-bottom: 12px; }
.c-title { padding: 12px 16px 6px; font-size: 13px; }
.plist { list-style: none; margin: 0; padding: 4px 8px 10px; display: grid; gap: 1px; font-size: 13px; max-height: 380px; overflow: auto; }
.plist li { padding: 6px 8px; border-radius: var(--radius-sm); display: flex; align-items: center; gap: 10px; min-width: 0; }
.plist li.ev { display: block; }
.row-link { cursor: pointer; }
.row-link:hover { background: var(--surface-hover); }
.restarts { font-weight: 700; color: var(--st-failed); min-width: 64px; font-variant-numeric: tabular-nums; }
.tbl-wrap { overflow-x: auto; margin-bottom: 12px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th { text-align: left; font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); font-weight: 600; padding: 8px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.tbl td { padding: 7px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.tbl tr:last-child td { border-bottom: 0; }
.r { text-align: right; font-variant-numeric: tabular-nums; }
.w { width: 160px; }
.name { max-width: 460px; overflow-wrap: anywhere; }
.img { max-width: 340px; }
.node { max-width: 200px; }
.obj { max-width: 260px; }
.msg { min-width: 280px; }
.nowrap { white-space: nowrap; }
.mono { font-family: var(--mono); }
.bad { color: var(--st-failed); font-weight: 600; }
@media (max-width: 960px) {
  .grid2, .usage { grid-template-columns: minmax(0, 1fr); }
  .grid2 > .card { overflow-x: auto; }
  .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
