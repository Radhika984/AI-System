"""API + store + audit tests on an isolated state dir (originals never touched)."""
import hashlib
import secrets
import json

import pytest
from fastapi.testclient import TestClient

from app import config, main, security
from app.store import Store

R004_Q = "68e870ef42c06737d6e565c4"
R015_Q = "6956d79788d7701e5617bc29"
R029_Q = "68e8734442c06737d6e56da4"
R022_Q = "61ee6c9d90a1a968a168686b"

FIXTURE = [
    {"reportId": "R004", "questionId": R004_Q, "verdict": "defect", "repair": "answer_key",
     "edit": {"field": "answer", "find": "A", "replace": "D"}, "route": "auto_apply", "confidence": 0.95,
     "evidence": "Both solves give 4800 (D); key A.", "student_reply": "The key was wrong; it's (D) 4800 N/m^2. Fixed."},
    {"reportId": "R015", "questionId": R015_Q, "verdict": "defect", "repair": "identical_options", "edit": None,
     "route": "faculty_review", "confidence": 0.97, "evidence": "Options B and C are both 0 W.",
     "student_reply": "You're right, two options are identical. A teacher is fixing it."},
    {"reportId": "R029", "questionId": R029_Q, "verdict": "no_error", "repair": None, "edit": None,
     "route": "no_change", "confidence": 0.95, "evidence": "F=90 N, mu=0.8 = key A.",
     "student_reply": "Subtract the two equations: F = 90 N, so mu = 0.8. The key is right."},
    {"reportId": "R022", "questionId": R022_Q, "verdict": "defect", "repair": "spelling",
     "edit": {"field": "question", "find": "Choroid plexux", "replace": "Choroid plexus"}, "route": "faculty_review",
     "confidence": 0.8, "evidence": "Option D reads 'plexux'.", "student_reply": "Thanks! A teacher is fixing the spelling."},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    res = tmp_path / "results.json"
    res.write_text(json.dumps(FIXTURE), encoding="utf-8")
    st = Store(state_dir=tmp_path / "state", results_path=res, details_path=tmp_path / "none.json")
    monkeypatch.setattr(main, "_store", st)
    passcode = secrets.token_urlsafe(12)  # throwaway per test; real value lives only in server env
    monkeypatch.setenv("REVIEWER_PASSCODE", passcode)
    security.reset_rate_limits()
    return TestClient(main.app, headers={"X-Reviewer-Passcode": passcode})


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["cases"] == 4 and r["mode"] == "precomputed"


def test_queue_order_tiers(client):
    q = client.get("/api/queue").json()
    order = [c["questionId"] for c in q]
    assert order[0] == R004_Q            # tier 1 answer key
    assert order[1] == R015_Q            # tier 2 identical options
    assert order[2] == R022_Q            # tier 4 cosmetic
    assert order[-1] == R029_Q           # tier 5 no change
    assert [c["rank"] for c in q] == [1, 2, 3, 4]


def test_auto_apply_bootstrapped_into_patch_layer_with_audit(client):
    c = client.get(f"/api/cases/{R004_Q}").json()
    assert c["status"] == "auto_applied" and c["answer"] == "A" and c["live_answer"] == "D"
    assert c["audit"][0]["actor"] == "system:auto_apply" and c["audit"][0]["before"] == "A" and c["audit"][0]["after"] == "D"


def test_case_has_diff_and_reports(client):
    c = client.get(f"/api/cases/{R022_Q}").json()
    assert "diff-del" in c["diff"]["before_html"] and "diff-ins" in c["diff"]["after_html"]
    assert c["reports"][0]["comment"] == "spelling of plexus wrong"


def test_approve_applies_patch_and_audits(client):
    before = sha(config.DATA_DIR / "questions.json")
    c = client.post(f"/api/cases/{R022_Q}/actions", json={"action": "approve", "actor": "Dr. Rao"}).json()
    assert c["status"] == "approved"
    assert "Choroid plexus" in c["live_question_html"] and "plexux" in c["question_html"]
    a = client.get("/api/audit", params={"questionId": R022_Q}).json()
    assert a[0]["action"] == "approve" and a[0]["actor"] == "Dr. Rao" and a[0]["at"]
    assert "plexux" in a[0]["before"] and "plexus" in a[0]["after"]
    assert sha(config.DATA_DIR / "questions.json") == before  # originals untouched


def test_double_approve_rejected(client):
    client.post(f"/api/cases/{R022_Q}/actions", json={"action": "approve"})
    r = client.post(f"/api/cases/{R022_Q}/actions", json={"action": "approve"})
    assert r.status_code == 422


def test_faculty_edit_revalidated_by_guard(client):
    bad = client.post(f"/api/cases/{R015_Q}/actions", json={
        "action": "edit", "actor": "Dr. Rao",
        "edit": {"field": "question", "find": "not-in-question", "replace": "x"}})
    assert bad.status_code == 422 and "exactly once" in bad.json()["detail"]
    xss = client.post(f"/api/cases/{R015_Q}/actions", json={
        "action": "edit", "edit": {"field": "question", "find": "(C) 0 W", "replace": "(C) <img src=x onerror=alert(1)>"}})
    assert xss.status_code == 422
    ok = client.post(f"/api/cases/{R015_Q}/actions", json={
        "action": "edit", "actor": "Dr. Rao", "note": "new distractor",
        "edit": {"field": "question", "find": "(C) 0 W", "replace": "(C) 500 W"}})
    assert ok.status_code == 200 and ok.json()["status"] == "edited"
    assert "(C) 500 W" in ok.json()["live_question_html"]


def test_reject_auto_applied_reverts_patch(client):
    c = client.post(f"/api/cases/{R004_Q}/actions", json={"action": "reject", "actor": "Dr. Rao", "note": "check"}).json()
    assert c["status"] == "rejected" and c["live_answer"] == "A"
    acts = [e["action"] for e in client.get("/api/audit", params={"questionId": R004_Q}).json()]
    assert acts[:2] == ["reject", "revert_auto_apply"]


def test_every_action_creates_audit_entry(client):
    n0 = len(client.get("/api/audit").json())
    client.post(f"/api/cases/{R029_Q}/actions", json={"action": "approve"})
    client.post(f"/api/cases/{R029_Q}/actions", json={"action": "reopen"})
    client.post(f"/api/cases/{R029_Q}/actions", json={"action": "reject", "note": "AI wrong"})
    assert len(client.get("/api/audit").json()) == n0 + 3


def test_unknown_case_404_and_bad_action_422(client):
    assert client.get("/api/cases/000000000000000000000000").status_code == 404
    assert client.post(f"/api/cases/{R029_Q}/actions", json={"action": "delete"}).status_code == 422


def test_state_survives_restart(tmp_path, client):
    client.post(f"/api/cases/{R022_Q}/actions", json={"action": "approve"})
    st = main._store
    st2 = Store(state_dir=st.state_dir, results_path=st.results_path, details_path=st.details_path)
    assert st2.case(R022_Q)["status"] == "approved"
    assert "Choroid plexus" in st2.case(R022_Q)["live_question_html"]
