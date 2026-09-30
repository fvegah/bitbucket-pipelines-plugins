<script setup>
// Panel lateral con el detalle de un recurso: resumen, pods, eventos, YAML y logs (pods).
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { ago, bytes, cores, fullDate } from '../format'
import LogViewer from './LogViewer.vue'
import Icon from './Icon.vue'

const props = defineProps({
  clusterId: { type: Number, required: true },
  target: { type: Object, required: true }, // { kind, namespace, name }
})
const emit = defineEmits(['close', 'open'])

const data = ref(null)
const error = ref('')
const tab = ref('summary')
const container = ref('')
const previous = ref(false)
const tail = ref(1000)
const follow = ref(false)
const isPod = computed(() => props.target.kind === 'pods')

async function load() {
  data.value = null
  error.value = ''
  try {
    data.value = await api.k8s(props.clusterId,
      `resource/${props.target.kind}/${props.target.namespace || '_'}/${props.target.name}`, {}, { quiet: true })
    if (isPod.value) {
      container.value = data.value.summary?.containers?.[0] || ''
      if (tab.value === 'summary') tab.value = 'logs'
    }
  } catch (e) {
    error.value = e.message
  }
}
watch(() => [props.target.kind, props.target.namespace, props.target.name], () => {
  tab.value = props.target.kind === 'pods' ? 'logs' : 'summary'
  previous.value = false
  follow.value = false
  load()
}, { immediate: true })

const loader = async (cursor) => api.k8s(props.clusterId, `log/${props.target.namespace}/${props.target.name}`, {
  container: container.value || undefined,
  previous: previous.value || undefined,
  tail: tail.value,
  since: cursor || undefined,
}, { quiet: true })
const logKey = computed(() => `${props.target.namespace}/${props.target.name}/${container.value}/${previous.value}/${tail.value}`)

function onKey(e) { if (e.key === 'Escape') emit('close') }
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

function stateText(s) {
  if (!s) return ''
  const [k, v] = Object.entries(s)[0] || []
  if (!k) return ''
  return `${k}${v?.reason ? ` · ${v.reason}` : ''}${v?.exitCode !== undefined ? ` (exit ${v.exitCode})` : ''}`
}
const KIND_LABEL = { pods: 'Pod', deployments: 'Deployment', statefulsets: 'StatefulSet', daemonsets: 'DaemonSet', cronjobs: 'CronJob', jobs: 'Job', services: 'Service', ingresses: 'Ingress', configmaps: 'ConfigMap', secrets: 'Secret', nodes: 'Nodo' }
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <aside class="panel" role="dialog" :aria-label="`${KIND_LABEL[target.kind]} ${target.name}`">
      <header class="p-head">
        <div class="grow">
          <span class="chip">{{ KIND_LABEL[target.kind] || target.kind }}</span>
          <h2 class="truncate" :title="target.name">{{ target.name }}</h2>
          <p v-if="target.namespace" class="muted ns">namespace <code>{{ target.namespace }}</code></p>
        </div>
        <button class="btn icon ghost" aria-label="Cerrar" @click="emit('close')"><Icon name="plus" style="transform: rotate(45deg)" /></button>
      </header>

      <nav class="p-tabs">
        <button v-if="isPod" :class="{ active: tab === 'logs' }" @click="tab = 'logs'">Logs</button>
        <button :class="{ active: tab === 'summary' }" @click="tab = 'summary'">Resumen</button>
        <button v-if="data?.pods" :class="{ active: tab === 'pods' }" @click="tab = 'pods'">Pods <span class="n">{{ data.pods.length }}</span></button>
        <button v-if="data?.jobs" :class="{ active: tab === 'jobs' }" @click="tab = 'jobs'">Ejecuciones <span class="n">{{ data.jobs.length }}</span></button>
        <button :class="{ active: tab === 'events' }" @click="tab = 'events'">Eventos <span v-if="data" class="n">{{ data.events.length }}</span></button>
        <button :class="{ active: tab === 'yaml' }" @click="tab = 'yaml'">YAML</button>
      </nav>

      <div class="p-body">
        <p v-if="error" class="error-text pad">{{ error }}</p>
        <p v-else-if="!data" class="muted pad">Cargando…</p>

        <template v-else-if="tab === 'logs' && isPod">
          <div class="log-opts">
            <label class="field inline">Contenedor
              <select v-model="container" class="select">
                <option v-for="c in data.summary.containers" :key="c" :value="c">{{ c }}</option>
              </select>
            </label>
            <label class="field inline">Líneas
              <select v-model.number="tail" class="select">
                <option :value="200">200</option><option :value="1000">1.000</option><option :value="5000">5.000</option><option :value="20000">20.000</option>
              </select>
            </label>
            <label class="check"><input v-model="previous" type="checkbox" /> Contenedor anterior <span class="faint">(tras un reinicio)</span></label>
            <label class="check"><input v-model="follow" type="checkbox" :disabled="previous" /> Seguir en vivo</label>
          </div>
          <LogViewer class="plog" :loader="loader" :loader-key="logKey" :live="follow && !previous" :title="container"
                     :subtitle="previous ? 'contenedor anterior' : `últimas ${tail} líneas`" :file-name="target.name" provider="k8s" />
        </template>

        <div v-else-if="tab === 'summary'" class="pad summary">
          <template v-if="isPod">
            <dl class="facts">
              <div><dt>Fase</dt><dd>{{ data.summary.phase }}<template v-if="data.summary.reason"> · {{ data.summary.reason }}</template></dd></div>
              <div><dt>Listos</dt><dd>{{ data.summary.ready }}</dd></div>
              <div><dt>Reinicios</dt><dd>{{ data.summary.restarts }}</dd></div>
              <div><dt>Nodo</dt><dd class="mono">{{ data.summary.node }}</dd></div>
              <div><dt>CPU</dt><dd>{{ cores(data.summary.cpu) }}</dd></div>
              <div><dt>Memoria</dt><dd>{{ bytes(data.summary.memory) }}<template v-if="data.summary.mem_limit"> / {{ bytes(data.summary.mem_limit) }}</template></dd></div>
              <div><dt>Inicio</dt><dd :title="fullDate(data.summary.started_at)">{{ ago(data.summary.started_at) }}</dd></div>
            </dl>
            <p v-if="data.summary.last_termination" class="warn-box">
              Último término: <strong>{{ data.summary.last_termination.reason }}</strong>
              (exit {{ data.summary.last_termination.exit_code }}) {{ ago(data.summary.last_termination.finished_at) }}.
              <button class="linkish" @click="previous = true; tab = 'logs'">Ver log del contenedor anterior</button>
            </p>
            <h3>Contenedores</h3>
            <ul class="list">
              <li v-for="c in data.container_states" :key="c.name">
                <strong>{{ c.name }}</strong> <span :class="c.ready ? 'ok' : 'bad'">{{ c.ready ? 'listo' : 'no listo' }}</span>
                <span class="faint">· {{ c.restarts }} reinicios · {{ stateText(c.state) }}</span>
                <div class="mono faint small">{{ c.image }}</div>
              </li>
            </ul>
          </template>
          <pre v-else class="yaml short">{{ data.yaml.split('\nstatus:')[1] ? 'status:' + data.yaml.split('\nstatus:')[1] : data.yaml.slice(0, 3000) }}</pre>
        </div>

        <ul v-else-if="tab === 'pods'" class="list pad">
          <li v-for="p in data.pods" :key="p.name" class="row-link" @click="emit('open', { kind: 'pods', namespace: p.namespace, name: p.name })">
            <span class="dot" :class="p.problem ? 'bad' : p.phase === 'Running' ? 'ok' : 'neutral'" aria-hidden="true"></span>
            <span class="grow truncate">{{ p.name }}</span>
            <span class="faint">{{ p.phase }}<template v-if="p.reason && p.reason !== p.phase"> · {{ p.reason }}</template></span>
            <span class="faint">{{ p.ready }} · ↻{{ p.restarts }}</span>
          </li>
          <li v-if="!data.pods.length" class="muted">Sin pods.</li>
        </ul>

        <ul v-else-if="tab === 'jobs'" class="list pad">
          <li v-for="j in data.jobs" :key="j.name" class="row-link" @click="emit('open', { kind: 'jobs', namespace: j.namespace, name: j.name })">
            <span class="dot" :class="j.status === 'failed' ? 'bad' : j.status === 'success' ? 'ok' : 'neutral'" aria-hidden="true"></span>
            <span class="grow truncate">{{ j.name }}</span>
            <span class="faint">{{ { failed: 'falló', success: 'ok', running: 'corriendo', queued: 'en cola' }[j.status] }}<template v-if="j.reason"> · {{ j.reason }}</template></span>
            <span class="faint" :title="fullDate(j.started_at)">{{ ago(j.started_at) }}</span>
          </li>
        </ul>

        <ul v-else-if="tab === 'events'" class="list pad">
          <li v-for="(e, i) in data.events" :key="i">
            <span :class="e.type === 'Warning' ? 'bad' : 'faint'">{{ e.type }}</span> <strong>{{ e.reason }}</strong>
            <span class="faint">· {{ ago(e.last_seen) }}<template v-if="e.count > 1"> · ×{{ e.count }}</template></span>
            <div class="small">{{ e.message }}</div>
          </li>
          <li v-if="!data.events.length" class="muted">Sin eventos recientes.</li>
        </ul>

        <pre v-else-if="tab === 'yaml'" class="yaml">{{ data.yaml }}</pre>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; z-index: 50; background: rgb(8 10 14 / 45%); display: flex; justify-content: flex-end; }
.panel { width: min(980px, 100vw); height: 100%; background: var(--bg); border-left: 1px solid var(--border); display: flex; flex-direction: column; box-shadow: var(--shadow-lg); }
.p-head { display: flex; gap: 12px; align-items: flex-start; padding: 16px 20px 10px; background: var(--surface); }
.p-head h2 { font-size: 17px; margin-top: 6px; overflow-wrap: anywhere; }
.ns { margin: 4px 0 0; font-size: 13px; }
.p-tabs { display: flex; gap: 4px; padding: 0 16px; border-bottom: 1px solid var(--border); background: var(--surface); overflow-x: auto; }
.p-tabs button { display: inline-flex; gap: 6px; align-items: center; padding: 8px 10px; margin-bottom: -1px; border: 0; border-bottom: 2px solid transparent; background: none; color: var(--text-muted); font: inherit; font-weight: 600; cursor: pointer; white-space: nowrap; }
.p-tabs button:hover { color: var(--text); }
.p-tabs button.active { color: var(--text); border-bottom-color: var(--accent); }
.n { min-width: 18px; height: 18px; padding: 0 5px; border-radius: 99px; background: var(--surface-2); border: 1px solid var(--border); font-size: 11px; display: inline-flex; align-items: center; justify-content: center; }
.p-body { flex: 1; overflow: auto; display: flex; flex-direction: column; min-height: 0; }
.pad { padding: 14px 20px; }
.log-opts { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; padding: 12px 20px; }
.field.inline { display: grid; gap: 4px; font-size: 12px; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.check input { accent-color: var(--accent); }
.plog { flex: 1; min-height: 420px; margin: 0 20px 20px; }
.summary h3 { margin: 18px 0 8px; font-size: 13px; }
.facts { display: flex; flex-wrap: wrap; gap: 10px 26px; margin: 0; }
.facts div { display: grid; gap: 2px; }
.facts dt { font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); font-weight: 600; }
.facts dd { margin: 0; font-size: 13px; }
.warn-box { margin: 14px 0 0; padding: 10px 12px; border-radius: var(--radius-sm); background: var(--st-waiting-soft); color: var(--text); font-size: 13px; }
.list { list-style: none; margin: 0; display: grid; gap: 2px; font-size: 13px; }
.list li { padding: 7px 8px; border-radius: var(--radius-sm); }
.row-link { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.row-link:hover { background: var(--surface-hover); }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.dot.ok { background: var(--st-success); }
.dot.bad { background: var(--st-failed); }
.dot.neutral { background: var(--st-queued); }
.ok { color: var(--st-success); font-weight: 600; }
.bad { color: var(--st-failed); font-weight: 600; }
.small { font-size: 12px; }
.mono { font-family: var(--mono); }
.yaml { margin: 0; padding: 14px 20px; font: 12px/1.55 var(--mono); color: var(--log-text); background: var(--log-bg); white-space: pre; overflow: auto; flex: 1; }
.yaml.short { padding: 12px; border-radius: var(--radius-sm); border: 1px solid var(--border); max-height: 60vh; }
.linkish { border: 0; background: none; padding: 0; color: var(--accent); font: inherit; cursor: pointer; }
.linkish:hover { text-decoration: underline; }
</style>
