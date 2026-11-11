import { useState } from 'react'
import Html from './Html'

// Faculty edit: same {field, find, replace} shape as the AI. The server re-runs the guard.
// A withheld AI suggestion is never pre-filled (c.edit is null then), so the correction is entered deliberately.
export default function EditForm({ c, busy, error, onInput, onCancel, onSubmit }) {
  const init = c.edit || { field: 'question', find: '', replace: '' }
  const [field, _setField] = useState(init.field)
  const [find, _setFind] = useState(init.find)
  const [replace, _setReplace] = useState(init.replace)
  const [note, setNote] = useState('')
  // Any change to the edit makes the server's last refusal outdated, so it is cleared.
  const touch = (set) => (v) => {
    set(v)
    onInput?.()
  }
  const setField = touch(_setField)
  const setFind = touch(_setFind)
  const setReplace = touch(_setReplace)
  const src = field === 'question' ? c.question_html : field === 'solution' ? c.solution_html : c.answer
  const count = find ? src.split(find).length - 1 : 0
  const preview = field !== 'answer' && count === 1 ? src.replace(find, `<ins class="diff-ins">${replace}</ins>`) : null

  return (
    <section className="rounded-lg border border-forest/30 bg-white p-6 shadow-[0_1px_3px_rgba(32,43,40,0.06)]">
      <p className="eyebrow mb-1">Faculty correction</p>
      <h3 className="section-title">Edit the fix yourself</h3>
      <p className="mt-1 text-[13px] text-muted">The server checks your edit with the same safety guard before anything is saved.</p>
      <div className="mt-5 grid gap-4">
        <label className="text-[13px]">
          <span className="font-medium text-ink">Field</span>
          <select value={field} onChange={(e) => {
            setField(e.target.value)
            if (e.target.value === 'answer') setFind(c.live_answer)
          }} className="field ml-3">
            <option value="question">question</option>
            <option value="solution">solution</option>
            <option value="answer">answer</option>
          </select>
        </label>
        <label className="text-[13px]">
          <span className="font-medium text-ink">Find (exact text from the stored {field})</span>
          <textarea value={find} onChange={(e) => setFind(e.target.value)} rows={2}
            className="field mt-1.5 w-full font-mono text-[12px]" />
          <span className={`mt-1 block text-[12px] ${field === 'answer' || count === 1 ? 'text-ok' : 'text-err'}`}>
            {field === 'answer' ? `Stored answer: ${c.live_answer}` : `Found ${count}× (must be exactly 1)`}
          </span>
        </label>
        <label className="text-[13px]">
          <span className="font-medium text-ink">Replace with</span>
          <textarea value={replace} onChange={(e) => setReplace(e.target.value)} rows={2}
            className="field mt-1.5 w-full font-mono text-[12px]" />
          {field === 'answer' && c.type === 'mcq' && (
            <span className="mt-1 block text-[12px] text-muted">Multiple-correct keys use a JSON list, like ["A", "C"].</span>
          )}
        </label>
        {preview && (
          <div className="rounded-md bg-ivory px-5 py-4">
            <p className="eyebrow mb-2">Preview</p>
            <Html html={preview} />
          </div>
        )}
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason (goes to the audit log)"
          className="field" />
        {error && (
          <p role="alert" className="rounded-md bg-errbg px-3 py-2 text-[13px] font-medium text-err">{error}</p>
        )}
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="btn text-muted hover:text-ink">Cancel</button>
          <button disabled={busy || !find || find === replace}
            onClick={() => onSubmit({ field, find, replace }, note)}
            className="btn-primary">
            {busy ? 'Saving…' : 'Validate & apply'}
          </button>
        </div>
      </div>
    </section>
  )
}
