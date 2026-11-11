"""Regression tests for the Criterion B adversarial findings:
N1 unsafe one-click suggestions, N2 unbounded edit sizes, O1 unknown request fields.
All state lives in tmp dirs; data/ and the committed results.json are never written."""
import hashlib
import json
import secrets

import pytest
from fastapi.testclient import TestClient

from app import config, main, security
from app.models import EDIT_FIND_MAX, EDIT_REPLACE_MAX
from app.store import Store

Q27 = "6062ec84518e9535e120c422"   # silver rod, key A (correct)
Q21 = "68f21caf941cda588bc04365"   # malformed mcq key ["", "B"]; real solvers: A=B, B=C
Q15 = "6956d79788d7701e5617bc29"   # identical options (faculty review, no edit)
Q22 = "61ee6c9d90a1a968a168686b"   # auto-applied spelling fix
Q04 = "68e870ef42c06737d6e565c4"   # auto-applied key A -> D
DATA_SHA = "178d08f199386bdd1e94268449106f2ecf9c00b6f38d2fd4d79fb011f030641a"


def make_client(st, monkeypatch, admin=None):
    monkeypatch.setattr(main, "_store", st)
    code = secrets.token_urlsafe(12)
    monkeypatch.setenv("REVIEWER_PASSCODE", code)
    if admin:
        monkeypatch.setenv("ADMIN_RESET_TOKEN", admin)
    security.reset_rate_limits()
    return TestClient(main.app, headers={"X-Reviewer-Passcode": code})


def files(st):
    return {f: (st.state_dir / f).read_bytes() if (st.state_dir / f).exists() else b""
            for f in ("patches.json", "case_status.json", "audit.jsonl")}


def isolated(tmp_path, rows, details):
    res, det = tmp_path / "results.json", tmp_path / "details.json"
    res.write_text(json.dumps(rows), encoding="utf-8")
    det.write_text(json.dumps(details), encoding="utf-8")
    return Store(state_dir=tmp_path / "state", results_path=res, details_path=det)


def row(rid, qid, repair, edit, route="faculty_review"):
    return {"reportId": rid, "questionId": qid, "verdict": "defect", "repair": repair, "edit": edit, "route": route,
            "confidence": 1.0, "evidence": "e" * 12, "student_reply": "We've sent this to a teacher to review."}


def details(qid, rid, answers, injection=False):
    return {qid: {"injection_in_group": injection, "agreement": {"answers": answers},
                  "reports": {rid: {"flags": [{"code": "injection", "detail": "x"}] if injection else []}}}}


# ======================================================================== N1
def test_n1_exact_attack_injection_flagged_wrong_suggestion_cannot_be_approved(tmp_path, monkeypatch):
    # the exact row the audit produced: injection-flagged, AI suggests the wrong key C, both solvers said A
    st = isolated(tmp_path, [row("R027", Q27, "answer_key", {"field": "answer", "find": "A", "replace": "C"})],
                  details(Q27, "R027", {"A": "A", "B": "A"}, injection=True))
    c = make_client(st, monkeypatch)
    case = c.get(f"/api/cases/{Q27}").json()
    assert case["edit"] is None and case["diff"] is None
    w = case["suggestion_withheld"]
    assert w["proposed"]["replace"] == "C"                                   # evidence preserved
    assert any("manipulation" in r for r in w["reasons"]) and any("solver A answered A" in r for r in w["reasons"])
    r = c.post(f"/api/cases/{Q27}/actions", json={"action": "approve", "actor": "Tired faculty"})
    assert r.status_code == 200
    after = c.get(f"/api/cases/{Q27}").json()
    assert after["live_answer"] == "A" and after["patches"] == [] and after["status"] == "approved"
    assert "withheld" in c.get("/api/audit").json()[0]["note"]


def test_n1_solver_disagreement_without_injection_is_withheld_real_r021(tmp_path, monkeypatch):
    st = Store(state_dir=tmp_path / "state")                                  # committed results + details
    c = make_client(st, monkeypatch)
    case = c.get(f"/api/cases/{Q21}").json()
    assert case["edit"] is None and not case["injection_in_group"]
    assert case["suggestion_withheld"]["reasons"] == ['blind solver B answered C, not the proposed ["B"]']
    assert c.post(f"/api/cases/{Q21}/actions", json={"action": "approve"}).status_code == 200
    assert c.get(f"/api/cases/{Q21}").json()["live_answer"] == '["", "B"]'  # nothing applied


def test_n1_deliberate_faculty_correction_still_works(tmp_path, monkeypatch):
    st = Store(state_dir=tmp_path / "state")
    c = make_client(st, monkeypatch)
    r = c.post(f"/api/cases/{Q21}/actions", json={"action": "edit", "actor": "Dr. Rao", "note": "checked: tau = 1.44 min",
                                                   "edit": {"field": "answer", "find": '["", "B"]', "replace": '["B"]'}})
    assert r.status_code == 200 and r.json()["live_answer"] == '["B"]' and r.json()["status"] == "edited"
    assert c.get("/api/audit").json()[0]["action"] == "edit"


@pytest.mark.parametrize("answers,approvable", [({"A": "D", "B": "D"}, True), ({"A": "D", "B": None}, False),
                                                ({"A": "D", "B": "B"}, False), ({}, False)])
def test_n1_answer_suggestion_offered_only_when_both_solvers_confirm(tmp_path, monkeypatch, answers, approvable):
    st = isolated(tmp_path, [row("R004", Q04, "answer_key", {"field": "answer", "find": "A", "replace": "D"})],
                  details(Q04, "R004", answers))
    c = make_client(st, monkeypatch)
    case = c.get(f"/api/cases/{Q04}").json()
    assert (case["edit"] is not None) == approvable
    c.post(f"/api/cases/{Q04}/actions", json={"action": "approve"})
    assert c.get(f"/api/cases/{Q04}").json()["live_answer"] == ("D" if approvable else "A")


def test_n1_legitimate_text_suggestion_still_one_click(tmp_path, monkeypatch):
    st = isolated(tmp_path, [row("R022", Q22, "spelling", {"field": "question", "find": "Choroid plexux", "replace": "Choroid plexus"})],
                  details(Q22, "R022", {"A": "B", "B": "B"}))
    c = make_client(st, monkeypatch)
    assert c.get(f"/api/cases/{Q22}").json()["suggestion_withheld"] is None
    assert "Choroid plexus" in c.post(f"/api/cases/{Q22}/actions", json={"action": "approve"}).json()["live_question_html"]


def test_n1_auto_applied_fixes_never_withheld(tmp_path):
    st = Store(state_dir=tmp_path / "state")
    autos = [q for q, s in st.status.items() if s["state"] == "auto_applied"]
    assert len(autos) == 13 and all(st.case(q)["suggestion_withheld"] is None and st.case(q)["edit"] for q in autos)


# ======================================================================== N2
@pytest.mark.parametrize("size", [200 * 1024, 1024 * 1024, 5 * 1024 * 1024])
def test_n2_oversized_edits_rejected_before_any_state_change(tmp_path, monkeypatch, size):
    st = Store(state_dir=tmp_path / "state")
    c = make_client(st, monkeypatch)
    before = files(st)
    r = c.post(f"/api/cases/{Q15}/actions",
               json={"action": "edit", "edit": {"field": "question", "find": "(C) 0 W", "replace": "(C) " + "A" * size}})
    assert r.status_code == 413
    assert files(st) == before and "(C) 0 W" in c.get(f"/api/cases/{Q15}").json()["live_question_html"]


def test_n2_body_limit_is_independent_of_field_limits(tmp_path, monkeypatch):
    st = Store(state_dir=tmp_path / "state")
    c = make_client(st, monkeypatch)
    before = files(st)
    padded = b'{"action": "approve"' + b" " * (main.MAX_BODY_BYTES + 1) + b"}"   # valid JSON, every field tiny
    r = c.post(f"/api/cases/{Q15}/actions", content=padded, headers={"content-type": "application/json"})
    assert r.status_code == 413 and files(st) == before
    small = b'{"action": "approve"' + b" " * 1000 + b"}"
    assert c.post(f"/api/cases/{Q15}/actions", content=small, headers={"content-type": "application/json"}).status_code == 200


def test_n2_field_limits_inside_body_limit(tmp_path, monkeypatch):
    st = Store(state_dir=tmp_path / "state")
    c = make_client(st, monkeypatch)
    before = files(st)
    for e in ({"field": "question", "find": "(C) 0 W", "replace": "x" * (EDIT_REPLACE_MAX + 1)},
              {"field": "question", "find": "y" * (EDIT_FIND_MAX + 1), "replace": "z"}):
        assert c.post(f"/api/cases/{Q15}/actions", json={"action": "edit", "edit": e}).status_code == 422
    assert files(st) == before
    ok = c.post(f"/api/cases/{Q15}/actions", json={"action": "edit", "edit": {"field": "question", "find": "(C) 0 W",
                                                                                "replace": "(C) 500 W"}})
    assert ok.status_code == 200


def test_n2_reverted_patches_not_returned_to_reviewers(tmp_path, monkeypatch):
    st = Store(state_dir=tmp_path / "state")
    c = make_client(st, monkeypatch)
    assert len(c.get(f"/api/cases/{Q04}").json()["patches"]) == 1            # live auto-apply
    c.post(f"/api/cases/{Q04}/actions", json={"action": "reject"})
    case = c.get(f"/api/cases/{Q04}").json()
    assert case["patches"] == [] and case["live_answer"] == "A"
    assert [e["action"] for e in case["audit"]] == ["auto_apply", "revert_auto_apply", "reject"]  # history kept in audit
    c.post(f"/api/cases/{Q15}/actions", json={"action": "edit", "edit": {"field": "question", "find": "(C) 0 W", "replace": "(C) 5 W"}})
    c.post(f"/api/cases/{Q15}/actions", json={"action": "reopen"})
    assert c.get(f"/api/cases/{Q15}").json()["patches"] == []


# ======================================================================== O1
@pytest.mark.parametrize("body", [
    {"action": "approve", "route": "auto_apply"},
    {"action": "approve", "questionId": Q22},
    {"action": "approve", "admin": True},
    {"action": "edit", "edit": {"field": "question", "find": "(C) 0 W", "replace": "(C) 5 W", "questionType": "mcq"}},
    {"action": "edit", "edit": {"field": "question", "find": "(C) 0 W", "replace": "(C) 5 W", "answer": "Z"}},
])
def test_o1_unknown_fields_rejected_with_no_state_change(tmp_path, monkeypatch, body):
    st = Store(state_dir=tmp_path / "state")
    c = make_client(st, monkeypatch)
    before = files(st)
    r = c.post(f"/api/cases/{Q15}/actions", json=body)
    assert r.status_code == 422 and files(st) == before


def test_o1_reset_unknown_fields_rejected(tmp_path, monkeypatch):
    st = Store(state_dir=tmp_path / "state")
    admin = secrets.token_urlsafe(16)
    c = make_client(st, monkeypatch, admin=admin)
    before = files(st)
    r = c.post("/api/admin/reset", json={"note": "x", "wipe_data": True}, headers={"X-Admin-Token": admin})
    assert r.status_code == 422 and files(st) == before


# ======================================================================== valid shapes + restart persistence
def test_valid_actions_and_restart_persistence(tmp_path, monkeypatch):
    st = Store(state_dir=tmp_path / "state")
    c = make_client(st, monkeypatch)
    assert c.post(f"/api/cases/{Q15}/actions", json={"action": "approve", "actor": "Dr. A", "note": "ok"}).status_code == 200
    assert c.post(f"/api/cases/{Q04}/actions", json={"action": "reject", "actor": "Dr. A"}).status_code == 200
    assert c.post(f"/api/cases/{Q22}/actions", json={"action": "edit", "actor": "Dr. A",
                                                    "edit": {"field": "question", "find": "Rugae", "replace": "Rugae (folds)"}}).status_code == 200
    assert c.post(f"/api/cases/{Q15}/actions", json={"action": "reopen"}).status_code == 200
    assert c.post(f"/api/cases/{Q15}/actions", json={"action": "edit", "bogus": 1}).status_code == 422      # O1 failure
    assert c.post(f"/api/cases/{Q15}/actions", json={"action": "edit", "edit": {"field": "question", "find": "(C) 0 W",
                                                                                  "replace": "A" * 300_000}}).status_code == 413  # N2 failure
    view = {q: st.case(q) for q in (Q15, Q04, Q22, Q21)}
    audit = st.audit.entries()
    again = Store(state_dir=st.state_dir)                                     # restart
    for q, v in view.items():
        w = again.case(q)
        assert (w["status"], w["live_question_html"], w["live_answer"], w["patches"]) == \
               (v["status"], v["live_question_html"], v["live_answer"], v["patches"])
    assert again.audit.entries() == audit
    assert hashlib.sha256((config.DATA_DIR / "questions.json").read_bytes()).hexdigest() == DATA_SHA
