<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, toast } from '../api'
import Modal from './Modal.vue'

const props = defineProps({ server: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved'])
const editing = computed(() => !!props.server)

const cfg = ref({ aliases: [], keys: [] })
const keyMode = ref(props.server?.has_private_key ? 'paste' : 'file')
const form = reactive({
  name: props.server?.name || '',
  host: props.server?.host || '',
  port: props.server?.port || 22,
  username: props.server?.username || '',
  key_path: props.server?.key_path || '',
  private_key: '',
  passphrase: '',
  use_sudo: props.server?.use_sudo ?? true,
  environment: props.server?.environment || '',
})
const tested = ref(null)
const busy = ref('')
const errorMsg = ref('')

onMounted(async () => {
  try {
    cfg.value = await api.sshConfig({ quiet: true })
    if (!form.key_path && cfg.value.keys.length) form.key_path = cfg.value.keys[0]
  } catch { /* */ }
})

function importAlias(alias) {
  const a = cfg.value.aliases.find((x) => x.alias === alias)
  if (!a) return
  form.name = form.name || a.alias
  form.host = a.host
  form.port = a.port || 22
  form.username = a.user || form.username
  if (a.key_path && cfg.value.keys.includes(a.key_path)) {
    keyMode.value = 'file'
    form.key_path = a.key_path
  }
}

function payload() {
  return {
    name: form.name.trim(), host: form.host.trim(), port: Number(form.port) || 22,
    username: form.username.trim(), use_sudo: form.use_sudo, environment: form.environment.trim() || null,
    key_path: keyMode.value === 'file' ? form.key_path : null,
    private_key: keyMode.value === 'paste' && form.private_key.trim() ? form.private_key : null,
    passphrase: form.passphrase || null,
  }
}
const canSave = computed(() => form.name.trim() && form.host.trim() && form.username.trim()
  && (keyMode.value === 'file' ? form.key_path : form.private_key.trim() || props.server?.has_private_key))

async function test() {
  busy.value = 'test'
  errorMsg.value = ''
  tested.value = null
  try {
    tested.value = await api.testServer(payload())
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    busy.value = ''
  }
}
async function save() {
  busy.value = 'save'
  errorMsg.value = ''
  try {
    const body = payload()
    const s = editing.value ? await api.updateServer(props.server.id, body) : await api.createServer(body)
    toast(editing.value ? 'Servidor actualizado' : `Servidor ${s.name} agregado`, 'info')
    emit('saved', s)
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <Modal :title="editing ? 'Editar servidor' : 'Agregar servidor'" @close="emit('close')">
    <form class="modal-body" @submit.prevent="save">
      <label v-if="!editing && cfg.aliases.length" class="field">Importar de ~/.ssh/config
        <select class="select" @change="importAlias($event.target.value)">
          <option value="">Elegir un host…</option>
          <option v-for="a in cfg.aliases" :key="a.alias" :value="a.alias">{{ a.alias }} — {{ a.user ? a.user + '@' : '' }}{{ a.host }}</option>
        </select>
      </label>
      <div class="two">
        <label class="field">Nombre<input v-model="form.name" class="input" placeholder="app-staging" maxlength="100" /></label>
        <label class="field">Entorno <span class="hint">opcional</span><input v-model="form.environment" class="input" placeholder="staging, producción…" /></label>
      </div>
      <div class="three">
        <label class="field">Host o IP<input v-model="form.host" class="input" placeholder="100.64.0.10" /></label>
        <label class="field">Puerto<input v-model="form.port" class="input" type="number" min="1" max="65535" /></label>
        <label class="field">Usuario<input v-model="form.username" class="input" placeholder="deploy" /></label>
      </div>
      <div class="field">Llave SSH
        <div class="segmented" role="group" aria-label="Llave">
          <button type="button" :aria-pressed="keyMode === 'file'" @click="keyMode = 'file'">De ~/.ssh</button>
          <button type="button" :aria-pressed="keyMode === 'paste'" @click="keyMode = 'paste'">Pegar llave</button>
        </div>
      </div>
      <select v-if="keyMode === 'file'" v-model="form.key_path" class="select" aria-label="Archivo de llave">
        <option v-for="k in cfg.keys" :key="k" :value="k">~/.ssh/{{ k }}</option>
      </select>
      <label v-else class="field">Llave privada <span class="hint">se guarda cifrada{{ server?.has_private_key ? '; vacío mantiene la actual' : '' }}</span>
        <textarea v-model="form.private_key" class="input mono" rows="4" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea>
      </label>
      <label class="field">Passphrase <span class="hint">solo si la llave la tiene</span>
        <input v-model="form.passphrase" class="input" type="password" autocomplete="off" />
      </label>
      <label class="check"><input v-model="form.use_sudo" type="checkbox" /> Usar <code>sudo -n</code> para lecturas que lo necesitan (puertos con proceso, journal, docker, postgres)</label>
      <div class="note">
        Solo se ejecutan comandos de lectura fijos (métricas, <code>ss</code>, <code>systemctl show</code>, <code>journalctl</code>, <code>tail</code>…). La huella del servidor se guarda la primera vez y la conexión se rechaza si cambia.
      </div>
      <p v-if="tested" class="ok-text">Conecta a <strong>{{ tested.hostname }}</strong> como <strong>{{ tested.user }}</strong> · sudo sin clave: {{ tested.sudo ? 'sí' : 'no' }} · huella <code>{{ tested.host_key }}</code></p>
      <p v-if="errorMsg" class="error-text">{{ errorMsg }}</p>
    </form>
    <div class="modal-foot">
      <button class="btn" :disabled="!canSave || !!busy" @click="test">{{ busy === 'test' ? 'Probando…' : 'Probar conexión' }}</button>
      <button class="btn primary" :disabled="!canSave || !!busy" @click="save">{{ busy === 'save' ? 'Conectando…' : editing ? 'Guardar' : 'Agregar servidor' }}</button>
    </div>
  </Modal>
</template>

<style scoped>
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.three { display: grid; grid-template-columns: 2fr 90px 1fr; gap: 12px; }
.check { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; }
.check input { accent-color: var(--accent); margin-top: 3px; }
.ok-text { margin: 0; color: var(--st-success); font-size: 13px; overflow-wrap: anywhere; }
.error-text { margin: 0; }
@media (max-width: 560px) { .two, .three { grid-template-columns: 1fr; } }
</style>
