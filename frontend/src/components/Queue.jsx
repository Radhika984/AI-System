import { headline, STATUS, TIER_TONE, timeAgo } from './labels'

const FILTERS = [
  ['todo', 'To review'],
  ['done', 'Done'],
  ['all', 'All'],
]

export function isDone(c) {
  return ['approved', 'edited', 'rejected'].includes(c.status)
}

export default function Queue({ items, selected, onSelect, filter, setFilter }) {
  const visible = items.filter((c) => (filter === 'all' ? true : filter === 'done' ? isDone(c) : !isDone(c)))
  const byTier = []
  for (const c of visible) {
    const last = byTier[byTier.length - 1]
    if (!last || last.tier !== c.tier || last.label !== c.tier_label) byTier.push({ tier: c.tier, label: c.tier_label, items: [c] })
    else last.items.push(c)
  }
  return (
    <nav aria-label="Case queue" className="flex h-full flex-col">
      <div className="flex gap-1 border-b border-slate-200 p-2">
        {FILTERS.map(([k, label]) => {
          const n = k === 'all' ? items.length : items.filter((c) => (k === 'done' ? isDone(c) : !isDone(c))).length
          return (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={`flex-1 rounded-md px-2 py-1.5 text-sm font-medium ${
                filter === k ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {label} <span className="opacity-70">{n}</span>
            </button>
          )
        })}
      </div>
      <div className="flex-1 overflow-y-auto">
        {visible.length === 0 && (
          <p className="p-6 text-center text-sm text-slate-500">
            {filter === 'todo' ? 'Queue clear. Nothing left to review.' : 'No cases here yet.'}
          </p>
        )}
        {byTier.map((g, gi) => (
          <section key={gi}>
            <h3 className="sticky top-0 z-10 border-b border-slate-200 bg-slate-100/95 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-600 backdrop-blur">
              {g.tier < 5 ? `Priority ${g.tier} · ` : ''}
              {g.label} <span className="font-normal">({g.items.length})</span>
            </h3>
            <ul>
              {g.items.map((c) => {
                const st = STATUS[c.status] || STATUS.pending
                const active = c.questionId === selected
                return (
                  <li key={c.questionId}>
                    <button
                      onClick={() => onSelect(c.questionId)}
                      aria-current={active ? 'true' : undefined}
                      className={`block w-full border-b border-l-4 border-slate-100 px-3 py-2.5 text-left ${TIER_TONE[c.tier]} ${
                        active ? 'bg-indigo-50' : 'bg-white hover:bg-slate-50'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className={`truncate text-sm font-semibold ${isDone(c) ? 'text-slate-400' : 'text-slate-900'}`}>
                          {headline(c.verdict, c.repair)}
                        </span>
                        <span className="shrink-0 text-xs text-slate-400">#{c.rank}</span>
                      </div>
                      <p className="mt-0.5 line-clamp-1 text-xs text-slate-500">{c.stem_preview}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
                        <span className="flex items-center gap-1">
                          <span className={`inline-block h-1.5 w-1.5 rounded-full ${st.dot}`} />
                          <span className={st.tone}>{st.label}</span>
                        </span>
                        <span>{c.subject}</span>
                        {c.needs_attention && (
                          <span className="rounded bg-rose-100 px-1 font-semibold text-rose-800" title={c.attention_reason || ''}>
                            AI unsure
                          </span>
                        )}
                        {c.reporters > 1 && <span className="font-semibold text-rose-700">{c.reporters} students</span>}
                        <span>AI {Math.round(c.confidence * 100)}%</span>
                        <span>{timeAgo(c.oldest_report)}</span>
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>
    </nav>
  )
}
