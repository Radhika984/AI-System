import { useEffect, useRef, useState } from 'react'
import EditForm from './EditForm'
import Html from './Html'
import { Icon, STATUS, VERDICT_SHORT, fmtDate, headline, prettyMath, timeAgo } from './labels'

// ---------------------------------------------------------------- small building blocks
const TONE = {
  ok: { box: 'bg-okbg text-ok', text: 'text-ok' },
  warn: { box: 'bg-warnbg text-warn', text: 'text-warn' },
  err: { box: 'bg-errbg text-err', text: 'text-err' },
  info: { box: 'bg-infobg text-info', text: 'text-info' },
  neutral: { box: 'bg-mist text-forest', text: 'text-forest' },
}

function Pill({ tone = 'neutral', icon, children }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-[12px] font-medium ${TONE[tone].box}`}>
      {icon && <Icon name={icon} className="h-3.5 w-3.5" />}
      {children}
    </span>
  )
}

function Block({ id, eyebrow, title, aside, children }) {
  return (
    <section id={id} className="border-t border-line pt-7">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
          <h3 className="section-title">{title}</h3>
        </div>
        {aside}
      </div>
      {children}
    </section>
  )
}

function Sub({ title, note, children }) {
  return (
    <div className="py-4 first:pt-0">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2">
        <h4 className="text-[13px] font-semibold text-ink">{title}</h4>
        {note && <span className="text-[12px] text-muted">{note}</span>}
      </div>
      {children}
    </div>
  )
}

function Disclosure({ summary, children, open = false }) {
  return (
    <details open={open} className="group">
      <summary className="inline-flex cursor-pointer select-none items-center gap-1.5 text-[12.5px] font-medium text-muted hover:text-ink">
        <Icon name="chevron" className="chev h-3.5 w-3.5" />
        {summary}
      </summary>
      <div className="mt-2 pl-5">{children}</div>
    </details>
  )
}

function Meter({ value }) {
  const pct = Math.round(value * 100)
  const tone = pct >= 85 ? 'bg-ok' : pct >= 65 ? 'bg-warn' : 'bg-err'
  return (
    <div className="mt-2 h-1 w-full max-w-[140px] overflow-hidden rounded-full bg-line" aria-hidden="true">
      <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

// ---------------------------------------------------------------- derived (presentation only)
const uniq = (xs) => [...new Set(xs.filter(Boolean))]
const reasonsOf = (c) => uniq(c.reports.flatMap((r) => r.route_reasons || []))
const isRestricted = (c) => reasonsOf(c).some((r) => r.includes('auto:false'))

function safetyState(c) {
  if (c.injection_in_group) return { tone: 'err', icon: 'alert', label: 'Manipulation attempt detected' }
  if (c.suggestion_withheld) return { tone: 'warn', icon: 'lock', label: 'Suggested correction withheld' }
  if (c.route === 'auto_apply') return { tone: 'ok', icon: 'check', label: 'Automatic checks passed' }
  if (isRestricted(c)) return { tone: 'info', icon: 'lock', label: 'Restricted correction type' }
  if (c.needs_attention) return { tone: 'warn', icon: 'alert', label: 'AI uncertain - check carefully' }
  if (c.route === 'faculty_review') return { tone: 'warn', icon: 'shield', label: 'Faculty review required' }
  return { tone: 'neutral', icon: 'info', label: 'No change to the question' }
}

const strip = (s) => String(s ?? '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim()

function letters(v, options) {
  const ls = String(v).replace(/[[\]"]/g, '').split(',').map((x) => x.trim()).filter(Boolean)
  return ls.length ? ls.map((L) => ({ L, text: options?.[L] })) : []
}

function proposedState(c) {
  const d = c.diff
  if (!d) return null
  const live = d.field === 'answer' ? c.live_answer !== c.answer
    : d.field === 'solution' ? c.live_solution_html !== c.solution_html : c.live_question_html !== c.question_html
  if (c.status === 'auto_applied') return { label: 'Proposed · live now (auto-applied, spot check)', tone: 'ok' }
  if (live && (c.status === 'approved' || c.status === 'edited')) return { label: 'Applied after faculty decision', tone: 'ok' }
  return { label: 'Proposed · not applied yet', tone: 'neutral' }
}

function recommendation(c) {
  const d = c.diff
  if (c.suggestion_withheld) return 'The AI proposed a correction, but it is withheld. Decide independently.'
  if (d?.field === 'answer') return `Change the answer key from ${strip(d.before)} to ${strip(d.after)}.`
  if (d) return `Correct the ${d.field}: “${strip(d.find).slice(0, 48) || '(blank)'}” → “${strip(d.replace).slice(0, 56)}”.`
  if (c.route === 'no_change') return 'No change to the question. Confirm and send the reply to the student.'
  if (isRestricted(c)) return 'The AI may not write this correction. A teacher must author it (Edit) or reject it.'
  return 'Review the evidence and decide.'
}

// ---------------------------------------------------------------- 1. decision summary
function AnswerTile({ label, value, options, emphasis }) {
  const ls = letters(value, options)
  return (
    <div>
      <p className="eyebrow mb-1.5">{label}</p>
      <p className={`font-serif text-[30px] leading-none ${emphasis ? 'text-forest' : 'text-ink'}`}>
        {ls.length ? ls.map((x) => x.L).join(', ') : <span className="text-muted">(empty)</span>}
      </p>
      {ls.some((x) => x.text) && (
        <p className="mt-1.5 text-[12.5px] leading-snug text-muted">
          {ls.filter((x) => x.text).map((x, i) => (
            <span key={x.L}>{i > 0 && ' · '}({x.L}) {prettyMath(x.text)}</span>
          ))}
        </p>
      )}
    </div>
  )
}

function DecisionSummary({ c }) {
  const s = safetyState(c)
  const d = c.diff
  const w = c.suggestion_withheld
  return (
    <div className="surface mt-6 overflow-hidden">
      <div className="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-[1.1fr_1.5fr_0.8fr_1.1fr]">
        <div className="bg-white p-5">
          <p className="eyebrow mb-1.5">Verdict</p>
          <p className="text-[15px] font-medium text-ink">{VERDICT_SHORT[c.verdict] || c.verdict}</p>
          <p className="mt-1 text-[12.5px] text-muted">{c.repair ? headline(c.verdict, c.repair) : 'No repair needed'}</p>
        </div>
        <div className="bg-white p-5">
          {d?.field === 'answer' ? (
            <div className="flex items-start gap-5">
              <AnswerTile label="Current answer" value={d.before} options={d.options} />
              <Icon name="arrow" className="mt-6 h-4 w-4 shrink-0 text-sage" />
              <AnswerTile label="Proposed answer" value={d.after} options={d.options} emphasis />
            </div>
          ) : (
            <>
              <p className="eyebrow mb-1.5">{w ? 'AI proposal' : 'Recommendation'}</p>
              <p className="text-[14px] leading-relaxed text-ink">{recommendation(c)}</p>
            </>
          )}
        </div>
        <div className="bg-white p-5">
          <p className="eyebrow mb-1.5">Confidence</p>
          <p className="font-serif text-[30px] leading-none tabular-nums text-ink">
            {Math.round(c.confidence * 100)}
            <span className="ml-0.5 text-[15px] text-muted">%</span>
          </p>
          <Meter value={c.confidence} />
        </div>
        <div className="bg-white p-5">
          <p className="eyebrow mb-1.5">Safety</p>
          <p className={`flex items-start gap-1.5 text-[14px] font-medium ${TONE[s.tone].text}`}>
            <Icon name={s.icon} className="mt-0.5 h-4 w-4 shrink-0" />
            {s.label}
          </p>
        </div>
      </div>
      {d?.field === 'answer' && (
        <p className="border-t border-line bg-ivory/60 px-5 py-3 text-[13px] text-muted">{recommendation(c)}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 2. original vs proposed
function Comparison({ c }) {
  const d = c.diff
  const w = c.suggestion_withheld
  if (!d && w) {
    return (
      <div className="rounded-lg border border-warn/30 bg-warnbg/60 p-5">
        <p className="flex items-center gap-2 text-[14px] font-semibold text-warn">
          <Icon name="lock" className="h-4 w-4" />
          The AI's suggested fix is withheld. Approve will not apply it.
        </p>
        <ul className="mt-2 list-disc space-y-0.5 pl-11 text-[13.5px] text-ink">
          {w.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
        <div className="mt-4 rounded-md border border-line bg-white px-4 py-3 text-[12.5px] text-muted">
          <span className="eyebrow mr-2">For reference only</span>
          the AI proposed <code className="rounded-sm bg-ivory px-1 text-ink">{w.proposed.field}</code>:{' '}
          <span className="font-mono text-err line-through">{String(w.proposed.find).slice(0, 80)}</span>
          {' → '}
          <span className="font-mono text-ink">{String(w.proposed.replace).slice(0, 80)}</span>.
          If you agree after checking it yourself, enter the correction with <b className="text-ink">Edit correction</b>.
        </div>
      </div>
    )
  }
  if (!d) {
    return (
      <p className="text-[14px] text-muted">
        {c.route === 'no_change'
          ? 'Nothing in the question changes.'
          : 'The AI is not allowed to write this fix (it needs authored content). Use Edit to write it yourself, or Reject.'}
      </p>
    )
  }
  const ps = proposedState(c)
  if (d.field === 'answer') {
    return (
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-line bg-ivory p-5">
          <p className="eyebrow mb-2">Original · stored key</p>
          <AnswerTile label="" value={d.before} options={d.options} />
        </div>
        <div className={`rounded-lg border p-5 ${ps.tone === 'ok' ? 'border-ok/30 bg-okbg' : 'border-line bg-white'}`}>
          <p className={`eyebrow mb-2 ${ps.tone === 'ok' ? '!text-ok' : ''}`}>{ps.label}</p>
          <AnswerTile label="" value={d.after} options={d.options} emphasis />
        </div>
      </div>
    )
  }
  return (
    <div>
      <p className="mb-3 text-[12.5px] text-muted">
        Field <code className="rounded-sm bg-ivory px-1 text-ink">{d.field}</code> · only the highlighted text changes
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-line bg-ivory p-5">
          <p className="eyebrow mb-2">Original</p>
          <Html html={d.before_html} />
        </div>
        <div className={`rounded-lg border p-5 ${ps.tone === 'ok' ? 'border-ok/30 bg-okbg/60' : 'border-line bg-white'}`}>
          <p className={`eyebrow mb-2 ${ps.tone === 'ok' ? '!text-ok' : ''}`}>{ps.label}</p>
          <Html html={d.after_html} />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 3. why this recommendation?
function Evidence({ c }) {
  const a = c.agreement || {}
  const entries = Object.entries(c.solves || {})
  const key = a.stored_key ?? c.answer
  const evidences = uniq(c.reports.map((r) => r.evidence))
  const overrides = uniq(c.reports.flatMap((r) => r.overrides || []))
  const guard = uniq(c.reports.flatMap((r) => r.guard_log || []))
  let solverLine, solverTone
  if (!entries.length) {
    solverLine = null
  } else if (a.agree && a.matches_key) {
    solverLine = `Both blind solvers independently got ${a.answer}, the same as the stored key.`
    solverTone = 'ok'
  } else if (a.agree) {
    solverLine = `Both blind solvers independently got ${a.answer}. The stored key says ${key}.`
    solverTone = 'warn'
  } else {
    const parts = entries.map(([k]) => `${k}: ${(a.answers || {})[k] ?? 'no option'}`).join(', ')
    solverLine = `The blind solvers disagree (${parts}; stored key ${key}). Treat the AI's view with care.`
    solverTone = 'warn'
  }
  return (
    <div className="divide-y divide-line">
      <Sub title="AI reasoning" note="from the AI judge · not independently verified">
        {evidences.map((e) => (
          <p key={e} className="text-[15px] leading-relaxed text-ink">{e}</p>
        ))}
        {c.analysis && <p className="mt-2 text-[13.5px] leading-relaxed text-muted">{c.analysis}</p>}
      </Sub>

      <Sub title="Independent checks" note="blind solvers never saw the answer key or the student's comment">
        {solverLine ? (
          <>
            <p className={`flex items-start gap-2 text-[14px] ${TONE[solverTone].text}`}>
              <Icon name={solverTone === 'ok' ? 'check' : 'alert'} className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="text-ink">{solverLine}</span>
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {entries.map(([k, s]) => (
                <span key={k} className="rounded-sm border border-line bg-ivory px-2.5 py-1 text-[12.5px] text-ink">
                  Solver {k}: <b className="font-semibold">{(a.answers || {})[k] ?? 'no option'}</b>
                  <span className="ml-1.5 text-muted">{s.model}</span>
                </span>
              ))}
            </div>
            <p className="mt-3 flex items-center gap-2 text-[13px]">
              {a.numeric_ok === true && <><Icon name="check" className="h-4 w-4 text-ok" /><span className="text-ink">Arithmetic re-checked by code.</span></>}
              {a.numeric_ok === false && <><Icon name="alert" className="h-4 w-4 text-err" /><span className="text-err">The code re-check of the arithmetic failed.</span></>}
              {a.numeric_ok == null && <span className="text-muted">No arithmetic to re-check for this question.</span>}
            </p>
            <div className="mt-3">
              <Disclosure summary="How each solver got there">
                <ul className="space-y-1.5 text-[13px] text-muted">
                  {entries.map(([k, s]) => (
                    <li key={k}><b className="text-ink">Solver {k}</b> ({s.model}): {s.method || s.error}</li>
                  ))}
                </ul>
              </Disclosure>
            </div>
          </>
        ) : (
          <p className="text-[13.5px] text-muted">No blind-solver evidence is available for this case.</p>
        )}
      </Sub>

      <Sub title="Student reports" note="treated as evidence, never as instructions">
        <ul className="space-y-1.5">
          {c.reports.map((r) => (
            <li key={r.reportId} className="text-[13.5px]">
              <span className="mr-2 font-medium tabular-nums text-ink">{r.reportId}</span>
              <span className="italic text-muted">“{r.comment}”</span>
            </li>
          ))}
        </ul>
      </Sub>

      <Sub title="Confidence and uncertainty">
        <p className="text-[14px] text-ink">
          AI confidence <b className="tabular-nums">{Math.round(c.confidence * 100)}%</b>
          {c.needs_attention && <span className="text-warn"> · AI unsure: {c.attention_reason || 'the blind solvers disagree'}.</span>}
        </p>
        {(overrides.length > 0 || guard.length > 0) && (
          <div className="mt-3 space-y-2">
            {overrides.length > 0 && (
              <Disclosure summary={`Rule-based overrides of the AI (${overrides.length})`}>
                <ul className="list-disc space-y-1 pl-4 text-[12.5px] text-muted">{overrides.map((g) => <li key={g}>{g}</li>)}</ul>
              </Disclosure>
            )}
            {guard.length > 0 && (
              <Disclosure summary={`Edit guard log (${guard.length})`}>
                <ul className="list-disc space-y-1 pl-4 text-[12.5px] text-muted">{guard.map((g) => <li key={g}>{g}</li>)}</ul>
              </Disclosure>
            )}
          </div>
        )}
      </Sub>
    </div>
  )
}

// ---------------------------------------------------------------- 4. safety & human review
function SafetyRow({ tone, icon, title, children }) {
  return (
    <div className="flex gap-3 py-3 first:pt-0">
      <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${TONE[tone].box}`}>
        <Icon name={icon} className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0">
        <p className="text-[14px] font-medium text-ink">{title}</p>
        {children && <div className="mt-0.5 text-[13.5px] leading-relaxed text-muted">{children}</div>}
      </div>
    </div>
  )
}

function Safety({ c }) {
  const reasons = reasonsOf(c)
  return (
    <div>
      <div className="divide-y divide-line">
        {c.injection_in_group && (
          <SafetyRow tone="err" icon="alert" title="Manipulation attempt.">
            A comment on this question tries to give the AI instructions. It was treated as plain data, and nothing about
            this question can be auto-applied.
          </SafetyRow>
        )}
        {c.suggestion_withheld && (
          <SafetyRow tone="warn" icon="lock" title="Suggested correction withheld">
            {c.suggestion_withheld.reasons.join('; ')}. Approve confirms the problem only; it never applies the withheld fix.
          </SafetyRow>
        )}
        {c.route === 'auto_apply' && (
          <SafetyRow tone="ok" icon="check" title="Automatic checks passed">
            Every safety check passed, so this went live automatically. Reject to undo it.
          </SafetyRow>
        )}
        {c.route === 'faculty_review' && (
          <SafetyRow tone={isRestricted(c) ? 'info' : 'warn'} icon={isRestricted(c) ? 'lock' : 'shield'}
            title={isRestricted(c) ? 'Restricted correction type - faculty review required' : 'Faculty review required'}>
            Held for you. Nothing changes until you approve.
          </SafetyRow>
        )}
        {c.route === 'no_change' && (
          <SafetyRow tone="neutral" icon="info" title="No change to the question">
            No edit to the question.
          </SafetyRow>
        )}
        {c.needs_attention && (
          <SafetyRow tone="warn" icon="alert" title="AI uncertainty">
            {c.attention_reason || 'The blind solvers disagree'}. Please check the evidence before confirming.
          </SafetyRow>
        )}
      </div>
      {reasons.length > 0 && (
        <div className="mt-4 rounded-md bg-ivory px-4 py-3">
          <p className="eyebrow mb-1.5">Why it was routed here</p>
          <ul className="list-disc space-y-0.5 pl-4 text-[13px] text-ink">
            {reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 5. student communication
function Communication({ c }) {
  return (
    <div className="space-y-6">
      {c.reports.map((r) => (
        <div key={r.reportId}>
          <p className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted">
            <span className="font-medium tabular-nums text-ink">{r.reportId}</span>
            <span>·</span><span>{r.source}</span>
            <span>·</span><span>{fmtDate(r.reportedAt)}</span>
            {r.verdict !== c.verdict && <span className="rounded-sm bg-mist px-1.5 text-forest">{headline(r.verdict, r.repair)}</span>}
            {(r.flags || []).map((f) => (
              <span key={f.code} title={f.detail}
                className={`rounded-sm px-1.5 ${f.code === 'injection' ? 'bg-errbg text-err' : 'bg-ivory text-muted'}`}>
                {f.code.replace(/_/g, ' ')}
              </span>
            ))}
          </p>
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-lg rounded-tl-sm border border-line bg-ivory px-4 py-2.5">
              <p className="mb-0.5 text-[11px] font-medium text-muted">Student</p>
              <p className="text-[14px] italic text-ink">“{r.comment}”</p>
            </div>
          </div>
          <div className="mt-2 flex justify-end">
            <div className="max-w-[85%] rounded-lg rounded-tr-sm bg-forest px-4 py-2.5 text-white">
              <p className="mb-0.5 text-[11px] font-medium text-mist/80">Acadza reply</p>
              <p className="text-[14px] leading-relaxed">{r.student_reply}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- 7. audit timeline
const ACTION_LABEL = {
  auto_apply: 'Auto-applied by the system',
  approve: 'Approved',
  edit: 'Edited',
  reject: 'Rejected',
  revert_auto_apply: 'Undid the auto-applied fix',
  reopen: 'Reopened',
  demo_reset: 'Demo reset',
}

function Timeline({ entries }) {
  if (!entries.length) return <p className="text-[14px] text-muted">No actions yet.</p>
  return (
    <ol className="relative ml-1.5 border-l border-line">
      {[...entries].reverse().map((e) => (
        <li key={e.id} className="relative pb-5 pl-6 last:pb-0">
          <span className={`absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white ${
            e.action === 'reject' || e.action === 'revert_auto_apply' ? 'bg-err' : e.action === 'auto_apply' ? 'bg-ok' : 'bg-forest'}`} />
          <p className="flex flex-wrap items-baseline gap-x-2 text-[13.5px]">
            <span className="font-medium text-ink">{ACTION_LABEL[e.action] || e.action}</span>
            <span className="text-muted">by {e.actor}</span>
            <span className="text-[12px] tabular-nums text-muted">{fmtDate(e.at)}</span>
          </p>
          {e.edit && (
            <p className="mt-1 break-words text-[12.5px] text-muted">
              <code className="rounded-sm bg-ivory px-1 text-ink">{e.edit.field}</code>{' '}
              <span className="font-mono text-err line-through">{String(e.edit.find).slice(0, 48)}</span>
              {' → '}
              <span className="font-mono text-ok">{String(e.edit.replace).slice(0, 48)}</span>
            </p>
          )}
          {!e.edit && typeof e.before === 'string' && typeof e.after === 'string' && e.before.length < 40 && (
            <p className="mt-1 text-[12.5px] text-muted">{e.before} → {e.after}</p>
          )}
          {e.note && <p className="mt-1 text-[12.5px] italic text-muted">{e.note}</p>}
        </li>
      ))}
    </ol>
  )
}

// ---------------------------------------------------------------- page
export default function CaseView({ c, rank, readOnly, canAct, onAction, busy, error }) {
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState('')
  const editRef = useRef(null)
  useEffect(() => {
    const h = (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.metaKey || e.ctrlKey) return
      if (e.key === 'e' && !readOnly && canAct) setEditing(true)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [readOnly, canAct])
  useEffect(() => {
    if (editing) editRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [editing])

  const st = STATUS[c.status] || STATUS.pending
  const done = ['approved', 'edited', 'rejected'].includes(c.status)
  const approveLabel =
    c.route === 'auto_apply' ? 'Keep correction' : c.diff ? 'Approve correction' : c.verdict === 'defect' ? 'Confirm problem' : 'Confirm & send reply'
  const approveHint = c.suggestion_withheld
    ? 'Confirm problem records the defect. The withheld suggestion is not applied.'
    : c.route === 'auto_apply' ? 'The correction is already live. Keep it, or reject to undo it.'
      : c.diff ? 'Approve applies the proposed change and sends the reply.'
        : c.verdict === 'defect' ? 'Records the problem for a teacher-authored fix.' : 'Confirms the verdict and sends the reply.'
  const n = c.reportIds.length

  return (
    <article className="mx-auto max-w-[960px] px-5 pb-10 pt-8 sm:px-8">
      {/* Case header */}
      <header>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted">
          <span>{c.subject}</span><span className="text-line">/</span><span>{c.chapter}</span>
          <span className="text-line">/</span><span className="uppercase tracking-wide">{c.type}</span>
          <span className="text-line">/</span><span className="tabular-nums">Queue #{rank ?? c.rank}</span>
          <span className={`ml-auto inline-flex items-center gap-1.5 font-medium ${st.tone}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />{st.label}
          </span>
        </div>
        <h2 className="mt-3 font-serif text-[30px] font-semibold leading-tight tracking-[-0.01em] text-ink sm:text-[34px]">
          {headline(c.verdict, c.repair)}
        </h2>
        <p className="mt-2 text-[14px] text-muted">
          {n} report{n > 1 ? 's' : ''} from {c.reporters} student{c.reporters > 1 ? 's' : ''} · first reported {timeAgo(c.oldest_report)}
        </p>
        <DecisionSummary c={c} />
      </header>

      <div className="mt-10 space-y-10">
        <Block eyebrow="What will change" title="Original vs proposed">
          <Comparison c={c} />
        </Block>

        <Block eyebrow="Evidence" title="Why this recommendation?">
          <Evidence c={c} />
        </Block>

        <Block eyebrow="Is it safe?" title="Safety and human review">
          <Safety c={c} />
        </Block>

        <section className="border-t border-line pt-7">
          <details open className="group">
            <summary className="flex cursor-pointer select-none items-baseline justify-between gap-2">
              <div>
                <p className="eyebrow mb-1">What the student receives</p>
                <h3 className="section-title inline-flex items-center gap-2">
                  Student communication
                  <Icon name="chevron" className="chev h-4 w-4 text-muted" />
                </h3>
              </div>
              <span className="text-[12px] text-muted">{n} message{n > 1 ? 's' : ''}</span>
            </summary>
            <div className="mt-5"><Communication c={c} /></div>
          </details>
        </section>

        <Block eyebrow="As students see it" title="Original question">
          <div className="surface px-6 py-5 sm:px-8 sm:py-6">
            <Html html={c.question_html} />
            {!c.has_images && /figure|diagram/i.test(c.question_html) && (
              <p className="mt-3 flex items-center gap-1.5 text-[12.5px] font-medium text-err">
                <Icon name="alert" className="h-3.5 w-3.5" /> No image is attached to this question.
              </p>
            )}
          </div>
          <div className="mt-4">
            <Disclosure summary={<>Stored solution · key <b className="text-ink">{c.answer}</b>{c.live_answer !== c.answer && <> → live <b className="text-ink">{c.live_answer}</b></>}</>}>
              <div className="rounded-md bg-ivory px-5 py-4"><Html html={c.solution_html} /></div>
            </Disclosure>
          </div>
          {c.errorHistory.length > 0 && (
            <p className="mt-3 text-[12.5px] text-muted">
              <span className="font-medium text-ink">Edit history:</span>{' '}
              {c.errorHistory.map((h, i) => <span key={i}>{fmtDate(h.at)} by {h.actor}: {h.note}</span>)}
            </p>
          )}
        </Block>

        <Block eyebrow="Accountability" title="Audit history">
          <Timeline entries={c.audit} />
        </Block>

        {editing && (
          <div ref={editRef}>
            <EditForm
              c={c}
              busy={busy}
              onCancel={() => setEditing(false)}
              onSubmit={async (edit, nt) => {
                const ok = await onAction({ action: 'edit', edit, note: nt })
                if (ok) setEditing(false)
              }}
            />
          </div>
        )}
      </div>

      {/* Decision bar: stays in view while reading */}
      <div className="sticky bottom-0 z-20 -mx-5 mt-10 border-t border-line bg-ivory/95 px-5 py-3 backdrop-blur sm:-mx-8 sm:px-8">
        {error && (
          <p role="alert" className="mb-2 flex items-start gap-2 rounded-md bg-errbg px-3 py-2 text-[13px] font-medium text-err">
            <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0" />{error}
          </p>
        )}
        {readOnly ? (
          <p className="text-[13.5px] text-warn">Read-only snapshot: actions are disabled because the API is unreachable.</p>
        ) : !canAct ? (
          <p className="flex items-center gap-2 text-[13.5px] text-warn">
            <Icon name="lock" className="h-4 w-4 shrink-0" />
            <span>View only. Enter the <b>reviewer passcode</b> (top right) to approve, edit or reject; the server checks it on every action.</span>
          </p>
        ) : done ? (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-[13.5px] text-muted">
              <span className={`font-medium ${st.tone}`}>{st.label}</span> by <b className="text-ink">{c.status_detail?.by}</b>
              {c.status_detail?.at && <> · {fmtDate(c.status_detail.at)}</>}
            </p>
            <button disabled={busy} onClick={() => onAction({ action: 'reopen', note })} className="btn-neutral ml-auto">
              Reopen
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <p className="hidden w-full text-[12px] text-muted lg:block">{approveHint}</p>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Optional note for the audit log"
              className="field hidden min-w-0 flex-1 sm:block"
            />
            <button disabled={busy} onClick={() => onAction({ action: 'reject', note })} className="btn-danger" title="Reject (R)">
              Reject recommendation <kbd>R</kbd>
            </button>
            <button disabled={busy} onClick={() => setEditing(true)} className="btn-neutral" title="Edit (E)">
              Edit correction <kbd>E</kbd>
            </button>
            <button disabled={busy} onClick={() => onAction({ action: 'approve', note })} className="btn-primary" title="Approve (A)">
              {busy ? 'Saving…' : approveLabel} <kbd className="border-white/30 bg-white/10 text-white">A</kbd>
            </button>
          </div>
        )}
      </div>
    </article>
  )
}
