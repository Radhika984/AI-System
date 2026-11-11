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


def test_rule5_skips_when_solvers_agree():
    assert solvers_dispute({"agree": True, "answers": {"A": "8", "B": "8"}}, {"A": {}, "B": {}}, "no_error", None) is None


# ---------------- integer answers are exact (regression: R033 solver B answered 3114, key 3113)
def test_integer_agreement_is_exact_r033(qof):
    # Real cached solves for R033: A "3113" (expression uses round() -> refused), B "3114" with
    # expression 10*6*7.203**2 = 3112.99 (which rounds to 3113, not to B's claimed 3114).
    a_rec = solve("3113", 3113.0, "10 * round(6 * 7.203**2, 1)")
    b_rec = {"final_answer": "3114", "numeric_value": 3114.0, "expression": "10 * 6 * 7.203**2"}
    b_rec["numeric_check"] = S.numeric_check(b_rec, "integerQuestion")
    assert b_rec["numeric_check"]["status"] == "mismatch"          # 3112.99 does not round to 3114
    a = S.agreement(qof("R033"), {"A": a_rec, "B": b_rec})
    assert not a["agree"] and a["answers"] == {"A": "3113", "B": "3114"}
    assert solvers_dispute(a, {"A": a_rec, "B": b_rec}, "no_error", None) == "A=3113, B=3114"


def test_integer_tolerances_only_absorb_float_noise():
    assert S.same("integerQuestion", 8, 8.0) and S.same("integerQuestion", 0.08, 0.08000000001)
    assert not S.same("integerQuestion", 100, 101) and not S.same("integerQuestion", 3113, 3114)
    ok = lambda claim, expr: S.numeric_check({"final_answer": claim, "numeric_value": float(claim), "expression": expr},
                                             "integerQuestion")["status"]
    assert ok("3113", "6*7.203**2*10") == "match"        # 3112.99 rounds to 3113
    assert ok("3114", "6*7.203**2*10") == "mismatch"
    assert ok("8", "(1/5e-3)*(2e-3*0.5-1.5e-3*0.4)*100") == "match"
    assert ok("1", "(1/2*1/2+1/8*2)*2") == "match"         # R005 solver B
    assert ok("0.08", "0.0812") == "match"                 # rounds to 0.08 at the claimed 2 d.p.
    assert ok("0.08", "0.0862") == "mismatch"              # rounds to 0.09: claimed precision is honoured
    # option questions keep the rounded-option tolerance (16.71 eV computed, option "16.8 eV")
    assert S.numeric_check({"final_answer": "B", "numeric_value": 16.8, "expression": "16.71"}, "scq")["status"] == "match"


def test_judge_packet_view_is_v1_only_for_the_packet(qof):
    b_rec = {"final_answer": "3114", "numeric_value": 3114.0, "expression": "10 * 6 * 7.203**2"}
    a_rec = {"final_answer": "3113", "numeric_value": 3113.0, "expression": None}
    pk_solves, pk_agree = S.judge_packet_view(qof("R033"), {"A": a_rec, "B": b_rec})
    assert pk_agree["agree"] is True                          # what judge-v1 was actually shown (cached input)
    assert pk_solves["B"]["numeric_check"]["status"] == "match"
    strict = {"A": {**a_rec, "numeric_check": S.numeric_check(a_rec, "integerQuestion")},
              "B": {**b_rec, "numeric_check": S.numeric_check(b_rec, "integerQuestion")}}
    assert S.agreement(qof("R033"), strict)["agree"] is False  # what routing / rule 5 use


# ---------------- SPEC §3 rule 5 scope: defects and no_error only
def test_rule5_scope_constant():
    from app.pipeline import RULE5_NON_DEFECT_VERDICTS
    assert RULE5_NON_DEFECT_VERDICTS == {"no_error"}


# ---------------- faculty-review replies: no claims that an action is underway or done
def test_pending_review_reply_removes_action_claims():
    from app.pipeline import FALLBACK_REPLY, PENDING_REVIEW_SENTENCE, _ACTION_CLAIM, pending_review_reply
    for before in ["Thank you. A teacher is restoring the missing option D to the question.",
                   "You are right. We are updating it to reflect 0.3 nm.",
                   "Thanks. The solution is being corrected.",
                   "Right. A teacher is now updating the chapter classification."]:
        after, dropped = pending_review_reply(before)
        assert dropped and after.endswith(PENDING_REVIEW_SENTENCE) and not _ACTION_CLAIM.search(after)
    same, dropped = pending_review_reply("You are right that options B and C are identical.")
    assert not dropped and same == "You are right that options B and C are identical."
    for k, t in FALLBACK_REPLY.items():
        if k != "already_fixed":  # already_fixed states a completed fix that errorHistory proves
            assert not _ACTION_CLAIM.search(t), k


# ---------------- coded verdicts carry evidence that supports them (R026)
def test_override_evidence_supports_syllabus_verdict():
    from app.pipeline import override_evidence
    ev = override_evidence("syllabus", {"agree": True, "matches_key": True, "stored_key": "B"})
    assert "outside the syllabus" in ev and "faculty" in ev and "stored key B" in ev


# ---------------- student replies never promise uncommitted features (R039)
def test_reply_promise_guard_and_templates():
    from app.pipeline import _PROMISE, FALLBACK_REPLY
    assert _PROMISE.search("We are working on adding support for other languages in the future.")
    assert _PROMISE.search("Hindi will be added soon.")
    assert not _PROMISE.search("The key was wrong; it's (D). Fixed now, thanks.")
    for k, t in FALLBACK_REPLY.items():  # templates must obey the same rule
        assert not _PROMISE.search(t), k
