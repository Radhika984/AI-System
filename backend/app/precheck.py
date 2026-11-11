"""Deterministic checks — run before any LLM call, cost nothing, and can't be
talked out of their findings by a student comment.

Question-level flags describe the stored record. Report-level flags describe
the comment (treated purely as data).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from . import normalize as N


@dataclass
class Flag:
    code: str
    detail: str

    def as_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail}


@dataclass
class QuestionCheck:
    question_id: str
    flags: list[Flag] = field(default_factory=list)
    normalized_answer: object = None
    options: dict = field(default_factory=dict)

    def has(self, code: str) -> bool:
        return any(f.code == code for f in self.flags)

    def get(self, code: str) -> Flag | None:
        return next((f for f in self.flags if f.code == code), None)


# --------------------------------------------------------------- question checks

_LATEX = re.compile(r"\\(frac|sqrt|times|alpha|beta|theta|lambda|mu|pi|AA|left|right|cdot|text|mathrm|circ)\b|\$[^$]+\$")
_EXAM = re.compile(r"\(\s*(?:NEET|JEE|AIIMS|MHT[- ]?CET|MHCET|CBSE|BITSAT|KCET|AIPMT)[^)]{0,30}\d{4}[^)]{0,20}\)", re.I)
_FIGURE = re.compile(r"\b(shown in (?:the )?(?:figure|diagram|fig)|as shown|given figure|figure (?:below|above|shows)|in the (?:figure|diagram))\b", re.I)


def check_question(q: dict) -> QuestionCheck:
    b = N.body(q)
    qtype = q["questionType"]
    qc = QuestionCheck(q["_id"])
    qhtml, shtml = b.get("question", "") or "", b.get("solution", "") or ""
    qtext, stext = N.to_text(qhtml), N.to_text(shtml)

    norm, problems = N.normalize_answer(qtype, b.get("answer"))
    qc.normalized_answer = norm
    for p in problems:
        qc.flags.append(Flag("answer_malformed", p))

    if qtype in ("scq", "mcq"):
        _, opts = N.split_options(qhtml)
        qc.options = opts
        missing = [L for L in N.LETTERS if L not in opts]
        if missing:
            qc.flags.append(Flag("option_missing", f"option marker(s) {missing} absent from question HTML"))
        for L, t in opts.items():
            if not t.strip():
                qc.flags.append(Flag("option_blank", f"option ({L}) has no content"))
        seen: dict[str, str] = {}
        for L, t in opts.items():
            key = re.sub(r"\s+", "", t).lower()
            if key and key in seen:
                qc.flags.append(Flag("options_identical", f"({seen[key]}) and ({L}) are both {t!r}"))
            else:
                seen[key] = L
        keyed = norm if isinstance(norm, list) else [norm]
        for L in keyed:
            if L in N.LETTERS and L not in opts:
                qc.flags.append(Flag("key_points_to_missing_option", f"key {L} but option ({L}) not present"))
            elif L in opts and not opts[L].strip():
                qc.flags.append(Flag("key_points_to_blank_option", f"key {L} but option ({L}) is blank"))

    if _FIGURE.search(qtext) and not b.get("quesImages") and "<img" not in qhtml.lower():
        qc.flags.append(Flag("figure_missing", "text refers to a figure but quesImages is empty and no <img>"))

    for name, txt in (("question", qtext), ("solution", stext)):
        m = _LATEX.search(txt)
        if m:
            qc.flags.append(Flag("raw_latex", f"{name} shows raw LaTeX {m.group(0)!r}"))
    m = _EXAM.search(qtext)
    if m:
        qc.flags.append(Flag("exam_reference", f"question contains {m.group(0)!r}"))

    if not stext.strip():
        qc.flags.append(Flag("solution_missing", "solution field is empty"))
    return qc


# --------------------------------------------------------------- report checks

_INJECTION = [
    r"ignore (?:all |any )?(?:previous|prior|above) (?:instructions|prompts?)",
    r"\byou are (?:now )?(?:the |an? )?(?:admin|system|developer|assistant|bot)\b",
    r"\bsystem prompt\b", r"\bdisregard\b.*\binstructions?\b",
    r"\bmark (?:this|the) (?:report|question) as\b", r"\b(?:change|set) the (?:answer|key) to\b",
    r"\bact as\b", r"\bjailbreak\b", r"</?(?:system|instruction)s?>",
]
_INJ = re.compile("|".join(_INJECTION), re.I)
_LANG = re.compile(r"\b(hindi|marathi|tamil|telugu|bengali|bangla|gujarati|kannada|malayalam|odia|urdu|language|bhasha)\b", re.I)
_APP = re.compile(r"(clicked .* (?:saved|recorded|selected)|saved (?:as|wrong)|keyboard|\blag\b|crash|app (?:is )?(?:hang|freez)|not submitting)", re.I)
_DISPLAY = re.compile(r"(cut (?:off|on)|on my (?:phone|screen)|not (?:loading|rendering)|takes? (?:forever|long) to load|slow|overlap|font|blurry|zoom)", re.I)
_KEYBOARD_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]


def is_gibberish(comment: str) -> bool:
    c = (comment or "").strip().lower()
    if not c:
        return True
    letters = re.sub(r"[^a-z]", "", c)
    if not letters:
        return not re.search(r"\d", c)  # pure punctuation
    if " " not in c and len(letters) >= 4:
        for row in _KEYBOARD_ROWS:
            if letters in row or all(ch in row for ch in letters):
                return True
        if not re.search(r"[aeiou]", letters):
            return True
    return False


def check_report(r: dict, q: dict | None) -> list[Flag]:
    flags: list[Flag] = []
    c = r.get("comment") or ""
    if q is None:
        return [Flag("unknown_question", f"questionId {r.get('questionId')} not in questions.json")]
    if _INJ.search(c):
        flags.append(Flag("injection", "comment contains instruction-like text aimed at the system; treated as data only"))
    if is_gibberish(c):
        flags.append(Flag("gibberish", f"comment {c!r} carries no readable claim"))
    if _LANG.search(c):
        flags.append(Flag("language_request", "comment asks for another language"))
    if _APP.search(c):
        flags.append(Flag("app_behaviour", "comment describes platform behaviour"))
    if _DISPLAY.search(c):
        flags.append(Flag("display_hint", "comment describes rendering/loading"))

    fixed = already_fixed_evidence(r, q)
    if fixed:
        flags.append(Flag("already_fixed", fixed))
    return flags


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def already_fixed_evidence(r: dict, q: dict) -> str | None:
    """An errorHistory edit made AFTER the report, whose 'old' text is no longer in the record."""
    reported = _ts(r["reportedAt"])
    b = N.body(q)
    live = (N.to_text(b.get("question", "")) + "\n" + N.to_text(b.get("solution", ""))).lower()
    for h in q.get("errorHistory") or []:
        at = h.get("at")
        if not at or _ts(at) <= reported:
            continue
        note = h.get("note", "")
        olds = re.findall(r"'([^']+)'\s*->\s*'([^']+)'", note)
        gone = [o for o, _ in olds if not re.search(rf"\b{re.escape(o.lower())}\b", live)]
        present_new = [n for _, n in olds if n.lower() in live]
        if olds and len(gone) == len(olds) and present_new:
            return (f"errorHistory {at} ({h.get('actor')}): {note}. Reported text no longer present; "
                    f"corrected text present. Report was filed {r['reportedAt']}.")
        if not olds:
            return f"errorHistory {at} ({h.get('actor')}): {h.get('type')} — edited after the report ({r['reportedAt']}); verify."
    return None
