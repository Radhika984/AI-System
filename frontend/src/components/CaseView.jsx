import { useEffect, useState } from 'react'
import Html from './Html'
import EditForm from './EditForm'
import { fmtDate, headline, ROUTE, STATUS } from './labels'

function Section({ n, title, children, tone = '' }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${tone}`}>
      <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-900 text-[10px] text-white">{n}</span>
        {title}
      </h3>
      {children}
    </section>
  )
}

function Confidence({ value }) {
  const pct = Math.round(value * 100)
  const tone = pct >= 85 ? 'bg-emerald-500' : pct >= 65 ? 'bg-amber-500' : 'bg-rose-500'
  return (
    <div className="flex items-center gap-2" title="AI confidence">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-slate-600">{pct}% sure</span>
    </div>
  )
}

function Solves({ c }) {
  const a = c.agreement || {}
  const entries = Object.entries(c.solves || {})
  if (!entries.length) return null
  const key = a.stored_key ?? c.answer
  let summary, tone
  if (a.agree && a.matches_key) {
    summary = `Both blind solvers independently got ${a.answer}, the same as the stored key.`
    tone = 'bg-emerald-50 text-emerald-900'
  } else if (a.agree) {
    summary = `Both blind solvers independently got ${a.answer}. The stored key says ${key}.`
    tone = 'bg-amber-50 text-amber-900'
  } else {
    const parts = entries.map(([k]) => `${k}: ${(a.answers || {})[k] ?? 'no option'}`).join(', ')
    summary = `The blind solvers disagree (${parts}; stored key ${key}). Treat the AI's view with care.`
    tone = 'bg-slate-100 text-slate-800'
  }
  return (
    <div className={`mt-3 rounded-lg px-3 py-2 text-sm ${tone}`}>
      {summary}
      {a.numeric_ok === true && <span className="ml-2 text-xs text-emerald-700">✓ Arithmetic re-checked by code.</span>}
      {a.numeric_ok === false && <span className="ml-2 text-xs text-rose-700">✗ The code re-check of the arithmetic failed.</span>}
      <details className="mt-1 text-xs text-slate-600">
        <summary className="cursor-pointer">How each solver got there</summary>
        <ul className="mt-1 space-y-1">
          {entries.map(([k, s]) => (
            <li key={k}><b>Solver {k}</b> ({s.model}): {s.method || s.error}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function fixSummary(c) {
  const d = c.diff
  if (!d) return null
  if (d.field === 'answer') return `Change the key from ${d.before} to ${d.after}`
  const strip = (s) => String(s).replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim()
  const f = strip(d.find).slice(0, 50)
  const r = strip(d.replace).slice(0, 60)
  return `In the ${d.field}: “${f || '(blank)'}” → “${r}”`
}

function Diff({ c }) {
  const d = c.diff
  if (!d) {
    const msg =
      c.route === 'no_change'
        ? 'Nothing in the question changes.'
        : 'The AI is not allowed to write this fix (it needs authored content). Use Edit to write it yourself, or Reject.'
    return <p className="text-sm text-slate-600">{msg}</p>
  }
  if (d.field === 'answer') {
    const opt = (letters) =>
      String(letters)
        .replace(/[[\]"]/g, '')
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean)
        .map((L) => (d.options?.[L] ? `(${L}) ${d.options[L]}` : `(${L})`))
        .join(', ') || '(empty)'
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg bg-rose-50 p-3">
          <div className="text-xs font-semibold text-rose-700">Current key</div>
          <div className="mt-1 font-mono text-lg text-rose-900">{d.before}</div>
          <div className="text-sm text-rose-800">{opt(d.before)}</div>
        </div>
        <div className="rounded-lg bg-emerald-50 p-3">
          <div className="text-xs font-semibold text-emerald-700">Key after the fix</div>
          <div className="mt-1 font-mono text-lg font-bold text-emerald-900">{d.after}</div>
          <div className="text-sm text-emerald-800">{opt(d.after)}</div>
        </div>
      </div>
    )
  }
  return (
    <div>
      <p className="mb-2 text-xs text-slate-500">
        Field <code className="rounded bg-slate-100 px-1">{d.field}</code> · only the highlighted part changes
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg border border-rose-200 p-3">
          <div className="mb-1 text-xs font-semibold text-rose-700">Before</div>
          <Html html={d.before_html} />
        </div>
        <div className="rounded-lg border border-emerald-200 p-3">
          <div className="mb-1 text-xs font-semibold text-emerald-700">After</div>
          <Html html={d.after_html} />
        </div>
      </div>
    </div>
  )
}

function Safety({ c }) {
  const reasons = [...new Set(c.reports.flatMap((r) => r.route_reasons || []))]
  const guard = [...new Set(c.reports.flatMap((r) => r.guard_log || []))]
  const overrides = [...new Set(c.reports.flatMap((r) => r.overrides || []))]
  const route = ROUTE[c.route]
  return (
    <div className="space-y-2 text-sm">
      {c.injection_in_group && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-rose-900">
          <b>Manipulation attempt.</b> A comment on this question tries to give the AI instructions. It was treated as
          plain data, and nothing about this question can be auto-applied.
        </div>
      )}
      <p>
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${route.tone}`}>{route.label}</span>{' '}
        <span className="text-slate-600">
          {c.route === 'auto_apply'
            ? 'Every safety check passed, so this went live automatically. Reject to undo it.'
            : c.route === 'faculty_review'
            ? 'Held for you. Nothing changes until you approve.'
            : 'No edit to the question.'}
        </span>
      </p>
      {reasons.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-slate-600">
          {reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {guard.length > 0 && (
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer">Edit guard log ({guard.length})</summary>
          <ul className="mt-1 list-disc pl-5">{guard.map((g) => <li key={g}>{g}</li>)}</ul>
        </details>
      )}
      {overrides.length > 0 && (
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer">Rule-based overrides of the AI ({overrides.length})</summary>
          <ul className="mt-1 list-disc pl-5">{overrides.map((g) => <li key={g}>{g}</li>)}</ul>
        </details>
      )}
    </div>
  )
}

function Replies({ c }) {
  return (
    <div className="space-y-3">
      {c.reports.map((r) => (
        <div key={r.reportId} className="rounded-lg bg-slate-50 p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <b className="text-slate-700">{r.reportId}</b>
            <span>{r.source}</span>
            <span>{fmtDate(r.reportedAt)}</span>
            {r.verdict !== c.verdict && <span className="rounded bg-slate-200 px-1">{headline(r.verdict, r.repair)}</span>}
            {(r.flags || []).map((f) => (
              <span
                key={f.code}
                title={f.detail}
                className={`rounded px-1 ${f.code === 'injection' ? 'bg-rose-200 text-rose-900' : 'bg-slate-200'}`}
              >
                {f.code.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
          <blockquote className="mt-1.5 border-l-2 border-slate-300 pl-2 text-sm italic text-slate-600">
            “{r.comment}”
          </blockquote>
          <div className="mt-2 flex justify-end">
            <div className="max-w-[90%] rounded-2xl rounded-br-sm bg-indigo-600 px-3 py-2 text-sm text-white shadow">
              {r.student_reply}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function CaseView({ c, readOnly, onAction, busy, error }) {
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState('')
  useEffect(() => {
    const h = (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.metaKey || e.ctrlKey) return
      if (e.key === 'e' && !readOnly) setEditing(true)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [readOnly])
  const st = STATUS[c.status] || STATUS.pending
  const done = ['approved', 'edited', 'rejected'].includes(c.status)
  const approveLabel =
    c.route === 'auto_apply' ? 'Keep fix' : c.diff ? 'Approve fix' : c.verdict === 'defect' ? 'Confirm problem' : 'Confirm & send reply'

  return (
    <article className="mx-auto max-w-5xl space-y-4 p-4 pb-32">
      {/* 1. What is wrong */}
      <header className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>{c.subject} · {c.chapter}</span>
          <span>· {c.type}</span>
          <span>· {c.reportIds.length} report{c.reportIds.length > 1 ? 's' : ''} from {c.reporters} student{c.reporters > 1 ? 's' : ''}</span>
          <span className={`ml-auto font-medium ${st.tone}`}>● {st.label}</span>
        </div>
        <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">{headline(c.verdict, c.repair)}</h2>
        {fixSummary(c) && <p className="mt-1 break-words font-medium text-indigo-800">{fixSummary(c)}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${ROUTE[c.route].tone}`}>{ROUTE[c.route].label}</span>
          <Confidence value={c.confidence} />
          {c.needs_attention && (
            <span className="rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-semibold text-rose-800">
              Both blind solvers disagree with the stored key. Please check.
            </span>
          )}
        </div>
      </header>

      <Section n="1" title="Why the AI thinks so">
        <p className="text-[15px] leading-relaxed text-slate-800">{c.reports[0]?.evidence}</p>
        {c.analysis && <p className="mt-2 text-sm text-slate-600">{c.analysis}</p>}
        <Solves c={c} />
      </Section>

      <Section n="2" title="What will change">
        <Diff c={c} />
      </Section>

      <Section n="3" title="Is it safe?">
        <Safety c={c} />
      </Section>

      <Section n="4" title="What the student receives">
        <Replies c={c} />
      </Section>

      <Section n="5" title="The question as students see it">
        <Html html={c.question_html} />
        {!c.has_images && /figure|diagram/i.test(c.question_html) && (
          <p className="mt-2 text-xs font-medium text-rose-700">No image is attached to this question.</p>
        )}
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-medium text-slate-600">
            Stored solution · key <b>{c.answer}</b>
            {c.live_answer !== c.answer && <> → live <b>{c.live_answer}</b></>}
          </summary>
          <div className="mt-2 rounded-lg bg-slate-50 p-3">
            <Html html={c.solution_html} />
          </div>
        </details>
        {c.errorHistory.length > 0 && (
          <div className="mt-3 text-xs text-slate-600">
            <b>Edit history:</b>{' '}
            {c.errorHistory.map((h, i) => (
              <span key={i}>
                {fmtDate(h.at)} by {h.actor}: {h.note}
              </span>
            ))}
          </div>
        )}
      </Section>

      <Section n="6" title="Audit trail for this question">
        {c.audit.length === 0 ? (
          <p className="text-sm text-slate-500">No actions yet.</p>
        ) : (
          <ol className="space-y-1 text-sm">
            {[...c.audit].reverse().map((e) => (
              <li key={e.id} className="flex flex-wrap gap-x-2">
                <span className="text-slate-500">{fmtDate(e.at)}</span>
                <b>{e.actor}</b>
                <span className="rounded bg-slate-100 px-1 text-xs leading-5">{e.action}</span>
                {e.edit && (
                  <span className="text-slate-600">
                    {e.edit.field}: “{String(e.edit.find).slice(0, 40)}” → “{String(e.edit.replace).slice(0, 40)}”
                  </span>
                )}
                {e.note && <span className="text-slate-500">{e.note}</span>}
              </li>
            ))}
          </ol>
        )}
      </Section>

      {editing && (
        <EditForm
          c={c}
          busy={busy}
          onCancel={() => setEditing(false)}
          onSubmit={async (edit, n) => {
            const ok = await onAction({ action: 'edit', edit, note: n })
            if (ok) setEditing(false)
          }}
        />
      )}

      {/* Sticky action bar */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200 bg-white/95 backdrop-blur md:left-[380px]">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-2 px-4 py-3">
          {error && <p className="w-full text-sm font-medium text-rose-700">{error}</p>}
          {readOnly ? (
            <p className="text-sm text-amber-800">Read-only snapshot: actions are disabled because the API is unreachable.</p>
          ) : done ? (
            <>
              <p className="text-sm text-slate-600">
                {st.label} by <b>{c.status_detail?.by}</b> · {c.status_detail?.at && fmtDate(c.status_detail.at)}
              </p>
              <button disabled={busy} onClick={() => onAction({ action: 'reopen', note })}
                className="ml-auto rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100">
                Reopen
              </button>
            </>
          ) : (
            <>
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Optional note for the audit log"
                className="hidden min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm sm:block"
              />
              <button disabled={busy} onClick={() => onAction({ action: 'reject', note })}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                title="Reject (R)">
                Reject <kbd>R</kbd>
              </button>
              <button disabled={busy} onClick={() => setEditing(true)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                title="Edit (E)">
                Edit <kbd>E</kbd>
              </button>
              <button disabled={busy} onClick={() => onAction({ action: 'approve', note })}
                className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-700 disabled:opacity-50"
                title="Approve (A)">
                {busy ? 'Saving…' : approveLabel} <kbd className="ml-1 border-indigo-400 bg-indigo-500 text-white">A</kbd>
              </button>
            </>
          )}
        </div>
      </div>
    </article>
  )
}
