"""Original data must never change (SPEC §1)."""
import hashlib
import re

from app import config, normalize as N

PINNED = {
    "questions.json": "178d08f199386bdd1e94268449106f2ecf9c00b6f38d2fd4d79fb011f030641a",
    "reports.json": "042751d1f233395927e108240e5a011b6fa9bd8843296b67e3d1ebf610cb7b55",
    "taxonomy.json": "3100ea343cb758111dcd13cfb7ace4769a0be0dffc006d8f1dfc04208893d2df",
}


def test_original_files_unchanged():
    for name, digest in PINNED.items():
        assert hashlib.sha256((config.DATA_DIR / name).read_bytes()).hexdigest() == digest, name


def test_counts_and_relationships():
    qs, rs = N.questions(), N.reports()
    assert len(qs) == 43 and len(rs) == 44
    ids = [q["_id"] for q in qs]
    assert len(set(ids)) == 43
    assert len({r["reportId"] for r in rs}) == 44
    qids = {r["questionId"] for r in rs}
    assert len(qids) == 39 and qids <= set(ids)
    assert len(set(ids) - qids) == 4


def test_qid_is_not_a_safe_key():
    qids = [q["qid"] for q in N.questions() if q["qid"]]
    assert len(qids) != len(set(qids))  # duplicates exist -> must key on _id


def test_loader_returns_copies():
    a = N.questions()
    a[0]["questionType"] = "tampered"
    assert N.questions()[0]["questionType"] != "tampered"


def test_content_lives_under_question_type():
    for q in N.questions():
        assert "question" in q[q["questionType"]]


def test_backend_never_writes_into_data_dir():
    """Every write in backend code must target cache/, artifacts/ or state/."""
    for p in (config.ROOT / "backend" / "app").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"DATA_DIR[^\n]*", src):
            line = m.group(0)
            assert "write" not in line and "open(" not in line, f"{p.name}: {line}"
