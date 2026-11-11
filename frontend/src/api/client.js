// API client with a read-only snapshot fallback.
// If the API is unreachable (e.g. free-tier backend asleep or down), the console
// loads /snapshot.json, bundled at build time, and clearly shows READ-ONLY mode.

const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const TIMEOUT_MS = 25000 // Render free tier can take ~20s to wake up

let snapshot = null
let mode = 'unknown' // 'live' | 'snapshot'

async function fetchJson(path, opts = {}) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(BASE + path, {
      ...opts,
      signal: ctrl.signal,
      headers: { 'content-type': 'application/json', ...(opts.headers || {}) },
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) {
      const err = new Error(body.detail || `HTTP ${res.status}`)
      err.status = res.status
      throw err
    }
    return body
  } finally {
    clearTimeout(t)
  }
}

async function loadSnapshot() {
  if (!snapshot) {
    const res = await fetch('/snapshot.json')
    if (!res.ok) throw new Error('API unreachable and no snapshot available')
    snapshot = await res.json()
  }
  return snapshot
}

export function getMode() {
  return mode
}

export async function getQueue() {
  try {
    const q = await fetchJson('/api/queue')
    mode = 'live'
    return q
  } catch (e) {
    if (e.status && e.status < 500) throw e
    const s = await loadSnapshot()
    mode = 'snapshot'
    return s.queue
  }
}

export async function getCase(id) {
  if (mode === 'snapshot') {
    const s = await loadSnapshot()
    if (!s.cases[id]) throw new Error('Case not in snapshot')
    return s.cases[id]
  }
  return fetchJson(`/api/cases/${id}`)
}

export async function postAction(id, payload) {
  if (mode === 'snapshot') throw new Error('Read-only snapshot mode: actions are disabled')
  return fetchJson(`/api/cases/${id}/actions`, { method: 'POST', body: JSON.stringify(payload) })
}

export async function getAudit() {
  if (mode === 'snapshot') {
    const s = await loadSnapshot()
    return s.audit || []
  }
  return fetchJson('/api/audit')
}

export async function getSnapshotMeta() {
  try {
    const s = await loadSnapshot()
    return s.meta
  } catch {
    return null
  }
}
