<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, toast } from '../api'
import {
  ACTIVE, PROVIDER_LABEL, STATUS_LABEL, ago, cleanBranch, commitUrl, duration, elapsed, fullDate, shortSha,
} from '../format'
import StatusIcon from '../components/StatusIcon.vue'
import ProviderIcon from '../components/ProviderIcon.vue'
import LogViewer from '../components/LogViewer.vue'
import Icon from '../components/Icon.vue'

const props = defineProps({ id: { type: String, required: true } })
const emit = defineEmits(['changed'])
const route = useRoute()
const router = useRouter()

const run = ref(null)
const error = ref('')
const now = ref(Date.now())
const busy = ref('')
const openJobs = ref(new Set())

const steps = computed(() => run.value?.steps || [])
const selectedId = computed(() => route.query.step || defaultStep()?.id)
const selected = computed(() => steps.value.find((s) => s.id === selectedId.value))
const isActive = computed(() => run.value && ACTIVE.has(run.value.status))

function defaultStep() {
  const s = steps.value
  return s.find((x) => x.status === 'failed') || s.find((x) => x.status === 'running') ||
    [...s].reverse().find((x) => x.started_at) || s[0]
}

function select(step) {
  router.replace({ query: { ...route.query, step: step.id } })
  if (step.substeps?.length) openJobs.value.add(step.id)
}
function toggleJob(step) {
  const set = new Set(openJobs.value)
  set.has(step.id) ? set.delete(step.id) : set.add(step.id)
  openJobs.value = set
}

let timer
async function load() {
  try {
    run.value = await api.run(props.id, { quiet: !!run.value })
    error.value = run.value.error || ''
    if (selected.value?.substeps?.length) openJobs.value.add(selected.value.id)
  } catch (e) {
    if (!run.value) error.value = e.message
  }
  now.value = Date.now()
  clearTimeout(timer)
  if (isActive.value) {
    const wait = run.value.status === 'waiting' ? 30000 : 5000
    timer = setTimeout(load, document.hidden ? Math.max(wait, 15000) : wait)
  }
}
const tick = setInterval(() => (now.value = Date.now()), 1000)
onMounted(load)
onBeforeUnmount(() => {
  clearTimeout(timer)
  clearInterval(tick)
})
watch(() => props.id, load)

function stepDuration(s) {
  if (s.status === 'running') return duration(elapsed(s.started_at, null, now.value))
  if (s.duration_s != null) return duration(s.duration_s)
  if (s.started_at && s.finished_at) return duration(elapsed(s.started_at, s.finished_at))
  return ''
}
const runDuration = computed(() => {
  const r = run.value
  if (!r) return ''
  if (r.status === 'running') return duration(elapsed(r.started_at, null, now.value))
  return duration(r.duration_s)
})

async function action(kind, failedOnly = false) {
  busy.value = kind
  try {
    if (kind === 'cancel') {
      await api.cancel(run.value.id)
      toast('Cancelación enviada', 'info')
    } else {
      await api.rerun(run.value.id, failedOnly)
      toast(run.value.provider === 'github' ? 'Re-ejecución enviada'
        : 'Ejecución nueva lanzada; aparecerá en la lista en unos segundos', 'info')
    }
    emit('changed')
    setTimeout(load, 2500)
  } catch {
    /* toast */
  } finally {
    busy.value = ''
  }
}

const logName = computed(() => {
  if (!run.value || !selected.value) return 'log'
  const slug = (s) => s.replace(/[^\w.-]+/g, '-').replace(/-+/g, '-').slice(0, 60)
  return `${slug(run.value.repo.name)}-${run.value.number}-${slug(selected.value.name)}`
})
</script>

<template>
  <main class="page detail">
    <RouterLink to="/" class="back"><Icon name="chevron" :size="13" style="transform: rotate(180deg)" /> Ejecuciones</RouterLink>

    <div v-if="!run && !error" class="card empty">Cargando…</div>
    <div v-else-if="!run" class="card empty"><h2>No se pudo cargar</h2><p>{{ error }}</p></div>

    <template v-else>
      <section class="card head">
        <div class="head-top">
          <StatusIcon :status="run.status" :size="24" />
          <div class="grow">
            <h1 class="title">{{ run.title || run.workflow }}</h1>
            <div class="sub">
              <span class="repo"><ProviderIcon :provider="run.provider" :size="14" />
                <a :href="run.repo.html_url" target="_blank" rel="noopener">{{ run.repo.full_name }}</a></span>
              <template v-if="run.workflow && run.workflow !== run.title">
                <span class="faint" aria-hidden="true">·</span>
                <span>{{ run.workflow }}</span>
              </template>
              <span v-if="run.number" class="faint">#{{ run.number }}<template v-if="run.attempt > 1"> · intento {{ run.attempt }}</template></span>
            </div>
          </div>
          <div class="head-actions">
            <button v-if="isActive" class="btn danger" :disabled="!!busy" @click="action('cancel')">
              <Icon name="stop" /> {{ run.provider === 'bitbucket' ? 'Detener' : 'Cancelar' }}
            </button>
            <template v-else>
              <button v-if="run.provider === 'github' && run.status === 'failed'" class="btn" :disabled="!!busy" @click="action('rerun', true)">
                <Icon name="refresh" /> Re-ejecutar fallidos
              </button>
              <button class="btn" :disabled="!!busy" @click="action('rerun')"
                      :title="{ bitbucket: 'Lanza un pipeline nuevo con el mismo target', cloudflare: 'Lanza un build nuevo del mismo commit' }[run.provider] || ''">
                <Icon name="refresh" :class="{ spin: busy === 'rerun' }" /> Re-ejecutar
              </button>
            </template>
            <a class="btn" :href="run.url" target="_blank" rel="noopener"><Icon name="external" /> {{ PROVIDER_LABEL[run.provider] }}</a>
          </div>
        </div>
        <dl class="facts">
          <div><dt>Estado</dt><dd><span class="badge" :class="run.status">{{ STATUS_LABEL[run.status] }}</span></dd></div>
          <div v-if="run.branch"><dt>Rama</dt><dd><span class="chip" :title="run.branch"><Icon name="branch" />{{ cleanBranch(run.branch) }}</span></dd></div>
          <div v-if="run.sha"><dt>Commit</dt><dd>
            <a v-if="commitUrl(run)" class="chip mono" :href="commitUrl(run)" target="_blank" rel="noopener">{{ shortSha(run.sha) }}</a>
            <span v-else class="chip mono">{{ shortSha(run.sha) }}</span></dd></div>
          <div v-if="run.actor"><dt>Por</dt><dd class="actor">
            <img v-if="run.actor_avatar" :src="run.actor_avatar" alt="" width="18" height="18" />{{ run.actor }}
            <span v-if="run.event" class="faint">· {{ run.event }}</span></dd></div>
          <div><dt>Inicio</dt><dd :title="fullDate(run.created_at)">{{ ago(run.created_at, now) }}</dd></div>
          <div><dt>Duración</dt><dd class="num">{{ runDuration }}</dd></div>
        </dl>
        <p v-if="error" class="error-text">No se pudo refrescar desde {{ PROVIDER_LABEL[run.provider] }}: {{ error }}</p>
      </section>

      <div class="layout">
        <nav class="card steps" :aria-label="run.provider === 'github' ? 'Jobs' : 'Steps'">
          <h3 class="steps-h">{{ run.provider === 'github' ? 'Jobs' : 'Steps' }} <span class="faint">{{ steps.length }}</span></h3>
          <p v-if="!steps.length" class="muted pad">Sin {{ run.provider === 'github' ? 'jobs' : 'steps' }} todavía.</p>
          <ul>
            <li v-for="s in steps" :key="s.id">
              <div class="step" :class="{ sel: s.id === selectedId }">
                <button class="step-btn" :aria-current="s.id === selectedId ? 'true' : undefined" @click="select(s)">
                  <StatusIcon :status="s.status" />
                  <span class="grow truncate" :title="s.name">{{ s.name }}</span>
                  <span v-if="s.manual" class="chip">manual</span>
                  <span v-if="s.environment" class="chip">{{ s.environment }}</span>
                  <span class="faint num">{{ stepDuration(s) }}</span>
                </button>
                <button v-if="s.substeps?.length" class="btn icon sm ghost expand" :aria-expanded="openJobs.has(s.id)"
                        :aria-label="`Ver pasos de ${s.name}`" @click="toggleJob(s)">
                  <Icon name="chevron" :size="12" :style="{ transform: openJobs.has(s.id) ? 'rotate(90deg)' : '' }" />
                </button>
              </div>
              <ol v-if="s.substeps?.length && openJobs.has(s.id)" class="substeps">
                <li v-for="ss in s.substeps" :key="ss.number">
                  <StatusIcon :status="ss.status" :size="12" />
                  <span class="truncate" :title="ss.name">{{ ss.name }}</span>
                </li>
              </ol>
            </li>
          </ul>
        </nav>

        <LogViewer v-if="selected" :key="selected.id" :run-id="run.id" :step="selected" :provider="run.provider" :file-name="logName" />
        <div v-else class="card empty">Elige un {{ run.provider === 'github' ? 'job' : 'step' }} para ver su log.</div>
      </div>
    </template>
  </main>
</template>

<style scoped>
.detail { max-width: 1440px; }
.back { display: inline-flex; align-items: center; gap: 4px; color: var(--text-muted); font-size: 13px; font-weight: 550; margin-bottom: 12px; }
.back:hover { color: var(--text); }
.head { padding: 18px 20px; margin-bottom: 14px; }
.head-top { display: flex; gap: 14px; align-items: flex-start; flex-wrap: wrap; }
.head-top > .status-icon { margin-top: 2px; }
.title { font-size: 19px; overflow-wrap: anywhere; }
.sub { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 4px; color: var(--text-muted); font-size: 13px; }
.repo { display: inline-flex; align-items: center; gap: 5px; font-weight: 600; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.facts { display: flex; flex-wrap: wrap; gap: 10px 28px; margin: 16px 0 0; padding-top: 14px; border-top: 1px solid var(--border); }
.facts div { display: grid; gap: 3px; }
.facts dt { font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); font-weight: 600; }
.facts dd { margin: 0; font-size: 13px; display: flex; align-items: center; gap: 6px; }
.actor img { border-radius: 50%; }
.num { font-variant-numeric: tabular-nums; }

.layout { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 14px; align-items: start; }
.layout > .log { height: calc(100vh - 290px); min-height: 460px; position: sticky; top: 70px; }
.steps { padding: 6px 0; max-height: calc(100vh - 290px); min-height: 200px; overflow: auto; position: sticky; top: 70px; }
.steps-h { padding: 8px 14px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); }
.pad { padding: 0 14px; font-size: 13px; }
.steps ul, .steps ol { list-style: none; margin: 0; padding: 0; }
.step { display: flex; align-items: center; margin: 1px 6px; border-radius: var(--radius-sm); }
.step:hover { background: var(--surface-hover); }
.step.sel { background: var(--accent-soft); }
.step-btn {
  flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; padding: 7px 8px;
  border: 0; background: none; color: var(--text); font: inherit; font-size: 13px; text-align: left; cursor: pointer;
}
.step.sel .step-btn { font-weight: 600; }
.step-btn .num { font-size: 12px; }
.expand { margin-right: 4px; }
.substeps { margin: 2px 6px 6px 30px !important; border-left: 1px solid var(--border); }
.substeps li { display: flex; align-items: center; gap: 7px; padding: 3px 10px; font-size: 12.5px; color: var(--text-muted); min-width: 0; }

@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .steps, .layout > .log { position: static; max-height: none; height: auto; }
  .layout > .log { height: 70vh; }
}
</style>
