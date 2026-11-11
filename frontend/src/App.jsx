import { useCallback, useEffect, useState } from 'react'
import { getAudit, getCase, getMode, getPasscode, getQueue, getSnapshotMeta, postAction, setPasscode } from './api/client'
import CaseView from './components/CaseView'
import Queue, { isDone } from './components/Queue'
import { fmtDate } from './components/labels'

function useActor() {
  const [actor, setActor] = useState(() => {
    try {
      return localStorage.getItem('rf-actor') || ''
    } catch {
      return ''
    }
  })
  const save = (v) => {
    setActor(v)
    try {
      localStorage.setItem('rf-actor', v)
    } catch {
      /* storage blocked: keep in memory */
    }
  }
  return [actor, save]
}

function AuditDrawer({ open, onClose }) {
  const [rows, setRows] = useState(null)
  useEffect(() => {
    if (open) getAudit().then(setRows).catch(() => setRows([]))
  }, [open])
  useEffect(() => {
    if (!open) return
    const h = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside className="h-full w-full max-w-lg overflow-y-auto bg-white p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-bold">Audit log (all questions)</h2>
          <button onClick={onClose} className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100">Close</button>
        </div>
        {rows === null ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-slate-500">No actions recorded yet.</p>
        ) : (
          <ol className="space-y-2">
            {rows.map((e) => (
              <li key={e.id} className="rounded-lg border border-slate-200 p-2 text-sm">
                <div className="flex flex-wrap gap-x-2 text-xs text-slate-500">
                  <span>{fmtDate(e.at)}</span>
                  <b className="text-slate-800">{e.actor}</b>
                  <span className="rounded bg-slate-100 px-1">{e.action}</span>
                  <span>{e.reportIds?.join(', ')}</span>
                </div>
                {e.edit && (
                  <p className="mt-1 break-words font-mono text-xs text-slate-600">
                    {e.edit.field}: “{String(e.edit.find).slice(0, 60)}” → “{String(e.edit.replace).slice(0, 60)}”
                  </p>
                )}
                {e.note && <p className="mt-1 text-xs text-slate-600">{e.note}</p>}
              </li>
            ))}
          </ol>
        )}
      </aside>
    </div>
  )
}

export default function App() {
  const [queue, setQueue] = useState(null)
  const [loadErr, setLoadErr] = useState('')
  const [selected, setSelected] = useState(null)
  const [current, setCurrent] = useState(null)
  const [caseErr, setCaseErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionErr, setActionErr] = useState('')
  const [filter, setFilter] = useState('todo')
  const [auditOpen, setAuditOpen] = useState(false)
  const [showWhy, setShowWhy] = useState(false)
  const [meta, setMeta] = useState(null)
  const [actor, setActor] = useActor()
  const [passcode, setPasscodeState] = useState(getPasscode())
  const updatePasscode = (v) => {
    setPasscode(v)
    setPasscodeState(v)
  }
  const [mobileList, setMobileList] = useState(true)

  const refreshQueue = useCallback(async () => {
    const q = await getQueue()
    setQueue(q)
    return q
  }, [])

  useEffect(() => {
    refreshQueue()
      .then((q) => {
        const first = q.find((c) => !isDone(c)) || q[0]
        if (first) setSelected(first.questionId)
      })
      .catch((e) => setLoadErr(e.message))
    getSnapshotMeta().then(setMeta)
  }, [refreshQueue])

  useEffect(() => {
    if (!selected) return
    setCurrent(null)
    setCaseErr('')
    setActionErr('')
    getCase(selected).then(setCurrent).catch((e) => setCaseErr(e.message))
  }, [selected])

  const select = (id) => {
    setSelected(id)
    setMobileList(false)
    window.scrollTo(0, 0)
  }

  const onAction = async (payload) => {
    setBusy(true)
    setActionErr('')
    try {
      const updated = await postAction(selected, { actor: actor || 'faculty', ...payload })
      setCurrent(updated)
      const q = await refreshQueue()
      if (payload.action !== 'reopen') {
        const idx = q.findIndex((c) => c.questionId === selected)
        const next = q.slice(idx + 1).find((c) => !isDone(c)) || q.find((c) => !isDone(c))
        if (next && next.questionId !== selected) setTimeout(() => select(next.questionId), 700)
      }
      return true
    } catch (e) {
      setActionErr(e.message)
      return false
    } finally {
      setBusy(false)
    }
  }

  // Keyboard: J/K move, A approve, R reject (ignored while typing)
  useEffect(() => {
    const h = (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.metaKey || e.ctrlKey) return
      if (!queue) return
      const visible = queue.filter((c) => (filter === 'all' ? true : filter === 'done' ? isDone(c) : !isDone(c)))
      const i = visible.findIndex((c) => c.questionId === selected)
      if (e.key === 'j' && visible[i + 1]) select(visible[i + 1].questionId)
      if (e.key === 'k' && i > 0) select(visible[i - 1].questionId)
      if (getMode() !== 'live' || !passcode || !current || busy || isDone(current)) return
      if (e.key === 'a') onAction({ action: 'approve' })
      if (e.key === 'r') onAction({ action: 'reject' })
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  })

  const readOnly = getMode() === 'snapshot'
  const done = queue ? queue.filter(isDone).length : 0

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
          <h1 className="text-base font-bold tracking-tight">
            Report <span className="text-indigo-600">→</span> Fix
            <span className="ml-2 font-normal text-slate-500">Faculty queue</span>
          </h1>
          {queue && (
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <div className="h-2 w-28 overflow-hidden rounded-full bg-slate-200">
                <div className="h-full bg-indigo-600" style={{ width: `${(done / queue.length) * 100}%` }} />
              </div>
              {done}/{queue.length} questions decided
            </div>
          )}
          <button onClick={() => setShowWhy((v) => !v)} className="text-sm text-indigo-700 underline-offset-2 hover:underline">
            Why this order?
          </button>
          <div className="flex w-full min-w-0 items-center gap-2 sm:ml-auto sm:w-auto">
            <input
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              placeholder="Your name (for audit)"
              aria-label="Your name for the audit log"
              className="w-0 min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm sm:w-40 sm:flex-none"
            />
            <input
              type="password"
              // Uncontrolled on purpose: a React-controlled value={...} is reflected into the DOM
              // `value` attribute, which would expose the passcode in the page HTML.
              onChange={(e) => updatePasscode(e.target.value)}
              placeholder={passcode ? 'Passcode set ✓' : 'Reviewer passcode'}
              aria-label="Reviewer passcode"
              autoComplete="off"
              className={`w-0 min-w-0 flex-1 rounded-md border px-2 py-1 text-sm sm:w-40 sm:flex-none ${passcode ? 'border-emerald-400 placeholder:text-emerald-700' : 'border-amber-400'}`}
            />
            {passcode && (
              <button
                onClick={(e) => {
                  updatePasscode('')
                  const box = e.currentTarget.parentElement.querySelector('input[type=password]')
                  if (box) box.value = ''
                }}
                className="shrink-0 rounded-md px-1.5 py-1 text-xs text-slate-500 hover:bg-slate-100"
                title="Forget the passcode in this tab"
              >
                Clear
              </button>
            )}
            <button onClick={() => setAuditOpen(true)} className="shrink-0 rounded-md border border-slate-300 px-2.5 py-1 text-sm hover:bg-slate-50">
              Audit log
            </button>
          </div>
        </div>
        {readOnly ? (
          <div className="bg-amber-100 px-4 py-1.5 text-sm text-amber-900">
            <b>Read-only snapshot.</b> The API is unreachable, so you're seeing results saved
            {meta?.generated_at ? ` on ${fmtDate(meta.generated_at)}` : ''}. Approve, Edit and Reject are disabled. A free server can take up to a minute to wake.{' '}
            <button onClick={() => location.reload()} className="ml-1 rounded border border-amber-400 bg-white px-2 py-0.5 text-xs font-semibold">
              Try live again
            </button>
          </div>
        ) : (
          <div className="bg-slate-100 px-4 py-1 text-xs text-slate-600">
            The AI verdicts were precomputed offline with free-tier Gemini models (two blind solvers and a judge). Your
            actions are live and audited, and the original question bank is never overwritten.
          </div>
        )}
        {showWhy && (
          <div className="border-t border-slate-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-950">
            <b>Most harm first.</b> A wrong answer key marks every student who solves it correctly as wrong, so wrong keys
            and unanswerable questions come first. Missing data, options and figures come next, because students
            can't attempt those at all. Then wrong solutions, then cosmetic issues, then reports that need no change.
            Within each band, cases with more students reporting go first, then the ones the AI is least sure about,
            then the oldest.
          </div>
        )}
      </header>

      {loadErr ? (
        <div className="m-8 rounded-xl border border-rose-200 bg-rose-50 p-6 text-rose-900">
          <b>Couldn't load the queue.</b> {loadErr}
          <button onClick={() => location.reload()} className="ml-3 underline">Retry</button>
        </div>
      ) : !queue ? (
        <div className="m-8 animate-pulse text-slate-500">Loading queue… (a free-tier server can take ~20s to wake up)</div>
      ) : (
        <div className="flex flex-1">
          <aside className={`${mobileList ? 'block' : 'hidden'} w-full shrink-0 border-r border-slate-200 bg-white md:sticky md:top-[88px] md:block md:h-[calc(100vh-88px)] md:w-[380px]`}>
            <Queue items={queue} selected={selected} onSelect={select} filter={filter} setFilter={setFilter} />
          </aside>
          <main className={`${mobileList ? 'hidden' : 'block'} min-w-0 flex-1 md:block`}>
            <button onClick={() => setMobileList(true)} className="m-3 rounded-md border border-slate-300 px-3 py-1 text-sm md:hidden">
              ← Queue
            </button>
            {caseErr && <p className="m-6 text-rose-700">Couldn't load this case: {caseErr}</p>}
            {!current && !caseErr && <div className="m-6 animate-pulse text-slate-500">Loading case…</div>}
            {current && (
              <CaseView key={current.questionId} c={current} readOnly={readOnly} canAct={!!passcode} onAction={onAction} busy={busy} error={actionErr} />
            )}
          </main>
        </div>
      )}
      <AuditDrawer open={auditOpen} onClose={() => setAuditOpen(false)} />
    </div>
  )
}
