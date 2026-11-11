"""Build frontend/public/snapshot.json: the read-only fallback the console loads
when the API is unreachable. Uses a throwaway state dir, so the snapshot shows
the initial state (auto-applied fixes applied, no faculty actions)."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.store import Store  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        st = Store(state_dir=Path(tmp))
        if not st.results:
            print("results.json missing or empty; run scripts/run_triage.py --all first")
            return 1
        queue = st.queue()
        snap = {
            "meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "results": len(st.results), "cases": len(queue), "mode": "snapshot"},
            "queue": queue,
            "cases": {c["questionId"]: st.case(c["questionId"]) for c in queue},
            "audit": list(reversed(st.audit.entries())),
        }
    out = ROOT / "frontend" / "public" / "snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(ROOT)}: {len(queue)} cases, {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
