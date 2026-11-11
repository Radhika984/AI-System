"""Restore the clean demo state from a shell on the server (or locally).

  python scripts/reset_demo_state.py --note "before demo recording"

Same operation as POST /api/admin/reset: current state/ files are archived to
state/archive/<timestamp>/, a fresh audit log starts with a `demo_reset` entry, and the
precomputed auto-applies are re-applied. data/ is never touched. Stop the API first
(or restart it afterwards) so the running process reloads the state.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.store import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--actor", default="admin-cli")
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    print(json.dumps(Store(bootstrap_auto_apply=False).reset_demo(args.actor, args.note), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
