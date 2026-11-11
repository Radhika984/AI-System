"""B1/B2: reviewer passcode on every write, admin-only demo reset, no secrets in the repo."""
import hashlib
import json
import re
import secrets
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import config, main, security
from app.store import Store

Q_SPELL = "61ee6c9d90a1a968a168686b"  # R022 (spelling)
Q_KEY = "68e870ef42c06737d6e565c4"    # R004 (answer key)
FIX = [
    {"reportId": "R004", "questionId": Q_KEY, "verdict": "defect", "repair": "answer_key",
     "edit": {"field": "answer", "find": "A", "replace": "D"}, "route": "auto_apply", "confidence": 0.95,
     "evidence": "Both solves give 4800 (D); key A.", "student_reply": "The key was wrong; it's (D). Fixed."},
    {"reportId": "R022", "questionId": Q_SPELL, "verdict": "defect", "repair": "spelling",
     "edit": {"field": "question", "find": "Choroid plexux", "replace": "Choroid plexus"}, "route": "faculty_review",
     "confidence": 0.8, "evidence": "Option D reads 'plexux'.", "student_reply": "Thanks! A teacher is fixing it."},
]
APPROVE = {"action": "approve", "actor": "Dr. Rao"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    res = tmp_path / "results.json"
    res.write_text(json.dumps(FIX), encoding="utf-8")
    st = Store(state_dir=tmp_path / "state", results_path=res, details_path=tmp_path / "none.json")
    monkeypatch.setattr(main, "_store", st)
    code, admin = secrets.token_urlsafe(12), secrets.token_urlsafe(16)
    monkeypatch.setenv("REVIEWER_PASSCODE", code)
    monkeypatch.setenv("ADMIN_RESET_TOKEN", admin)
    security.reset_rate_limits()
    return TestClient(main.app), code, admin, st


def post(c, path, body, **headers):
    return c.post(path, json=body, headers=headers)


# ---------------------------------------------------------------- B1 reviewer passcode
def test_reads_need_no_passcode(env):
    c, *_ = env
    assert c.get("/health").status_code == 200
    assert c.get("/api/queue").status_code == 200
    assert c.get(f"/api/cases/{Q_SPELL}").status_code == 200
    assert c.get("/api/audit").status_code == 200


def test_write_without_or_with_wrong_passcode_rejected_and_nothing_changes(env):
    c, code, _, st = env
    n0 = len(c.get("/api/audit").json())
    assert post(c, f"/api/cases/{Q_SPELL}/actions", APPROVE).status_code == 401
    assert post(c, f"/api/cases/{Q_SPELL}/actions", APPROVE, **{"X-Reviewer-Passcode": "wrong"}).status_code == 401
    assert post(c, f"/api/cases/{Q_SPELL}/actions", APPROVE, **{"X-Reviewer-Passcode": code + "x"}).status_code == 401
    assert len(c.get("/api/audit").json()) == n0
    assert c.get(f"/api/cases/{Q_SPELL}").json()["status"] == "pending"


def test_correct_passcode_allows_every_action(env):
    c, code, *_ = env
    h = {"X-Reviewer-Passcode": code}
    assert post(c, f"/api/cases/{Q_SPELL}/actions", APPROVE, **h).status_code == 200
    assert post(c, f"/api/cases/{Q_SPELL}/actions", {"action": "reopen"}, **h).status_code == 200
    assert post(c, f"/api/cases/{Q_SPELL}/actions", {"action": "reject"}, **h).status_code == 200
    assert post(c, f"/api/cases/{Q_KEY}/actions", {"action": "edit", "edit": {"field": "answer", "find": "A", "replace": "D"}}, **h).status_code == 200


def test_writes_fail_closed_when_passcode_not_configured(env, monkeypatch):
    c, code, *_ = env
    monkeypatch.delenv("REVIEWER_PASSCODE")
    r = post(c, f"/api/cases/{Q_SPELL}/actions", APPROVE, **{"X-Reviewer-Passcode": code})
    assert r.status_code == 503
    assert c.get("/health").json()["faculty_actions"].startswith("disabled")


def test_bruteforce_is_rate_limited(env):
    c, code, *_ = env
    codes = [post(c, f"/api/cases/{Q_SPELL}/actions", APPROVE, **{"X-Reviewer-Passcode": f"guess{i}"}).status_code
             for i in range(security.MAX_FAILURES + 2)]
    assert codes[: security.MAX_FAILURES] == [401] * security.MAX_FAILURES
    assert codes[-1] == 429
    # even the right passcode is refused while the client is locked out
    assert post(c, f"/api/cases/{Q_SPELL}/actions", APPROVE, **{"X-Reviewer-Passcode": code}).status_code == 429


def test_cors_allows_passcode_header():
    c = TestClient(main.app)
    r = c.options("/api/queue", headers={"Origin": "https://x.vercel.app", "Access-Control-Request-Method": "POST",
                                         "Access-Control-Request-Headers": "content-type,x-reviewer-passcode"})
    assert "x-reviewer-passcode" in r.headers.get("access-control-allow-headers", "").lower()


# ---------------------------------------------------------------- B2 demo reset
def test_reset_not_exposed_without_admin_token(env, monkeypatch):
    c, code, *_ = env
    monkeypatch.delenv("ADMIN_RESET_TOKEN")
    assert post(c, "/api/admin/reset", {}, **{"X-Admin-Token": "anything"}).status_code == 404
    assert "/api/admin/reset" not in json.dumps(c.get("/openapi.json").json())


def test_reset_rejects_reviewer_passcode_and_wrong_token(env):
    c, code, admin, _ = env
    assert post(c, "/api/admin/reset", {}).status_code == 401
    assert post(c, "/api/admin/reset", {}, **{"X-Admin-Token": code}).status_code == 401
    assert post(c, "/api/admin/reset", {}, **{"X-Reviewer-Passcode": code}).status_code == 401


def test_reset_disabled_if_token_equals_passcode(env, monkeypatch):
    c, code, *_ = env
    monkeypatch.setenv("ADMIN_RESET_TOKEN", code)
    assert post(c, "/api/admin/reset", {}, **{"X-Admin-Token": code}).status_code == 404


def test_reset_restores_clean_state_and_archives_history(env):
    c, code, admin, st = env
    data_hash = hashlib.sha256((config.DATA_DIR / "questions.json").read_bytes()).hexdigest()
    h = {"X-Reviewer-Passcode": code}
    post(c, f"/api/cases/{Q_SPELL}/actions", APPROVE, **h)
    post(c, f"/api/cases/{Q_KEY}/actions", {"action": "reject"}, **h)
    assert c.get(f"/api/cases/{Q_KEY}").json()["live_answer"] == "A"  # reverted by reject
    old_audit = len(c.get("/api/audit").json())

    r = post(c, "/api/admin/reset", {"note": "before demo"}, **{"X-Admin-Token": admin})
    assert r.status_code == 200, r.text
    body = r.json()
    archive = st.state_dir / body["archived"].split("state/", 1)[1]
    assert (archive / "audit.jsonl").exists() and len((archive / "audit.jsonl").read_text().splitlines()) == old_audit

    assert c.get(f"/api/cases/{Q_SPELL}").json()["status"] == "pending"
    k = c.get(f"/api/cases/{Q_KEY}").json()
    assert k["status"] == "auto_applied" and k["live_answer"] == "D"  # precomputed auto-apply restored
    actions = [e["action"] for e in c.get("/api/audit").json()]
    assert actions[-1] == "demo_reset" and "auto_apply" in actions and "approve" not in actions
    assert hashlib.sha256((config.DATA_DIR / "questions.json").read_bytes()).hexdigest() == data_hash


# ---------------------------------------------------------------- no secrets committed
def test_no_secret_values_in_tracked_files():
    tracked = subprocess.run(["git", "ls-files"], cwd=config.ROOT, capture_output=True, text=True).stdout.split()
    assert ".env" not in tracked
    example = (config.ROOT / ".env.example").read_text(encoding="utf-8")
    for var in ("GEMINI_API_KEY", "REVIEWER_PASSCODE", "ADMIN_RESET_TOKEN"):
        assert re.search(rf"^{var}=\s*$", example, re.M), f"{var} must be empty in .env.example"
    src = "\n".join(p.read_text(encoding="utf-8") for p in (config.ROOT / "backend").rglob("*.py"))
    assert not re.search(r"(REVIEWER_PASSCODE|ADMIN_RESET_TOKEN)\"\s*,\s*\"[^\"]+\"", src)  # no default values
