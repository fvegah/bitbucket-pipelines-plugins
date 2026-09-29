<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api, toast } from '../api'
import { PROVIDER_LABEL, REVIEW_LABEL, STATUS_LABEL, ago, fullDate, shortSha } from '../format'
import { renderMarkdown } from '../markdown'
import PrIcon from '../components/PrIcon.vue'
import ProviderIcon from '../components/ProviderIcon.vue'
import StatusIcon from '../components/StatusIcon.vue'
import DiffView from '../components/DiffView.vue'
import Icon from '../components/Icon.vue'

const props = defineProps({ id: { type: String, required: true } })
const emit = defineEmits(['changed'])

const pr = ref(null)
const error = ref('')
const now = ref(Date.now())
const tab = ref('conversation')
const busy = ref('')
const openFiles = reactive(new Set())
const comment = ref('')
const panel = ref('') // 'changes' | 'merge' | 'decline'
const changesBody = ref('')
const merge = reactive({ strategy: 'merge', close: false, message: '' })

async function load(quiet = false) {
  try {
    const data = await api.pr(props.id, { quiet })
    const first = !pr.value
    pr.value = data
    error.value = data.error || ''
    if (first) {
      data.files.slice(0, data.files.length <= 8 ? 8 : 0).forEach((f) => openFiles.add(f.path))
    }
  } catch (e) {
    if (!pr.value) error.value = e.message
  }
  now.value = Date.now()
}
let timer
onMounted(() => {
  load()
  timer = setInterval(() => !document.hidden && !busy.value && load(true), 30000)
})
onBeforeUnmount(() => clearInterval(timer))

const isOpen = computed(() => pr.value?.state === 'open')
const canReview = computed(() => isOpen.value && !pr.value.is_mine)
const inlineComments = computed(() => {
  const map = {}
  for (const c of pr.value?.comments || []) if (c.path) (map[c.path] ||= []).push(c)
  return map
})
const generalComments = computed(() => (pr.value?.comments || []).filter((c) => !c.path))
const conflicts = computed(() => pr.value?.mergeable === false || pr.value?.merge_state === 'dirty')
const mergeHint = computed(() => {
  const p = pr.value
  if (!p || !isOpen.value) return ''
  if (p.draft) return 'Es un borrador.'
  if (conflicts.value) return 'Tiene conflictos con la rama destino.'
  if (p.merge_state === 'blocked') return 'GitHub lo bloquea: faltan aprobaciones o checks requeridos.'
  if (p.merge_state === 'behind') return 'La rama está atrasada respecto del destino.'
  if (p.changes_requested) return 'Hay cambios pedidos.'
  if (p.ci?.status === 'failed') return 'El CI falló.'
  if (!p.approvals) return 'Nadie lo ha aprobado todavía.'
  return ''
})

async function act(action, body = {}, okMsg = '') {
  busy.value = action
  try {
    await api.prAction(pr.value.id, action, body)
    if (okMsg) toast(okMsg, 'info')
    panel.value = ''
    emit('changed')
    await load(true)
  } catch {
    /* toast */
  } finally {
    busy.value = ''
  }
}
async function sendComment() {
  if (!comment.value.trim()) return
  await act('comment', { body: comment.value.trim() }, 'Comentario publicado')
  if (!busy.value) comment.value = ''
}
function toggleFile(path) {
  openFiles.has(path) ? openFiles.delete(path) : openFiles.add(path)
}
function allFiles(open) {
  for (const f of pr.value.files) open ? openFiles.add(f.path) : openFiles.delete(f.path)
}
const STRATEGIES = computed(() => pr.value?.provider === 'bitbucket'
  ? [['merge', 'Merge commit'], ['squash', 'Squash'], ['rebase', 'Fast-forward']]
  : [['merge', 'Merge commit'], ['squash', 'Squash and merge'], ['rebase', 'Rebase and merge']])
const FILE_STATUS = { added: 'nuevo', removed: 'borrado', renamed: 'renombrado', modified: '', conflict: 'conflicto' }
</script>

<template>
  <main class="page detail">
    <RouterLink to="/prs" class="back"><Icon name="chevron" :size="13" style="transform: rotate(180deg)" /> Pull requests</RouterLink>

    <div v-if="!pr && !error" class="card empty">Cargando…</div>
    <div v-else-if="!pr" class="card empty"><h2>No se pudo cargar</h2><p>{{ error }}</p></div>

    <template v-else>
      <section class="card head">
        <div class="head-top">
          <PrIcon :state="pr.state" :draft="pr.draft" :size="24" />
          <div class="grow">
            <h1 class="title">{{ pr.title }} <span class="faint">#{{ pr.number }}</span></h1>
            <div class="sub">
              <span class="badge" :class="pr.draft && isOpen ? 'draft' : pr.state">
                {{ pr.draft && isOpen ? 'Borrador' : pr.state === 'open' ? 'Abierto' : pr.state === 'merged' ? 'Mergeado' : 'Cerrado' }}
              </span>
              <span class="repo"><ProviderIcon :provider="pr.provider" :size="14" />
                <a :href="pr.repo.html_url" target="_blank" rel="noopener">{{ pr.repo.full_name }}</a></span>
              <span class="author"><img v-if="pr.author_avatar" :src="pr.author_avatar" alt="" width="18" height="18" />{{ pr.author }}</span>
              <span>quiere mergear</span>
              <span class="chip">{{ pr.source_branch }}</span><span aria-hidden="true">→</span><span class="chip">{{ pr.target_branch }}</span>
            </div>
          </div>
          <div class="head-actions">
            <template v-if="canReview">
              <button v-if="pr.my_review !== 'approved'" class="btn" :disabled="!!busy" @click="act('approve', {}, 'Aprobado')">
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" /></svg>
                Aprobar
              </button>
              <button v-else-if="pr.provider === 'bitbucket'" class="btn" :disabled="!!busy" @click="act('unapprove', {}, 'Aprobación retirada')">Quitar aprobación</button>
              <button class="btn" :class="{ on: panel === 'changes' }" :aria-expanded="panel === 'changes'" @click="panel = panel === 'changes' ? '' : 'changes'">Pedir cambios</button>
            </template>
            <button v-if="isOpen" class="btn primary" :aria-expanded="panel === 'merge'" :disabled="pr.draft" @click="panel = panel === 'merge' ? '' : 'merge'">
              <PrIcon state="merged" :size="15" decorative style="color: inherit" /> Mergear
            </button>
            <a class="btn" :href="pr.url" target="_blank" rel="noopener"><Icon name="external" /> {{ PROVIDER_LABEL[pr.provider] }}</a>
          </div>
        </div>

        <form v-if="panel === 'changes'" class="panel" @submit.prevent="act('request_changes', { body: changesBody.trim() }, 'Cambios pedidos')">
          <label class="field">Qué hay que cambiar
            <span class="hint">{{ pr.provider === 'github' ? 'Obligatorio en GitHub.' : 'Opcional: se publica como comentario.' }}</span>
            <textarea v-model="changesBody" class="input" rows="3"></textarea>
          </label>
          <div class="panel-actions">
            <button type="button" class="btn" @click="panel = ''">Cancelar</button>
            <button class="btn danger" :disabled="!!busy || (pr.provider === 'github' && !changesBody.trim())">Pedir cambios</button>
          </div>
        </form>

        <form v-if="panel === 'merge'" class="panel" @submit.prevent="act('merge', { strategy: merge.strategy, close_source_branch: merge.close, body: merge.message.trim() || null }, 'Mergeado')">
          <p v-if="mergeHint" class="warn">{{ mergeHint }}</p>
          <div class="merge-grid">
            <label class="field">Estrategia
              <select v-model="merge.strategy" class="select">
                <option v-for="[v, l] in STRATEGIES" :key="v" :value="v">{{ l }}</option>
              </select>
            </label>
            <label class="field">Mensaje <span class="hint">opcional</span>
              <input v-model="merge.message" class="input" :placeholder="pr.provider === 'github' ? 'Título del commit de merge' : 'Mensaje del merge'" />
            </label>
          </div>
          <label class="check"><input v-model="merge.close" type="checkbox" /> Borrar la rama <code>{{ pr.source_branch }}</code> después del merge</label>
          <div class="panel-actions">
            <button type="button" class="btn" @click="panel = ''">Cancelar</button>
            <button class="btn primary" :disabled="!!busy">{{ busy === 'merge' ? 'Mergeando…' : `Confirmar merge en ${pr.target_branch}` }}</button>
          </div>
        </form>

        <p v-if="error" class="error-text">No se pudo refrescar desde {{ PROVIDER_LABEL[pr.provider] }}: {{ error }}</p>
      </section>

      <div class="layout">
        <section class="main">
          <nav class="tabs" aria-label="Secciones">
            <button :class="{ active: tab === 'conversation' }" @click="tab = 'conversation'">Conversación <span class="n">{{ generalComments.length }}</span></button>
            <button :class="{ active: tab === 'files' }" @click="tab = 'files'">Archivos <span class="n">{{ pr.files.length }}</span></button>
            <button :class="{ active: tab === 'commits' }" @click="tab = 'commits'">Commits <span class="n">{{ pr.commits.length }}</span></button>
          </nav>

          <template v-if="tab === 'conversation'">
            <article class="card comment">
              <header><img v-if="pr.author_avatar" :src="pr.author_avatar" alt="" width="22" height="22" /><strong>{{ pr.author }}</strong>
                <span class="faint" :title="fullDate(pr.created_at)">abrió {{ ago(pr.created_at, now) }}</span></header>
              <div v-if="pr.body" class="md" v-html="renderMarkdown(pr.body)"></div>
              <p v-else class="muted">Sin descripción.</p>
            </article>
            <article v-for="c in generalComments" :key="c.id" class="card comment">
              <header><img v-if="c.author_avatar" :src="c.author_avatar" alt="" width="22" height="22" /><strong>{{ c.author }}</strong>
                <span class="faint" :title="fullDate(c.created_at)">{{ ago(c.created_at, now) }}</span></header>
              <div class="md" v-html="renderMarkdown(c.body)"></div>
            </article>
            <p v-if="Object.keys(inlineComments).length" class="muted inline-note">
              {{ pr.comments.length - generalComments.length }} comentarios en el código: están en <button class="linkish" @click="tab = 'files'">Archivos</button>.
            </p>
            <form v-if="isOpen" class="card comment-box" @submit.prevent="sendComment">
              <label class="sr-only" for="new-comment">Comentario</label>
              <textarea id="new-comment" v-model="comment" class="input" rows="3" placeholder="Escribe un comentario (Markdown)…" @keydown.meta.enter="sendComment" @keydown.ctrl.enter="sendComment"></textarea>
              <div class="panel-actions">
                <span class="faint hint">⌘ + Enter para enviar</span>
                <button class="btn primary" :disabled="!comment.trim() || !!busy">Comentar</button>
              </div>
            </form>
          </template>

          <template v-else-if="tab === 'files'">
            <div class="files-bar">
              <span class="muted"><span class="add">+{{ pr.additions ?? 0 }}</span> <span class="del">−{{ pr.deletions ?? 0 }}</span> en {{ pr.files.length }} archivos</span>
              <span class="row"><button class="linkish" @click="allFiles(true)">Expandir todo</button><button class="linkish" @click="allFiles(false)">Contraer todo</button></span>
            </div>
            <div v-for="f in pr.files" :key="f.path" class="card file">
              <button class="file-head" :aria-expanded="openFiles.has(f.path)" @click="toggleFile(f.path)">
                <Icon name="chevron" :size="12" class="chev" :class="{ open: openFiles.has(f.path) }" />
                <span class="path truncate" :title="f.path">
                  <template v-if="f.old_path">{{ f.old_path }} → </template>{{ f.path }}
                </span>
                <span v-if="FILE_STATUS[f.status]" class="chip" :class="{ conflict: f.status === 'conflict' }">{{ FILE_STATUS[f.status] }}</span>
                <span v-if="inlineComments[f.path]" class="chip">{{ inlineComments[f.path].length }} 💬</span>
                <span class="stat"><span class="add">+{{ f.additions }}</span> <span class="del">−{{ f.deletions }}</span></span>
              </button>
              <template v-if="openFiles.has(f.path)">
                <DiffView v-if="f.patch" :patch="f.patch" />
                <p v-else class="muted nodiff">Sin diff para mostrar (binario o muy grande).</p>
                <div v-for="c in inlineComments[f.path] || []" :key="c.id" class="inline-comment">
                  <header><img v-if="c.author_avatar" :src="c.author_avatar" alt="" width="18" height="18" /><strong>{{ c.author }}</strong>
                    <span class="faint">línea {{ c.line ?? '?' }} · {{ ago(c.created_at, now) }}</span></header>
                  <div class="md" v-html="renderMarkdown(c.body)"></div>
                </div>
              </template>
            </div>
          </template>

          <div v-else class="card">
            <ul class="commits">
              <li v-for="c in pr.commits" :key="c.sha">
                <span class="grow truncate" :title="c.message">{{ c.message.split('\n')[0] }}</span>
                <span class="faint">{{ c.author }}</span>
                <span class="faint" :title="fullDate(c.date)">{{ ago(c.date, now) }}</span>
                <span class="chip mono">{{ shortSha(c.sha) }}</span>
              </li>
            </ul>
          </div>
        </section>

        <aside class="side">
          <section class="card box">
            <h3>Estado</h3>
            <ul class="facts">
              <li v-if="pr.state === 'merged'"><PrIcon state="merged" /> Mergeado<template v-if="pr.merged_by"> por {{ pr.merged_by }}</template> {{ ago(pr.closed_at, now) }}</li>
              <li v-else-if="pr.state === 'closed'"><PrIcon state="closed" /> Cerrado {{ ago(pr.closed_at, now) }}</li>
              <template v-else>
                <li v-if="conflicts"><StatusIcon status="failed" /> Tiene conflictos</li>
                <li v-else-if="pr.mergeable === true"><StatusIcon status="success" /> Sin conflictos</li>
                <li v-if="pr.ready"><StatusIcon status="success" /> Lista para mergear</li>
                <li v-else-if="mergeHint"><StatusIcon status="waiting" /> {{ mergeHint }}</li>
              </template>
              <li class="faint">Actualizado {{ ago(pr.updated_at, now) }}</li>
              <li v-if="pr.task_count" class="faint">{{ pr.task_count }} tareas abiertas</li>
            </ul>
          </section>

          <section class="card box">
            <h3>Revisores</h3>
            <p v-if="!pr.reviewers.length" class="muted small">Nadie asignado.</p>
            <ul class="people">
              <li v-for="r in pr.reviewers" :key="r.id">
                <img v-if="r.avatar" :src="r.avatar" alt="" width="22" height="22" />
                <span class="grow truncate">{{ r.name }}<template v-if="r.id === pr.me"> (tú)</template></span>
                <span class="badge" :class="{ success: r.state === 'approved', failed: r.state === 'changes_requested', waiting: r.state === 'pending', queued: r.state === 'commented' }">{{ REVIEW_LABEL[r.state] }}</span>
              </li>
            </ul>
          </section>

          <section class="card box">
            <h3>Checks</h3>
            <p v-if="!pr.checks.length && !pr.ci" class="muted small">Sin checks para el último commit.</p>
            <ul class="checks">
              <li v-for="r in pr.ci?.runs || []" :key="'run' + r.id">
                <StatusIcon :status="r.status" />
                <RouterLink :to="`/runs/${r.id}`" class="grow truncate">{{ r.workflow }}</RouterLink>
                <span v-if="r.number" class="faint">#{{ r.number }}</span>
              </li>
              <li v-for="(c, i) in pr.checks.filter((c) => !(pr.ci?.runs || []).some((r) => r.workflow === c.name))" :key="'chk' + i">
                <StatusIcon :status="c.status" />
                <a v-if="c.url" :href="c.url" target="_blank" rel="noopener" class="grow truncate">{{ c.name }}</a>
                <span v-else class="grow truncate">{{ c.name }}</span>
                <span class="faint small">{{ STATUS_LABEL[c.status] }}</span>
              </li>
            </ul>
          </section>

          <button v-if="isOpen && panel !== 'decline'" class="btn ghost danger decline" @click="panel = 'decline'">
            {{ pr.provider === 'bitbucket' ? 'Declinar PR' : 'Cerrar PR' }}
          </button>
          <div v-if="panel === 'decline'" class="card box">
            <p class="small">¿{{ pr.provider === 'bitbucket' ? 'Declinar' : 'Cerrar' }} este PR sin mergear?</p>
            <div class="panel-actions">
              <button class="btn sm" @click="panel = ''">No</button>
              <button class="btn sm danger" :disabled="!!busy" @click="act('decline', {}, 'PR cerrado')">Sí, {{ pr.provider === 'bitbucket' ? 'declinar' : 'cerrar' }}</button>
            </div>
          </div>
        </aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
.detail { max-width: 1360px; }
.back { display: inline-flex; align-items: center; gap: 4px; color: var(--text-muted); font-size: 13px; font-weight: 550; margin-bottom: 12px; }
.back:hover { color: var(--text); }
.head { padding: 18px 20px; margin-bottom: 14px; }
.head-top { display: flex; gap: 14px; align-items: flex-start; flex-wrap: wrap; }
.head-top > .pr-icon { margin-top: 2px; }
.title { font-size: 19px; overflow-wrap: anywhere; }
.title .faint { font-weight: 400; }
.sub { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 6px; color: var(--text-muted); font-size: 13px; }
.repo, .author { display: inline-flex; align-items: center; gap: 5px; font-weight: 600; }
.author img { border-radius: 50%; }
.sub .chip { max-width: 300px; overflow: hidden; text-overflow: ellipsis; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.head-actions .btn.on { background: var(--accent-soft); }
.panel { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); display: grid; gap: 12px; }
.panel-actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; }
.panel-actions .hint { margin-right: auto; font-size: 12px; }
.merge-grid { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 12px; }
.check { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.check input { accent-color: var(--accent); width: 16px; height: 16px; }
.warn { margin: 0; padding: 8px 12px; border-radius: var(--radius-sm); background: var(--st-waiting-soft); color: var(--st-waiting); font-size: 13px; font-weight: 550; }

.layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
.main { min-width: 0; display: grid; gap: 12px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); }
.tabs button { display: inline-flex; align-items: center; gap: 7px; padding: 8px 12px; margin-bottom: -1px; border: 0; border-bottom: 2px solid transparent; background: none; color: var(--text-muted); font: inherit; font-weight: 600; cursor: pointer; }
.tabs button:hover { color: var(--text); }
.tabs button.active { color: var(--text); border-bottom-color: var(--accent); }
.n { min-width: 20px; height: 20px; padding: 0 6px; border-radius: 99px; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-muted); font-size: 11.5px; display: inline-flex; align-items: center; justify-content: center; }
.comment { padding: 12px 16px; }
.comment header, .inline-comment header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 13px; }
.comment header img, .inline-comment header img, .people img { border-radius: 50%; }
.inline-note { margin: 0; font-size: 13px; }
.linkish { border: 0; background: none; padding: 0; color: var(--accent); font: inherit; cursor: pointer; }
.linkish:hover { text-decoration: underline; }
.comment-box { padding: 12px; display: grid; gap: 10px; }
.files-bar { display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
.files-bar .row { gap: 14px; }
.add { color: var(--st-success); font-weight: 600; }
.del { color: var(--st-failed); font-weight: 600; }
.file { overflow: hidden; }
.file-head { width: 100%; display: flex; align-items: center; gap: 8px; padding: 9px 12px; border: 0; background: var(--surface-2); color: var(--text); font: 12.5px var(--mono); cursor: pointer; text-align: left; }
.file-head:hover { background: var(--surface-hover); }
.path { flex: 1; min-width: 0; }
.chip.conflict { color: var(--st-failed); border-color: var(--st-failed); }
.stat { font-family: var(--font); font-size: 12px; white-space: nowrap; }
.chev { transition: transform .12s; flex: none; }
.chev.open { transform: rotate(90deg); }
.nodiff { padding: 12px 16px; margin: 0; font-size: 13px; }
.inline-comment { border-top: 1px solid var(--border); padding: 10px 16px; background: var(--surface); }
.commits { list-style: none; margin: 0; padding: 0; }
.commits li { display: flex; align-items: center; gap: 10px; padding: 9px 14px; border-bottom: 1px solid var(--border); font-size: 13px; min-width: 0; }
.commits li:last-child { border-bottom: 0; }

.side { display: grid; gap: 12px; position: sticky; top: 70px; }
.box { padding: 12px 14px; }
.box h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); margin-bottom: 8px; }
.facts, .people, .checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; font-size: 13px; }
.facts li, .people li, .checks li { display: flex; align-items: center; gap: 8px; min-width: 0; }
.small { font-size: 12.5px; margin: 0; }
.decline { justify-self: start; }
@media (max-width: 960px) {
  .layout { grid-template-columns: minmax(0, 1fr); }
  .side { position: static; }
  .tabs { overflow-x: auto; }
  .merge-grid { grid-template-columns: 1fr; }
}
</style>
