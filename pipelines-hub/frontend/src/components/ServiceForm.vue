<script setup>
import { computed, reactive, ref } from 'vue'
import { api, toast } from '../api'
import Modal from './Modal.vue'

const props = defineProps({
  serverId: { type: Number, required: true },
  service: { type: Object, default: null }, // edición
  preset: { type: Object, default: null }, // sugerencia detectada
  platforms: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'saved'])
const editing = computed(() => !!props.service)
const base = props.service || props.preset || {}

const KINDS = [
  ['systemd', 'Servicio systemd', 'puma, sidekiq, nginx, uvicorn…'],
  ['docker', 'Contenedor Docker', ''],
  ['redis', 'Redis', 'memoria, clientes, keys'],
  ['postgres', 'PostgreSQL', 'conexiones y tamaño de bases'],
  ['sidekiq', 'Sidekiq', 'colas, reintentos y muertos (vía Redis)'],
  ['rabbitmq', 'RabbitMQ', 'colas y consumidores'],
  ['http', 'Chequeo HTTP', 'código, latencia y certificado'],
  ['tcp', 'Puerto TCP', 'que algo escuche en el puerto'],
  ['process', 'Proceso', 'por patrón de pgrep'],
  ['log', 'Solo un log', 'archivo que quieres poder leer'],
]
const form = reactive({
  name: base.name || '',
  kind: base.kind || 'systemd',
  platform: base.platform || '',
  config: { host: '127.0.0.1', port: 6379, db: 0, mode: 'local', expect: 200, ...(base.config || {}) },
  log: { type: 'none', ...(base.log || {}) },
  password: '',
})
const busy = ref(false)
const errorMsg = ref('')
const needsPassword = computed(() => ['redis', 'sidekiq'].includes(form.kind) || (form.kind === 'postgres' && form.config.mode === 'remote'))

function cleanConfig() {
  const c = form.config
  const pick = (...keys) => Object.fromEntries(keys.filter((k) => c[k] !== undefined && c[k] !== '').map((k) => [k, c[k]]))
  return {
    systemd: pick('unit'), docker: pick('container'), redis: pick('host', 'port', 'db', 'tls'),
    sidekiq: pick('unit', 'host', 'port', 'db', 'tls', 'namespace'),
    postgres: c.mode === 'remote' ? pick('mode', 'host', 'port', 'user', 'database') : { mode: 'local' },
    rabbitmq: {}, http: pick('url', 'from_server', 'expect'), tcp: pick('port'), process: pick('pattern'), log: {},
  }[form.kind]
}
function cleanLog() {
  const l = form.log
  if (l.type === 'journal') return { type: 'journal', unit: l.unit || form.config.unit }
  if (l.type === 'file') return { type: 'file', path: l.path }
  if (l.type === 'docker') return { type: 'docker', container: l.container || form.config.container }
  return { type: 'none' }
}

async function save() {
  busy.value = true
  errorMsg.value = ''
  try {
    const body = { name: form.name.trim(), platform: form.platform.trim() || null, config: cleanConfig(), log: cleanLog() }
    if (form.password) body.password = form.password
    const s = editing.value ? await api.updateService(props.service.id, body)
      : await api.addService(props.serverId, { ...body, kind: form.kind })
    toast(editing.value ? 'Servicio actualizado' : `${s.name}: ${s.summary || s.status}`, 'info')
    emit('saved', s)
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal :title="editing ? `Editar ${service.name}` : 'Agregar servicio'" @close="emit('close')">
    <form class="modal-body" @submit.prevent="save">
      <label v-if="!editing" class="field">Tipo
        <select v-model="form.kind" class="select">
          <option v-for="[k, l, d] in KINDS" :key="k" :value="k">{{ l }}{{ d ? ` — ${d}` : '' }}</option>
        </select>
      </label>
      <div class="two">
        <label class="field">Nombre<input v-model="form.name" class="input" placeholder="Sidekiq de Edutecnia" /></label>
        <label class="field">Plataforma <span class="hint">agrupa los servicios</span>
          <input v-model="form.platform" class="input" list="platforms" placeholder="Edutecnia, quizkid…" />
          <datalist id="platforms"><option v-for="p in platforms" :key="p" :value="p" /></datalist>
        </label>
      </div>

      <label v-if="['systemd', 'sidekiq'].includes(form.kind)" class="field">Unidad systemd <span v-if="form.kind === 'sidekiq'" class="hint">opcional: para ver si el proceso corre</span>
        <input v-model="form.config.unit" class="input mono" placeholder="sidekiq_app" />
      </label>
      <label v-if="form.kind === 'docker'" class="field">Contenedor<input v-model="form.config.container" class="input mono" /></label>
      <div v-if="['redis', 'sidekiq'].includes(form.kind)" class="three">
        <label class="field">Host de Redis<input v-model="form.config.host" class="input mono" /></label>
        <label class="field">Puerto<input v-model.number="form.config.port" class="input" type="number" /></label>
        <label class="field">DB<input v-model.number="form.config.db" class="input" type="number" min="0" max="15" /></label>
      </div>
      <label v-if="form.kind === 'sidekiq'" class="field">Namespace <span class="hint">prefijo de las keys, si usan redis-namespace (ej: <code>edutecnia:</code>)</span>
        <input v-model="form.config.namespace" class="input mono" />
      </label>
      <template v-if="form.kind === 'postgres'">
        <div class="segmented" role="group" aria-label="Postgres">
          <button type="button" :aria-pressed="form.config.mode === 'local'" @click="form.config.mode = 'local'">Local (sudo -u postgres)</button>
          <button type="button" :aria-pressed="form.config.mode === 'remote'" @click="form.config.mode = 'remote'">Remoto / RDS</button>
        </div>
        <div v-if="form.config.mode === 'remote'" class="two">
          <label class="field">Host<input v-model="form.config.host" class="input mono" /></label>
          <label class="field">Puerto<input v-model.number="form.config.port" class="input" type="number" placeholder="5432" /></label>
          <label class="field">Usuario<input v-model="form.config.user" class="input mono" /></label>
          <label class="field">Base<input v-model="form.config.database" class="input mono" /></label>
        </div>
      </template>
      <template v-if="form.kind === 'http'">
        <label class="field">URL<input v-model="form.config.url" class="input mono" placeholder="https://api.example.com/" /></label>
        <div class="two">
          <label class="field">Código esperado<input v-model.number="form.config.expect" class="input" type="number" /></label>
          <label class="check"><input v-model="form.config.from_server" type="checkbox" /> Probar desde el servidor (útil para URLs internas como <code>http://127.0.0.1:3000</code>)</label>
        </div>
      </template>
      <label v-if="form.kind === 'tcp'" class="field">Puerto<input v-model.number="form.config.port" class="input" type="number" /></label>
      <label v-if="form.kind === 'process'" class="field">Patrón (pgrep -f)<input v-model="form.config.pattern" class="input mono" placeholder="sidekiq 7" /></label>
      <label v-if="needsPassword" class="field">Clave <span class="hint">{{ service?.has_password ? 'guardada; vacío la mantiene' : 'opcional, se guarda cifrada' }}</span>
        <input v-model="form.password" class="input" type="password" autocomplete="off" />
      </label>

      <fieldset class="logsrc">
        <legend>Log</legend>
        <div class="segmented" role="group" aria-label="Fuente del log">
          <button v-for="[t, l] in [['none', 'Sin log'], ['journal', 'journal'], ['file', 'Archivo'], ['docker', 'docker logs']]" :key="t" type="button"
                  :aria-pressed="form.log.type === t" @click="form.log.type = t">{{ l }}</button>
        </div>
        <label v-if="form.log.type === 'journal'" class="field">Unidad<input v-model="form.log.unit" class="input mono" :placeholder="form.config.unit || 'mi-servicio'" /></label>
        <label v-if="form.log.type === 'file'" class="field">Ruta<input v-model="form.log.path" class="input mono" placeholder="/var/www/app/shared/log/production.log" /></label>
        <label v-if="form.log.type === 'docker'" class="field">Contenedor<input v-model="form.log.container" class="input mono" :placeholder="form.config.container" /></label>
      </fieldset>
      <p v-if="errorMsg" class="error-text">{{ errorMsg }}</p>
    </form>
    <div class="modal-foot">
      <button class="btn" @click="emit('close')">Cancelar</button>
      <button class="btn primary" :disabled="!form.name.trim() || busy" @click="save">{{ busy ? 'Probando…' : editing ? 'Guardar' : 'Agregar y chequear' }}</button>
    </div>
  </Modal>
</template>

<style scoped>
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: end; }
.three { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 12px; }
.check { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; }
.check input { accent-color: var(--accent); margin-top: 3px; }
.logsrc { border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px 12px; margin: 0; display: grid; gap: 10px; }
.logsrc legend { font-size: 13px; font-weight: 600; padding: 0 4px; }
.error-text { margin: 0; }
@media (max-width: 560px) { .two, .three { grid-template-columns: 1fr; } }
</style>
