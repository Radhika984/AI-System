import { useCallback, useEffect, useRef, useState } from 'react'
import { getAudit, getCase, getMode, getPasscode, getQueue, getSnapshotMeta, postAction, setPasscode } from './api/client'
import CaseView, { AuditChange } from './components/CaseView'
import Queue, { filterItems, isDone } from './components/Queue'
import { GROUPS, Icon, displayOrder, fmtDate, groupOf } from './components/labels'

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

const ACTION_LABEL = {
  auto_apply: 'Auto-applied by the system', approve: 'Approved', edit: 'Edited', reject: 'Rejected',
  revert_auto_apply: 'Undid the auto-applied fix', reopen: 'Reopened', demo_reset: 'Demo reset',
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
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/25" onClick={onClose}>
      <aside className="h-full w-full max-w-lg overflow-y-auto bg-ivory px-7 py-6 shadow-xl" onClick={(e) => e.stopPropagation()}
        role="dialog" aria-label="Audit log">
        <div className="mb-5 flex items-start justify-between">
          <div>
            <p className="eyebrow mb-1">Accountability</p>
            <h2 className="font-serif text-[22px] font-semibold text-ink">Audit log (all questions)</h2>
          </div>
          <button onClick={onClose} className="btn px-2 text-muted hover:text-ink" aria-label="Close audit log">
            <Icon name="x" className="h-4 w-4" />
          </button>
        </div>
        {rows === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted">No actions recorded yet.</p>
        ) : (
          <ol className="relative ml-1.5 border-l border-line">
            {rows.map((e) => (
              <li key={e.id} className="relative pb-5 pl-6">
                <span className={`absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-ivory ${
                  e.action === 'reject' || e.action === 'revert_auto_apply' ? 'bg-err' : e.action === 'auto_apply' ? 'bg-ok' : 'bg-forest'}`} />
                <p className="flex flex-wrap items-baseline gap-x-2 text-[13.5px]">
                  <span className="font-medium text-ink">{ACTION_LABEL[e.action] || e.action}</span>
                  <span className="text-muted">by {e.actor}</span>
                </p>
                <p className="text-[12px] tabular-nums text-muted">{fmtDate(e.at)} · {e.reportIds?.join(', ')}</p>
                {e.edit && <AuditChange edit={e.edit} />}
                {e.note && <p className="mt-1 text-[12px] italic text-muted">{e.note}</p>}
              </li>
            ))}
          </ol>
        )}
      </aside>
    </div>
  )
}

function Overview({ queue, showWhy, setShowWhy }) {
  const count = (k) => queue.filter((c) => groupOf(c) === k).length
  const total = queue.length
  const waiting = count('urgent') + count('review')
  const auto = count('auto')
  const nochange = count('nochange')
  const completed = count('completed')
  const stats = [
    { label: 'Total questions', value: total, dot: 'bg-ink' },
    { label: 'Waiting for review', value: waiting, dot: 'bg-warn' },
    { label: 'Auto-corrected · spot check', value: auto, dot: 'bg-ok' },
    { label: 'No change needed', value: nochange, dot: 'bg-sage' },
    { label: 'Completed decisions', value: completed, dot: 'bg-forest' },
  ]
  return (
    <section aria-label="Workspace overview" className="border-b border-line bg-ivory px-5 py-5 sm:px-8">
      <div className="grid grid-cols-3 items-end gap-x-4 gap-y-4 sm:flex sm:flex-wrap sm:gap-x-8">
        {stats.map((s) => (
          <div key={s.label} className="min-w-0 sm:min-w-[110px]">
            <p className="font-serif text-[26px] leading-none tabular-nums text-ink">{s.value}</p>
            <p className="mt-1.5 flex items-center gap-1.5 text-[12px] text-muted">
              <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />{s.label}
            </p>
          </div>
        ))}
        <div className="col-span-3 min-w-[220px] flex-1">
          <div className="flex h-1.5 overflow-hidden rounded-full bg-line" role="img"
            aria-label={`${completed} of ${total} decided by faculty, ${auto} auto-applied awaiting spot check`}>
            <div className="bg-forest" style={{ width: `${(completed / total) * 100}%` }} />
            <div className="bg-ok/60" style={{ width: `${(auto / total) * 100}%` }} />
          </div>
          <p className="mt-2 flex flex-wrap justify-between gap-2 text-[12px] text-muted">
            <span><b className="font-medium text-ink">{completed}</b> of {total} decided by faculty · <b className="font-medium text-ink">{auto}</b> auto-applied, awaiting spot check</span>
            <button onClick={() => setShowWhy((v) => !v)} className="font-medium text-forest underline-offset-2 hover:underline">
              Why this order?
            </button>
          </p>
        </div>
      </div>
      {showWhy && (
        <div className="mt-4 max-w-3xl rounded-md border border-line bg-white px-5 py-4 text-[13.5px] leading-relaxed text-ink">
          <b className="font-semibold">Most harm first.</b> A wrong answer key marks every student who solves it correctly
          as wrong, so wrong keys, unanswerable questions and cases where the AI is unsure come first. Then fixes the AI
          may not apply on its own: missing data, options or figures, wrong solutions, and cosmetic or metadata issues.
          Auto-applied fixes are already live and wait for a spot check; reports needing no change come last. Inside each
          group, cases keep the server's urgency rank: more students reporting first, then lower AI confidence, then the
          oldest report.
          <span className="mt-2 block text-[12px] text-muted">Groups: {GROUPS.map((g) => g.label).join(' · ')}</span>
        </div>
      )}
    </section>
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
  const [query, setQuery] = useState('')
  const [auditOpen, setAuditOpen] = useState(false)
  const [showWhy, setShowWhy] = useState(false)
  const [meta, setMeta] = useState(null)
  const [toast, setToast] = useState('')
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
        const ordered = displayOrder(q)
        const first = ordered.find((c) => !isDone(c)) || ordered[0]
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

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 2600)
    return () => clearTimeout(t)
  }, [toast])

  const select = (id) => {
    setSelected(id)
    setMobileList(false)
    window.scrollTo(0, 0)
  }

  const DONE_MSG = {
    approve: 'Decision recorded in the audit log.',
    edit: 'Correction applied and recorded in the audit log.',
    reject: 'Recommendation rejected and recorded in the audit log.',
    reopen: 'Case reopened.',
  }

  const inFlight = useRef(false) // blocks a second submit before the busy state has re-rendered
  const onAction = async (payload) => {
    if (inFlight.current) return false
    inFlight.current = true
    setBusy(true)
    setActionErr('')
    try {
      const updated = await postAction(selected, { actor: actor || 'faculty', ...payload })
      setCurrent(updated)
      setToast(DONE_MSG[payload.action] || 'Saved.')
      const q = await refreshQueue()
      if (payload.action !== 'reopen') {
        const ordered = displayOrder(q)
        const idx = ordered.findIndex((c) => c.questionId === selected)
        const next = ordered.slice(idx + 1).find((c) => !isDone(c)) || ordered.find((c) => !isDone(c))
        if (next && next.questionId !== selected) setTimeout(() => select(next.questionId), 700)
      }
      return true
    } catch (e) {
      setActionErr(e.message)
      return false
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  // Keyboard: J/K move through the list as displayed (ignored while typing).
  // A / R are handled by CaseView, which asks for confirmation before calling onAction.
  useEffect(() => {
    const h = (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.metaKey || e.ctrlKey) return
      if (!queue) return
      const visible = filterItems(queue, filter, query)
      const i = visible.findIndex((c) => c.questionId === selected)
      if (e.key === 'j' && visible[i + 1]) select(visible[i + 1].questionId)
      if (e.key === 'k' && i > 0) select(visible[i - 1].questionId)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  })

  const readOnly = getMode() === 'snapshot'

  return (
    <div className="min-h-screen bg-ivory">
      <header className="border-b border-line bg-white">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-4 px-5 py-4 sm:px-8">
          <div className="flex items-center gap-5">
            <div className="leading-none">
              <p className="text-[13px] font-semibold tracking-[0.28em] text-forest">ACADZA</p>
              <p className="mt-1 text-[10.5px] uppercase tracking-[0.14em] text-sage">Academic Intelligence</p>
            </div>
            <span className="hidden h-9 w-px bg-line sm:block" />
            <div>
              <h1 className="font-serif text-[22px] font-semibold leading-tight text-ink">Faculty Review Workspace</h1>
              <p className="mt-0.5 hidden text-[13px] text-muted md:block">
                Review reported questions, verify AI recommendations and make informed academic decisions.
              </p>
            </div>
          </div>
          <div className="flex w-full min-w-0 items-center gap-2 lg:ml-auto lg:w-auto">
            <label className="relative min-w-0 flex-1 lg:flex-none">
              <span className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-muted"><Icon name="user" className="h-3.5 w-3.5" /></span>
              <input
                value={actor}
                onChange={(e) => setActor(e.target.value)}
                placeholder="Your name"
                title="Recorded as the actor in the audit log"
                aria-label="Your name for the audit log"
                className="field w-full pl-8 lg:w-44"
              />
            </label>
            <label className="relative min-w-0 flex-1 lg:flex-none">
              <span className={`pointer-events-none absolute inset-y-0 left-2.5 flex items-center ${passcode ? 'text-ok' : 'text-warn'}`}>
                <Icon name={passcode ? 'check' : 'lock'} className="h-3.5 w-3.5" />
              </span>
              <input
                type="password"
                // Uncontrolled on purpose: a React-controlled value={...} is reflected into the DOM
                // `value` attribute, which would expose the passcode in the page HTML.
                onChange={(e) => updatePasscode(e.target.value)}
                placeholder={passcode ? 'Passcode set ✓' : 'Reviewer passcode'}
                aria-label="Reviewer passcode"
                autoComplete="off"
                className={`field w-full pl-8 lg:w-44 ${passcode ? 'border-ok/50 placeholder:text-ok' : ''}`}
              />
            </label>
            {passcode && (
              <button
                onClick={(e) => {
                  updatePasscode('')
                  const box = e.currentTarget.parentElement.querySelector('input[type=password]')
                  if (box) box.value = ''
                }}
                className="btn shrink-0 px-2 text-[12px] text-muted hover:text-ink"
                title="Forget the passcode in this tab"
              >
                Clear
              </button>
            )}
            <button onClick={() => setAuditOpen(true)} className="btn-neutral shrink-0 px-3">
              Audit log
            </button>
          </div>
        </div>
        {readOnly ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-warn/20 bg-warnbg px-5 py-2 text-[13px] text-warn sm:px-8">
            <Icon name="alert" className="h-4 w-4 shrink-0" />
            <span>
              <b>Read-only snapshot.</b> The API is unreachable, so you're seeing results saved
              {meta?.generated_at ? ` on ${fmtDate(meta.generated_at)}` : ''}. Approve, Edit and Reject are disabled. A free server can take up to a minute to wake.
            </span>
            <button onClick={() => location.reload()} className="btn-neutral px-2.5 py-1 text-[12px]">
              Try live again
            </button>
          </div>
        ) : null}
      </header>

      {queue && <Overview queue={queue} showWhy={showWhy} setShowWhy={setShowWhy} />}

      {loadErr ? (
        <div className="m-8 flex items-start gap-3 rounded-lg border border-err/30 bg-errbg p-6 text-err">
          <Icon name="alert" className="mt-0.5 h-5 w-5" />
          <div>
            <b>Couldn't load the queue.</b> {loadErr}
            <button onClick={() => location.reload()} className="ml-3 underline">Retry</button>
          </div>
        </div>
      ) : !queue ? (
        <div className="m-8 animate-pulse text-muted">Loading queue… (a free-tier server can take ~20s to wake up)</div>
      ) : (
        <div className="flex">
          <aside className={`${mobileList ? 'block' : 'hidden'} w-full shrink-0 border-r border-line bg-white md:sticky md:top-0 md:block md:h-screen md:w-[320px] lg:w-[360px]`}>
            <Queue items={queue} selected={selected} onSelect={select} filter={filter} setFilter={setFilter} query={query} setQuery={setQuery} />
          </aside>
          <main className={`${mobileList ? 'hidden' : 'block'} min-w-0 flex-1 md:block`}>
            <button onClick={() => setMobileList(true)} className="btn-neutral m-4 mb-0 md:hidden">
              <Icon name="menu" className="h-4 w-4" /> Queue
            </button>
            {caseErr && <p className="m-8 text-err">Couldn't load this case: {caseErr}</p>}
            {!current && !caseErr && <div className="m-8 animate-pulse text-muted">Loading case…</div>}
            {current && (
              <CaseView key={current.questionId} c={current} rank={queue.find((q) => q.questionId === current.questionId)?.rank} readOnly={readOnly} canAct={!!passcode} onAction={onAction} busy={busy} error={actionErr} clearError={() => setActionErr('')} />
            )}
          </main>
        </div>
      )}

      {toast && (
        <div role="status" className="fixed bottom-24 right-6 z-50 flex items-center gap-2 rounded-md bg-ink px-4 py-2.5 text-[13px] text-white shadow-lg">
          <Icon name="check" className="h-4 w-4 text-mist" />{toast}
        </div>
      )}
      <AuditDrawer open={auditOpen} onClose={() => setAuditOpen(false)} />
    </div>
  )
}
