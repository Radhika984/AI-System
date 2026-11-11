"""Closed taxonomy (loaded from data/taxonomy.json — never hard-coded)."""
from __future__ import annotations

import json
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads((config.DATA_DIR / "taxonomy.json").read_text(encoding="utf-8"))


def verdicts() -> list[str]:
    return list(load()["verdicts"].keys())


def repairs() -> dict[str, dict]:
    return load()["repairs"]


def repair_fields(repair: str) -> list[str]:
    return list(repairs()[repair]["fields"])


def repair_is_auto(repair: str) -> bool:
    return bool(repairs()[repair]["auto"])


def is_verdict(v: str) -> bool:
    return v in load()["verdicts"]


def is_repair(r: str) -> bool:
    return r in repairs()


# Queue priority tiers (SPEC §5). Lower = more urgent.
TIER_OF_REPAIR = {
    "answer_key": 1, "wrong_question": 1, "unsound": 1,
    "stem_data": 2, "option_repair": 2, "identical_options": 2, "diagram": 2,
    "solution_fix": 3, "solution_missing": 3,
    "spelling": 4, "noise": 4, "exam_reference": 4, "markup_leak": 4, "notation": 4,
    "answer_form": 4, "type_mismatch": 4, "wrong_chapter": 4, "syllabus": 4,
}
TIER_LABEL = {
    1: "Wrong answer / unanswerable / AI unsure",
    2: "Missing content",
    3: "Solution error",
    4: "Cosmetic / metadata",
    5: "No change needed",
}


def tier(verdict: str, repair: str | None) -> int:
    if verdict != "defect" or not repair:
        return 5
    return TIER_OF_REPAIR.get(repair, 4)
