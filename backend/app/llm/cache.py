"""Content-addressed disk cache for LLM responses.

Key = sha256(provider, model, prompt_version, system, user, temperature).
Committed to git so `results.json` is reproducible with zero API calls.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(**parts: Any) -> str:
        blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _path(self, k: str) -> Path:
        return self.root / k[:2] / f"{k}.json"

    def get(self, k: str) -> dict | None:
        p = self._path(k)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, k: str, record: dict) -> None:
        p = self._path(k)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
