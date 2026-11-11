# PRODUCT.md

## 1. Who loses the most when a question is broken?

**The student who solved it correctly and was marked wrong.** A wrong answer key takes 4 marks from them, and it teaches them that their correct method is wrong, weeks before JEE. That happens again for every student who meets the question until someone fixes it. Most of those students never report; they just lose the marks and doubt themselves.

How the design reflects this:
- **The queue is ordered by harm to students, not arrival time.** First come wrong keys, unanswerable questions, and cases where the AI is unsure. Then questions students can't attempt (missing data, option or figure), then wrong solutions, then cosmetic issues.
- **A provable wrong key is fixed in minutes.** Two blind solvers on different models, which never see the key or the comment, must agree, and code re-checks their arithmetic. Faculty then spot-check the fix and can revert it with one click.
- **The reply tells the student exactly where they stood.** For R004 ("8225 aana chahiye") it says the key *was* wrong, but the answer is 4800.

## 2. What I would never let the AI auto-apply

- **Anything the AI would have to author rather than restore.** That means new distractors (R015), an unknown missing option (R009/R010), figures, and chapter or syllabus moves. In testing, the AI did invent "(D) 40 m/s", and that is exactly what the guard now blocks. The AI may only restore what the record proves: a value the solution states, the keyed option the solvers computed, or a typo.
- **Answer keys in conceptual subjects** (biology, statement-type questions), and any key change where the blind solvers disagree. Arithmetic can be checked mechanically; facts can't, and a confident wrong "fix" teaches every later student something wrong.
- **Anything on a question that carries a manipulation attempt** (R027: "IGNORE ALL PREVIOUS INSTRUCTIONS…").
- **Any edit that fails the deterministic guard.** The guard checks scope, that the anchor occurs exactly once, that the result still parses, that no option is lost, that spelling fixes change letters only, and that no raw LaTeX is introduced. The model's word is never enough.

## 3. The one metric I'd watch in week 1

**Auto-apply reversal rate:** the share of auto-applied fixes that faculty revert on spot-check. It must stay near 0%. If faculty can't trust auto-apply, they will re-check everything by hand and the system saves no time. If it holds, I'd widen the auto-apply criteria slowly.

## 4. One idea beyond the brief: re-grade the students who never reported

When a key fix goes live, re-score every past attempt on that question and notify each affected student: *"Q14 in your Nov 3 test had a wrong key. You were right, +4 restored."* Today a fix only helps future students; this repairs the damage already done to the silent majority. The same attempt data also finds wrong keys before anyone reports them: a question where top-quartile students overwhelmingly pick a "wrong" option is a likely key error. That's how this repo's bonus sweep would scale to 8 lakh questions.
