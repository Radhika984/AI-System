"""Append-only audit log (JSON Lines). One entry per faculty/system action."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, *, actor: str, action: str, question_id: str, report_ids: list[str],
               before=None, after=None, edit=None, note: str = "", extra: dict | None = None) -> dict:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "actor": actor,
            "action": action,
            "questionId": question_id,
            "reportIds": report_ids,
            "before": before,
            "after": after,
            "edit": edit,
            "note": note,
            **(extra or {}),
        }
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self, question_id: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if question_id is None or e.get("questionId") == question_id:
                out.append(e)
        return out
