import json

import pytest

from app import guard as G
from app.models import Edit


def E(field, find, replace):
    return Edit(field=field, find=find, replace=replace)


# ---------------- valid edits (must pass)
def test_valid_spelling_r022(qof):
    assert G.check_edit(qof("R022"), "spelling", E("question", "Choroid plexux", "Choroid plexus")).ok


def test_valid_exam_reference_r013(qof):
    assert G.check_edit(qof("R013"), "exam_reference", E("question", "(NEET 2019) Which", "Which")).ok


def test_valid_answer_form_r024(qof):
    g = G.check_edit(qof("R024"), "answer_form",
                     E("question", "the frictional force is equal to", "the frictional force (in N) is equal to"))
    assert not g.ok  # not additive: find is not contained verbatim in replace
    g = G.check_edit(qof("R024"), "answer_form",
                     E("question", "frictional force is equal to", "frictional force is equal to (in N)"))
    assert g.ok, g.errors


def test_valid_stem_data_r007(qof):
    g = G.check_edit(qof("R007"), "stem_data",
                     E("question", "and an inductance are", "and an inductance of 95.5 mH are"))
    assert g.ok, g.errors


def test_valid_answer_key_r004(qof):
    assert G.check_edit(qof("R004"), "answer_key", E("answer", "A", "D")).ok


def test_valid_mcq_key_r021(qof):
    g = G.check_edit(qof("R021"), "answer_key", E("answer", json.dumps(["", "B"]), json.dumps(["B"])))
    assert g.ok, g.errors


def test_valid_option_repair_r011(qof):
    g = G.check_edit(qof("R011"), "option_repair", E("question", "(C) <br />", "(C) 1 : 1<br />"))
    assert g.ok, g.errors


def test_valid_markup_leak_r014(qof):
    g = G.check_edit(qof("R014"), "markup_leak", E(
        "question", "\\frac{7}{8} th",
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><mn>7</mn><mn>8</mn></mfrac></math> th'))
    assert g.ok, g.errors


def test_dry_run_does_not_mutate(qof):
    q = qof("R022")
    before = json.dumps(q, sort_keys=True)
    G.apply_edit(q, E("question", "Choroid plexux", "Choroid plexus"))
    assert json.dumps(q, sort_keys=True) == before


# ---------------- invalid edits (must be rejected)
INVALID = [
    ("R022", "spelling", E("answer", "B", "D"), "outside the scope"),
    ("R022", "spelling", E("solution", "small intestine", "small intestines"), "exactly once"),  # appears twice
    ("R022", "spelling", E("question", "plexux-not-there", "plexus"), "exactly once"),
    ("R022", "spelling", E("question", "Choroid plexux", "Choroid plexus 2"), "digits"),
    ("R013", "exam_reference", E("question", "(NEET 2019) Which", "(JEE 2020) Which"), "delete"),
    ("R024", "answer_form", E("question", "is equal to", "equals (in N)"), "additive"),
    ("R007", "stem_data", E("question", "and an inductance are", "and an inductance of 120 mH are"), "not stated"),
    ("R004", "answer_key", E("answer", "B", "D"), "does not equal stored"),
    ("R004", "answer_key", E("answer", "A", "E"), "invalid"),
    ("R009", "answer_key", E("answer", "C", "D"), "missing/blank option"),
    ("R015", "identical_options", E("question", "(C) 0 W", "(C) 5 W"), "no editable fields"),
    ("R025", "diagram", E("question", "as shown in figure", "as shown in figure <img src=x>"), "no editable fields"),
    ("R011", "option_repair", E("question", "There are two charges", "There are three charges"), "stem"),
    ("R014", "markup_leak", E("question", "\\frac{7}{8} th", "<script>alert(1)</script>"), "script"),
    ("R022", "solution_fix", E("question", "Choroid plexux", "Choroid plexus"), "outside the scope"),
    ("R021", "answer_key", E("answer", json.dumps(["", "B"]), "B"), "JSON list"),
    ("R022", "not_a_repair", E("question", "Choroid plexux", "Choroid plexus"), "unknown repair"),
    ("R014", "markup_leak", E("question", "\\frac{7}{8} th", "9/8 th"), "numbers"),
]


@pytest.mark.parametrize("rid,repair,edit,needle", INVALID)
def test_invalid_edits_rejected(qof, rid, repair, edit, needle):
    g = G.check_edit(qof(rid), repair, edit)
    assert not g.ok
    assert any(needle in e for e in g.errors), g.errors


def test_identical_find_replace_rejected_by_schema():
    with pytest.raises(Exception):
        Edit(field="question", find="x", replace="x")


# ---------------- routing
AGREE = {"agree": True, "answer": "D", "matches_key": False, "numeric_ok": True}


def test_route_non_defect_is_no_change(qof):
    r = G.route(q=qof("R029"), verdict="no_error", repair=None, edit=None, confidence=0.9,
                injection_in_group=False, solver_agreement=AGREE)
    assert r.route == "no_change" and r.edit is None


def test_route_auto_false_is_faculty_with_null_edit(qof):
    r = G.route(q=qof("R015"), verdict="defect", repair="identical_options",
                edit=E("question", "(C) 0 W", "(C) 5 W"), confidence=0.99,
                injection_in_group=False, solver_agreement=AGREE)
    assert r.route == "faculty_review" and r.edit is None


def test_route_answer_key_auto_when_verified(qof):
    r = G.route(q=qof("R004"), verdict="defect", repair="answer_key", edit=E("answer", "A", "D"),
                confidence=0.95, injection_in_group=False, solver_agreement=AGREE)
    assert r.route == "auto_apply", r.reasons


def test_route_answer_key_needs_solver_agreement(qof):
    r = G.route(q=qof("R004"), verdict="defect", repair="answer_key", edit=E("answer", "A", "D"),
                confidence=0.95, injection_in_group=False,
                solver_agreement={"agree": False, "answer": None, "matches_key": False})
    assert r.route == "faculty_review"


def test_route_answer_key_must_match_solvers(qof):
    r = G.route(q=qof("R004"), verdict="defect", repair="answer_key", edit=E("answer", "A", "B"),
                confidence=0.95, injection_in_group=False, solver_agreement=AGREE)
    assert r.route == "faculty_review"


def test_route_biology_answer_key_goes_to_faculty(qof):
    r = G.route(q=qof("R035"), verdict="defect", repair="answer_key", edit=E("answer", "D", "A"),
                confidence=0.99, injection_in_group=False,
                solver_agreement={"agree": True, "answer": "A", "matches_key": False})
    assert r.route == "faculty_review"


def test_route_injection_never_auto(qof):
    r = G.route(q=qof("R027"), verdict="defect", repair="answer_key", edit=E("answer", "A", "C"),
                confidence=0.99, injection_in_group=True,
                solver_agreement={"agree": True, "answer": "C", "matches_key": False})
    assert r.route == "faculty_review"


def test_route_low_confidence_escalates_but_keeps_valid_suggestion(qof):
    r = G.route(q=qof("R022"), verdict="defect", repair="spelling",
                edit=E("question", "Choroid plexux", "Choroid plexus"),
                confidence=0.6, injection_in_group=False, solver_agreement=AGREE)
    assert r.route == "faculty_review" and r.edit is not None


def test_route_guard_failure_drops_edit(qof):
    r = G.route(q=qof("R022"), verdict="defect", repair="spelling",
                edit=E("question", "nope-not-present", "x"), confidence=0.99,
                injection_in_group=False, solver_agreement=AGREE)
    assert r.route == "faculty_review" and r.edit is None
