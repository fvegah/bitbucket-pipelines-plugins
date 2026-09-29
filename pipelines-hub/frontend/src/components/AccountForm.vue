<script setup>
import { computed, reactive, ref } from 'vue'
import { api, toast } from '../api'
import Modal from './Modal.vue'
import ProviderIcon from './ProviderIcon.vue'

const props = defineProps({ account: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved'])

const editing = computed(() => !!props.account)
const form = reactive({
  provider: props.account?.provider || 'github',
  name: props.account?.name || '',
  token: '',
  username: props.account?.username || '',
  api_url: props.account?.api_url || '',
})
const advanced = ref(!!props.account?.api_url)
const tested = ref(null)
const busy = ref('')
const errorMsg = ref('')

const canSubmit = computed(() => form.name.trim() && (editing.value || form.token.trim()))

function payload() {
  return {
    provider: form.provider,
    name: form.name.trim(),
    token: form.token.trim(),
    username: form.provider === 'bitbucket' ? form.username.trim() : '',
    api_url: form.api_url.trim(),
  }
}

async function test() {
  busy.value = 'test'
  errorMsg.value = ''
  tested.value = null
  try {
    tested.value = await api.testAccount(payload())
    if (!form.name.trim()) form.name = `${{ github: 'GitHub', bitbucket: 'Bitbucket', cloudflare: 'Cloudflare' }[form.provider]} · ${tested.value.login}`
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
    let acc
    if (editing.value) {
      const body = { name: form.name.trim(), api_url: form.api_url.trim() }
      if (form.token.trim()) body.token = form.token.trim()
      if (form.provider === 'bitbucket') body.username = form.username.trim()
      acc = await api.updateAccount(props.account.id, body)
      toast('Cuenta actualizada', 'info')
    } else {
      acc = await api.createAccount(payload())
      toast(`Cuenta conectada como ${acc.login}`, 'info')
    }
    emit('saved', acc)
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <Modal :title="editing ? 'Editar cuenta' : 'Agregar cuenta'" @close="emit('close')">
    <form class="modal-body" @submit.prevent="save">
      <div v-if="!editing" class="providers" role="radiogroup" aria-label="Proveedor">
        <button v-for="p in ['github', 'bitbucket', 'cloudflare']" :key="p" type="button" class="prov-opt" role="radio"
                :aria-checked="form.provider === p" @click="form.provider = p; tested = null; errorMsg = ''">
          <ProviderIcon :provider="p" :size="20" />
          <span>{{ { github: 'GitHub', bitbucket: 'Bitbucket', cloudflare: 'Cloudflare' }[p] }}</span>
        </button>
      </div>

      <label class="field">Nombre
        <input v-model="form.name" class="input" placeholder="Ej: GitHub trabajo" maxlength="100" />
      </label>

      <template v-if="form.provider === 'bitbucket'">
        <label class="field">Email de Atlassian
          <span class="hint">Déjalo vacío si usas un access token de workspace o repositorio.</span>
          <input v-model="form.username" class="input" type="email" autocomplete="off" placeholder="tu-email@empresa.com" />
        </label>
        <label class="field">API token
          <span v-if="editing" class="hint">Déjalo vacío para mantener el actual.</span>
          <input v-model="form.token" class="input mono" type="password" autocomplete="off" placeholder="ATATT3x…" />
        </label>
        <div class="note">
          Créalo en <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" rel="noopener">id.atlassian.com → API tokens</a>
          con <strong>Create API token with scopes</strong> → Bitbucket. Scopes:
          <ul>
            <li><code>read:user:bitbucket</code>, <code>read:workspace:bitbucket</code>, <code>read:repository:bitbucket</code></li>
            <li><code>read:pipeline:bitbucket</code> (y <code>write:pipeline:bitbucket</code> para re-ejecutar o detener)</li>
            <li><code>read:pullrequest:bitbucket</code> (y <code>write:pullrequest:bitbucket</code> para aprobar, comentar, mergear o declinar)</li>
          </ul>
        </div>
      </template>

      <template v-else-if="form.provider === 'cloudflare'">
        <label class="field">API token
          <span v-if="editing" class="hint">Déjalo vacío para mantener el actual.</span>
          <input v-model="form.token" class="input mono" type="password" autocomplete="off" placeholder="Token de usuario de Cloudflare" />
        </label>
        <div class="note">
          Créalo en <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" rel="noopener">My Profile → API Tokens</a>
          → <strong>Create Token → Custom token</strong>. Tiene que ser de <strong>usuario</strong> (no de cuenta): la API de Workers Builds no acepta tokens de cuenta. Permisos de <em>Account</em>:
          <ul>
            <li><code>Account Settings: Read</code> (listar tus cuentas/organizaciones)</li>
            <li><code>Workers Scripts: Read</code> y <code>Workers Builds Configuration: Read</code> (en la API figura como <em>Workers CI</em>; <em>Edit</em> para re-lanzar o cancelar builds)</li>
            <li><code>Cloudflare Pages: Read</code> (<em>Edit</em> para reintentar deployments)</li>
          </ul>
          En <em>Account Resources</em> elige <strong>All accounts</strong> o las que quieras ver. Opcional: <code>User Details: Read</code> para mostrar tu email.
        </div>
      </template>

      <template v-else>
        <label class="field">Personal access token
          <span v-if="editing" class="hint">Déjalo vacío para mantener el actual.</span>
          <input v-model="form.token" class="input mono" type="password" autocomplete="off" placeholder="ghp_… o github_pat_…" />
        </label>
        <div class="note">
          Classic: scopes <code>repo</code> y <code>read:org</code> (más <code>workflow</code> para re-ejecutar). <code>repo</code> ya cubre los PR.
          Fine-grained: <em>Actions</em>, <em>Deployments</em>, <em>Pull requests</em>, <em>Contents</em> y <em>Commit statuses</em> de lectura (escritura en Actions y Pull requests para actuar), sobre los repos que quieras ver.
          Si usas <code>gh</code>, <code>gh auth token</code> te entrega uno que sirve.
        </div>
        <button type="button" class="linkish" @click="advanced = !advanced">{{ advanced ? 'Ocultar' : 'Opciones avanzadas' }}</button>
        <label v-if="advanced" class="field">URL de la API (GitHub Enterprise)
          <input v-model="form.api_url" class="input" placeholder="https://github.miempresa.com/api/v3" />
        </label>
      </template>

      <p v-if="tested" class="ok-text">Conecta como <strong>{{ tested.login }}</strong><template v-if="tested.name"> ({{ tested.name }})</template>.</p>
      <p v-if="errorMsg" class="error-text">{{ errorMsg }}</p>
    </form>
    <div class="modal-foot">
      <button v-if="!editing" class="btn" :disabled="!form.token.trim() || !!busy" @click="test">
        {{ busy === 'test' ? 'Probando…' : 'Probar conexión' }}
      </button>
      <button class="btn primary" :disabled="!canSubmit || !!busy" @click="save">
        {{ busy === 'save' ? 'Guardando…' : editing ? 'Guardar' : 'Conectar cuenta' }}
      </button>
    </div>
  </Modal>
</template>

<style scoped>
.providers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
@media (max-width: 520px) { .providers { grid-template-columns: 1fr; } }
.prov-opt {
  display: flex; align-items: center; gap: 10px; padding: 12px 14px;
  border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--surface);
  color: var(--text); font: inherit; font-weight: 600; cursor: pointer;
}
.prov-opt:hover { background: var(--surface-hover); }
.prov-opt[aria-checked='true'] { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); background: var(--accent-soft); }
.linkish { justify-self: start; border: 0; background: none; padding: 0; color: var(--accent); font: 13px var(--font); cursor: pointer; }
.linkish:hover { text-decoration: underline; }
.ok-text { margin: 0; color: var(--st-success); font-size: 13px; }
.error-text { margin: 0; }
</style>
