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
  // Kubernetes
  k8sContexts: (o) => request('GET', '/api/k8s/contexts', null, o),
  k8sClusters: (o) => request('GET', '/api/k8s/clusters', null, o),
  k8sAddCluster: (body) => request('POST', '/api/k8s/clusters', body),
  k8sRemoveCluster: (id) => request('DELETE', `/api/k8s/clusters/${id}`),
  k8s: (id, path, params, o) => request('GET', `/api/k8s/${id}/${path}${qs(params)}`, null, o),
  // Servidores
  sshConfig: (o) => request('GET', '/api/servers/ssh-config', null, o),
  servers: (o) => request('GET', '/api/servers', null, o),
  server: (id, o) => request('GET', `/api/servers/${id}`, null, o),
  testServer: (body) => request('POST', '/api/servers/test', body),
  createServer: (body) => request('POST', '/api/servers', body),
  updateServer: (id, body) => request('PATCH', `/api/servers/${id}`, body),
  deleteServer: (id) => request('DELETE', `/api/servers/${id}`),
  serverSnapshot: (id) => request('POST', `/api/servers/${id}/snapshot`),
  pollServer: (id) => request('POST', `/api/servers/${id}/poll`),
  serverSamples: (id, hours, o) => request('GET', `/api/servers/${id}/samples${qs({ hours })}`, null, o),
  serverSuggestions: (id) => request('GET', `/api/servers/${id}/suggestions`),
  addService: (serverId, body) => request('POST', `/api/servers/${serverId}/services`, body),
  updateService: (id, body) => request('PATCH', `/api/services/${id}`, body),
  deleteService: (id) => request('DELETE', `/api/services/${id}`),
  checkService: (id) => request('POST', `/api/services/${id}/check`),
  serviceHistory: (id, o) => request('GET', `/api/services/${id}/history`, null, o),
  serviceLog: (id, params, o) => request('GET', `/api/services/${id}/log${qs(params)}`, null, o),
  sync: (sourceId) => request('POST', `/api/sync${qs({ source_id: sourceId })}`),
}
