# Report → Fix

A triage engine and faculty console for the Acadza AI intern assignment. The original brief is in [ASSIGNMENT.md](ASSIGNMENT.md), moved byte-identical.

Students tap **Report error** and type whatever they feel like. This system decides what is really wrong with each report and proposes a *surgical*, guard-checked fix. It auto-applies a fix only when it can be proven safe. Everything else goes to a faculty queue ordered by harm to students.

| Deliverable | Where |
|---|---|
| Triage output for all 44 reports | [`results.json`](results.json) |
| Per-case evidence (solves, guard log, overrides) | [`artifacts/triage_details.json`](artifacts/triage_details.json) |
| Product prompts + coding-assistant prompts + mistakes + decision log | [`PROMPTS.md`](PROMPTS.md) (raw log: [`PROMPTS_LOG.md`](PROMPTS_LOG.md)) |
| Product thinking (1 page) | [`PRODUCT.md`](PRODUCT.md) |
| Spec, routing rules, traceability | [`SPEC.md`](SPEC.md) |
| Bonus: unreported defects | [`bonus_findings.json`](bonus_findings.json) |
| Live console | _see submission email_ |

> **Precomputed results.** The live console serves `results.json`, which was generated offline with **Google AI Studio free-tier Gemini models (₹0 spent)**. The deployed API makes **no LLM calls**, so it can't run out of credits or be prompt-injected at runtime. Faculty actions (approve/edit/reject) are live and audited.

## Architecture

```
reports.json ─┐
questions.json┼─► precheck (deterministic) ──────────────┐
taxonomy.json ┘   malformed keys, missing/blank/duplicate │
                  options, missing figure, raw LaTeX, exam │
                  tags, already-fixed, injection, gibberish│
                                                          ▼
   question_view (stem+options only) ─► Solver A ┐   evidence packet ─► Judge (per question,
                                        Solver B ┼─► (comments escaped,      grouped reports)
   (blind: no key, no solution, no comment)      │    quoted as data)              │
   restricted evaluator re-checks their arithmetic┘                                ▼
                                                     Pydantic validation ─► guard ─► routing
                                                                                     │
                                       results.json ◄────────────────────────────────┘
                                             │
                    FastAPI (store = originals + patch layer, audit.jsonl)
                                             │
                           React console (Vite + Tailwind, DOMPurify + native MathML)
```

* **Two blind solvers** run on *different* free models, `gemini-3-flash-preview` and `gemini-3.1-flash-lite`, so their errors are independent. They get only the stem and options, never the key, the stored solution or the student's comment. Each also returns one arithmetic expression, which `safe_eval.py` (an AST whitelist, never `eval`) recomputes.
* **The judge** (`gemini-3-flash-preview`) sees one question at a time with *all* of its reports grouped. It also gets the deterministic flags, both solves, the raw HTML (for exact edit anchors) and each comment escaped inside `<student_comment>` tags, labelled as untrusted data.
* **The guard** (`guard.py`) checks every proposed edit. The field must be in the repair's scope (from `taxonomy.json`), and `find` must occur exactly once. The edit is dry-run on a copy and re-parsed with `lxml`, and no option may be lost. Each repair type has its own rule: spelling moves letters only, `exam_reference` and `noise` only delete, `answer_form` only adds, `stem_data` values must appear in the stored solution, and `option_repair` may not touch the stem. A failed edit gets one LLM repair attempt, which is guarded again, and is dropped if it still fails.
* **Routing** is deterministic code ([SPEC §3](SPEC.md)), not the model. A non-defect becomes `no_change`. An `auto:false` repair goes to `faculty_review` with `edit: null`. An `auto:true` repair is auto-applied only if:
  - the guard passes, and confidence is at least 0.85
  - no report on that question carries an injection flag
  - for answer keys: both solvers agree on the new key, the arithmetic re-check passes, and the subject is computational (biology keys always go to faculty)
* **Patch layer.** `data/` is never written; it's read-only and SHA-256 pinned in tests. Approved and auto-applied edits live in `state/patches.json`. Every action (auto-apply, approve, edit, reject, revert, reopen) appends to `state/audit.jsonl` with the actor, timestamp and before/after values.

### Faculty console

The queue is grouped by question and ordered by harm to students:

1. **Priority 1:** wrong key, wrong question, unsound question
2. **Priority 2:** missing data, option or figure
3. **Priority 3:** wrong solution
4. **Priority 4:** cosmetic issues
5. **Priority 5:** no change needed

Within a band, more distinct reporters come first, then lower AI confidence, then the oldest report. A case where both blind solvers dispute a key the judge called correct is raised to priority 1.

Each case answers five questions top to bottom: *what is wrong, why, what will change (rendered before/after diff), is it safe (route reasons, guard log, injection warning), what the student receives*. **Approve** is the primary action. Keyboard shortcuts: `A` approve, `E` edit, `R` reject, `J`/`K` next/previous. The console advances to the next case automatically after each decision.

## Run it locally

Requires Python 3.10+ and Node 18+.

```bash
pip install -r backend/requirements.txt
python -m pytest -q tests                  # deterministic + offline-stub tests, no API key needed

# API (serves the committed results.json; no key needed)
cd backend && uvicorn app.main:app --port 8000

# Console (in another terminal; proxies /api to :8000)
cd frontend && npm ci && npm run dev       # http://localhost:5173
```

### Re-running the triage engine (optional, free tier)

```bash
cp .env.example .env                       # then set GEMINI_API_KEY (Google AI Studio, no billing)
python scripts/smoke_llm.py                # one tiny call per configured model
python scripts/run_triage.py --pilot       # R005 R004 R027 R017 R009 R034
python scripts/run_triage.py --all         # all 44 -> results.json + artifacts/triage_details.json
LLM_OFFLINE=1 python scripts/run_triage.py --all   # replay from cache/, zero API calls
python scripts/eval_results.py             # schema/safety validation + disagreements vs hand audit
python scripts/build_snapshot.py           # refresh the console's read-only fallback snapshot
```

| Env var | Purpose |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio key (free tier). Read only from env or `.env`, sent only in the `x-goog-api-key` header, never logged. |
| `SOLVER_A_MODEL`, `SOLVER_B_MODEL`, `JUDGE_MODEL` | Must be on the free-tier allowlist in `backend/app/config.py`; any other model is refused. |
| `SOLVER_BATCH_SIZE`, `JUDGE_BATCH_SIZE` | Questions per call (free tier = 20 requests/day/model). |
| `LLM_MIN_INTERVAL_S`, `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES` | Pacing, timeout and backoff settings. |
| `LLM_OFFLINE=1` | Cache-only replay; any cache miss is an error, so the API is never called. |
| `CORS_ORIGINS`, `STATE_DIR` | API server settings. |

**Cost controls.**
- Every response is cached by (model, prompt version, prompt); the cache is committed, so reruns are free and reproducible.
- Calls are paced, and 429/5xx responses get exponential backoff with jitter, honouring the server's `retryDelay`.
- On a daily-quota 429 the run stops cleanly (exit code 3) and resumes from cache later. It never switches model or provider.
- Malformed JSON is recovered locally first, with at most one repair call.

## Deployment

* **Backend → Render** (`render.yaml`, free plan): `uvicorn app.main:app`, health check `/health`. Set `CORS_ORIGINS` to the Vercel URL.
* **Frontend → Vercel** (`vercel.json`): builds `frontend/`. Set `VITE_API_BASE` to the Render URL.
* **Snapshot fallback.** `frontend/public/snapshot.json` is bundled at build time. If the API is unreachable (for example, the free Render instance is asleep and fails to wake), the console loads the snapshot and shows a **read-only** banner, with all actions disabled.
* **Single-service fallback.** If `frontend/dist` exists, FastAPI also serves the console from the same origin.

## Limitations, stated honestly

* **Free-tier limits.** Gemini's free tier allows 20 requests per day per model, so questions are batched: 10 per solver call and 4 per judge call. Solver A and the judge share a model; solver B is a different model.
* **Render free tier has an ephemeral disk.** Faculty actions and the audit log survive restarts of the process, but are lost on redeploy or spin-down. A production version would use a database.
* There is no authentication. The reviewer name typed in the header is recorded as the audit actor.
* `results.json` is the engine's output. Any deviation from what the engine produced would be listed in `PROMPTS.md`; there are none unless stated there.
