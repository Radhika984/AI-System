import { useMemo } from 'react'
import { GROUP, GROUPS, Icon, STATUS, displayOrder, groupOf, headline, isDone, prettyMath, timeAgo } from './labels'

export { isDone }

const FILTERS = [
  ['todo', 'To review'],
  ['done', 'Done'],
  ['all', 'All'],
]

export function filterItems(items, filter, query = '') {
  const q = query.trim().toLowerCase()
  return displayOrder(items).filter((c) => {
    if (filter === 'done' && !isDone(c)) return false
    if (filter === 'todo' && isDone(c)) return false
    if (!q) return true
    const hay = [c.stem_preview, c.subject, c.chapter, headline(c.verdict, c.repair), ...(c.reportIds || [])]
      .join(' ')
      .toLowerCase()
    return hay.includes(q)
  })
}

function Item({ c, active, onSelect }) {
  const g = GROUP[groupOf(c)]
  const st = STATUS[c.status] || STATUS.pending
  const n = c.reportIds.length
  return (
    <li>
      <button
        onClick={() => onSelect(c.questionId)}
        aria-current={active ? 'true' : undefined}
        className={`group relative block w-full rounded-md px-4 py-3 text-left transition-colors duration-150 ${
          active ? 'bg-mist' : 'hover:bg-ivory'
        }`}
      >
        <span className={`absolute inset-y-2 left-0 w-[3px] rounded-full ${active ? 'bg-forest' : g.bar} ${active ? '' : 'opacity-70'}`} />
        <span className="flex items-baseline justify-between gap-3">
          <span className={`text-[14px] font-medium leading-snug ${isDone(c) ? 'text-muted' : 'text-ink'}`}>
            {headline(c.verdict, c.repair)}
          </span>
          <span className="shrink-0 text-[11px] tabular-nums text-muted">#{c.rank}</span>
        </span>
        <span className="mt-1 line-clamp-2 block text-[12.5px] leading-snug text-muted">{prettyMath(c.stem_preview)}</span>
        <span className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted">
          <span className={`inline-flex items-center gap-1.5 ${st.tone}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />
            {st.label}
          </span>
          <span className="truncate">{c.subject}</span>
          <span className={n > 1 ? 'font-medium text-ink' : ''}>
            {n} report{n > 1 ? 's' : ''}
          </span>
          {c.needs_attention && (
            <span className="rounded-sm bg-errbg px-1.5 py-px font-medium text-err" title={c.attention_reason || ''}>
              AI unsure
            </span>
          )}
          <span className="tabular-nums">AI {Math.round(c.confidence * 100)}%</span>
          <span>{timeAgo(c.oldest_report)}</span>
        </span>
      </button>
    </li>
  )
}

export default function Queue({ items, selected, onSelect, filter, setFilter, query, setQuery }) {
  const visible = useMemo(() => filterItems(items, filter, query), [items, filter, query])
  const counts = {
    todo: items.filter((c) => !isDone(c)).length,
    done: items.filter(isDone).length,
    all: items.length,
  }
  // "To review" = every open case; the overview's "Waiting for review" = only the open cases needing a decision.
  const open = items.filter((c) => !isDone(c))
  const nOpen = (k) => open.filter((c) => groupOf(c) === k).length
  const decide = nOpen('urgent') + nOpen('review')
  return (
    <nav aria-label="Review queue" className="flex h-full flex-col">
      <div className="space-y-3 border-b border-line px-5 pb-4 pt-5">
        <div className="flex items-baseline justify-between">
          <h2 className="font-serif text-[17px] font-semibold text-ink">Review queue</h2>
          <span className="text-[11px] text-muted">most harm first</span>
        </div>
        <label className="relative block">
          <span className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-muted">
            <Icon name="search" className="h-3.5 w-3.5" />
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search question, subject or report ID"
            aria-label="Search the queue"
            className="field w-full pl-8"
          />
        </label>
        <div className="flex rounded-md bg-ivory p-0.5" role="tablist">
          {FILTERS.map(([k, label]) => (
            <button
              key={k}
              role="tab"
              aria-selected={filter === k}
              onClick={() => setFilter(k)}
              className={`flex-1 rounded-[5px] px-2 py-1.5 text-[13px] font-medium transition-colors ${
                filter === k ? 'bg-white text-forest shadow-[0_1px_2px_rgba(32,43,40,0.08)]' : 'text-muted hover:text-ink'
              }`}
            >
              {label} <span className="tabular-nums opacity-70">{counts[k]}</span>
            </button>
          ))}
        </div>
        {filter === 'todo' && counts.todo > 0 && (
          <p className="text-[11.5px] leading-snug text-muted">
            All {counts.todo} open cases: <b className="font-medium text-ink">{decide}</b> waiting for your decision,{' '}
            {nOpen('auto')} auto-applied to spot-check, {nOpen('nochange')} with no change needed.
          </p>
        )}
      </div>
      <div className="scroll-quiet flex-1 overflow-y-auto px-2 pb-6">
        {visible.length === 0 && (
          <p className="px-4 py-10 text-center text-sm text-muted">
            {query ? 'No questions match your search.' : filter === 'todo' ? 'Queue clear. Nothing left to review.' : 'No decisions recorded yet.'}
          </p>
        )}
        {GROUPS.map((g) => {
          const rows = visible.filter((c) => groupOf(c) === g.key)
          if (!rows.length) return null
          return (
            <section key={g.key} className="mt-4">
              <h3 className="flex items-center gap-2 px-4 pb-1.5" title={g.hint}>
                <span className={`h-1.5 w-1.5 rounded-full ${g.dot}`} />
                <span className="eyebrow">{g.label}</span>
                <span className="text-[11px] tabular-nums text-muted">{rows.length}</span>
              </h3>
              <ul className="space-y-0.5">
                {rows.map((c) => (
                  <Item key={c.questionId} c={c} active={c.questionId === selected} onSelect={onSelect} />
                ))}
              </ul>
            </section>
          )
        })}
      </div>
    </nav>
  )
}
