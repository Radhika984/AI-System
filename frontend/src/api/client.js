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
      const detail = Array.isArray(body.detail)
        ? body.detail.map((d) => `${(d.loc || []).slice(1).join('.') || 'request'}: ${d.msg}`).join('; ')
        : body.detail
      const err = new Error(detail || `HTTP ${res.status}`)
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

// Reviewer passcode: kept only for this browser tab (sessionStorage), sent as a header.
// The server is the one that enforces it; this is just how the console supplies it.
let passcode = ''
try {
  passcode = sessionStorage.getItem('rf-passcode') || ''
} catch {
  /* storage blocked: memory only */
}

export function getPasscode() {
  return passcode
}

export function setPasscode(v) {
  passcode = v
  try {
    if (v) sessionStorage.setItem('rf-passcode', v)
    else sessionStorage.removeItem('rf-passcode')
  } catch {
    /* storage blocked */
  }
}

export async function postAction(id, payload) {
  if (mode === 'snapshot') throw new Error('Read-only snapshot mode: actions are disabled')
  if (!passcode) throw new Error('Enter the reviewer passcode (top right) to approve, edit or reject.')
  try {
    return await fetchJson(`/api/cases/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'x-reviewer-passcode': passcode },
    })
  } catch (e) {
    if (e.status === 401) throw new Error('Reviewer passcode is incorrect. Nothing was changed.')
    if (e.status === 429) throw new Error('Too many wrong passcode attempts. Wait a few minutes and try again.')
    if (e.status === 413) throw new Error('That edit is too large to save. Keep corrections short and surgical.')
    if (e.status === 422 && /extra|forbidden|not permitted/i.test(e.message)) throw new Error('Request contained unexpected fields and was rejected. Nothing was changed.')
    if (e.status === 503) throw new Error('Faculty actions are disabled on this server (no passcode configured).')
    throw e
  }
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
