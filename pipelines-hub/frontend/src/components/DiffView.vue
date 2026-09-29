<script setup>
import { computed } from 'vue'

const props = defineProps({ patch: { type: String, default: '' } })
const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/

const lines = computed(() => {
  const out = []
  let oldN = 0
  let newN = 0
  for (const raw of props.patch.split('\n')) {
    const m = raw.match(HUNK)
    if (m) {
      oldN = +m[1]
      newN = +m[2]
      out.push({ type: 'hunk', text: raw })
    } else if (raw.startsWith('+')) {
      out.push({ type: 'add', o: '', n: newN++, text: raw.slice(1) })
    } else if (raw.startsWith('-')) {
      out.push({ type: 'del', o: oldN++, n: '', text: raw.slice(1) })
    } else if (raw.startsWith('\\')) {
      out.push({ type: 'meta', text: raw })
    } else {
      out.push({ type: 'ctx', o: oldN++, n: newN++, text: raw.slice(1) })
    }
  }
  return out
})
</script>

<template>
  <div class="diff" role="table" aria-label="Diff">
    <div v-for="(l, i) in lines" :key="i" class="dl" :class="l.type" role="row">
      <template v-if="l.type === 'hunk' || l.type === 'meta'">
        <span class="hunk-text" role="cell">{{ l.text }}</span>
      </template>
      <template v-else>
        <span class="num" role="cell">{{ l.o }}</span>
        <span class="num" role="cell">{{ l.n }}</span>
        <span class="sign" aria-hidden="true">{{ l.type === 'add' ? '+' : l.type === 'del' ? '−' : ' ' }}</span>
        <span class="code" role="cell">{{ l.text }}</span>
      </template>
    </div>
  </div>
</template>

<style scoped>
.diff { font: 12px/1.55 var(--mono); background: var(--log-bg); color: var(--log-text); overflow-x: auto; }
.dl { display: flex; min-width: max-content; }
.num { flex: none; width: 48px; padding: 0 8px; text-align: right; color: var(--log-gutter); user-select: none; font-variant-numeric: tabular-nums; }
.sign { flex: none; width: 16px; text-align: center; user-select: none; }
.code { white-space: pre; padding-right: 16px; }
.add { background: var(--diff-add-bg); }
.add .num { background: var(--diff-add-gutter); color: var(--log-text); }
.add .sign { color: var(--st-success); }
.del { background: var(--diff-del-bg); }
.del .num { background: var(--diff-del-gutter); color: var(--log-text); }
.del .sign { color: var(--st-failed); }
.hunk, .meta { background: var(--diff-hunk-bg); color: var(--diff-hunk-text); }
.hunk-text { padding: 2px 12px; white-space: pre; }
</style>
