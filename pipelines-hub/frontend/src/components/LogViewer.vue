<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { AnsiUp } from 'ansi_up'
import { api } from '../api'
import { ACTIVE, STATUS_LABEL, duration } from '../format'
import Icon from './Icon.vue'
import StatusIcon from './StatusIcon.vue'

const props = defineProps({
  runId: { type: [Number, String], required: true },
  step: { type: Object, required: true },
  provider: { type: String, required: true },
  fileName: { type: String, default: 'log' },
})

const MAX_RENDER = 6000
const TS = /^\uFEFF?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) ?/
const ANSI = /\x1b\[[0-9;]*[A-Za-z]/g

const raw = ref('')
const offset = ref(0)
const state = reactive({ loading: true, available: true, message: '', error: '' })
const opts = reactive({ wrap: true, follow: true, timestamps: false, showAll: false })
const query = ref('')
const current = ref(0)
const openGroups = reactive(new Set())
const body = ref(null)

const isActive = computed(() => ACTIVE.has(props.step.status))

// ---------- parseo ----------
const parsed = computed(() => {
  const au = new AnsiUp()
  au.use_classes = true
  au.escape_html = true
  const lines = raw.value.replace(/\r\n?/g, '\n').split('\n')
  if (lines.length && lines[lines.length - 1] === '') lines.pop()
  const blocks = []
  let group = null
  let n = 0
  let firstError = null
  for (let line of lines) {
    let ts = null
    const m = line.match(TS)
    if (m) {
      ts = m[1]
      line = line.slice(m[0].length)
    }
    if (line.startsWith('##[group]')) {
      group = { type: 'group', id: `g${n + 1}`, title: line.slice(9), lines: [], n: ++n, ts, hasError: false }
      blocks.push(group)
      continue
    }
    if (line.startsWith('##[endgroup]')) {
      group = null
      continue
    }
    let cls = ''
    const tag = line.match(/^##\[(error|warning|notice|debug|command|section)\]/)
    if (tag) {
      cls = tag[1]
      line = line.slice(tag[0].length)
    } else if (props.provider === 'bitbucket' && line.startsWith('+ ')) {
      cls = 'command'
    } else if (/^\[command\]/.test(line)) {
      cls = 'command'
      line = line.slice(9)
    }
    const plain = line.replace(ANSI, '')
    const entry = { type: 'line', n: ++n, ts, cls, html: au.ansi_to_html(line), plain }
    if (cls === 'error' && firstError === null) firstError = entry.n
    if (group) {
      if (cls === 'error') group.hasError = true
      group.lines.push(entry)
    } else {
      blocks.push(entry)
    }
  }
  return { blocks, total: n, firstError }
})

const matches = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (q.length < 2) return []
  const out = []
  for (const b of parsed.value.blocks) {
    if (b.type === 'group') {
      if (b.title.toLowerCase().includes(q)) out.push({ n: b.n, group: b.id })
      for (const l of b.lines) if (l.plain.toLowerCase().includes(q)) out.push({ n: l.n, group: b.id })
    } else if (b.plain.toLowerCase().includes(q)) {
      out.push({ n: b.n, group: null })
    }
  }
  return out
})
const matchSet = computed(() => new Set(matches.value.map((m) => m.n)))
const currentN = computed(() => matches.value[current.value]?.n)

// Si el log es muy largo, se muestran solo las últimas líneas (fuera de grupos)
const visible = computed(() => {
  const blocks = parsed.value.blocks
  if (opts.showAll || parsed.value.total <= MAX_RENDER) return { blocks, hidden: 0 }
  let count = 0
  let i = blocks.length
  while (i > 0 && count < MAX_RENDER) {
    i--
    count += blocks[i].type === 'group' ? 1 : 1
  }
  const hidden = blocks.slice(0, i).reduce((a, b) => a + (b.type === 'group' ? b.lines.length + 1 : 1), 0)
  return { blocks: blocks.slice(i), hidden }
})

function isOpen(g) {
  return openGroups.has(g.id)
}
function toggle(g) {
  if (openGroups.has(g.id)) openGroups.delete(g.id)
  else openGroups.add(g.id)
}

function fmtTs(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('es-CL', { hour12: false })
}

// ---------- carga ----------
let timer = null
let seq = 0

async function fetchLog(reset = false) {
  const my = ++seq
  if (reset) {
    raw.value = ''
    offset.value = 0
    state.loading = true
    state.error = ''
    openGroups.clear()
    query.value = ''
  }
  try {
    const chunk = await api.log(props.runId, props.step.id, offset.value, { quiet: true })
    if (my !== seq) return
    state.available = chunk.available
    state.message = chunk.message || ''
    state.error = ''
    if (chunk.available) {
      if (props.provider === 'github') raw.value = chunk.text // GitHub devuelve todo
      else if (chunk.text) raw.value += chunk.text
      offset.value = chunk.next_offset
    }
  } catch (e) {
    if (my === seq) state.error = e.message
  } finally {
    if (my === seq) state.loading = false
  }
  if (my !== seq) return
  await nextTick()
  if (reset) revealInitial()
  else if (opts.follow && isActive.value) scrollBottom()
  schedule()
}

function schedule() {
  clearTimeout(timer)
  if (!isActive.value && state.available) return
  // Bitbucket entrega el log en vivo; GitHub solo al terminar el job
  const wait = props.provider === 'github' ? 8000 : 3000
  timer = setTimeout(() => {
    if (document.hidden) return schedule()
    fetchLog(false)
  }, wait)
}

function revealInitial() {
  const { firstError, blocks } = parsed.value
  if (firstError !== null && props.step.status === 'failed') {
    for (const b of blocks) if (b.type === 'group' && b.lines.some((l) => l.n === firstError)) openGroups.add(b.id)
    nextTick(() => scrollToLine(firstError))
  } else if (isActive.value || props.step.status === 'failed') {
    const last = [...blocks].reverse().find((b) => b.type === 'group')
    if (last && props.step.status === 'failed') openGroups.add(last.id)
    nextTick(scrollBottom)
  } else if (body.value) {
    body.value.scrollTop = 0
  }
}

function scrollBottom() {
  if (body.value) body.value.scrollTop = body.value.scrollHeight
}
function scrollToLine(n) {
  const el = body.value?.querySelector(`[data-n="${n}"]`)
  if (el) el.scrollIntoView({ block: 'center' })
}

function go(delta) {
  if (!matches.value.length) return
  current.value = (current.value + delta + matches.value.length) % matches.value.length
  const m = matches.value[current.value]
  if (m.group) openGroups.add(m.group)
  opts.showAll = opts.showAll || parsed.value.total > MAX_RENDER
  nextTick(() => scrollToLine(m.n))
}
watch(query, () => {
  current.value = 0
  if (matches.value.length) go(0)
})

function onScroll() {
  const el = body.value
  if (!el || !isActive.value) return
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  if (!atBottom && opts.follow) opts.follow = false
}

function download() {
  const text = raw.value.replace(ANSI, '')
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.fileName}.log`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function expandAll(open) {
  for (const b of parsed.value.blocks) {
    if (b.type !== 'group') continue
    if (open) openGroups.add(b.id)
    else openGroups.delete(b.id)
  }
}

watch(() => props.step.id, () => fetchLog(true), { immediate: true })
watch(() => props.step.status, (now, before) => {
  // terminó el paso: traer lo que falte
  if (ACTIVE.has(before) && !ACTIVE.has(now)) fetchLog(false)
  else if (ACTIVE.has(now)) schedule()
})
watch(() => opts.follow, (v) => v && scrollBottom())
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <section class="log card" :class="{ nowrap: !opts.wrap }">
    <header class="log-head">
      <div class="log-title">
        <StatusIcon :status="step.status" />
        <h2 class="truncate" :title="step.name">{{ step.name }}</h2>
        <span class="faint dur">{{ STATUS_LABEL[step.status] }} · {{ duration(step.duration_s) }}</span>
      </div>
      <div class="log-tools">
        <label class="log-search">
          <Icon name="search" :size="13" />
          <span class="sr-only">Buscar en el log</span>
          <input v-model="query" class="input" placeholder="Buscar en el log" @keydown.enter.prevent="go($event.shiftKey ? -1 : 1)" />
          <span v-if="query.trim().length > 1" class="hits">{{ matches.length ? current + 1 : 0 }}/{{ matches.length }}</span>
        </label>
        <button class="btn icon sm ghost" title="Anterior (Shift+Enter)" aria-label="Coincidencia anterior" :disabled="!matches.length" @click="go(-1)"><Icon name="chevron" style="transform: rotate(-90deg)" /></button>
        <button class="btn icon sm ghost" title="Siguiente (Enter)" aria-label="Coincidencia siguiente" :disabled="!matches.length" @click="go(1)"><Icon name="chevron" style="transform: rotate(90deg)" /></button>
        <span class="divider" aria-hidden="true"></span>
        <button v-if="provider !== 'bitbucket'" class="btn sm ghost" :aria-pressed="opts.timestamps" :class="{ on: opts.timestamps }" title="Mostrar hora de cada línea" @click="opts.timestamps = !opts.timestamps"><Icon name="clock" :size="13" /></button>
        <button class="btn sm ghost" :class="{ on: opts.wrap }" :aria-pressed="opts.wrap" title="Ajustar líneas largas" @click="opts.wrap = !opts.wrap"><Icon name="wrap" :size="13" /></button>
        <button v-if="isActive" class="btn sm ghost" :class="{ on: opts.follow }" :aria-pressed="opts.follow" title="Seguir el final del log" @click="opts.follow = !opts.follow"><Icon name="follow" :size="13" /></button>
        <button class="btn sm ghost" title="Descargar log" aria-label="Descargar log" :disabled="!raw" @click="download"><Icon name="download" :size="13" /></button>
      </div>
    </header>

    <div ref="body" class="log-body" @scroll.passive="onScroll">
      <div v-if="state.loading && !raw" class="log-msg">Cargando log…</div>
      <div v-else-if="state.error" class="log-msg error-text">{{ state.error }}</div>
      <div v-else-if="!state.available && !raw" class="log-msg">
        <StatusIcon v-if="isActive" :status="step.status" />
        {{ state.message || 'Log no disponible.' }}
        <a v-if="step.url" :href="step.url" target="_blank" rel="noopener">Ver en {{ { github: 'GitHub', bitbucket: 'Bitbucket', cloudflare: 'Cloudflare' }[provider] }}</a>
      </div>
      <div v-else-if="!raw" class="log-msg">{{ isActive ? 'Esperando salida…' : 'El paso no generó salida.' }}</div>

      <template v-else>
        <button v-if="visible.hidden" class="show-all" @click="opts.showAll = true">
          {{ visible.hidden.toLocaleString('es-CL') }} líneas anteriores ocultas — mostrar todo
        </button>
        <div v-if="parsed.blocks.some((b) => b.type === 'group')" class="group-tools">
          <button class="linkish" @click="expandAll(true)">Expandir todo</button>
          <button class="linkish" @click="expandAll(false)">Contraer todo</button>
        </div>
        <template v-for="b in visible.blocks" :key="b.type === 'group' ? b.id : b.n">
          <div v-if="b.type === 'line'" class="ln" :class="[b.cls, { match: matchSet.has(b.n), current: currentN === b.n }]" :data-n="b.n">
            <span class="gut">{{ b.n }}</span><span v-if="opts.timestamps" class="ts">{{ fmtTs(b.ts) }}</span><span class="tx" v-html="b.html || ' '"></span>
          </div>
          <div v-else class="grp" :class="{ open: isOpen(b), err: b.hasError }">
            <button class="ln grp-title" :class="{ match: matchSet.has(b.n), current: currentN === b.n }" :data-n="b.n" :aria-expanded="isOpen(b)" @click="toggle(b)">
              <span class="gut">{{ b.n }}</span><span v-if="opts.timestamps" class="ts">{{ fmtTs(b.ts) }}</span>
              <span class="tx"><Icon name="chevron" :size="12" class="chev" />{{ b.title }}</span>
            </button>
            <template v-if="isOpen(b)">
              <div v-for="l in b.lines" :key="l.n" class="ln in" :class="[l.cls, { match: matchSet.has(l.n), current: currentN === l.n }]" :data-n="l.n">
                <span class="gut">{{ l.n }}</span><span v-if="opts.timestamps" class="ts">{{ fmtTs(l.ts) }}</span><span class="tx" v-html="l.html || ' '"></span>
              </div>
            </template>
          </div>
        </template>
        <div v-if="isActive && state.available" class="log-live"><StatusIcon status="running" :size="13" /> en vivo</div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.log { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.log-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px 10px 16px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.log-title { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1 1 200px; }
.log-title h2 { font-size: 14px; }
.dur { font-size: 12.5px; white-space: nowrap; }
.log-tools { display: flex; align-items: center; gap: 2px; }
.log-tools .btn.on { background: var(--accent-soft); color: var(--text); }
.log-search { position: relative; display: flex; align-items: center; margin-right: 4px; }
.log-search svg { position: absolute; left: 8px; color: var(--text-faint); pointer-events: none; }
.log-search .input { height: 28px; width: 190px; padding-left: 26px; padding-right: 44px; font-size: 12.5px; }
.hits { position: absolute; right: 8px; font-size: 11px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.divider { width: 1px; height: 18px; background: var(--border); margin: 0 4px; }

.log-body {
  flex: 1; overflow: auto; min-height: 320px;
  background: var(--log-bg); color: var(--log-text);
  font: 12.5px/1.6 var(--mono);
  padding: 8px 0 16px;
}
.log-msg { padding: 28px 20px; color: var(--text-muted); font-family: var(--font); font-size: 13px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.ln { display: flex; min-width: 0; padding-right: 16px; }
.ln:hover { background: color-mix(in srgb, var(--log-group) 70%, transparent); }
.gut {
  flex: none; width: 56px; padding-right: 12px; text-align: right;
  color: var(--log-gutter); user-select: none; font-variant-numeric: tabular-nums;
}
.ts { flex: none; width: 70px; color: var(--log-gutter); user-select: none; }
.tx { flex: 1; min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.nowrap .tx { white-space: pre; overflow-wrap: normal; }
.nowrap .log-body .ln { width: max-content; min-width: 100%; }
.ln.in .tx { padding-left: 18px; }
.ln.command .tx { color: var(--st-running); font-weight: 600; }
.ln.error { background: var(--log-error-bg); }
.ln.error .tx { color: var(--st-failed); }
.ln.warning { background: var(--log-warn-bg); }
.ln.warning .tx { color: var(--st-waiting); }
.ln.debug .tx { color: var(--text-faint); }
.ln.match { background: var(--log-match); }
.ln.current { background: var(--log-match-current); box-shadow: inset 3px 0 var(--st-waiting); }
.ln.match .gut, .ln.current .gut, .ln.match .tx, .ln.current .tx { color: var(--log-text); }
.grp-title {
  width: 100%; border: 0; background: transparent; color: inherit; font: inherit;
  text-align: left; cursor: pointer; padding-top: 0; padding-bottom: 0;
}
.grp-title .tx { font-weight: 600; display: flex; gap: 4px; align-items: center; }
.grp.open > .grp-title { background: var(--log-group); }
.grp.err > .grp-title .tx { color: var(--st-failed); }
.chev { transition: transform .12s; flex: none; }
.grp.open .chev { transform: rotate(90deg); }
.show-all, .linkish {
  border: 0; background: none; color: var(--accent); font: 12.5px var(--font); cursor: pointer; padding: 4px 0;
}
.show-all { display: block; width: 100%; padding: 8px; background: var(--log-group); margin-bottom: 6px; }
.show-all:hover, .linkish:hover { text-decoration: underline; }
.group-tools { display: flex; gap: 14px; padding: 0 16px 6px 68px; }
.log-live { display: flex; align-items: center; gap: 6px; padding: 8px 16px 0 68px; font: 12px var(--font); color: var(--st-running); }

/* Colores ANSI legibles en ambos temas */
.log-body :deep(.ansi-bold) { font-weight: 700; }
.log-body :deep(.ansi-black-fg) { color: var(--text-faint); }
.log-body :deep(.ansi-red-fg), .log-body :deep(.ansi-bright-red-fg) { color: var(--st-failed); }
.log-body :deep(.ansi-green-fg), .log-body :deep(.ansi-bright-green-fg) { color: var(--st-success); }
.log-body :deep(.ansi-yellow-fg), .log-body :deep(.ansi-bright-yellow-fg) { color: var(--st-waiting); }
.log-body :deep(.ansi-blue-fg), .log-body :deep(.ansi-bright-blue-fg) { color: var(--st-running); }
.log-body :deep(.ansi-magenta-fg), .log-body :deep(.ansi-bright-magenta-fg) { color: var(--env-prod); }
.log-body :deep(.ansi-cyan-fg), .log-body :deep(.ansi-bright-cyan-fg) { color: var(--accent); }
.log-body :deep(.ansi-white-fg), .log-body :deep(.ansi-bright-white-fg) { color: var(--log-text); }
.log-body :deep(.ansi-bright-black-fg) { color: var(--log-gutter); }
.log-body :deep([class*='-bg']) { background: var(--log-group); }

@media (max-width: 720px) {
  .log-search .input { width: 140px; }
  .gut { width: 40px; padding-right: 8px; }
  .group-tools, .log-live { padding-left: 48px; }
}
</style>
