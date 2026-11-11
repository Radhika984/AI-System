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
