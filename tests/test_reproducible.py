"""results.json must be reproducible from the committed cache with zero API calls,
using the code defaults (a clean clone has no .env)."""
import json

from app import config, pipeline


def test_offline_replay_reproduces_results_json(monkeypatch):
    monkeypatch.setattr(config, "LLM_OFFLINE", True)
    results, _, stats = pipeline.run(log=lambda *a, **k: None)
    assert stats["calls"] == 0
    committed = json.loads((config.ROOT / "results.json").read_text(encoding="utf-8"))
    assert [r.model_dump() for r in results] == committed


def test_committed_replies_never_claim_pending_actions():
    from app.pipeline import _ACTION_CLAIM, _PROMISE
    for r in json.loads((config.ROOT / "results.json").read_text(encoding="utf-8")):
        assert not _PROMISE.search(r["student_reply"]), r["reportId"]
        if r["route"] == "faculty_review":
            assert not _ACTION_CLAIM.search(r["student_reply"]), r["reportId"]
