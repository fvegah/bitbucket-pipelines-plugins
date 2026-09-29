import { PROVIDER_LABEL, STATUS_LABEL } from './format'

const COMMON_TAIL = [
  { key: 'provider', label: 'Proveedor', noPattern: true },
  { key: 'account', label: 'Cuenta' },
]

// Campos filtrables por pantalla. `specials` son valores que no salen de los datos.
export const SCOPE_FIELDS = {
  runs: [
    { key: 'org', label: 'Organización' },
    { key: 'repo', label: 'Repositorio' },
    { key: 'branch', label: 'Rama' },
    { key: 'workflow', label: 'Workflow / pipeline' },
    { key: 'status', label: 'Estado', noPattern: true, specials: ['active'] },
    { key: 'actor', label: 'Autor' },
    { key: 'event', label: 'Evento' },
    ...COMMON_TAIL,
  ],
  prs: [
    { key: 'org', label: 'Organización' },
    { key: 'repo', label: 'Repositorio' },
    { key: 'author', label: 'Autor' },
    { key: 'target', label: 'Rama destino' },
    { key: 'source', label: 'Rama origen' },
    { key: 'state', label: 'Estado', noPattern: true, specials: ['draft'] },
    ...COMMON_TAIL,
  ],
  deployments: [
    { key: 'org', label: 'Organización' },
    { key: 'repo', label: 'Repositorio' },
    { key: 'environment', label: 'Entorno' },
    { key: 'status', label: 'Estado', noPattern: true },
    { key: 'actor', label: 'Desplegó' },
    ...COMMON_TAIL,
  ],
}

export function fieldLabel(scope, key) {
  return SCOPE_FIELDS[scope]?.find((f) => f.key === key)?.label || key
}

export const PERIODS = [
  [null, 'Todo'],
  [24, '24 h'],
  [24 * 7, '7 días'],
  [24 * 30, '30 días'],
]

const EVENT_LABEL = { push: 'push', manual: 'manual', schedule: 'programado', pull_request: 'pull request', api: 'API' }
const PR_STATE = { open: 'Abierto', merged: 'Mergeado', closed: 'Cerrado', draft: 'Borrador' }

export function valueLabel(field, value) {
  if (field === 'status') return value === 'active' ? 'En curso' : STATUS_LABEL[value] || value
  if (field === 'state') return PR_STATE[value] || value
  if (field === 'provider') return PROVIDER_LABEL[value] || value
  if (field === 'event') return EVENT_LABEL[value] || value
  return value
}

export function emptyFilter() {
  return { include: {}, exclude: {}, since_hours: null }
}

/** Quita listas vacías y ordena para comparar y serializar; conserva claves extra (p. ej. bucket). */
export function normalize(f) {
  const out = emptyFilter()
  for (const part of ['include', 'exclude']) {
    for (const [k, v] of Object.entries(f?.[part] || {})) if (v?.length) out[part][k] = [...v].sort()
  }
  out.since_hours = f?.since_hours || null
  for (const [k, v] of Object.entries(f || {})) {
    if (!['include', 'exclude', 'since_hours'].includes(k) && v !== undefined && v !== null && v !== '') out[k] = v
  }
  return out
}

export function isEmpty(f) {
  const n = normalize(f)
  return !Object.keys(n.include).length && !Object.keys(n.exclude).length && !n.since_hours
}

export function sameFilter(a, b) {
  const s = (x) => JSON.stringify(Object.fromEntries(Object.entries(normalize(x)).sort()))
  return s(a) === s(b)
}

export function toParam(f) {
  if (isEmpty(f)) return undefined
  const { include, exclude, since_hours } = normalize(f)
  return JSON.stringify({ include, exclude, since_hours })
}
