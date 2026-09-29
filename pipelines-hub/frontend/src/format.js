const rtf = new Intl.RelativeTimeFormat('es', { numeric: 'auto' })

export function ago(iso, now = Date.now()) {
  if (!iso) return '—'
  const s = Math.round((new Date(iso).getTime() - now) / 1000)
  const abs = Math.abs(s)
  if (abs < 45) return 'recién'
  if (abs < 3600) return rtf.format(Math.round(s / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(s / 3600), 'hour')
  if (abs < 86400 * 30) return rtf.format(Math.round(s / 86400), 'day')
  return new Date(iso).toLocaleDateString('es-CL', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function fullDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('es-CL', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

export function duration(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

export function elapsed(startIso, endIso, now = Date.now()) {
  if (!startIso) return null
  const end = endIso ? new Date(endIso).getTime() : now
  return (end - new Date(startIso).getTime()) / 1000
}

export const STATUS_LABEL = {
  queued: 'En cola',
  running: 'En curso',
  waiting: 'En pausa',
  success: 'Exitoso',
  failed: 'Fallido',
  cancelled: 'Cancelado',
  skipped: 'Omitido',
}

// ACTIVE = todavía no termina (se puede cancelar, el log puede crecer).
// RUNNING = corriendo de verdad: lo en pausa espera un step manual y no cuenta como en curso.
export const ACTIVE = new Set(['queued', 'running', 'waiting'])
export const RUNNING = new Set(['queued', 'running'])

export const PROVIDER_LABEL = { github: 'GitHub', bitbucket: 'Bitbucket', cloudflare: 'Cloudflare' }

export function shortSha(sha) {
  return sha ? sha.slice(0, 7) : ''
}

export function commitUrl(run) {
  if (!run?.sha) return null
  // Cloudflare: el commit vive en el repo de GitHub/GitLab que despliega
  if (run.repo?.git_url) return `${run.repo.git_url}/commit/${run.sha}`
  if (run.provider === 'cloudflare' || !run.repo?.html_url) return null
  return run.provider === 'github'
    ? `${run.repo.html_url}/commit/${run.sha}`
    : `${run.repo.html_url}/commits/${run.sha}`
}

export function cleanBranch(branch) {
  if (!branch) return ''
  return branch.replace(/^refs\/(heads|tags)\//, '').replace(/^refs\/pull\/(\d+)\/.*/, 'PR #$1')
}

export const PR_STATE_LABEL = { open: 'Abierto', merged: 'Mergeado', closed: 'Cerrado', draft: 'Borrador' }
export const REVIEW_LABEL = {
  approved: 'Aprobó',
  changes_requested: 'Pidió cambios',
  commented: 'Comentó',
  pending: 'Pendiente',
}
