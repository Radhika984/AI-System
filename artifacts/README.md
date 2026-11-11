# artifacts/

| File | What it is | Part of the submission? |
|---|---|---|
| `../results.json` (repo root) | **The final submission**: 44 rows, scored by Acadza. | **Yes** |
| `triage_details.json` | Evidence behind the final `results.json`: per-question blind solves (model, answer, arithmetic re-check), solver agreement, judge analysis, prechecks, guard log, route reasons and rule-based overrides. The console reads this file. | Yes (supporting evidence) |
| `history/pilot_run1_2026-11-11_results.json` | **Historical only.** Output of pilot run #1 (6 reports, gemini-3.8-flash judge, solver prompts v1), *before* the fixes described in PROMPTS.md. Its R005 says `faculty_review`; that was the bug behind "AI mistake #1". Kept unchanged as evidence. | **No** |
| `runs/` | Where `scripts/run_triage.py --pilot` / `--reports` write partial reruns. | **No** |
| `run_all*.log` | Local per-call LLM logs (gitignored). | No |

Only `results.json` at the repo root is the scored output. It is reproducible from `cache/llm/` with zero API calls:
`LLM_OFFLINE=1 python scripts/run_triage.py --all` (asserted by `tests/test_reproducible.py`).
