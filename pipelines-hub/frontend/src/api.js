import { reactive } from 'vue'

export const toasts = reactive([])
let toastId = 0

export function toast(message, kind = 'error') {
  const id = ++toastId
  toasts.push({ id, message, kind })
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id)
    if (i >= 0) toasts.splice(i, 1)
  }, kind === 'error' ? 7000 : 3500)
}

async function request(method, path, body, { quiet = false } = {}) {
  let res
  try {
    res = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    if (!quiet) toast('No hay conexión con el servicio')
    throw e
  }
  if (res.status === 204) return null
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    let msg = data?.detail ?? res.statusText
    if (Array.isArray(msg)) msg = msg.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join(' · ')
    const err = new Error(msg)
    err.status = res.status
    if (!quiet) toast(msg)
    throw err
  }
  return data
}

const qs = (params) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') p.set(k, v)
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  overview: (o) => request('GET', '/api/overview', null, o),
  runs: (params, o) => request('GET', `/api/runs${qs(params)}`, null, o),
  runStats: (params, o) => request('GET', `/api/runs/stats${qs(params)}`, null, o),
  runFacets: (params, o) => request('GET', `/api/runs/facets${qs(params)}`, null, o),
  views: (params, o) => request('GET', `/api/views${qs(params)}`, null, o),
  createView: (body) => request('POST', '/api/views', body),
  updateView: (id, body) => request('PUT', `/api/views/${id}`, body),
  deleteView: (id) => request('DELETE', `/api/views/${id}`),
  run: (id, o) => request('GET', `/api/runs/${id}`, null, o),
  log: (id, stepId, offset, o) =>
    request('GET', `/api/runs/${id}/steps/${encodeURIComponent(stepId)}/log${qs({ offset })}`, null, o),
  cancel: (id) => request('POST', `/api/runs/${id}/cancel`),
  rerun: (id, failedOnly = false) => request('POST', `/api/runs/${id}/rerun`, { failed_only: failedOnly }),
  deployments: (params, o) => request('GET', `/api/deployments${qs(params)}`, null, o),
  repos: (o) => request('GET', '/api/repos', null, o),
  accounts: () => request('GET', '/api/accounts'),
  testAccount: (body) => request('POST', '/api/accounts/test', body),
  createAccount: (body) => request('POST', '/api/accounts', body),
  updateAccount: (id, body) => request('PATCH', `/api/accounts/${id}`, body),
  revalidate: (id) => request('POST', `/api/accounts/${id}/revalidate`),
  deleteAccount: (id) => request('DELETE', `/api/accounts/${id}`),
  discover: (id) => request('GET', `/api/accounts/${id}/discover`),
  addSource: (accountId, body) => request('POST', `/api/accounts/${accountId}/sources`, body),
  updateSource: (id, body) => request('PATCH', `/api/sources/${id}`, body),
  deleteSource: (id) => request('DELETE', `/api/sources/${id}`),
  sourceRepos: (id) => request('GET', `/api/sources/${id}/repos`),
  updateRepo: (id, body) => request('PATCH', `/api/repos/${id}`, body),
  prFacets: (params, o) => request('GET', `/api/prs/facets${qs(params)}`, null, o),
  deploymentFacets: (params, o) => request('GET', `/api/deployments/facets${qs(params)}`, null, o),
  prs: (params, o) => request('GET', `/api/prs${qs(params)}`, null, o),
  pr: (id, o) => request('GET', `/api/prs/${id}`, null, o),
  prAction: (id, action, body) => request('POST', `/api/prs/${id}/${action}`, body || {}),
  sync: (sourceId) => request('POST', `/api/sync${qs({ source_id: sourceId })}`),
}
