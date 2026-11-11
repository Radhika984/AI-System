import { useState } from 'react'
import Html from './Html'

// Faculty edit: same {field, find, replace} shape as the AI. The server re-runs the guard.
export default function EditForm({ c, busy, onCancel, onSubmit }) {
  const init = c.edit || { field: 'question', find: '', replace: '' }
  const [field, setField] = useState(init.field)
  const [find, setFind] = useState(init.find)
  const [replace, setReplace] = useState(init.replace)
  const [note, setNote] = useState('')
  const src = field === 'question' ? c.question_html : field === 'solution' ? c.solution_html : c.answer
  const count = find ? src.split(find).length - 1 : 0
  const preview = field !== 'answer' && count === 1 ? src.replace(find, `<ins class="diff-ins">${replace}</ins>`) : null

  return (
    <section className="rounded-xl border-2 border-indigo-300 bg-white p-4 shadow">
      <h3 className="mb-3 font-semibold text-slate-900">Edit the fix yourself</h3>
      <div className="grid gap-3">
        <label className="text-sm">
          <span className="font-medium text-slate-700">Field</span>
          <select value={field} onChange={(e) => {
            setField(e.target.value)
            if (e.target.value === 'answer') setFind(c.live_answer)
          }} className="ml-2 rounded border border-slate-300 px-2 py-1">
            <option value="question">question</option>
            <option value="solution">solution</option>
            <option value="answer">answer</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="font-medium text-slate-700">Find (exact text from the stored {field})</span>
          <textarea value={find} onChange={(e) => setFind(e.target.value)} rows={2}
            className="mt-1 w-full rounded border border-slate-300 p-2 font-mono text-xs" />
          <span className={`text-xs ${count === 1 ? 'text-emerald-700' : 'text-rose-700'}`}>
            {field === 'answer' ? `Stored answer: ${c.live_answer}` : `Found ${count}× (must be exactly 1)`}
          </span>
        </label>
        <label className="text-sm">
          <span className="font-medium text-slate-700">Replace with</span>
          <textarea value={replace} onChange={(e) => setReplace(e.target.value)} rows={2}
            className="mt-1 w-full rounded border border-slate-300 p-2 font-mono text-xs" />
          {field === 'answer' && c.type === 'mcq' && (
            <span className="text-xs text-slate-500">Multiple-correct keys use a JSON list, like ["A", "C"].</span>
          )}
        </label>
        {preview && (
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="mb-1 text-xs font-semibold text-slate-500">Preview</div>
            <Html html={preview} />
          </div>
        )}
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason (goes to the audit log)"
          className="rounded border border-slate-300 px-3 py-2 text-sm" />
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">Cancel</button>
          <button disabled={busy || !find || find === replace}
            onClick={() => onSubmit({ field, find, replace }, note)}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
            Validate & apply
          </button>
        </div>
      </div>
    </section>
  )
}
