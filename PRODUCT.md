# PRODUCT.md

**Users and flow.** Faculty reviewers are the primary users and make the final call; students are who it protects. Reports are grouped by question (R001–R003 are one case) and queued by harm. Each case shows the AI verdict beside independent evidence, original vs proposed, safety checks and the drafted student reply. Faculty approve or reject (both confirmed first) or edit; every action is audited and the question bank is never overwritten. AI verdicts were precomputed offline (free-tier Gemini); the running app makes no AI calls.

## 1. Who loses the most when a question is broken?

**The student who solved it correctly and was marked wrong.** A wrong key costs them the marks and teaches them their correct method is wrong, weeks before JEE. It repeats for every student who meets the question until it is fixed, and many probably never report; they just lose the marks.

How the design reflects this:

- **The queue is ordered by harm, not arrival time.** *Urgent attention* first: wrong keys, unanswerable questions, cases where the AI is unsure. Then *Faculty review* (missing data, options, figures, solutions, cosmetics), live fixes awaiting a spot check, and no-change reports.
- **A provable wrong key goes live without waiting.** Two blind solvers on different models, which never see the key or the comment, must agree, and code re-checks any arithmetic. Faculty spot-check it; a confirmed Reject undoes it.
- **The reply shows the working.** For R004 ("8225 aana chahiye") the drafted reply gives P = (1/3)ρv² = 4800 N/m² and says the key was corrected to D, without telling the student outright they were wrong.

## 2. What I would never let the AI auto-apply

- **The six types that need authored content or judgement**, `auto:false` in the taxonomy, always go to faculty: `identical_options` (new distractor, R015), `diagram`, `wrong_question`, `unsound`, `wrong_chapter`, `syllabus`.
- **Anything else it would have to author rather than restore**, like an unknown missing option (R009/R010). In testing the AI invented "(D) 40 m/s"; the guard now blocks exactly that. It may restore only what the record supports: a value stated in the solution, a keyed option whose value a blind solver reproduced, a solution fix that reaches the key both solvers confirm, or a mechanical cleanup such as a typo, stray tag, raw markup or unit label.
- **Answer-key changes outside physics, chemistry and maths**, or where the blind solvers disagree. Facts, unlike arithmetic, can't be checked mechanically, and a wrong "fix" misteaches every later student. Unless both solvers gave exactly the AI's proposed key, the console withholds it and Approve only records the problem (R021).
- **Anything on a question carrying a manipulation attempt** (R027).
- **Any edit failing the deterministic guard**: scope, anchor occurs exactly once, result parses, no option lost, spelling fixes change letters only, no raw LaTeX.

## 3. The one metric I'd watch in week 1

**Auto-apply reversal rate:** the share of auto-applied fixes faculty undo on spot-check. It must stay near 0%; if faculty can't trust auto-apply, they re-check everything and the system saves no time. If it holds, widen the criteria slowly.

## 4. One idea beyond the brief: re-grade the students who never reported

When a key fix goes live, re-score every past attempt on that question and notify each affected student: *"Q14 in your Nov 3 test had a wrong key. You were right, +4 restored."* Today a fix only helps future students; this repairs the damage already done. Attempt data also finds unreported wrong keys: a question where top-quartile students overwhelmingly pick a "wrong" option is a likely key error. That's how this repo's bonus sweep would scale to 8 lakh questions.
