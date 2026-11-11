from app import solver as S


def solve(ans, val=None, expr=None):
    rec = {"final_answer": ans, "numeric_value": val, "expression": expr}
    rec["numeric_check"] = S.numeric_check(rec)
    return rec


def test_r005_intermediate_expression_tolerated_when_other_solver_reproduces(qof):
    # Real pilot case: solver A's expression computed flux (0.5) instead of n (1).
    a = S.agreement(qof("R005"), {"A": solve("1", 1.0, "(1/2)*(1/2)+(1/8)*2"), "B": solve("1", 1.0, "(1/2*1/2+1/8*2)*2")})
    assert a["agree"] and a["answer"] == "1" and not a["matches_key"] and a["numeric_ok"] is True


def test_arithmetic_never_reproduced_blocks():
    q = {"questionType": "integerQuestion", "integerQuestion": {"answer": "2", "question": ""}}
    a = S.agreement(q, {"A": solve("1", 1.0, "0.5"), "B": solve("1", 1.0, "3")})
    assert a["agree"] and a["numeric_ok"] is False


def test_unsafe_expression_is_unknown_not_evidence():
    q = {"questionType": "integerQuestion", "integerQuestion": {"answer": "2", "question": ""}}
    a = S.agreement(q, {"A": solve("1", 1.0, "q/eps"), "B": solve("1", 1.0, None)})
    assert a["numeric_ok"] is None


def test_scq_letters_and_disagreement(qof):
    a = S.agreement(qof("R004"), {"A": solve("(D) 4800 N/m^2"), "B": solve("B")})
    assert not a["agree"] and a["answers"] == {"A": "D", "B": "B"}


def test_mcq_sets(qof):
    a = S.agreement(qof("R020"), {"A": solve("A,B,D"), "B": solve("D, A, B")})
    assert a["agree"] and a["answer"] == "A,B,D" and a["matches_key"]


def test_solver_view_is_blind(qof):
    from app import normalize as N
    from app.llm import prompts as P
    q = qof("R004")
    u = P.solver_user(N.question_view(q))
    assert "4800 N / m" not in u.split("OPTIONS")[0]  # solution value not in stem section
    assert "solution" not in u.lower() and "answer key" not in u.lower()


# ---------------- SPEC §3 rule 5 (solver disagreement) - pipeline.solvers_dispute
from app.pipeline import solvers_dispute  # noqa: E402


def test_rule5_definite_disagreement_counts_for_any_verdict():
    agree = {"answers": {"A": "A", "B": "C"}}
    assert solvers_dispute(agree, {"A": {}, "B": {}}, "no_error", None) == "A=A, B=C"
    assert solvers_dispute(agree, {"A": {}, "B": {}}, "defect", "wrong_chapter") == "A=A, B=C"


def test_rule5_no_answer_is_abstention():
    assert solvers_dispute({"answers": {"A": "C", "B": None}}, {"A": {}, "B": {}}, "defect", "option_repair") is None


def test_rule5_missing_content_report_is_abstention_only_for_missing_content_defects():
    agree = {"answers": {"A": "50", "B": "0"}}
    solves = {"A": {"problems_noticed": ["Missing edge length; assumed 10 cm"]},
              "B": {"problems_noticed": ["Missing initial volume of the cube"]}}
    assert solvers_dispute(agree, solves, "defect", "stem_data") is None      # R006: the failure IS the defect
    assert solvers_dispute(agree, solves, "no_error", None) == "A=50, B=0"     # otherwise it is a real dispute


def test_rule5_agreement_is_not_dispute():
    assert solvers_dispute({"answers": {"A": "B", "B": "B"}}, {"A": {}, "B": {}}, "no_error", None) is None


def test_rule5_respects_numeric_tolerance():
    # R033: 3113 vs 3112.99 are the same answer within solver.agreement's 1% tolerance
    assert solvers_dispute({"agree": True, "answers": {"A": "3113", "B": "3112.99"}}, {"A": {}, "B": {}}, "no_error", None) is None


# ---------------- student replies never promise uncommitted features (R039)
def test_reply_promise_guard_and_templates():
    from app.pipeline import _PROMISE, FALLBACK_REPLY
    assert _PROMISE.search("We are working on adding support for other languages in the future.")
    assert _PROMISE.search("Hindi will be added soon.")
    assert not _PROMISE.search("The key was wrong; it's (D). Fixed now, thanks.")
    for k, t in FALLBACK_REPLY.items():  # templates must obey the same rule
        assert not _PROMISE.search(t), k
