"""V1 regression tests: auto:true repairs may not carry a meaning-changing edit.

Attacks from the Safety & Trust audit must be blocked; legitimate corrections must still pass.
Synthetic questions are in-memory copies only - data/ is never written."""
import copy
import json

import pytest

from app import guard as G
from app import normalize as N
from app.models import Edit

AGREE = {"agree": True, "answer": None, "matches_key": True, "numeric_ok": True}


def E(find, replace, field="question"):
    return Edit(field=field, find=find, replace=replace)


def synthetic(qof, rid, question_html=None, solution_html=None):
    q = copy.deepcopy(qof(rid))
    b = N.body(q)
    if question_html is not None:
        b["question"] = question_html
    if solution_html is not None:
        b["solution"] = solution_html
    return q


def auto_route(q, repair, edit):
    return G.route(q=q, verdict="defect", repair=repair, edit=edit, confidence=1.0,
                   injection_in_group=False, solver_agreement=AGREE)


# ---------------------------------------------------------------- the four audit attacks
ATTACKS = [
    ("R035", "noise", E("not antagonistic", "antagonistic"), "noise"),
    ("R040", "spelling", E("Golden rice", "Golden wheat"), "rewrites a word"),
    ("R013", "exam_reference", E("(NEET 2019) Which of the following", "Which"), "more than the exam reference"),
    ("R024", "answer_form", E("equal to", "equal to (the answer is 25)"), "unit or rounding"),
]


@pytest.mark.parametrize("rid,repair,edit,needle", ATTACKS)
def test_audit_attacks_blocked_by_guard_and_route(qof, rid, repair, edit, needle):
    q = qof(rid)
    g = G.check_edit(q, repair, edit)
    assert not g.ok and any(needle in e for e in g.errors), g.errors
    r = auto_route(q, repair, edit)  # confidence 1.0, all other conditions satisfied
    assert r.route == "faculty_review" and r.edit is None


# ---------------------------------------------------------------- more bypass attempts
MORE = [
    ("R035", "spelling", E("not antagonistic", "now antagonistic"), "meaning-critical"),        # negation flip, 1 letter
    ("R022", "spelling", E("Choroid plexux", "Choroid"), "number of words"),                    # word dropped
    ("R024", "answer_form", E("equal to", "equal to (in C)"), "unit or rounding"),               # option letter as "unit"
    ("R024", "answer_form", E("equal to", "equal to (in N, 25)"), "unit or rounding"),           # stray number
    ("R024", "answer_form", E("equal to", "equal to (in N; option B)"), "unit or rounding"),     # option text
]


@pytest.mark.parametrize("rid,repair,edit,needle", MORE)
def test_more_semantic_bypasses_blocked(qof, rid, repair, edit, needle):
    g = G.check_edit(qof(rid), repair, edit)
    assert not g.ok and any(needle in e for e in g.errors), g.errors


def test_noise_cannot_delete_ordinary_words(qof):
    q = synthetic(qof, "R022", question_html="<h3>Q.12 Which part is not a gland? (A) X<br />(B) Y<br />(C) Z<br />(D) W</h3>")
    assert not G.check_edit(q, "noise", E("Q.12 Which part is not", "Which part is")).ok


def test_markup_leak_cannot_change_surrounding_words(qof):
    g = G.check_edit(qof("R014"), "markup_leak", E(r"\frac{7}{8} th of its original mass to disintegrate",
                                                   "7/8 th of its original mass to remain"))
    assert not g.ok and any("words" in e for e in g.errors)


def test_notation_cannot_change_words_or_numbers(qof):
    q = synthetic(qof, "R027", question_html="<h3>coefficient 5.7 x 10-5 per degree<br />(A) a<br />(B) b<br />(C) c<br />(D) d</h3>")
    assert G.check_edit(q, "notation", E("10-5 per", "10<sup>-5</sup> per")).ok                 # legit: exponent restored
    assert not G.check_edit(q, "notation", E("10-5 per", "10<sup>-6</sup> per")).ok              # number changed
    assert not G.check_edit(q, "notation", E("10-5 per degree", "10<sup>-5</sup> per kelvin")).ok  # word changed


def test_stem_data_is_insert_only(qof):
    q = qof("R007")
    assert G.check_edit(q, "stem_data", E("and an inductance are", "and an inductance of 95.5 mH are")).ok
    g = G.check_edit(q, "stem_data", E("A resistance of 40 ohm", "A resistance of 95.5 ohm"))
    assert not g.ok and any("only add" in e for e in g.errors)


def test_solution_fix_cannot_invent_numbers(qof):
    q = qof("R016")
    assert G.check_edit(q, "solution_fix", E("a = 40 cm", "a = 20 cm", "solution")).ok          # 20 is the key
    g = G.check_edit(q, "solution_fix", E("a = 40 cm", "a = 37 cm", "solution"))
    assert not g.ok and any("introduces number" in e for e in g.errors)


def test_type_mismatch_question_text_edit_never_auto(qof):
    q = qof("R021")
    e = E("A sample", "One sample")
    r = G.route(q=q, verdict="defect", repair="type_mismatch", edit=e, confidence=1.0, injection_in_group=False,
                solver_agreement={"agree": True, "answer": "B", "matches_key": True, "numeric_ok": True})
    assert r.route == "faculty_review"


def test_type_mismatch_type_change_must_match_solvers(qof):
    q = qof("R021")  # mcq; solvers' agreed answer "B" implies scq
    ok = G.route(q=q, verdict="defect", repair="type_mismatch", edit=Edit(field="questionType", find="mcq", replace="scq"),
                 confidence=1.0, injection_in_group=False, solver_agreement={"agree": True, "answer": "B", "matches_key": True})
    bad = G.route(q=q, verdict="defect", repair="type_mismatch",
                  edit=Edit(field="questionType", find="mcq", replace="integerQuestion"), confidence=1.0,
                  injection_in_group=False, solver_agreement={"agree": True, "answer": "B", "matches_key": True})
    assert ok.route == "auto_apply" and bad.route == "faculty_review"


# ---------------------------------------------------------------- legitimate corrections still pass
LEGIT = [
    ("R012", "spelling", E("Epithellial tisue", "Epithelial tissue")),
    ("R022", "spelling", E("Choroid plexux", "Choroid plexus")),
    ("R040", "spelling", E("Canolla", "Canola")),
    ("R025", "spelling", E("hemispherial", "hemispherical")),
    ("R013", "exam_reference", E("(NEET 2019) ", "")),
    ("R024", "answer_form", E("equal to", "equal to (in N)")),
    ("R024", "answer_form", E("equal to", "equal to (in m/s^2, rounded to the nearest integer)")),
    ("R024", "answer_form", E("equal to", "equal to (correct to two decimal places)")),
    ("R014", "markup_leak", E(r"\frac{7}{8}", "7/8")),
]


@pytest.mark.parametrize("rid,repair,edit", LEGIT)
def test_legitimate_corrections_still_pass(qof, rid, repair, edit):
    g = G.check_edit(qof(rid), repair, edit)
    assert g.ok, g.errors
    assert auto_route(qof(rid), repair, edit).route == "auto_apply"


@pytest.mark.parametrize("html,find,replace", [
    ("<h3>Q.12 Which tissue lines the gut?<br />(A) a<br />(B) b<br />(C) c<br />(D) d</h3>", "Q.12 Which", "Which"),
    ("<h3>Which tissue lines the gut? Space for rough work<br />(A) a<br />(B) b<br />(C) c<br />(D) d</h3>",
     "gut? Space for rough work", "gut?"),
    ("<h3>Which tissue lines the gut? (Source: Allen module)<br />(A) a<br />(B) b<br />(C) c<br />(D) d</h3>",
     "gut? (Source: Allen module)", "gut?"),
])
def test_legitimate_noise_removal_passes(qof, html, find, replace):
    q = synthetic(qof, "R012", question_html=html)
    g = G.check_edit(q, "noise", E(find, replace))
    assert g.ok, g.errors


def test_all_committed_auto_applies_still_pass(qof):
    from app import config
    rows = json.loads((config.ROOT / "results.json").read_text(encoding="utf-8"))
    autos = [r for r in rows if r["route"] == "auto_apply"]
    assert len(autos) == 16
    for r in autos:
        g = G.check_edit(qof(r["reportId"]), r["repair"], Edit(**r["edit"]))
        assert g.ok, (r["reportId"], g.errors)
