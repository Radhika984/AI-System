// Plain-language vocabulary, status styling and queue grouping for the faculty workspace.
// Everything here is derived from fields the API already returns - no new data is invented.
import { createElement as h } from 'react'

export const REPAIR_HEADLINE = {
  answer_key: 'Answer key is wrong',
  wrong_question: 'Solution belongs to a different question',
  unsound: 'No option is correct as written',
  stem_data: 'Question is missing a value',
  option_repair: 'An option is missing or blank',
  identical_options: 'Two options are identical',
  diagram: 'Figure is missing',
  solution_fix: 'Solution has a wrong step',
  solution_missing: 'Solution is missing',
  spelling: 'Spelling mistake',
  noise: 'Stray text in question',
  exam_reference: 'Exam tag inside question text',
  markup_leak: 'Raw code visible to students',
  answer_form: 'Unit / answer format not stated',
  notation: 'A symbol got lost',
  type_mismatch: 'Stored as the wrong question type',
  wrong_chapter: 'Filed under the wrong chapter',
  syllabus: 'Possibly out of syllabus',
}

export const VERDICT_HEADLINE = {
  defect: 'Real defect',
  no_error: 'Question is correct - student was mistaken',
  display_issue: 'Display / loading problem - content is fine',
  app_issue: 'App problem - not this question',
  language_mode: 'Language request',
  already_fixed: 'Already fixed in the live question',
  not_actionable: 'Nothing to act on',
}

export const VERDICT_SHORT = {
  defect: 'Defect confirmed',
  no_error: 'No error',
  display_issue: 'Display issue',
  app_issue: 'App issue',
  language_mode: 'Language request',
  already_fixed: 'Already fixed',
  not_actionable: 'Not actionable',
}

export function headline(verdict, repair) {
  if (verdict === 'defect' && repair) return REPAIR_HEADLINE[repair] || repair
  return VERDICT_HEADLINE[verdict] || verdict
}

// Display-only rewording of the pipeline's routing / attention reasons for faculty. The raw reason is
// unchanged in the API and audit; callers keep it available as a tooltip. Unknown strings pass through.
const pct = (x) => `${Math.round(parseFloat(x) * 100)}%`
const REASON_RULES = [
  [/^all auto-apply conditions passed$/, () => 'Every automatic safety check passed, so the fix went live without waiting for a teacher.'],
  [/^blind solvers do not agree with each other$/, () => 'The two independent AI solvers reached different answers.'],
  [/^blind solvers disagree \(A=(.+), B=(.+)\)$/, (a, b) => `The two independent AI solvers got different answers (${a} and ${b})`],
  [/^both blind solvers dispute the stored key$/, () => 'Both independent AI solvers got a different answer from the stored key'],
  [/^confidence ([\d.]+) < ([\d.]+)$/, (c, t) => `The AI's confidence (${pct(c)}) is below the ${pct(t)} needed to apply a fix automatically.`],
  [/^(\w+) is auto:false in taxonomy/, (r) => `“${REPAIR_HEADLINE[r] || r.replace(/_/g, ' ')}” is a type of fix that always needs a teacher to write or approve it.`],
  [/^edit writes option\(s\)/, () => 'The proposed fix fills in a wrong (distractor) option. Only the correct option may be restored automatically; distractors must be written by a teacher.'],
  [/^guard: no edit proposed$/, () => 'The AI did not propose an exact text change, so there is nothing to apply automatically.'],
  [/^restricted evaluator did not reproduce/, () => "The code-based calculation re-check could not reproduce the solvers' numeric answer."],
  [/^solvers do not confirm the keyed answer/, () => 'The independent solvers did not confirm the answer key that the corrected solution must reach.'],
  [/^verdict (\w+) is not a defect$/, (v) => `No fault was found in the question (${(VERDICT_HEADLINE[v] || v.replace(/_/g, ' ')).toLowerCase()}), so nothing in it changes; only the reply is sent.`],
]

export function friendlyReason(raw) {
  if (!raw) return raw
  for (const [re, fn] of REASON_RULES) {
    const m = raw.match(re)
    if (m) return fn(...m.slice(1))
  }
  return raw
}

// Route = what the triage engine decided (never changed by the console).
export const ROUTE = {
  auto_apply: { label: 'Auto-applied', tone: 'bg-okbg text-ok' },
  faculty_review: { label: 'Needs your decision', tone: 'bg-warnbg text-warn' },
  no_change: { label: 'No change', tone: 'bg-mist text-forest' },
}

// Status = what has happened to the case so far.
export const STATUS = {
  pending: { label: 'Pending', tone: 'text-muted', dot: 'bg-sage' },
  auto_applied: { label: 'Auto-applied - spot check', tone: 'text-ok', dot: 'bg-ok' },
  approved: { label: 'Approved', tone: 'text-forest', dot: 'bg-forest' },
  edited: { label: 'Edited & applied', tone: 'text-forest', dot: 'bg-forest' },
  rejected: { label: 'Rejected', tone: 'text-err', dot: 'bg-err' },
}

export function isDone(c) {
  return ['approved', 'edited', 'rejected'].includes(c.status)
}

// Queue groups. Order and membership come only from existing fields:
// status (done / auto_applied), route, needs_attention and the server's priority tier.
export const GROUPS = [
  { key: 'urgent', label: 'Urgent attention', hint: 'Wrong or unanswerable keys, and cases where the AI is unsure', bar: 'bg-err', dot: 'bg-err' },
  { key: 'review', label: 'Faculty review', hint: 'Fixes the AI may not apply on its own', bar: 'bg-warn', dot: 'bg-warn' },
  { key: 'auto', label: 'Auto-applied - spot check', hint: 'Already live; keep or undo', bar: 'bg-ok', dot: 'bg-ok' },
  { key: 'nochange', label: 'No change needed', hint: 'Confirm the reply and close', bar: 'bg-sage', dot: 'bg-sage' },
  { key: 'completed', label: 'Completed', hint: 'Decided by faculty', bar: 'bg-line', dot: 'bg-muted' },
]
export const GROUP = Object.fromEntries(GROUPS.map((g) => [g.key, g]))

export function groupOf(c) {
  if (isDone(c)) return 'completed'
  if (c.status === 'auto_applied') return 'auto'
  if (c.route === 'no_change' && !c.needs_attention) return 'nochange'
  if (c.tier === 1) return 'urgent'
  return 'review'
}

// Display order: group order, then the server's rank (urgency) within the group.
export function displayOrder(items) {
  const idx = Object.fromEntries(GROUPS.map((g, i) => [g.key, i]))
  return [...items].sort((a, b) => idx[groupOf(a)] - idx[groupOf(b)] || a.rank - b.rank)
}

export function timeAgo(iso) {
  const d = new Date(iso)
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (days >= 1) return `${days}d ago`
  const hrs = Math.floor((Date.now() - d.getTime()) / 3600000)
  return hrs >= 1 ? `${hrs}h ago` : 'just now'
}

export function fmtDate(iso) {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// Display-only: the API's plain-text option/preview strings use "x^(2)" and "sqrt(..)" notation
// (a linearisation of the MathML). Render those as real superscripts / root signs. Stored text is untouched.
export function prettyMath(text) {
  const s = String(text ?? '').replace(/sqrt\(/g, '√(')
  const out = []
  const re = /\^\(([^()]{1,24})\)/g
  let last = 0
  let m
  let i = 0
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index))
    out.push(h('sup', { key: i++, className: 'text-[0.75em]' }, m[1].replace(/\s+/g, '')))
    last = m.index + m[0].length
  }
  if (last < s.length) out.push(s.slice(last))
  return out
}

// Minimal inline icons (no icon library). Always paired with text - never colour alone.
const PATHS = {
  check: 'M5 12.5l4.5 4.5L19 7.5',
  alert: 'M12 8v5M12 16.5v.5M10.3 3.9L2.6 17.5A2 2 0 004.3 20.5h15.4a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z',
  shield: 'M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z',
  lock: 'M7 11V8a5 5 0 0110 0v3M6 11h12v9H6z',
  info: 'M12 11v6M12 7.5v.5M12 21a9 9 0 110-18 9 9 0 010 18z',
  eye: 'M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12zM12 15a3 3 0 100-6 3 3 0 000 6z',
  chevron: 'M9 6l6 6-6 6',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  search: 'M11 18a7 7 0 110-14 7 7 0 010 14zM21 21l-4.3-4.3',
  user: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c1.5-4 4.5-6 8-6s6.5 2 8 6',
  menu: 'M4 7h16M4 12h16M4 17h16',
  x: 'M6 6l12 12M18 6L6 18',
}

export function Icon({ name, className = 'h-4 w-4' }) {
  return h(
    'svg',
    { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round',
      strokeLinejoin: 'round', className, 'aria-hidden': 'true' },
    h('path', { d: PATHS[name] }),
  )
}
