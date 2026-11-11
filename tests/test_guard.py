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


# ---------------- option_repair: restore keyed option only (regression: real run invented "(D) 40 m/s")


def _r009_invented_edit(q):
    from app import normalize as N
    html = N.body(q)["question"]
    tail = html[html.rindex("(C)"):]
    return E("question", tail, tail.replace("</h3>", "<br/>(D) 40 m/s</h3>"))


def test_option_repair_invented_distractor_never_auto(qof):
    q = qof("R009")
    edit = _r009_invented_edit(q)
    assert G.check_edit(q, "option_repair", edit).ok  # structurally fine...
    solves = {"A": {"final_answer": "C", "numeric_value": 10.0}, "B": {"final_answer": "C", "numeric_value": 10.0}}
    r = G.route(q=q, verdict="defect", repair="option_repair", edit=edit, confidence=1.0, injection_in_group=False,
                solver_agreement={"agree": True, "answer": "C", "matches_key": True, "numeric_ok": True}, solves=solves)
    assert r.route == "faculty_review" and r.edit is None  # ...but authored content: never auto, never suggested
    assert any("authored content" in x for x in r.reasons)


def test_option_repair_restores_keyed_blank_when_solvers_computed_it(qof):
    q = qof("R011")
    edit = E("question", "(C) <br />", "(C) 1 : 1<br />")
    solves = {"A": {"final_answer": "C", "numeric_value": None},  # real run: A picked the blank C
              "B": {"final_answer": "None of these", "numeric_value": 1.0}}  # real run: B computed 1:1
    r = G.route(q=q, verdict="defect", repair="option_repair", edit=edit, confidence=1.0, injection_in_group=False,
                solver_agreement={"agree": False, "answer": None, "matches_key": False}, solves=solves)
    assert r.route == "auto_apply", r.reasons


def test_option_repair_wrong_value_blocked(qof):
    q = qof("R011")
    r = G.route(q=q, verdict="defect", repair="option_repair", edit=E("question", "(C) <br />", "(C) 4 : 3<br />"),
                confidence=1.0, injection_in_group=False, solver_agreement={},
                solves={"A": {"final_answer": "C", "numeric_value": 1.0}, "B": {"final_answer": "C", "numeric_value": 1.0}})
    assert r.route == "faculty_review"


def test_syllabus_claim_flag(qof, reps):
    from app import precheck as P
    assert "syllabus_claim" in {f.code for f in P.check_report(reps["R026"], qof("R026"))}
    assert "syllabus_claim" not in {f.code for f in P.check_report(reps["R042"], qof("R042"))}


def test_edit_may_not_introduce_latex(qof):
    # regression: the real run proposed "$K = \frac{h^2}{2m\lambda^2}$" as a solution_fix for R018
    g = G.check_edit(qof("R016"), "solution_fix", E("solution", "a = 40 cm", r"$a = \sqrt{400}$ = 20 cm"))
    assert not g.ok and any("LaTeX" in e for e in g.errors)
    assert not G.check_faculty_edit(qof("R016"), E("solution", "a = 40 cm", "$a=20$ cm")).ok
    # removing LaTeX (markup_leak) is still allowed
    assert G.check_edit(qof("R014"), "markup_leak", E("question", r"\frac{7}{8}", "7/8")).ok
