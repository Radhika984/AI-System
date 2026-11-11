"""Pydantic schemas. `Result` is exactly the brief's results.json row."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from . import taxonomy

Route = Literal["auto_apply", "faculty_review", "no_change"]
EditField = Literal["question", "solution", "answer", "questionType"]


class Edit(BaseModel):
    field: EditField
    find: str
    replace: str

    @model_validator(mode="after")
    def _non_trivial(self):
        if self.find == self.replace:
            raise ValueError("edit.find and edit.replace are identical")
        if self.field in ("question", "solution") and not self.find:
            raise ValueError("text edits need a non-empty find anchor")
        return self


def count_sentences(text: str) -> int:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    return len(parts)


class Result(BaseModel):
    reportId: str = Field(pattern=r"^R\d{3}$")
    questionId: str = Field(pattern=r"^[0-9a-f]{24}$")
    verdict: str
    repair: Optional[str] = None
    edit: Optional[Edit] = None
    route: Route
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(min_length=10, max_length=600)
    student_reply: str = Field(min_length=10, max_length=450)

    @field_validator("verdict")
    @classmethod
    def _verdict(cls, v):
        if not taxonomy.is_verdict(v):
            raise ValueError(f"unknown verdict {v!r}")
        return v

    @model_validator(mode="after")
    def _consistency(self):
        if self.verdict == "defect":
            if not self.repair or not taxonomy.is_repair(self.repair):
                raise ValueError("defect needs a taxonomy repair")
            if self.route == "no_change":
                raise ValueError("a confirmed defect cannot be no_change")
            if not taxonomy.repair_is_auto(self.repair) and (self.route == "auto_apply" or self.edit is not None):
                raise ValueError(f"repair {self.repair} is auto:false -> faculty_review with edit=null")
            if self.edit is not None and self.edit.field not in taxonomy.repair_fields(self.repair):
                raise ValueError(f"edit.field {self.edit.field} outside scope of {self.repair}")
            if self.route == "auto_apply" and self.edit is None:
                raise ValueError("auto_apply needs an edit")
        else:
            if self.repair is not None or self.edit is not None or self.route != "no_change":
                raise ValueError("non-defect verdicts are no_change with repair=null, edit=null")
        n = count_sentences(self.student_reply)
        if not 1 <= n <= 3:
            raise ValueError(f"student_reply must be 1-3 sentences (got {n})")
        return self


# ---- LLM output schemas -------------------------------------------------------

class SolverOutput(BaseModel):
    final_answer: str  # option letter(s) "B" / "A,C", or a number for integer questions
    numeric_value: Optional[float] = None
    expression: Optional[str] = None  # arithmetic expression for the final value, for safe_eval
    method: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    problems_noticed: list[str] = Field(default_factory=list)


class JudgeReportDecision(BaseModel):
    reportId: str
    verdict: str
    repair: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    student_reply: str


class JudgeEditProposal(BaseModel):
    field: EditField
    find: str
    replace: str


class JudgeOutput(BaseModel):
    question_analysis: str
    correct_answer: Optional[str] = None
    decisions: list[JudgeReportDecision]
    edit: Optional[JudgeEditProposal] = None
