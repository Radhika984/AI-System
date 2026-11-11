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
