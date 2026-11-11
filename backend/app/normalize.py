"""Read-only access to the original data + HTML/MathML normalisation.

* Content is always read through q[q["questionType"]].
* HTML is parsed with lxml.html (tolerates the unbalanced <span>s in production data).
* MathML is linearised into plain text ("(a)/(b)", "x^(2)", "sqrt(..)") so options can be
  extracted and the LLM sees compact text; the raw HTML is kept for surgical edits.
"""
from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from typing import Any

from lxml import html as LH

from . import config

LETTERS = ["A", "B", "C", "D"]


# ---------------------------------------------------------------- loading

@lru_cache(maxsize=1)
def _questions_raw() -> tuple[dict, ...]:
    return tuple(json.loads((config.DATA_DIR / "questions.json").read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def _reports_raw() -> tuple[dict, ...]:
    return tuple(json.loads((config.DATA_DIR / "reports.json").read_text(encoding="utf-8")))


def questions() -> list[dict]:
    """Deep copies — callers can never mutate the loaded originals."""
    return [copy.deepcopy(q) for q in _questions_raw()]


def reports() -> list[dict]:
    return [copy.deepcopy(r) for r in _reports_raw()]


def questions_by_id() -> dict[str, dict]:
    return {q["_id"]: q for q in questions()}


def body(q: dict) -> dict:
    return q.get(q["questionType"]) or {}


# ---------------------------------------------------------------- HTML -> text

_BLOCK = {"br", "p", "h1", "h2", "h3", "h4", "div", "li", "tr", "mspace"}


def _local(tag: Any) -> str:
    return tag.split("}")[-1].lower() if isinstance(tag, str) else ""


def _m(el) -> str:
    tag = _local(el.tag)
    kids = [c for c in el if isinstance(c.tag, str)]
    if tag == "mfrac" and len(kids) == 2:
        return f"({_m(kids[0]).strip()})/({_m(kids[1]).strip()})"
    if tag == "msup" and len(kids) == 2:
        return f"{_m(kids[0]).strip()}^({_m(kids[1]).strip()})"
    if tag == "msub" and len(kids) == 2:
        return f"{_m(kids[0]).strip()}_{_m(kids[1]).strip()}"
    if tag == "msubsup" and len(kids) == 3:
        return f"{_m(kids[0]).strip()}_{_m(kids[1]).strip()}^({_m(kids[2]).strip()})"
    if tag == "msqrt":
        return "sqrt(" + "".join(_m(k) for k in kids).strip() + ")"
    if tag == "mroot" and len(kids) == 2:
        return f"root{_m(kids[1]).strip()}({_m(kids[0]).strip()})"
    if tag == "sup":
        return "^(" + (el.text_content() or "").strip() + ")"
    if tag == "img":
        return " [image] "
    s = el.text or ""
    for k in el:
        if isinstance(k.tag, str):
            s += _m(k)
        s += k.tail or ""
    if tag in _BLOCK:
        s = "\n" + s
    return s


def to_text(html_str: str | None) -> str:
    if not html_str:
        return ""
    root = LH.fromstring(f"<div>{html_str}</div>")
    t = _m(root)
    t = t.replace(" ", " ").replace("​", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def parses(html_str: str) -> bool:
    try:
        LH.fromstring(f"<div>{html_str}</div>")
        return True
    except Exception:  # noqa: BLE001 - any parser failure means "does not parse"
        return False


# ---------------------------------------------------------------- options

_MARK = re.compile(r"\(([A-D])\)")


def split_options(question_html: str) -> tuple[str, dict[str, str]]:
    """Return (stem_text, {letter: option_text}).

    Options are the LAST in-order run of (A),(B),(C),(D) markers, so stems like
    "Assertion (A): ..." are not mistaken for options.
    """
    text = to_text(question_html)
    marks = [(m.group(1), m.start(), m.end()) for m in _MARK.finditer(text)]
    best: list[tuple[str, int, int]] = []
    for i, (letter, _, _) in enumerate(marks):
        if letter != "A":
            continue
        chain = [marks[i]]
        expect = 1
        for nxt in marks[i + 1:]:
            if expect < 4 and nxt[0] == LETTERS[expect]:
                chain.append(nxt)
                expect += 1
        if len(chain) >= 2:
            best = chain  # keep the last qualifying chain
    if not best:
        return text, {}
    stem = text[: best[0][1]].strip()
    opts: dict[str, str] = {}
    for j, (letter, _, end) in enumerate(best):
        stop = best[j + 1][1] if j + 1 < len(best) else len(text)
        opts[letter] = re.sub(r"\s+", " ", text[end:stop]).strip()
    return stem, opts


# ---------------------------------------------------------------- answers

def answer_to_str(ans: Any) -> str:
    """Canonical string form used in edit.find / edit.replace (SPEC §2)."""
    if isinstance(ans, list):
        return json.dumps(ans, ensure_ascii=False)
    return str(ans)


def normalize_answer(qtype: str, ans: Any) -> tuple[Any, list[str]]:
    """Return (normalised_answer, problems). Never mutates input."""
    problems: list[str] = []
    if qtype == "mcq":
        if not isinstance(ans, list):
            problems.append("mcq answer is not a list")
            ans = [ans]
        letters: list[str] = []
        for item in ans:
            s = str(item).strip()
            if s == "":
                problems.append("empty string entry in mcq answer list")
                continue
            parts = [p.strip().upper() for p in re.split(r"[,\s]+", s) if p.strip()]
            if len(parts) > 1:
                problems.append(f"several options packed into one entry: {s!r}")
            for p in parts:
                if p not in LETTERS:
                    problems.append(f"invalid option letter {p!r}")
                elif p not in letters:
                    letters.append(p)
        return sorted(letters), problems
    if qtype == "scq":
        s = str(ans).strip().upper()
        if s not in LETTERS:
            problems.append(f"scq answer {ans!r} is not a single option letter")
        return s, problems
    if qtype == "integerQuestion":
        s = str(ans).strip()
        if not re.fullmatch(r"-?\d+(\.\d+)?", s):
            problems.append(f"integer answer {ans!r} is not numeric")
        return s, problems
    problems.append(f"unknown questionType {qtype!r}")
    return ans, problems


def question_view(q: dict) -> dict:
    """Compact, LLM-friendly view of a question (no student data)."""
    b = body(q)
    stem, opts = split_options(b.get("question", ""))
    return {
        "_id": q["_id"],
        "type": q["questionType"],
        "subject": q.get("subject"),
        "chapter": q.get("chapter"),
        "stem": stem,
        "options": opts,
        "has_images": bool(b.get("quesImages")),
    }
