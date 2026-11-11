"""FastAPI service for the faculty console.

The console serves PRECOMPUTED triage results (results.json, generated offline
by scripts/run_triage.py on the Gemini free tier). The API itself makes no LLM
calls, so it costs nothing to keep online and cannot be prompt-injected at runtime.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .models import Edit
from .security import require_admin, require_reviewer, writes_enabled
from .store import Store

app = FastAPI(title="Acadza Report->Fix console API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST"],
    allow_headers=["content-type", "x-reviewer-passcode", "x-admin-token"],
)

_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


class ActionIn(BaseModel):
    action: Literal["approve", "edit", "reject", "reopen"]
    actor: str = Field(default="faculty", max_length=60)
    note: str = Field(default="", max_length=500)
    edit: Optional[Edit] = None


@app.get("/health")
def health():
    s = store()
    return {
        "status": "ok",
        "results": len(s.results),
        "cases": len(s.groups()),
        "mode": "precomputed",
        "llm_calls_at_runtime": False,
        "faculty_actions": "enabled (reviewer passcode required)" if writes_enabled() else "disabled (no passcode configured)",
        "note": "Triage results were precomputed offline with Gemini free-tier models; the API serves them and records faculty actions.",
    }


@app.get("/api/queue")
def queue():
    return store().queue()


@app.get("/api/cases/{question_id}")
def get_case(question_id: str):
    try:
        return store().case(question_id)
    except KeyError:
        raise HTTPException(404, f"no reported case for question {question_id}")


@app.post("/api/cases/{question_id}/actions", dependencies=[Depends(require_reviewer)])
def act(question_id: str, body: ActionIn):
    try:
        return store().act(question_id, body.action, body.actor, body.note,
                           body.edit.model_dump() if body.edit else None)
    except KeyError:
        raise HTTPException(404, f"no reported case for question {question_id}")
    except ValueError as e:
        raise HTTPException(422, str(e))


class ResetIn(BaseModel):
    actor: str = Field(default="admin", max_length=60)
    note: str = Field(default="", max_length=200)


@app.post("/api/admin/reset", dependencies=[Depends(require_admin)], include_in_schema=False)
def reset_demo(body: ResetIn):
    """Restore the clean demo state (archives current state; never touches data/)."""
    return store().reset_demo(body.actor, body.note)


@app.get("/api/audit")
def audit(questionId: Optional[str] = Query(default=None)):
    return list(reversed(store().audit.entries(questionId)))


# Single-service fallback: serve the built console from the same origin if present.
_dist = config.ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        if path and f.is_file() and _dist in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
