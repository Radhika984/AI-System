"""Deterministic edit guard. Every proposed edit — from the LLM or from a faculty
member editing in the console — passes through `check_edit` before it can be
stored, and through `route()` before anything is auto-applied.

The guard never trusts the proposer: it re-derives scope from taxonomy.json,
dry-runs the edit on a deep copy, re-parses the result, and compares
before/after structure.
"""
from __future__ import annotations

import copy
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from . import normalize as N
from . import taxonomy
from .config import AUTO_APPLY_MIN_CONFIDENCE
from .models import Edit

_TAG = re.compile(r"<[^>]+>")
_DANGEROUS = re.compile(r"<\s*(script|style|iframe|object|embed|link|meta|form|input)\b|\bon\w+\s*=|javascript:", re.I)
_DIGITS = re.compile(r"\d")
_LATEX_CMD = re.compile(r"\\[A-Za-z]+")
COMPUTATIONAL_SUBJECTS = {"physics", "chemistry", "mathematics", "maths", "math"}


@dataclass
class GuardResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    before: str = ""
    after: str = ""
    before_text: str = ""
    after_text: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors}


def apply_edit(q: dict, edit: Edit) -> dict:
    """Return a NEW question dict with the edit applied (input untouched)."""
    nq = copy.deepcopy(q)
    b = N.body(nq)
    if edit.field == "answer":
        b["answer"] = json.loads(edit.replace) if nq["questionType"] == "mcq" else edit.replace
    elif edit.field == "questionType":
        old = nq["questionType"]
        nq["questionType"] = edit.replace
        nq[edit.replace] = nq.pop(old)
    else:
        b[edit.field] = (b.get(edit.field) or "").replace(edit.find, edit.replace, 1)
    return nq


def _introduces_latex(find: str, replace: str) -> bool:
    def latex(s: str) -> set[str]:
        return set(_LATEX_CMD.findall(s)) | ({"$"} if re.search(r"\$[^$]+\$", s) else set())
    return bool(latex(replace) - latex(find))


def _is_subsequence(small: str, big: str) -> bool:
    it = iter(big)
    return all(ch in it for ch in small)


def check_edit(q: dict, repair: str, edit: Edit | dict | None) -> GuardResult:
    errs: list[str] = []
    if edit is None:
        return GuardResult(False, ["no edit proposed"])
    if isinstance(edit, dict):
        try:
            edit = Edit(**edit)
        except Exception as e:  # pydantic ValidationError
            return GuardResult(False, [f"edit schema: {e.errors()[0]['msg'] if hasattr(e, 'errors') else e}"])
    if not taxonomy.is_repair(repair):
        return GuardResult(False, [f"unknown repair {repair!r}"])
    allowed = taxonomy.repair_fields(repair)
    if not allowed:
        return GuardResult(False, [f"repair {repair} has no editable fields (auto:false) — human authors the fix"])
    if edit.field not in allowed:
        return GuardResult(False, [f"field {edit.field!r} is outside the scope of {repair} {allowed}"])

    qtype = q["questionType"]
    b = N.body(q)

    # ---------------- answer edits
    if edit.field == "answer":
        stored = N.answer_to_str(b.get("answer"))
        if edit.find != stored:
            errs.append(f"answer find {edit.find!r} does not equal stored answer {stored!r}")
        new_ans, probs = _parse_answer(qtype, edit.replace)
        if probs:
            errs.extend(f"new answer invalid: {p}" for p in probs)
        if qtype in ("scq", "mcq") and not probs:
            _, opts = N.split_options(b.get("question", ""))
            letters = new_ans if isinstance(new_ans, list) else [new_ans]
            for L in letters:
                if L not in opts or not opts[L].strip():
                    errs.append(f"new key {L} points to a missing/blank option")
        return GuardResult(not errs, errs, stored, edit.replace, stored, edit.replace)

    if edit.field == "questionType":
        if edit.find != qtype or edit.replace not in ("scq", "mcq", "integerQuestion"):
            errs.append("questionType edit must change the stored type to scq/mcq/integerQuestion")
        return GuardResult(not errs, errs, qtype, edit.replace)

    # ---------------- text edits (question / solution)
    src = b.get(edit.field) or ""
    n = src.count(edit.find)
    if n != 1:
        errs.append(f"find must occur exactly once in {edit.field} (found {n})")
    if _DANGEROUS.search(edit.replace):
        errs.append("replace contains script/style/event-handler markup")
    if "<img" in edit.replace.lower() and "<img" not in edit.find.lower():
        errs.append("edit introduces an image; images are authored content (diagram repair)")
    if len(edit.replace) > max(600, 3 * len(edit.find) + 400):
        errs.append("replace is too large for a surgical edit")
    if _introduces_latex(edit.find, edit.replace):
        errs.append("replace introduces raw LaTeX ($...$ or \\command) - students would see code (markup_leak)")
    if errs:
        return GuardResult(False, errs)

    after_html = src.replace(edit.find, edit.replace, 1)
    if not N.parses(after_html):
        errs.append("edited HTML does not parse")
    before_text, after_text = N.to_text(src), N.to_text(after_html)

    if edit.field == "question" and qtype in ("scq", "mcq"):
        s0, o0 = N.split_options(src)
        s1, o1 = N.split_options(after_html)
        if len([v for v in o1.values() if v.strip()]) < len([v for v in o0.values() if v.strip()]):
            errs.append("edit removes or blanks an option")
        if repair == "option_repair":
            if _norm_ws(s0) != _norm_ws(s1):
                errs.append("option_repair changed the stem text")
            changed = [L for L in o0 if o0.get(L) != o1.get(L)]
            added = [L for L in o1 if L not in o0]
            for L in changed:
                if o0[L].strip():
                    errs.append(f"option_repair rewrote non-blank option ({L})")
            if not changed and not added:
                errs.append("option_repair did not restore any option")

    find_txt, rep_txt = _strip_tags(edit.find), _strip_tags(edit.replace)
    if repair == "spelling":
        if Counter(_DIGITS.findall(edit.find)) != Counter(_DIGITS.findall(edit.replace)):
            errs.append("spelling edit moves digits")
        if _TAG.findall(edit.find) != _TAG.findall(edit.replace):
            errs.append("spelling edit changes markup")
        if re.sub(r"[A-Za-z\s’'\-]", "", find_txt) != re.sub(r"[A-Za-z\s’'\-]", "", rep_txt):
            errs.append("spelling edit changes symbols")
    elif repair in ("noise", "exam_reference"):
        if not _is_subsequence(rep_txt, find_txt) or len(rep_txt) >= len(find_txt):
            errs.append(f"{repair} edit must only delete stray text")
    elif repair == "answer_form":
        if edit.find not in edit.replace:
            errs.append("answer_form is additive only: replace must contain find verbatim")
    elif repair == "markup_leak":
        if not (_LATEX_CMD.search(edit.find) or "&lt;" in edit.find or "$" in edit.find):
            errs.append("markup_leak find contains no raw LaTeX/HTML")
        if _LATEX_CMD.search(_strip_tags(edit.replace)):
            errs.append("markup_leak replace still contains raw LaTeX")
        if Counter(_DIGITS.findall(find_txt)) != Counter(_DIGITS.findall(_strip_tags(edit.replace))):
            errs.append("markup_leak edit changes numbers")
    elif repair == "stem_data":
        if edit.field != "question":
            errs.append("stem_data edits the question only")
        new_nums = set(re.findall(r"\d+(?:\.\d+)?", rep_txt)) - set(re.findall(r"\d+(?:\.\d+)?", find_txt))
        sol_txt = N.to_text(b.get("solution", ""))
        sol_nums = set(re.findall(r"\d+(?:\.\d+)?", sol_txt))
        missing = sorted(x for x in new_nums if x not in sol_nums)
        if missing:
            errs.append(f"stem_data inserts value(s) {missing} not stated in the solution")
    elif repair in ("solution_fix", "solution_missing"):
        if edit.field != "solution":
            errs.append(f"{repair} edits the solution only")

    return GuardResult(not errs, errs, edit.find, edit.replace, before_text, after_text)


def _parse_answer(qtype: str, s: str):
    if qtype == "mcq":
        try:
            val = json.loads(s)
        except json.JSONDecodeError:
            return None, ["mcq answer must be a JSON list like [\"A\", \"C\"]"]
        if not isinstance(val, list) or not val:
            return None, ["mcq answer must be a non-empty list"]
        probs = [f"bad entry {v!r}" for v in val if v not in N.LETTERS]
        if len(set(val)) != len(val):
            probs.append("duplicate letters")
        return val, probs
    norm, probs = N.normalize_answer(qtype, s)
    return norm, probs


def _strip_tags(s: str) -> str:
    return N.to_text(s) if "<" in s else s


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def check_faculty_edit(q: dict, edit: Edit | dict) -> GuardResult:
    """Faculty may author content the AI may not (e.g. new distractors for
    identical_options), so repair *scope* is not enforced — but structure is:
    find-once, parses, no script/handlers, valid answer format, no option lost."""
    if isinstance(edit, dict):
        try:
            edit = Edit(**edit)
        except Exception as e:  # noqa: BLE001
            return GuardResult(False, [f"edit schema: {e}"])
    errs: list[str] = []
    b = N.body(q)
    if edit.field == "answer":
        return check_edit(q, "answer_key", edit)
    if edit.field not in ("question", "solution"):
        return GuardResult(False, [f"faculty edits may touch question/solution/answer, not {edit.field}"])
    src = b.get(edit.field) or ""
    n = src.count(edit.find)
    if n != 1:
        errs.append(f"find must occur exactly once in {edit.field} (found {n})")
    if _DANGEROUS.search(edit.replace):
        errs.append("replace contains script/style/event-handler markup")
    if _introduces_latex(edit.find, edit.replace):
        errs.append("replace introduces raw LaTeX ($...$ or \\command) - students would see code")
    if errs:
        return GuardResult(False, errs)
    after = src.replace(edit.find, edit.replace, 1)
    if not N.parses(after):
        errs.append("edited HTML does not parse")
    if edit.field == "question" and q["questionType"] in ("scq", "mcq"):
        _, o0 = N.split_options(src)
        _, o1 = N.split_options(after)
        if len([v for v in o1.values() if v.strip()]) < len([v for v in o0.values() if v.strip()]):
            errs.append("edit removes or blanks an option")
    return GuardResult(not errs, errs, edit.find, edit.replace, N.to_text(src), N.to_text(after))


# ------------------------------------------------------------------ routing

@dataclass
class RouteDecision:
    route: str
    edit: Edit | None
    reasons: list[str]


def _option_value(text: str) -> float | None:
    """'1 : 1' -> 1.0, '9:16' -> 0.5625, '40 m/s' -> 40.0"""
    t = (text or "").replace(" ", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?):(-?\d+(?:\.\d+)?)", t)
    if m and float(m.group(2)) != 0:
        return float(m.group(1)) / float(m.group(2))
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group()) if m else None


def option_restore_check(q: dict, edit: Edit | None, solves: dict | None) -> list[str]:
    """option_repair may only RESTORE the keyed option, with content the blind solvers computed.
    A missing/blank distractor is authored content -> never auto (SPEC §3). Returns blocking reasons."""
    if edit is None or edit.field != "question":
        return ["no restorable option edit"]
    b = N.body(q)
    _, o0 = N.split_options(b.get("question", ""))
    _, o1 = N.split_options(apply_edit(q, edit)[q["questionType"]]["question"])
    touched = [L for L in o1 if o0.get(L, "") != o1[L]]
    key, _ = N.normalize_answer(q["questionType"], b.get("answer"))
    keyed = key if isinstance(key, list) else [key]
    if len(touched) != 1 or touched[0] not in keyed:
        return [f"edit writes option(s) {touched} but only the keyed option {keyed} may be restored; "
                "a missing distractor is authored content"]
    L = touched[0]
    val = _option_value(o1[L])
    reasons = []
    solves = solves or {}
    nums = [s.get("numeric_value") for s in solves.values() if s.get("numeric_value") is not None]
    if val is None or not any(abs(n - val) <= 0.02 * max(1.0, abs(val)) for n in nums):
        reasons.append(f"restored option ({L}) value not reproduced by any blind solver")
    for name, s in solves.items():
        picked = re.findall(r"\b([A-D])\b", str(s.get("final_answer", "")).upper())
        if picked and picked[0] != L and o0.get(picked[0], "").strip():
            reasons.append(f"solver {name} picked a different existing option ({picked[0]})")
    return reasons


def route(*, q: dict, verdict: str, repair: str | None, edit: Edit | None, confidence: float,
          injection_in_group: bool, solver_agreement: dict, solves: dict | None = None) -> RouteDecision:
    """SPEC §3. `solver_agreement` = {"agree": bool, "answer": str|None, "matches_key": bool, "numeric_ok": bool|None}."""
    if verdict != "defect":
        return RouteDecision("no_change", None, [f"verdict {verdict} is not a defect"])
    if not repair or not taxonomy.is_repair(repair):
        return RouteDecision("faculty_review", None, ["defect without a valid repair"])
    if not taxonomy.repair_is_auto(repair):
        return RouteDecision("faculty_review", None, [f"{repair} is auto:false in taxonomy — faculty must author/approve"])

    reasons: list[str] = []
    g = check_edit(q, repair, edit) if edit is not None else GuardResult(False, ["no edit proposed"])
    if not g.ok:
        reasons += [f"guard: {e}" for e in g.errors]
        edit = None  # never surface an edit that failed the guard
    if confidence < AUTO_APPLY_MIN_CONFIDENCE:
        reasons.append(f"confidence {confidence:.2f} < {AUTO_APPLY_MIN_CONFIDENCE}")
    if injection_in_group:
        reasons.append("an injection-flagged report targets this question")

    subject = (q.get("subject") or "").lower()
    if repair == "answer_key" or (edit is not None and edit.field == "answer"):
        if subject not in COMPUTATIONAL_SUBJECTS:
            reasons.append(f"answer-key change in {q.get('subject')} (conceptual) needs faculty")
        if not solver_agreement.get("agree"):
            reasons.append("blind solvers do not agree with each other")
        elif edit is not None and edit.field == "answer" and not _same_answer(q, solver_agreement.get("answer"), edit.replace):
            # malformed-key repairs (e.g. ["", "B"] -> ["B"]) must also match the solvers
            reasons.append("new key does not match the blind solvers' answer")
        if solver_agreement.get("numeric_ok") is False:
            reasons.append("restricted evaluator did not reproduce the solvers' value")
    if repair == "option_repair":
        blockers = option_restore_check(q, edit, solves)
        if blockers:
            reasons += blockers
            if any("authored content" in b for b in blockers):
                edit = None  # never even suggest invented options
        
    if repair in ("solution_fix", "solution_missing"):
        if not solver_agreement.get("agree") or not solver_agreement.get("matches_key"):
            reasons.append("solvers do not confirm the keyed answer the solution must end at")

    if reasons:
        return RouteDecision("faculty_review", edit, reasons)
    return RouteDecision("auto_apply", edit, ["all auto-apply conditions passed"])


def _same_answer(q: dict, solver_ans: str | None, new_ans_str: str) -> bool:
    if solver_ans is None:
        return False
    qtype = q["questionType"]
    if qtype == "mcq":
        try:
            new = sorted(json.loads(new_ans_str))
        except json.JSONDecodeError:
            return False
        sol, _ = N.normalize_answer("mcq", [solver_ans])
        return sol == new
    if qtype == "integerQuestion":
        try:
            return abs(float(solver_ans) - float(new_ans_str)) < 1e-6
        except ValueError:
            return False
    return solver_ans.strip().upper() == new_ans_str.strip().upper()
