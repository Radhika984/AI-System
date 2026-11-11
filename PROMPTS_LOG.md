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
