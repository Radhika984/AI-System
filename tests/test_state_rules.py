"""Criterion F regressions (throwaway state only; data/ and the real state/ are never touched):
1. decision-state rules: one decision per case until it is reopened; only decided cases reopen;
2. damaged state files fail closed (never read as empty, never overwritten); a missing file is fresh state;
3. rate-limit identity ignores X-Forwarded-For unless the direct peer is a configured trusted proxy."""
import json
import secrets

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import config, main, security
from app.store import StateFileError, Store

Q15 = "6956d79788d7701e5617bc29"   # R015 faculty_review (identical options), no AI edit offered
Q22 = "61ee6c9d90a1a968a168686b"   # R022 auto-applied spelling fix
Q04 = "68e870ef42c06737d6e565c4"   # R004 auto-applied answer key A -> D
Q29 = "68e8734442c06737d6e56da4"   # R029 no_change
EDIT15 = {"field": "question", "find": "(C) 0 W", "replace": "(C) 500 W"}


@pytest.fixture
def store(tmp_path):
    return Store(state_dir=tmp_path / "state")


def files(st):
    return {n: (st.state_dir / n).read_bytes() for n in ("patches.json", "case_status.json", "audit.jsonl")
            if (st.state_dir / n).exists()}


# ============================================================ 1. decision-state rules
@pytest.mark.parametrize("first", ["approve", "edit", "reject"])
@pytest.mark.parametrize("second", ["approve", "edit", "reject"])
def test_no_second_decision_without_reopen(store, first, second):
    store.act(Q15, first, "Dr. A", edit=EDIT15 if first == "edit" else None)
    before_case, before_files = store.case(Q15), files(store)
    with pytest.raises(ValueError, match="reopen it before making a new decision"):
        store.act(Q15, second, "Dr. B", edit=EDIT15 if second == "edit" else None)
    assert files(store) == before_files                        # no state or audit change at all
    assert store.case(Q15)["status"] == before_case["status"]
    assert store.case(Q15)["live_question_html"] == before_case["live_question_html"]


def test_edit_can_never_stay_live_under_rejected(store):
    store.act(Q15, "edit", "Dr. A", edit=EDIT15)
    with pytest.raises(ValueError):
        store.act(Q15, "reject", "Dr. A")
    c = store.case(Q15)
    assert c["status"] == "edited" and "(C) 500 W" in c["live_question_html"]   # consistent: edited + live
    store.act(Q15, "reopen", "Dr. A")                                            # the legitimate path
    c = store.act(Q15, "reject", "Dr. A")
    assert c["status"] == "rejected" and "(C) 500 W" not in c["live_question_html"]


def test_repeated_reject_of_auto_fix_adds_no_duplicate_audit(store):
    store.act(Q04, "reject", "Dr. A")
    n = len(store.audit.entries(Q04))
    with pytest.raises(ValueError):
        store.act(Q04, "reject", "Dr. A")
    assert len(store.audit.entries(Q04)) == n and store.case(Q04)["live_answer"] == "A"


@pytest.mark.parametrize("qid,state", [(Q15, "pending"), (Q22, "auto-applied")])
def test_reopen_only_for_decided_cases(store, qid, state):
    before = files(store)
    with pytest.raises(ValueError, match=f"case is {state}, not decided"):
        store.act(qid, "reopen", "Dr. A")
    assert files(store) == before


def test_full_workflow_still_works(store):
    assert store.act(Q29, "approve", "Dr. A")["status"] == "approved"
    assert store.act(Q29, "reopen", "Dr. A")["status"] == "pending"
    assert store.act(Q29, "reject", "Dr. A")["status"] == "rejected"
    assert store.act(Q22, "approve", "Dr. A")["status"] == "approved"           # keep an auto-applied fix
    assert "Choroid plexus" in store.case(Q22)["live_question_html"]
    store.act(Q15, "edit", "Dr. A", edit=EDIT15)
    store.act(Q15, "reopen", "Dr. A")                                            # reverts the faculty edit
    c = store.act(Q15, "edit", "Dr. A", edit={"field": "question", "find": "(C) 0 W", "replace": "(C) 250 W"})
    assert "(C) 250 W" in c["live_question_html"] and "(C) 500 W" not in c["live_question_html"]
    assert [e["action"] for e in store.audit.entries(Q15)] == ["edit", "reopen", "edit"]
    again = Store(state_dir=store.state_dir)                                     # restart keeps it all
    assert again.case(Q15)["status"] == "edited" and again.case(Q29)["status"] == "rejected"


def test_api_returns_422_for_second_decision(tmp_path, monkeypatch):
    st = Store(state_dir=tmp_path / "state")
    monkeypatch.setattr(main, "_store", st)
    code = secrets.token_urlsafe(12)
    monkeypatch.setenv("REVIEWER_PASSCODE", code)
    security.reset_rate_limits()
    c, h = TestClient(main.app), {"X-Reviewer-Passcode": code}
    assert c.post(f"/api/cases/{Q29}/actions", json={"action": "approve"}, headers=h).status_code == 200
    r = c.post(f"/api/cases/{Q29}/actions", json={"action": "reject"}, headers=h)
    assert r.status_code == 422 and "reopen" in r.json()["detail"]


# ============================================================ 2. damaged state files
DAMAGED = {
    "malformed": "{ this is not json",
    "truncated": '{"6956d79788d7701e5617bc29": {"state": "edi',
    "empty": "",
    "wrong type": "[1, 2, 3]",
}


@pytest.mark.parametrize("name", ["patches.json", "case_status.json"])
@pytest.mark.parametrize("kind", list(DAMAGED))
def test_damaged_state_file_fails_closed_and_is_not_overwritten(tmp_path, name, kind):
    st = Store(state_dir=tmp_path / "state")
    st.act(Q15, "edit", "Dr. A", edit=EDIT15)                    # real decisions exist
    target = st.state_dir / name
    target.write_text(DAMAGED[kind], encoding="utf-8")
    other = {n: b for n, b in files(st).items() if n != name}
    with pytest.raises(StateFileError, match="nothing was overwritten"):
        Store(state_dir=st.state_dir)
    assert target.read_text(encoding="utf-8") == DAMAGED[kind]    # damaged file left for recovery
    assert {n: b for n, b in files(st).items() if n != name} == other   # valid files untouched


def test_missing_state_files_are_a_fresh_start(tmp_path):
    st = Store(state_dir=tmp_path / "state")
    assert st.status.get(Q04, {}).get("state") == "auto_applied"   # bootstrap works from nothing
    (st.state_dir / "case_status.json").unlink()
    (st.state_dir / "patches.json").unlink()
    assert Store(state_dir=st.state_dir).status[Q04]["state"] == "auto_applied"


def test_api_reports_damaged_state_with_503_and_recovers(tmp_path, monkeypatch):
    state = tmp_path / "state"
    Store(state_dir=state)                                         # create valid state
    good = (state / "case_status.json").read_bytes()
    (state / "case_status.json").write_text("{ broken", encoding="utf-8")
    monkeypatch.setattr(config, "STATE_DIR", state)
    monkeypatch.setattr(main, "_store", None)
    c = TestClient(main.app)
    for path in ("/health", "/api/queue", f"/api/cases/{Q04}", "/api/audit"):
        r = c.get(path)
        assert r.status_code == 503 and "case_status.json" in r.json()["detail"]
    assert (state / "case_status.json").read_text(encoding="utf-8") == "{ broken"
    (state / "case_status.json").write_bytes(good)                 # operator restores the file
    assert c.get("/health").status_code == 200


# ============================================================ 3. rate-limit identity
def req(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers, "client": (peer, 1234)})


def test_spoofed_forwarded_header_is_ignored_without_trusted_proxy(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    assert security._client_key(req("203.0.113.7", "1.1.1.1")) == "203.0.113.7"
    assert security._client_key(req("203.0.113.7", "2.2.2.2, 3.3.3.3")) == "203.0.113.7"


def test_forwarded_header_used_only_from_trusted_proxy(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8, 192.0.2.10")
    assert security._client_key(req("10.1.2.3", "198.51.100.4")) == "198.51.100.4"
    # a client-supplied left-most value is ignored: the right-most untrusted hop is the client
    assert security._client_key(req("10.1.2.3", "6.6.6.6, 198.51.100.4, 192.0.2.10")) == "198.51.100.4"
    assert security._client_key(req("203.0.113.7", "198.51.100.4")) == "203.0.113.7"   # peer not trusted
    assert security._client_key(req("10.1.2.3")) == "10.1.2.3"                           # no header


def test_malformed_trusted_proxy_entries_never_trust_everything(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "not-an-ip, *, 0.0.0.0/garbage")
    assert security._client_key(req("203.0.113.7", "1.1.1.1")) == "203.0.113.7"


def test_rotating_spoofed_header_still_hits_the_rate_limit(tmp_path, monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    monkeypatch.setattr(main, "_store", Store(state_dir=tmp_path / "state"))
    monkeypatch.setenv("REVIEWER_PASSCODE", secrets.token_urlsafe(12))
    security.reset_rate_limits()
    c = TestClient(main.app)
    codes = [c.post(f"/api/cases/{Q29}/actions", json={"action": "approve"},
                    headers={"X-Reviewer-Passcode": "wrong", "X-Forwarded-For": f"198.51.100.{i}"}).status_code
             for i in range(security.MAX_FAILURES + 1)]
    assert codes[: security.MAX_FAILURES] == [401] * security.MAX_FAILURES and codes[-1] == 429
