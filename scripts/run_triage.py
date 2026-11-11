"""Run the triage engine.

  python scripts/run_triage.py --pilot          # R005 R004 R027 R017 R009 R034 -> artifacts/runs/pilot_results.json (NOT the submission)
  python scripts/run_triage.py --reports R004 R011
  python scripts/run_triage.py --all            # all 44 -> results.json + artifacts/triage_details.json
  LLM_OFFLINE=1 python scripts/run_triage.py --all   # replay from cache/, zero API calls

On a free-tier quota stop the script exits with code 3; completed calls are
cached, so simply re-run later and it resumes where it stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config, pipeline  # noqa: E402
from app.llm.client import LLMError, QuotaExhausted  # noqa: E402

PILOT = ["R005", "R004", "R027", "R017", "R009", "R034"]


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", action="store_true")
    g.add_argument("--all", action="store_true")
    g.add_argument("--reports", nargs="+")
    args = ap.parse_args()

    ids = PILOT if args.pilot else (args.reports if args.reports else None)
    print(f"provider={config.LLM_PROVIDER} solverA={config.SOLVER_A_MODEL} solverB={config.SOLVER_B_MODEL} "
          f"judge={config.JUDGE_MODEL} offline={config.LLM_OFFLINE}")
    t0 = time.time()
    try:
        results, details, stats = pipeline.run(ids)
    except QuotaExhausted as e:
        print(f"\nSTOPPED SAFELY: {e}\nNo paid model was used. Re-run later to resume from cache.")
        return 3
    except LLMError as e:
        print(f"\nLLM error: {e}")
        return 2

    config.ARTIFACTS_DIR.mkdir(exist_ok=True)
    rows = [r.model_dump() for r in results]
    if args.all:
        (ROOT / "results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        (config.ARTIFACTS_DIR / "triage_details.json").write_text(
            json.dumps(details, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        out = "results.json"
    else:
        name = "pilot" if args.pilot else "partial"
        (config.ARTIFACTS_DIR / "runs").mkdir(exist_ok=True)
        (config.ARTIFACTS_DIR / "runs" / f"{name}_results.json").write_text(
            json.dumps({"results": rows, "details": details}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        out = f"artifacts/runs/{name}_results.json (not the submission; results.json is)"
    print(f"\nwrote {out}: {len(rows)} rows in {time.time() - t0:.0f}s | llm stats {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
