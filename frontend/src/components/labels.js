// Plain-language headlines: what a tired faculty member reads first.
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

export function headline(verdict, repair) {
  if (verdict === 'defect' && repair) return REPAIR_HEADLINE[repair] || repair
  return VERDICT_HEADLINE[verdict] || verdict
}

export const ROUTE = {
  auto_apply: { label: 'Auto-applied', tone: 'bg-emerald-100 text-emerald-800 ring-emerald-200' },
  faculty_review: { label: 'Needs your decision', tone: 'bg-amber-100 text-amber-900 ring-amber-200' },
  no_change: { label: 'No change', tone: 'bg-slate-100 text-slate-700 ring-slate-200' },
}

export const STATUS = {
  pending: { label: 'Pending', tone: 'text-slate-500', dot: 'bg-slate-300' },
  auto_applied: { label: 'Auto-applied - spot check', tone: 'text-emerald-700', dot: 'bg-emerald-500' },
  approved: { label: 'Approved', tone: 'text-indigo-700', dot: 'bg-indigo-500' },
  edited: { label: 'Edited & applied', tone: 'text-indigo-700', dot: 'bg-indigo-500' },
  rejected: { label: 'Rejected', tone: 'text-rose-700', dot: 'bg-rose-500' },
}

export const TIER_TONE = {
  1: 'border-l-rose-500',
  2: 'border-l-orange-400',
  3: 'border-l-amber-400',
  4: 'border-l-sky-400',
  5: 'border-l-slate-300',
}

export function timeAgo(iso) {
  const d = new Date(iso)
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (days >= 1) return `${days}d ago`
  const h = Math.floor((Date.now() - d.getTime()) / 3600000)
  return h >= 1 ? `${h}h ago` : 'just now'
}

export function fmtDate(iso) {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
