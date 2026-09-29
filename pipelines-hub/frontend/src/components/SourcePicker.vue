<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, toast } from '../api'
import Modal from './Modal.vue'

const props = defineProps({ account: { type: Object, required: true } })
const emit = defineEmits(['close', 'saved'])

const isBB = computed(() => props.account.provider === 'bitbucket')
const isCF = computed(() => props.account.provider === 'cloudflare')
const noun = computed(() => (isCF.value ? 'cuenta' : isBB.value ? 'workspace' : 'organización'))
const nounPlural = computed(() => (isCF.value ? 'cuentas' : isBB.value ? 'workspaces' : 'organizaciones'))
const found = ref([])
const loading = ref(true)
const loadError = ref('')
const selected = reactive(new Set())
const manual = reactive({ slug: '', kind: isCF.value ? 'account' : isBB.value ? 'workspace' : 'org' })
const busy = ref(false)

onMounted(async () => {
  try {
    found.value = await api.discover(props.account.id)
  } catch (e) {
    loadError.value = e.message
  } finally {
    loading.value = false
  }
})

function toggle(slug) {
  selected.has(slug) ? selected.delete(slug) : selected.add(slug)
}

async function save() {
  busy.value = true
  const items = found.value.filter((f) => selected.has(f.slug))
  if (manual.slug.trim()) items.push({ kind: manual.kind, slug: manual.slug.trim(), name: manual.slug.trim() })
  let ok = 0
  for (const f of items) {
    try {
      await api.addSource(props.account.id, {
        kind: f.kind, slug: f.slug, display_name: f.name, avatar_url: f.avatar_url,
      })
      ok++
    } catch {
      /* toast */
    }
  }
  busy.value = false
  if (ok) {
    toast(`${ok} ${ok === 1 ? noun.value : nounPlural.value} agregada(s). Sincronizando…`, 'info')
    emit('saved')
  }
}

const KIND = { org: 'Organización', user: 'Usuario', workspace: 'Workspace', account: 'Cuenta' }
const count = computed(() => selected.size + (manual.slug.trim() ? 1 : 0))
</script>

<template>
  <Modal :title="`Agregar ${nounPlural}`" @close="emit('close')">
    <div class="modal-body">
      <p class="muted intro">
        <template v-if="isCF">Se siguen los Workers y proyectos de Pages con deploys recientes de cada cuenta</template>
        <template v-else>Se siguen los repos con actividad reciente de cada {{ noun }}</template>
        (por defecto, los 30 más activos de los últimos 45 días). Lo puedes ajustar después.
      </p>
      <div v-if="loading" class="muted">Buscando lo que ve esta cuenta…</div>
      <p v-else-if="loadError" class="error-text">No se pudo listar: {{ loadError }}</p>
      <ul v-else-if="found.length" class="found">
        <li v-for="f in found" :key="f.slug">
          <label :class="{ disabled: f.added }">
            <input type="checkbox" :checked="f.added || selected.has(f.slug)" :disabled="f.added" @change="toggle(f.slug)" />
            <img v-if="f.avatar_url" :src="f.avatar_url" alt="" width="24" height="24" />
            <span v-else class="ph" aria-hidden="true">{{ (f.name || f.slug)[0] }}</span>
            <span class="grow">
              <strong>{{ f.name || f.slug }}</strong>
              <span class="faint"> · {{ KIND[f.kind] }}<template v-if="f.name && f.name !== f.slug"> · {{ f.slug }}</template></span>
            </span>
            <span v-if="f.added" class="chip">Agregada</span>
          </label>
        </li>
      </ul>
      <p v-else class="muted">El token no ve {{ nounPlural }}; agrégala a mano.</p>

      <p v-if="!isBB && !isCF" class="note">
        ¿Falta una organización? Un token <strong>fine-grained</strong> solo ve al dueño que elegiste al
        crearlo (tu usuario o una org). Para ver todas, usa un token <strong>classic</strong> con
        <code>repo</code> y <code>read:org</code>, y si la org usa SSO, autorízalo con <em>Configure SSO</em>.
      </p>
      <fieldset class="manual">
        <legend>O escribe el slug</legend>
        <div class="row">
          <select v-if="!isBB && !isCF" v-model="manual.kind" class="select" aria-label="Tipo">
            <option value="org">Organización</option>
            <option value="user">Usuario</option>
          </select>
          <input v-model="manual.slug" class="input grow" :placeholder="isCF ? 'nombre o ID de la cuenta' : isBB ? 'mi-workspace' : 'mi-organizacion'" aria-label="Slug" />
        </div>
      </fieldset>
    </div>
    <div class="modal-foot">
      <button class="btn" @click="emit('close')">Cancelar</button>
      <button class="btn primary" :disabled="!count || busy" @click="save">
        {{ busy ? 'Agregando…' : count ? `Agregar ${count}` : 'Agregar' }}
      </button>
    </div>
  </Modal>
</template>

<style scoped>
.intro { margin: 0; font-size: 13px; }
.found { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border); border-radius: var(--radius); max-height: 320px; overflow: auto; }
.found li + li { border-top: 1px solid var(--border); }
.found label { display: flex; align-items: center; gap: 10px; padding: 9px 12px; cursor: pointer; font-size: 13px; }
.found label:hover { background: var(--surface-hover); }
.found label.disabled { cursor: default; opacity: .75; }
.found img, .ph { width: 24px; height: 24px; border-radius: 6px; flex: none; }
.ph { display: grid; place-items: center; background: var(--surface-2); color: var(--text-muted); font-weight: 700; text-transform: uppercase; font-size: 12px; }
.found input { accent-color: var(--accent); width: 16px; height: 16px; }
.manual { border: 0; padding: 0; margin: 0; display: grid; gap: 6px; }
.manual legend { font-size: 13px; font-weight: 550; margin-bottom: 6px; }
</style>
