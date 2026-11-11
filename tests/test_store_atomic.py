"""V2 regression tests: faculty actions are atomic. A refused request leaves the live question,
status, patch file and audit trail unchanged; audit entries are written only after success.
Uses the committed results.json on a throwaway state dir (data/ is never written)."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app import config, main, security
from app.store import SYSTEM_ACTOR, Store

R022_Q = "61ee6c9d90a1a968a168686b"   # auto-applied spelling fix: "Choroid plexux" -> "Choroid plexus"
R004_Q = "68e870ef42c06737d6e565c4"   # auto-applied answer key A -> D
FIXED, TYPO = "Choroid plexus", "Choroid plexux"
INVALID_EDITS = [
    {"field": "question", "find": "not-in-the-question", "replace": "x"},                 # anchor absent
    {"field": "question", "find": "Choroid plexux", "replace": "<script>alert(1)</script>"},  # XSS
    {"field": "question", "find": "Choroid plexux", "replace": "$\\alpha$"},                 # raw LaTeX
    {"field": "answer", "find": "B", "replace": "Z"},                                         # bad key
    {"field": "question", "find": "same", "replace": "same"},                                # no-op (schema)
]


def snapshot(st: Store):
    return {
        "live": st.case(R022_Q)["live_question_html"],
        "status": st.case(R022_Q)["status"],
        "patches_file": (st.state_dir / "patches.json").read_bytes(),
        "status_file": (st.state_dir / "case_status.json").read_bytes(),
        "audit_file": (st.state_dir / "audit.jsonl").read_bytes(),
        "active_system_patch": any(p["actor"] == SYSTEM_ACTOR and not p.get("reverted") for p in st.patches[R022_Q]),
    }


@pytest.fixture
def store(tmp_path):
    return Store(state_dir=tmp_path / "state")


def test_r022_starts_auto_applied(store):
    c = store.case(R022_Q)
    assert c["status"] == "auto_applied" and FIXED in c["live_question_html"] and TYPO in c["question_html"]


@pytest.mark.parametrize("bad", INVALID_EDITS)
def test_refused_edit_changes_nothing_r022(store, bad):
    before = snapshot(store)
    with pytest.raises(ValueError):
        store.act(R022_Q, "edit", "Dr. Typo", edit=bad)
    after = snapshot(store)
    assert after == before                                   # live, status, patch file, status file, audit file
    assert FIXED in after["live"] and after["status"] == "auto_applied" and after["active_system_patch"]
    assert not any(e["action"] == "revert_auto_apply" for e in store.audit.entries(R022_Q))


def test_refused_edit_survives_restart(store):
    with pytest.raises(ValueError):
        store.act(R022_Q, "edit", "Dr. Typo", edit=INVALID_EDITS[0])
    again = Store(state_dir=store.state_dir)                 # simulated server restart
    c = again.case(R022_Q)
    assert c["status"] == "auto_applied" and FIXED in c["live_question_html"]
    assert [e["action"] for e in again.audit.entries(R022_Q)] == ["auto_apply"]


def test_valid_edit_replaces_auto_apply_atomically(store):
    # faculty edit written against the ORIGINAL text (the system fix is replaced, not stacked)
    c = store.act(R022_Q, "edit", "Dr. Rao", note="prefer the full term",
                  edit={"field": "question", "find": "Choroid plexux", "replace": "Choroid plexus (brain)"})
    assert c["status"] == "edited" and "Choroid plexus (brain)" in c["live_question_html"]
    acts = [e["action"] for e in store.audit.entries(R022_Q)]
    assert acts == ["auto_apply", "revert_auto_apply", "edit"]
    e = store.audit.entries(R022_Q)[-1]
    assert e["actor"] == "Dr. Rao" and TYPO in e["before"] and "Choroid plexus (brain)" in e["after"]
    again = Store(state_dir=store.state_dir)
    assert "Choroid plexus (brain)" in again.case(R022_Q)["live_question_html"]


def test_valid_edit_on_already_fixed_text_also_works(store):
    # an edit whose anchor only exists once the system fix is removed is validated against that base
    c = store.act(R022_Q, "edit", "Dr. Rao", edit={"field": "question", "find": "Rugae", "replace": "Rugae (folds)"})
    assert c["status"] == "edited" and "Rugae (folds)" in c["live_question_html"]


def test_reject_reverts_auto_apply_and_restores_original_key(store):
    c = store.act(R004_Q, "reject", "Dr. Rao", note="verify")
    assert c["status"] == "rejected" and c["live_answer"] == "A" == c["answer"]
    assert [e["action"] for e in store.audit.entries(R004_Q)] == ["auto_apply", "revert_auto_apply", "reject"]
    assert Store(state_dir=store.state_dir).case(R004_Q)["live_answer"] == "A"


def test_failed_save_rolls_back_and_writes_no_audit(store, monkeypatch):
    before = snapshot(store)

    def boom():
        raise OSError("disk full")
    monkeypatch.setattr(store, "_save", boom)
    with pytest.raises(OSError):
        store.act(R022_Q, "edit", "Dr. Rao", edit={"field": "question", "find": "Choroid plexux", "replace": "Choroid plexus"})
    monkeypatch.undo()
    assert snapshot(store) == before and store.case(R022_Q)["status"] == "auto_applied"


def test_refused_edit_via_api_returns_422_and_changes_nothing(tmp_path, monkeypatch):
    st = Store(state_dir=tmp_path / "state")
    monkeypatch.setattr(main, "_store", st)
    code = "pc-" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]   # throwaway, not a real secret
    monkeypatch.setenv("REVIEWER_PASSCODE", code)
    security.reset_rate_limits()
    client = TestClient(main.app, headers={"X-Reviewer-Passcode": code})
    before = snapshot(st)
    r = client.post(f"/api/cases/{R022_Q}/actions", json={"action": "edit", "edit": INVALID_EDITS[0]})
    assert r.status_code == 422
    assert snapshot(st) == before
    assert FIXED in client.get(f"/api/cases/{R022_Q}").json()["live_question_html"]
    data_hash = hashlib.sha256((config.DATA_DIR / "questions.json").read_bytes()).hexdigest()
    assert data_hash == "178d08f199386bdd1e94268449106f2ecf9c00b6f38d2fd4d79fb011f030641a"
