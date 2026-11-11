"""FastAPI service for the faculty console.

The console serves PRECOMPUTED triage results (results.json, generated offline
by scripts/run_triage.py on the Gemini free tier). The API itself makes no LLM
calls, so it costs nothing to keep online and cannot be prompt-injected at runtime.
"""
from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import config
from .models import Edit
from .security import require_admin, require_reviewer, writes_enabled
from .store import StateFileError, Store

_log = logging.getLogger("uvicorn.error")

app = FastAPI(title="Acadza Report->Fix console API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST"],
    allow_headers=["content-type", "x-reviewer-passcode", "x-admin-token"],
)

# N2: hard cap on request bodies, enforced while the body streams in - before JSON parsing,
# validation, state writes or audit. The largest valid action (an edit at the field limits) is ~6 KB.
MAX_BODY_BYTES = 64 * 1024


class BodySizeLimit:
    """Pure ASGI middleware: 413 for a declared or actual body over MAX_BODY_BYTES."""

    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            return await self._reject(send)
        body, more = b"", True
        while more:  # read the whole body up front so nothing downstream sees a partial request
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
            if len(body) > self.limit:
                return await self._reject(send)
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await self.app(scope, replay, send)

    async def _reject(self, send):
        payload = json.dumps({"detail": f"Request body too large (limit {self.limit // 1024} KB)."}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
        await send({"type": "http.response.body", "body": payload})


app.add_middleware(BodySizeLimit, limit=MAX_BODY_BYTES)

_store: Store | None = None


def store() -> Store:
    """Lazily load the store. A damaged state file fails closed: every request gets a 503 that says
    which file is damaged, and nothing is written, until the file is restored and the server restarted."""
    global _store
    if _store is None:
        try:
            _store = Store()
        except StateFileError as e:
            _log.error("%s", e)
            raise HTTPException(503, str(e))
    return _store


class ActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # O1

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
    model_config = ConfigDict(extra="forbid")  # O1

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
