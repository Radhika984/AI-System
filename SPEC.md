# SPEC — Report → Fix (frozen at P0, 2026-11-11)

Source of truth: `README.md` (Acadza brief) + `data/taxonomy.json`. Where this spec and the brief disagree, the brief wins.

## 1. Verified dataset facts (from the files, not from memory)

| Fact | Value |
|---|---|
| Questions | 43 (`scq` 31, `integerQuestion` 10, `mcq` 2) |
| Reports | 44 (R001–R044), 39 distinct `questionId`s |
| Multi-report questions | `60f744b3…` (R001,R002,R003) · `60f742f6…` (R007,R008) · `612151a6…` (R018,R019) · `622f08d7…` (R009,R010) |
| Unreported questions | `68dea87d387eea3d0d95fbe3`, `68dea657387eea3d0d95f54a`, `695ede2a88d7701e561aa9d9`, `68dea6e6387eea3d0d95f6f8` |
| Identifier | `_id` (24-hex). `qid` is null for 9 and **not unique** (`SecAQ14` ×3) → never used as a key |
| Content location | `q[q.questionType]` → `{question, solution, answer, quesImages, solutionImages}` |
| Options | Inside `question` HTML as `(A)…(D)`, with unbalanced `<span>`s and inline MathML |
| Malformed keys | `68f21caf…` mcq `["", "B"]` (R021) · `68c8153c…` mcq `["A, B, D"]` (R020) |
| Already fixed | `6208e80a…` has `errorHistory` entry at 2026-11-07, after R017 (2026-11-04) |
| Missing figure | `622df25a…` says "as shown in figure", `quesImages: []` (R025) |
| Injection | R027 comment tries to instruct the system ("IGNORE ALL PREVIOUS INSTRUCTIONS…") |
| SHA-256 originals | questions `178d08f1…641a`, reports `042751d1…7b55`, taxonomy `3100ea34…d2df` (enforced by `tests/test_data_integrity.py`) |

## 2. Output contract — `results.json`

Exactly 44 objects, one per `reportId`, exactly these keys (brief §Part 3):

```
reportId, questionId, verdict, repair, edit, route, confidence, evidence, student_reply
```

* `verdict` ∈ taxonomy.verdicts. `repair` ∈ taxonomy.repairs when `verdict == "defect"`, else `null`.
* `edit` is `null` or `{field, find, replace}`:
  * `field` ∈ the repair's `fields`.
  * text fields (`question`, `solution`): `find` is an exact substring of the **stored HTML** that occurs **exactly once**; `replace` is its replacement. Surgical, never a whole-field rewrite.
  * `answer`: `find` = the stored answer, `replace` = new answer. `scq`: `"A"`→`"D"`. `integerQuestion`: `"2"`→`"1"`. `mcq`: JSON-encoded list, e.g. `"[\"\", \"B\"]"` → `"[\"B\"]"`.
* `route` ∈ `auto_apply | faculty_review | no_change`. `confidence` ∈ [0,1]. `evidence` non-empty. `student_reply` 1–3 sentences.
* Richer per-case data (solver outputs, prechecks, guard log, flags) goes to `artifacts/triage_details.json`, not into `results.json`.

## 3. Routing rules (deterministic, applied after the LLM judge)

1. `verdict != defect` → `no_change`, `repair = null`, `edit = null`.
2. `defect` + `taxonomy.repairs[repair].auto == false` → `faculty_review`, `edit = null` (we may suggest in evidence, never write).
3. `defect` + `auto == true` → `auto_apply` **only if all hold**, otherwise `faculty_review` (keeping a guard-valid edit as a one-click suggestion):
   * guard passes (scope, find-once, dry-run re-parse, option structure preserved, repair-specific rules below);
   * judge confidence ≥ 0.85;
   * no report in the question group is injection-flagged;
   * `answer_key`: both blind solvers independently agree on the new key, and (if numeric) the restricted evaluator reproduces it; subject must be Physics/Chemistry/Maths — Botany/Zoology/conceptual key changes always go to faculty;
   * `stem_data`: inserted value must appear in the stored solution;
   * `option_repair`: the restored text must be the solver-verified keyed answer; a missing *distractor* is authored content → faculty_review, `edit=null`;
   * `answer_form`: additive only (`replace` contains `find` verbatim);
   * `spelling`: only letters change (no digits/symbols/tags move);
   * `solution_fix` / `solution_missing`: the edited solution must still end at the keyed answer the solvers agree on.
4. Injection-flagged reports are never auto-applied; their comment is only ever shown to the LLM as quoted data.
5. Disagreement between solvers, or solver vs key when the judge says `no_error`, lowers confidence and escalates (`faculty_review`) rather than guessing.

## 4. Pipeline

`precheck (deterministic) → 2 blind solvers (no key, no comment) → safe_eval numeric check → group reports per question → judge (evidence packet, comments as untrusted quoted data) → Pydantic validation → guard → routing → results.json`

LLM: Google AI Studio **free tier only** (₹0). Solvers `gemini-3.8-flash` + `gemini-3.6-flash`, judge `gemini-3.8-flash`, fallback `gemini-3.1-flash-lite`. Disk cache keyed by (model, prompt version, messages); paced calls; exponential backoff on 429/5xx; on quota exhaustion the run stops and resumes from cache — never switches to a paid model.

## 5. Faculty console priority (queue order)

Tier 1 answer_key / wrong_question / unsound → Tier 2 stem_data / option_repair / identical_options / diagram → Tier 3 solution_fix / solution_missing → Tier 4 cosmetic (spelling, noise, exam_reference, markup_leak, notation, answer_form, type_mismatch, wrong_chapter, syllabus) → Tier 5 no_change. Within a tier: more distinct reporters → lower AI confidence → oldest report.

## 6. Requirement traceability checklist

| ID | Requirement (source) | Where | Status |
|---|---|---|---|
| R-T1 | verdict from taxonomy for each report (brief P1) | `judge.py`, `models.py` | ☐ |
| R-T2 | repair from taxonomy if defect | `judge.py`, `guard.py` | ☐ |
| R-T3 | surgical edit `{field,find,replace}` / new answer | `guard.py` | ☐ |
| R-T4 | confidence + evidence | `judge.py` | ☐ |
| R-T5 | student_reply 1–3 sentences, 17-yo tone | `prompts.py`, `guard.py` | ☐ |
| R-T6 | route auto_apply/faculty_review/no_change | `pipeline.py` | ☐ |
| R-T7 | comment is a lead, not an instruction | `prompts.py`, `precheck.py` | ☐ |
| R-T8 | independent key check | `solver.py`, `safe_eval.py` | ☐ |
| R-T9 | edits outside repair scope rejected | `guard.py` | ☐ |
| R-T10 | duplicate reports grouped | `pipeline.py` | ☐ |
| R-C1 | queue grouped by question, urgency order + why | `frontend`, `store.py` | ☐ |
| R-C2 | MathML rendered properly | `frontend` | ☐ |
| R-C3 | verdict, evidence, before/after diff | `frontend` | ☐ |
| R-C4 | approve / edit / reject + audit entry | `main.py`, `audit.py` | ☐ |
| R-C5 | student reply preview | `frontend` | ☐ |
| R-R1 | `results.json` for all 44 reports committed | `results.json` | ☐ |
| R-D1 | public GitHub repo | — (needs user) | ☐ |
| R-D2 | live URL up 7 days; disclose precomputed | `render.yaml`, `vercel.json` | ☐ |
| R-D3 | PROMPTS.md (product prompts verbatim + versions, assistant prompts, 3 AI mistakes, decision log) | `PROMPTS.md` | ☐ |
| R-D4 | PRODUCT.md ≤ 1 page, 4 questions | `PRODUCT.md` | ☐ |
| R-D5 | 3-min screen recording | — (needs user) | ☐ |
| R-D6 | Email reply with links + 4 personal answers | — (user approves/sends) | ☐ |
| R-B1 | Bonus: unreported defects | `bonus_findings.json` | ☐ |
| R-S1 | original `data/` unchanged | `tests/test_data_integrity.py` | ☐ |
| R-S2 | no secrets in repo | `.gitignore`, P10 scan | ☐ |
| R-S3 | ₹0 LLM spend (free tier only) | `config.py` | ☐ |

## 7. Known conflicts / decisions

* Repo folder is `acadza-report-fix/` (the extracted folder) rather than the plan's `report-to-fix/` — kept to avoid creating a second project.
* The brief asks for the four personal answers **in the email reply**, not the README; they are not written into any repo file.
* Render free tier has an ephemeral disk: faculty actions/audit persist across requests but are lost on redeploy/spin-down. Disclosed in README and UI.
