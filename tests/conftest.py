import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import pytest  # noqa: E402

from app import normalize as N  # noqa: E402


@pytest.fixture(scope="session")
def qs():
    return N.questions_by_id()


@pytest.fixture(scope="session")
def reps():
    return {r["reportId"]: r for r in N.reports()}


@pytest.fixture(scope="session")
def qof(qs, reps):
    return lambda rid: qs[reps[rid]["questionId"]]
