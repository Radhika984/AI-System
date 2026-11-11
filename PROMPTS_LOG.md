# PROMPTS_LOG (running log, append-only)

Raw working log of (a) prompts I gave my AI coding assistant (Claude Code, model Claude Opus 5.5) and (b) product-prompt revisions. `PROMPTS.md` is the curated version of this file.

---

## 2026-11-11 08:36 IST — Coding-assistant prompt #1 (master brief)

Gave Claude Code a long master prompt ("ACADZA AI INTERN ASSIGNMENT — COMPLETE IMPLEMENTATION"). Key verbatim excerpts:

> You are my senior engineer and technical implementation partner. [...] Before writing or modifying any code, inspect the entire project folder. [...] Do not rely on assumptions from previous summaries when the actual files are available.

> Always use question `_id` as the unique identifier, never `qid`. [...] R027 contains adversarial prompt-injection content. R034 requires independent mathematical verification. [...] Do not blindly accept any previous hand-solved hypothesis as ground truth.

> Original `data/` files must remain unchanged. [...] All approved edits must be stored in a separate patch layer. Never invent missing options, evidence, or question content.

> Follow the exact agreed phase structure P0–P15 [...] Do not push to GitHub, change repository visibility, deploy publicly, or send emails without asking me first.

What the assistant did: read README, taxonomy, all 44 reports and all 43 questions (flattened HTML/MathML to text with a scratch lxml script), verified dataset facts, then asked before using an existing paid OpenAI key.

## 2026-11-11 08:45 IST — Decision: no paid LLM

The assistant found an `OPENAI_API_KEY` in the shell and asked whether to use it (est. < US$1). I answered **"No, I'll give a free key"**.

## 2026-11-11 08:50 IST — Coding-assistant prompt #2 (verbatim)

> Use Gemini API through Google AI Studio exclusively for this assignment. My budget is strictly ₹0. Do not use OpenAI, paid APIs, or any service that requires billing.
>
> Before implementation:
> 1. Verify which Gemini models currently have a free API tier.
> 2. Check their free-tier rate limits and availability.
> 3. Select a suitable free model for the two blind solvers and judge.
> 4. Use GEMINI_API_KEY from my local environment.
> 5. Never print, expose, commit, or log the API key.
> 6. Implement caching, rate-limit handling, retries, and exponential backoff.
> 7. Minimize API calls and reuse cached responses.
> 8. If free-tier limits are reached, pause safely and explain the situation instead of switching to a paid model.
>
> Keep the LLM client provider-agnostic, but use Gemini as the configured provider.
>
> My total API spending must remain zero.

Outcome: assistant fetched the official pricing page (ai.google.dev → aistudio.google.com/docs/pricing). Free-of-charge text models: `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite`, (deprecated) `gemini-2.5-flash/-lite`. The public rate-limit page no longer lists free-tier numbers (points to the per-account AI Studio page), so limits are discovered at runtime from 429 responses. Chosen: solver A `gemini-3.8-flash`, solver B `gemini-3.6-flash` (different model → more independent), judge `gemini-3.8-flash`, fallback `gemini-3.1-flash-lite`. Key sent only in the `x-goog-api-key` header (never in URLs, which end up in logs).

## 2026-11-11 08:55 IST — P0 spec freeze

`SPEC.md` written: output contract, edit encoding (incl. mcq answers as JSON-encoded lists), deterministic routing rules, queue tiers, traceability checklist. Original data files set read-only + SHA-256 pinned.

## 2026-11-11 09:20 IST — P0 smoke test

`scripts/smoke_llm.py`: gemini-3.8-flash, gemini-3.6-flash, gemini-3.1-flash-lite all returned `{"ok": true, "sum": 42}`; 3 calls, 0 retries. Key loaded from gitignored `.env`; never printed.

## 2026-11-11 09:25 IST — Pilot run #1 (R005 R004 R027 R017 R009 R034) — AI mistake #1

20 calls, 208 s, 2 automatic 429/5xx retries. R004 auto_apply A→D ✓, R017 already_fixed ✓, R027 no_error (injection ignored, key A verified) ✓, R009/R010 option_repair → faculty, edit null ✓, R034 unsound → faculty ✓.
**R005 was wrongly held for faculty.** Both blind solvers answered n = 1, but solver A's `expression` was `(1/2)*(1/2)+(1/8)*2` = 0.5 — the flux in units of q/ε₀, an intermediate step, not n. The restricted evaluator flagged the mismatch and my rule "any mismatch blocks auto-apply" fired.
Caught by: reading `route_reasons` in `artifacts/pilot_results.json` (`"restricted evaluator did not reproduce the solvers' value"`) and comparing to the hand audit (expected auto_apply).
Fix: (1) solver prompts v1→v2: "expression must evaluate to EXACTLY numeric_value — the final quantity asked for, not an intermediate step"; (2) rule: numeric_ok = True if ≥1 solver's arithmetic reproduces its claim (both final answers must already agree); False only if evaluated arithmetic never reproduces; None if nothing evaluable (unsafe expressions count as "unverified", not as evidence). Regression test `tests/test_solver.py::test_r005_intermediate_expression_tolerated_when_other_solver_reproduces` uses the exact pilot expressions.

## 2026-11-11 09:35 IST — Pilot run #2 + free-tier quota wall

Pilot #2 (solver prompts v2): R005 → auto_apply ✓ (regression fixed). Mid-run the client raised `QuotaExhausted` and stopped:
`quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue: 20` for gemini-3.8-flash (retry in ~4 h). So the free tier is **20 requests/day per model** — the full un-batched run (~117 calls) cannot fit in one day.
Assistant paused and asked; I chose: **batch questions per call + reassign roles to other free models**.

### Coding-assistant prompt #3 (verbatim, mid-run)
> Don't allow any automatic fallback to paid models or billing.

Assistant's response: confirmed the allowlist + stop-on-quota already enforce this (tests `test_paid_model_refused`, `test_daily_quota_stops_without_switching_models`), and **removed the unused `FALLBACK_MODEL` setting** so there is no fallback path even on paper.

### Batching design (prompt `batch-v1`)
* Solvers: `SOLVER_BATCH_SUFFIX` appended to each solver's system prompt; questions labelled Q1..Qn, "solve EACH independently". A question missing/invalid in a batch answer is re-solved alone.
* Judge: `JUDGE_BATCH_SUFFIX`; cases labelled C1..Cn, "never carry facts, answers or comments across cases". Each case validated separately; invalid → re-judged alone with the single-case prompt.
* Deterministic post-rules / guard / routing are unchanged and still per question (`pipeline.finalize`).

## 2026-11-11 09:50 IST — Second quota stop, final model assignment

gemini-3.6-flash also hit 20/day (my usage estimate missed that rate-limited retries count). Stopped safely again, no paid call. Final assignment (all free tier):
solver A `gemini-3-flash-preview`, solver B `gemini-3.1-flash-lite` (different models → independent errors), judge `gemini-3-flash-preview`; solver batch 10, judge batch 4 → ~18 calls for 39 questions.
Trade-off noted honestly: judge and solver A share a model. Solvers never see the key/solution/comments, so blindness holds, but the judge is not a third independent model.

## 2026-11-11 10:40 IST — Full run (P3) + edit-repair quota

All solver + judge calls completed (18 batched calls). The one optional `editfix-v1` retry then hit gemini-3-flash-preview's 20/day cap and — by my earlier design — `QuotaExhausted` aborted the whole run. Changed: a quota/offline miss inside the *optional* edit-repair retry is now logged ("edit-repair retry skipped") and the case routes to faculty with edit=null (conservative). Re-ran: 44 rows, all other calls served from cache.

## 2026-11-11 10:50 IST — Disagreement review vs hand audit (`scripts/eval_results.py`) — AI mistakes #2 and #3

First full results: verdict 43/44, repair 42/44, route 37/44 vs my pre-registered hand audit. Investigated each, did not force:

* **AI mistake #2 (R009/R010): the judge invented an option and my guard auto-applied it.** The judge's edit appended `(D) 40 m/s` to a question whose option D is simply missing (a distractor nobody knows). SPEC §3 says a missing distractor is authored content → faculty, edit=null — but `guard.route()` only checked "solvers agree with the key", never *which* option the edit restores. Caught by: eval disagreement (engine auto_apply vs audit faculty_review) → read the edit text. Fix: `guard.option_restore_check` — option_repair may only restore the single **keyed** option, its value must be reproduced by ≥1 blind solver's numeric answer, and no solver may pick a different existing option; otherwise faculty_review and the edit is dropped entirely. Regression tests use the exact invented edit.
* **R011 (verification gap, same code):** both solvers had computed 1:1 (A picked the blank (C); B said "None of these", numeric 1.0) but the old rule required letter agreement. The new rule verifies the restored *content* → auto_apply.
* **R026 (policy):** judge ruled "outgroup analysis is in syllabus → no_error". The taxonomy defines `syllabus` as "Student says it is outside the syllabus. **Faculty confirm**; question stays live meanwhile" — scope is a faculty decision. Added deterministic rule (`syllabus_claim` flag → defect/syllabus/faculty_review, template reply). The flag is kept out of the judge packet so the judge-v1 cache stays byte-identical.
* **AI mistake #3 (R018/R019): suggested fix would itself have been a defect.** The `solution_fix` suggestion (faculty_review, so not live) wrote raw LaTeX `$K = \frac{h^2}{2m\lambda^2}$` into an HTML/MathML solution — a one-click approve would have created a `markup_leak`. Caught by reading every edit in results.json. Fix: guard rejects any edit (AI or faculty) that *introduces* LaTeX commands or `$...$`.
* **Accepted as engine output (safer than my audit):** R018/R019 — both blind solvers got the physics wrong (C and A; true answer B = 16.8 eV) and disagreed, so the system refused to auto-apply a solution rewrite: the safety net working. R021 — judge chose `type_mismatch` (student: "only B is correct but its multiple correct type"), a defensible reading; malformed-key edit was rejected by the guard (judge wrote `"B"` not `["B"]`) and the repair retry had no quota → faculty.

Final (offline cache replay, 0 API calls): VALIDATION PASS; verdict 44/44, repair 43/44, route 41/44 vs hand audit; routes auto_apply 16 / faculty_review 11 / no_change 17. No manual edits to results.json.

## 2026-11-11 10:55 IST — P5/P7 browser verification, P10 clean clone

* Headless Chromium (Playwright) drove the real console: 39/39 cases render with no page errors; native MathML present; mobile 390 px has no horizontal scroll; approve (keyboard `A`) / edit (guard error shown, then valid faculty distractor) / reject (reverts auto-apply, live key back to A) all create audit entries; snapshot build with an unreachable API shows the read-only banner and hides all actions.
* UX fixes from the screenshots: struck-through "C" in the key diff read as "€" → plain "Current key"; solver chips "A ≠ key" read as a warning on a *good* case → one plain sentence ("Both blind solvers independently got A. The stored key says C."); added a one-line fix summary under the headline; contextual primary label; note field hidden on phones.
* **Clean clone caught a reproducibility bug:** code defaults (solver A 3.6-flash, judge batch 3) differed from my `.env` overrides used for the real run, so a fresh clone missed the cache. Defaults now equal the run config; `tests/test_reproducible.py` asserts an offline replay equals the committed results.json with 0 calls. Also generated JSON is written with LF so the replay is byte-identical on Windows.

## 2026-11-11 ~11:30 IST — Compliance audit (no changes), then approved local corrections

### Coding-assistant prompt #6 (key lines, verbatim)
> Before proceeding to P6, I want a strict **Assignment Requirements Compliance Audit**. [...] Do not mark a requirement complete just because code exists. Do not fabricate test results or claim something works without executing it. [...] Do not change any code during this audit.

Audit (executed, read-only) found: B1 open writes on a public demo, B2 no demo reset, **B3 SPEC §3 rule 5 only partly implemented** (R029/R030/R032/R039/R044 at confidence 1.0 despite solver disagreement), B4 doc inaccuracies (stale "109 tests"; edit-repair statement; R018/R019 guard log said "quota exhausted" during an offline replay), README placeholder. Verdict: NOT READY FOR DEPLOYMENT.

### Coding-assistant prompt #7 (key lines, verbatim)
> Fix B3 strictly according to SPEC.md §3 rule 5. Solver disagreement must lower confidence and escalate as specified, including for non-defect verdicts. Do not change correct verdicts just to resolve confidence issues. [...] Address B1 by implementing backend-enforced reviewer protection for mutation endpoints. Use a simple shared reviewer passcode, with the secret stored only in environment variables. Never hardcode or commit it. Address B2 by implementing a safe demo reset mechanism [...] Do not expose an unrestricted public reset endpoint.

What changed:
* **B3** `pipeline.solvers_dispute`: two different *definite* blind answers → confidence ≤ 0.7 for any verdict; non-defects raised to console priority 1 ("AI unsure"). Abstention: no usable answer, or missing-content report on a missing-content defect (R006/R011/R025). First version compared answers as strings and flagged R033; I wrongly called that a false positive ("3113 vs 3112.99, equal within tolerance") and changed the code to defer to `solver.agreement`'s 1% tolerance. **Correction (14:15 IST, see below): solver B actually answered 3114, so the first version was right and my "fix" suppressed a genuine dispute.** Offline replay (0 calls): only `confidence` changed on 10 reports; verdict/repair/route/edit identical.
* **Guard log**: edit-repair skips now state the true cause (`free-tier quota exhausted` vs `offline cache replay; no cached edit-repair response`).
* **B1** `security.py`: `REVIEWER_PASSCODE` (env only) required on every write, constant-time compare, 401 wrong/missing, 429 after 8 failures/10 min/client, 503 if unset (fail closed). Console: password field (sessionStorage per tab), view-only until entered.
* **B2** `Store.reset_demo` via `POST /api/admin/reset` (separate `ADMIN_RESET_TOKEN`; 404 when unset or equal to the passcode; hidden from OpenAPI) or `scripts/reset_demo_state.py`; archives state to `state/archive/<ts>/`, fresh audit with `demo_reset`, re-applies auto-applies.
* **E2E** moved into `tests/e2e/run_e2e.py` (self-contained). While porting, the assistant wrote one check as `... or True` (always passes) — caught on review before running and made strict. First run caught a real regression: the new passcode field overflowed the 390 px header (scrollWidth 407) → fixed. Tier-1 headers fragmented after rule 5 → one header per tier + "AI unsure" badge.

## 2026-11-11 ~11:50 IST — Pre-deployment polish

* `artifacts/pilot_results.json` (pilot run #1, referenced above) moved unchanged (`git mv`, sha256 fd65f80f…) to `artifacts/history/pilot_run1_2026-11-11_results.json`; `artifacts/README.md` labels every artifact; pilot/partial reruns now write to `artifacts/runs/`. Only root `results.json` is the submission.
* R039's reply promised "we are working on adding support for other languages in the future" — a commitment nobody made. Added a deterministic reply guard (`pipeline._PROMISE`): replies that promise features/timelines are replaced by the verdict template and the override is logged. Scan of all 44 replies: R039 was the only hit. Two of my own templates ("we'll look again", "will be updated shortly") also violated the rule and were reworded. Offline replay: only R039's `student_reply` changed.

## 2026-11-11 ~14:15 IST — Independent end-to-end triage audit → PASS WITH ISSUES → corrections (0 API calls)

### Coding-assistant prompt #8 (key lines, verbatim)
> Perform a FINAL END-TO-END TRIAGE CORRECTNESS AUDIT [...] Do not treat passing tests or schema validation as proof of academic correctness. [...] For anything you cannot independently establish, mark UNVERIFIED.

The assistant re-solved all 30 computational questions from first principles (separate script, no pipeline code) and read every record. Findings: R033 rule-5 miss (solver B = 3114 accepted by 1%/3% tolerances; three places misdescribed it as 3112.99), R021 repair type questionable, R026 evidence contradicting its coded verdict, rule 5 applied to R039 (language request), 9 replies claiming in-progress actions while faculty approval was pending, PRODUCT.md overstating R004's reply.

### Coding-assistant prompt #9 (key lines, verbatim)
> 1. R033: Fix integer-answer agreement and arithmetic verification tolerances so incorrect integer answers cannot be treated as correct due to loose percentage tolerance. Apply the original assignment's Rule 5 correctly. Correct all three inaccurate references describing the R033 disagreement. [...] 6. R021: Re-evaluate the repair classification against the original taxonomy. Do not invent a correction. Preserve faculty review if necessary.

What changed:
* **Tolerances** (`solver.py`): integer answers agree only if exactly equal (float noise ≤ 1e-6); a solver's expression must round to its claimed integer answer at the claimed precision (3112.99→3113 ✓, →3114 ✗). Option questions keep 3% (printed options are rounded). R033 now: dispute A=3113/B=3114 → confidence 0.95→0.7, console "AI unsure". My own test initially expected 0.0812 to mismatch a claimed 0.08 — wrong (it rounds to 0.08); test corrected.
* **Replay without API calls**: the stricter numbers changed the judge packet text → cache miss. Rather than re-judging, judge-v1 packets are rebuilt from the v1 numeric summary the judge was actually sent (`solver.judge_packet_view`); everything after the judge uses the strict checks. Documented in code and here.
* **Rule 5 scope**: SPEC text names defects (→ faculty_review) and no_error (→ priority 1). language_mode etc. are outside it → R039 confidence restored to the judge's 1.0 and logged "rule 5 not applied". R042 (a defect) stays capped: the spec requires it; no route effect.
* **R026 evidence** now supports the coded syllabus verdict (judge's original evidence kept as `judge_evidence` in details).
* **Replies**: on faculty_review routes, sentences claiming an action is underway/done are replaced by "We've sent this to a teacher to review." (11 replies: R009, R010, R015, R018, R019, R021, R023, R025, R026 template, R034, R042). Trade-off: R009/R010/R019 lost their specific sentence, which *was* the claim.
* **R021**: precheck proves the key `["", "B"]` is malformed; taxonomy `answer_key` = "Answer key wrong **or malformed**"; `type_mismatch` needs evidence of a wrong stored type, and an mcq with one correct option is valid. → repair `answer_key`, edit `["", "B"]`→`["B"]` (the stored key's own normalisation, guard-validated; nothing invented). Route stays faculty_review (solvers disagree → rule 5).
* **PRODUCT.md**: R004 sentence now describes what the reply actually says.

## 2026-11-11 ~15:00 IST — Safety & Trust audit → V1/V2 fixed (0 API calls)

### Coding-assistant prompt #10 (key lines, verbatim)
> Now perform a complete independent audit of Evaluation Criterion B: Safety and Trust (10 marks). [...] Do not treat passing unit tests alone as proof of safety. Test the actual implementation and backend behaviour.

Audit ran the real server on throwaway state, the real UI, and a *stub judge that obeys any injection*. Restricted types, answer-key protection, data protection, passcode and audit all held. Two defects found:
* **V1** `guard.check_edit` rules were shape-only: with an unflagged Hindi-English comment ("bhai yeh question theek karo please"), an obedient judge got `noise` "not antagonistic"→"antagonistic" and `spelling` "Golden rice"→"Golden wheat" **auto-applied end-to-end**; `exam_reference` could delete ordinary words; `answer_form` could append "(the answer is 25)".
* **V2** `store.act` "edit" reverted the system auto-apply *before* validating; a refused (422) edit on R022 put the typo "plexux" back live, kept status "auto_applied", and wrote a `revert_auto_apply` audit entry for a failed request (the revert was not persisted, so after a restart the audit claimed a revert that never happened).

### Coding-assistant prompt #11 (key lines, verbatim)
> I approve fixing ONLY V1 and V2 [...] Do not simply block all edits of these types. Preserve legitimate corrections. [...] Refactor the store.act edit path so that: 1. The proposed edit is fully validated first. 2. Existing patches are not reverted before validation succeeds. 3. The new patch and any necessary revert happen atomically. 4. Audit entries are written only after the corresponding operation succeeds. 5. A rejected edit leaves the live question, status, patch file and audit trail unchanged.

What changed:
* `guard.py`: semantic bounds per repair (spelling word-count/edit-distance/meaning-critical words; exam_reference & noise deletions must match defined patterns; answer_form additions must be unit/rounding only; markup_leak keeps words; notation keeps words+numbers; stem_data insert-only; solution_fix no invented numbers; type_mismatch routing). All 16 committed auto-applies still pass; results.json byte-identical.
* `store.py`: `act` is transactional (validate → stage → atomic two-file save → audit after commit; snapshot rollback on any exception). Faculty edits replacing an auto-apply are validated against the question without the system patch.
* Tests: `tests/test_guard_semantic.py` (attacks blocked, legitimate fixes pass), `tests/test_store_atomic.py` (R022 scenarios, restart, valid edit, reject/revert, failed save), Hinglish + insistent judge (which insists twice, incl. the edit-repair retry) in `tests/test_llm_offline.py`. Run against the old code at ba394da: 24 of the new tests fail; on the new code all pass (177 total).
* Harness slips while writing tests: synthetic report id "RX01" was rejected by the `R###` schema (a guard working); a stub with no scripted edit-repair reply raised IndexError — replaced with an attacker that insists again (stronger test).

## 2026-11-11 ~16:00 IST — Five extra adversarial tests → N1/N2/O1 fixed (0 API calls)

### Coding-assistant prompt #12 (key lines, verbatim)
> Run 5 ADDITIONAL ADVERSARIAL TESTS for Criterion B (Safety and Trust) [...] INDIRECT PROMPT INJECTION [...] CONFLICTING AI SOLVERS [...] MALICIOUS FACULTY INPUT [...] CROSS-REPORT MANIPULATION [...] RESTART AND PERSISTENCE [...] Do not fix anything; report only.

Results: no automatic path could be bent (7 injection styles incl. teacher-approval claims, quoted "SYSTEM" text, role-play, Hindi-English, JSON payloads, tag break-out; 8 solver-conflict combinations; 18 malformed faculty requests; cross-question IDs; two restarts). Findings: **N1** an injection-steered key (A→C, contradicting both blind solvers) stayed the one-click suggestion — one Approve set the live key to C; **N2** no size limit on faculty edits (5 MB accepted; a case response reached 18 MB because reverted patches were returned); **O1** unknown request fields silently ignored. The assistant also noticed its own "5 MB body rejected" pass was only due to the note-length cap and re-tested with the payload inside the edit.

### Coding-assistant prompt #13 (key lines, verbatim)
> Fix N1, N2 and O1 [...] If a case is flagged for prompt injection/manipulation, do not offer its AI-proposed edit as a one-click faculty approval. If the proposed answer conflicts with either blind solver, do not offer that edit as an approvable suggestion. [...] Add a reasonable maximum request-body size. [...] Reject unknown top-level request fields. Reject unknown nested edit fields.

What changed: `Store.suggestion` (N1; console shows the withheld proposal + reasons, Approve applies nothing, Edit form starts empty); `BodySizeLimit` ASGI middleware 64 KB + `Edit` field limits + reverted patches hidden (N2); `extra="forbid"` on `Edit`, `ActionIn`, `ResetIn` (O1); `judge.fix_edit_once` now passes only field/find/replace to `Edit` so cached replays are unaffected; client shows readable 413/422 messages (it used to print "[object Object]" for validation errors). results.json unchanged; R021's suggestion is now withheld (solver B answered C). New tests `tests/test_n1_n2_o1.py`: 19/22 fail on 055378b, 22/22 pass now; 199 total.
