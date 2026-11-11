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
| Submission outcome | 44 reports: **16** auto-applied, **11** sent to faculty review, **17** no change. 56 successful Gemini free-tier calls in total (rate-limited attempts that failed aren't counted), ₹0. See [`artifacts/README.md`](artifacts/README.md) for which files are submission and which are historical. |
| Live console | **Not deployed yet.** After deployment this row lists the Vercel console URL and the Render API `/health` URL. Until then, run it locally (below). |

> **Precomputed results.** The live console serves `results.json`, which was generated offline with **Google AI Studio free-tier Gemini models (₹0 spent)**. The deployed API makes **no LLM calls**, so it can't run out of credits or be prompt-injected at runtime. Faculty actions (approve/edit/reject) are live and audited, and they require a **reviewer passcode** checked by the server. Without it the console is view-only; the passcode is shared privately with reviewers, never published.

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

* **Two blind solvers** run on *different* free models, `gemini-3-flash-preview` and `gemini-3.1-flash-lite`, so their errors are more independent than two runs of one model. Solver B, the lighter model, is the weaker one: the two solvers' answers differ on 13 of 39 questions.
  - On 3 of those (R006, R011, R025) a solver couldn't answer because content is missing, which is evidence for the defect.
  - R039 is a language request, which SPEC §3 rule 5 doesn't cover.
  - On the other 9 questions (10 reports) the case is escalated rather than trusted (rule 5).

  Integer answers must match exactly (R033: 3113 vs 3114 is a disagreement). They get only the stem and options, never the key, the stored solution or the student's comment. Each also returns one arithmetic expression, which `safe_eval.py` (an AST whitelist, never `eval`) recomputes.
* **The judge** (`gemini-3-flash-preview`) sees one question at a time with *all* of its reports grouped. It also gets the deterministic flags, both solves, the raw HTML (for exact edit anchors) and each comment escaped inside `<student_comment>` tags, labelled as untrusted data.
* **The guard** (`guard.py`) checks every proposed edit. The field must be in the repair's scope (from `taxonomy.json`), and `find` must occur exactly once. The edit is dry-run on a copy and re-parsed with `lxml`, and no option may be lost. Each repair type is bounded to what its taxonomy label allows, so a structurally valid edit can't change academic meaning:
  - **spelling:** same word count, at most 3 words changed, each within 2 letter edits and ≤ ⅓ of its length, and never touching meaning-critical words such as *not*, *true/false* or *increase/decrease*. "Golden rice" → "Golden wheat" is refused.
  - **exam_reference:** the deleted text must *be* an exam tag like "(NEET 2019)".
  - **noise:** the deleted text must be a question number, a rough-work note, a source label or a URL. Deleting "not" is refused.
  - **answer_form:** may only add a unit or rounding instruction, with no numbers, answer text or option letters.
  - **markup_leak:** keeps the surrounding words.
  - **notation:** may change only symbols, brackets and exponents.
  - **stem_data:** may only add, and only values the solution states.
  - **solution_fix:** may not introduce numbers found nowhere in the question, solution or key.
  - **option_repair:** may only restore the keyed option.
  - **type_mismatch:** auto-applies only as a type change consistent with both blind solvers.
  - **No edit** may introduce raw LaTeX. A failed edit gets one LLM repair attempt, which is guarded again, and is dropped if it still fails.
* **Routing** is deterministic code ([SPEC §3](SPEC.md)), not the model. A non-defect becomes `no_change`. An `auto:false` repair goes to `faculty_review` with `edit: null`. An `auto:true` repair is auto-applied only if:
  - the guard passes, and confidence is at least 0.85
  - no report on that question carries an injection flag
  - for answer keys: both solvers agree on the new key, the arithmetic re-check passes, and the subject is computational (biology keys always go to faculty)
  - the two blind solvers don't disagree: a disagreement caps confidence at 0.7, which sends defects to faculty and marks no-change cases "AI unsure" (SPEC §3 rule 5)
* **Patch layer.** `data/` is never written; it's read-only and SHA-256 pinned in tests. Approved and auto-applied edits live in `state/patches.json`. Every action (auto-apply, approve, edit, reject, revert, reopen) appends to `state/audit.jsonl` with the actor, timestamp and before/after values.
* **Faculty actions are transactional.** Each action is validated first, then all changes are staged and both state files are saved, and only then is the audit entry written. A refused request (for example an invalid edit on an auto-applied case) leaves the live question, status, patch file and audit log exactly as they were, including after a restart.

### Faculty console

The queue is grouped by question (one entry per question, however many students reported it) and shown in five groups, ordered by harm to students:

1. **Urgent attention:** wrong key (unless already auto-applied), wrong question, unsound question, and "AI unsure" cases (the blind solvers disagree, or both dispute the stored key)
2. **Faculty review:** fixes the AI may not apply on its own: missing data, option or figure, then wrong solution, then cosmetic issues
3. **Auto-applied - spot check:** fixes that are already live; keep them, or reject to undo
4. **No change needed:** confirm the verdict and the drafted reply
5. **Completed:** decided by faculty

Within a group, cases keep the server's urgency rank: priority band (1 = wrong key, wrong or unsound question, "AI unsure"; 2 = missing data, option or figure; 3 = wrong solution; 4 = cosmetic; 5 = no change), then more distinct reporters, then lower AI confidence, then the oldest report. The **To review** tab lists every open case; the overview's **Waiting for review** counts only the open cases that need a faculty decision (Urgent attention + Faculty review). **Why this order?** in the console explains the ranking.

Each case reads top to bottom: a decision summary (verdict, current vs proposed answer, confidence, safety), *Original vs proposed* (rendered before/after diff), *Why this recommendation?* (AI reasoning, blind-solver and arithmetic checks, student reports), *Safety and human review* (route reasons, guard log, injection warning), *Student communication* (the student's comment and the drafted reply), the original question, and its audit history. **Approve** is the primary action.

Keyboard shortcuts: `A` approve and `R` reject each open a confirmation first; nothing is recorded until you press **Enter** or click **Yes**, and **Escape** or **Cancel** closes it without recording anything. `E` opens the edit form; `J`/`K` move to the next/previous case. The console advances to the next case automatically after each decision.

## Run it locally

Requires Python 3.10+ and Node 18+.

```bash
pip install -r backend/requirements.txt
python -m pytest -q tests                  # 228 deterministic, offline-stub, API and security tests; no API key needed

# API (serves the committed results.json; no LLM key needed).
# Faculty actions need a reviewer passcode, read from the environment only (see "Reviewer access").
cd backend && REVIEWER_PASSCODE='<choose one>' uvicorn app.main:app --port 8000

# Console (in another terminal; proxies /api to :8000)
cd frontend && npm ci && npm run dev       # http://localhost:5173
```

On Windows (PowerShell), set environment variables with `$env:` instead of the `NAME=value command` prefix:

```powershell
cd backend; $env:REVIEWER_PASSCODE = '<choose one>'; uvicorn app.main:app --port 8000
cd frontend; npm ci; npm run dev
$env:LLM_OFFLINE = '1'; python scripts/run_triage.py --all     # offline replay (see below)
```

**Read endpoints** (public, no passcode): `GET /health` (status, result and case counts, whether faculty actions are enabled), `GET /api/queue` (one entry per reported question, in urgency order), `GET /api/cases/{questionId}` (full case: verdicts, evidence, diff, replies, patches, audit), `GET /api/audit?questionId=` (audit log, newest first; all questions if omitted). FastAPI's interactive docs are at `/docs`. The write endpoints are described under "Reviewer access" below.

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
| `LLM_PROVIDER` | LLM provider for the triage engine. Default `gemini`, the only configured provider. |
| `CORS_ORIGINS`, `STATE_DIR` | API server settings. |
| `TRUSTED_PROXIES` | Comma-separated IPs or CIDR ranges of reverse proxies in front of the API. Only requests arriving *from* these addresses have their `X-Forwarded-For` header used to identify the client for rate limiting. Default empty: the header is ignored and the direct peer address is used. Behind a proxy, set it to the proxy's range, or every client shares one rate-limit bucket. |
| `API_PROXY` | Vite dev/preview server only: where `/api` and `/health` are proxied. Default `http://127.0.0.1:8000`. |
| `REVIEWER_PASSCODE` | Shared passcode for approve, edit and reject (header `X-Reviewer-Passcode`). Set only in the server environment. If unset, faculty actions are **disabled**. |
| `ADMIN_RESET_TOKEN` | Separate token for `POST /api/admin/reset` (header `X-Admin-Token`). If unset, or equal to the passcode, the endpoint doesn't exist (404). |

**Cost controls.**
- Every response is cached by (model, prompt version, prompt); the cache is committed, so reruns are free and reproducible.
- Calls are paced, and 429/5xx responses get exponential backoff with jitter, honouring the server's `retryDelay`.
- On a daily-quota 429 the run stops cleanly (exit code 3) and resumes from cache later. It never switches model or provider.
- Malformed JSON is recovered locally first, with at most one repair call.

## Reviewer access and demo reset

* **Every write is protected by the backend.** `POST /api/cases/{id}/actions` (approve, edit, reject, reopen) requires the header `X-Reviewer-Passcode` to match `REVIEWER_PASSCODE` from the server environment.
  - The comparison is constant-time.
  - A wrong or missing passcode returns 401 and changes nothing.
  - Repeated failures from one client return 429.
  - If the variable is unset, writes are disabled (503), never left open.
  - Read endpoints stay public.
  - The console asks for the passcode once per browser tab (it's kept in `sessionStorage`) and shows **view only** until one is entered.
* **Unsafe AI suggestions are never one-click.** For a case awaiting faculty review, the AI's proposed fix is offered for approval only if:
  - no report on the question is flagged as a manipulation attempt; and
  - for answer-key changes, **both** blind solvers independently gave exactly the proposed key.

  Otherwise the console shows the proposal as evidence, with the reason it was withheld, and **Approve** confirms the problem without applying anything. Faculty can still enter their own correction with **Edit**; the form starts empty.
* **Request limits.**
  - Request bodies over 64 KB get a 413 before they're parsed or stored.
  - Edit `find` is limited to 2,000 characters and `replace` to 4,000.
  - Unknown fields in an action, an edit or a reset get a 422.
  - Reverted patches aren't sent to reviewers; the audit log keeps the full history.
* **One decision per case.** Approve, edit and reject are refused (422) on a case that is already approved, edited or rejected; reopen it first (reopen undoes faculty patches). Reopen is only accepted for decided cases. A refused action changes nothing and writes no audit entry.
* **Damaged state files fail closed.** If `state/patches.json` or `state/case_status.json` exists but is empty, truncated or not a JSON object, the API answers every request with a 503 naming the file (the response never includes a filesystem path; the full detail is in the server log) and writes nothing, so decisions are never silently dropped or overwritten. Restore the file (or move it aside to start fresh); no restart is needed, because the next request loads it again. A missing file is simply a fresh state.
* **Restoring a clean demo state** (for example before a recording, or after visitors have clicked around). There are two ways:
  - `POST /api/admin/reset` with header `X-Admin-Token: <ADMIN_RESET_TOKEN>`. It doesn't exist unless that variable is set, the reviewer passcode is not accepted, and it's hidden from the OpenAPI schema.
  - Or, from a shell on the server: `python scripts/reset_demo_state.py --note "before demo"`.

  Either way, the current `state/` files are **archived** to `state/archive/<timestamp>/` (nothing is deleted), a fresh audit log starts with a `demo_reset` entry, and the precomputed auto-applies are re-applied. `data/` is never touched.

  ```bash
  curl -X POST "$API/api/admin/reset" -H "X-Admin-Token: $ADMIN_RESET_TOKEN" -H "content-type: application/json" -d '{"note":"before demo"}'
  ```

## Browser end-to-end checks

```bash
pip install playwright==1.48.0 && python -m playwright install chromium
cd frontend && npm ci && cd ..
python tests/e2e/run_e2e.py      # 26 checks; screenshots go to tests/e2e/out/ (gitignored)
```

The runner is self-contained. It starts the API on a throwaway `STATE_DIR` with a random passcode, starts Vite, and drives headless Chromium through these checks:
- all 39 cases render, with native MathML
- view-only mode without a passcode, a wrong passcode refused by the server, and the passcode never present in the page HTML
- approve, edit (including a guard error) and reject, which reverts an auto-apply, each producing an audit entry
- auto-advance to the next case, and no horizontal scroll at 390 px
- the read-only snapshot fallback when the API is unreachable

It then stops everything and confirms `data/` is unchanged. It isn't collected by pytest, because it needs a browser and Node.

## Deployment

* **Backend → Render** (`render.yaml`, free plan): `uvicorn app.main:app`, health check `/health`. Set `CORS_ORIGINS` to the Vercel URL.
* **Frontend → Vercel** (`vercel.json`): builds `frontend/`. Set `VITE_API_BASE` to the Render URL.
* **Secrets on Render:** set `REVIEWER_PASSCODE` and a *different* `ADMIN_RESET_TOKEN` in the Render dashboard. They're declared `sync: false` in `render.yaml`, so they're never stored in the repo. Share the passcode with reviewers privately; the reset token stays with the maintainer.
* **Cold start and snapshot fallback.** A free Render instance sleeps after inactivity and can take up to about a minute to wake. The console waits 25 seconds; if the API still hasn't answered, it loads `frontend/public/snapshot.json` (bundled at build time) and shows a **read-only** banner with all actions disabled. The banner has a **Try live again** button, which reloads once the API is awake.
* **Single-service fallback.** If `frontend/dist` exists, FastAPI also serves the console from the same origin.

## Limitations, stated honestly

* **Free-tier limits.** Gemini's free tier allows 20 requests per day per model, so questions are batched: 10 per solver call and 4 per judge call. Solver A and the judge share a model; solver B is a different model.
* **Google's free tier may use prompts to improve its products.** That's acceptable here because every prompt contains only the public assignment data.
* **Render free tier has an ephemeral disk.** Faculty actions and the audit log persist across requests and survived a local process restart in testing. On Render's free tier they are lost on redeploy or spin-down, which resets to the clean demo state. A production version would use a database.
* **Access control is a single shared passcode, not per-user accounts.** The name typed in the header is recorded as the audit actor but isn't authenticated. Wrong passcodes and wrong reset tokens share one rate limit: 8 failures per 10 minutes per client, after which even the correct passcode gets 429 until the window passes. The limiter is in-memory, so it resets when the process restarts.
* **Audit timestamps for system auto-applies** show when the API process loaded the results (or when the demo was last reset), not when the offline triage ran.
* **`results.json` is the engine's output, with no hand edits.** Every non-LLM decision is a coded rule, logged per report under `overrides` in `artifacts/triage_details.json` and explained in `PROMPTS.md`. These cover:
  - R017: verified already-fixed.
  - R026: syllabus claims go to faculty, with evidence that supports that verdict.
  - R021: a precheck-proven malformed key is classified `answer_key`, and its edit is the stored key's own normalisation; it still goes to faculty.
  - The 10 rule-5 confidence caps.
  - R039: a reply that promised an uncommitted feature was replaced.
  - 11 faculty-review replies: sentences claiming an action was underway were replaced with "We've sent this to a teacher to review". Running `LLM_OFFLINE=1 python scripts/run_triage.py --all` reproduces the file byte-for-byte.
