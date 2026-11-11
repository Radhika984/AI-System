"""Validate results.json and list disagreements with the hand audit (P3).

  python scripts/eval_results.py [results.json]

Checks: exactly 44 unique reportIds, every report covered with the right
questionId, schema (Pydantic Result), taxonomy keys, edits pass the guard,
auto_apply only for auto:true repairs, injection never auto-applied, replies
1-3 sentences. Then prints agreement with eval/audit_hypotheses.json.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import guard as G, normalize as N, precheck as PC, taxonomy  # noqa: E402
from app.models import Edit, Result  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    reps = {r["reportId"]: r for r in N.reports()}
    qs = N.questions_by_id()
    errors: list[str] = []

    ids = [r.get("reportId") for r in rows]
    if len(rows) != 44 or len(set(ids)) != 44 or set(ids) != set(reps):
        errors.append(f"expected 44 unique reportIds matching reports.json; got {len(rows)} rows, {len(set(ids))} unique")
    for r in rows:
        rid = r.get("reportId")
        try:
            Result(**r)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{rid}: schema: {e}")
            continue
        if set(r) != set(Result.model_fields):
            errors.append(f"{rid}: unexpected keys {sorted(set(r) ^ set(Result.model_fields))}")
        if rid in reps and r["questionId"] != reps[rid]["questionId"]:
            errors.append(f"{rid}: questionId mismatch")
        q = qs.get(r["questionId"])
        if r.get("edit"):
            g = G.check_edit(q, r["repair"], Edit(**r["edit"]))
            if not g.ok:
                errors.append(f"{rid}: edit fails guard: {g.errors}")
        if r["route"] == "auto_apply":
            if not taxonomy.repair_is_auto(r["repair"]):
                errors.append(f"{rid}: auto_apply on auto:false repair")
            if any(f.code == "injection" for f in PC.check_report(reps[rid], q)):
                errors.append(f"{rid}: injection report auto-applied")

    print(f"rows={len(rows)} routes={dict(Counter(r['route'] for r in rows))}")
    print(f"verdicts={dict(Counter(r['verdict'] for r in rows))}")
    print("VALIDATION:", "PASS" if not errors else f"FAIL ({len(errors)})")
    for e in errors:
        print("  -", e)

    hyp = json.loads((ROOT / "eval" / "audit_hypotheses.json").read_text(encoding="utf-8"))
    agree = {"verdict": 0, "repair": 0, "route": 0}
    diffs = []
    for r in sorted(rows, key=lambda x: x["reportId"]):
        h = hyp.get(r["reportId"])
        if not h:
            continue
        for k in agree:
            if r.get(k) == h[k]:
                agree[k] += 1
        if (r["verdict"], r.get("repair"), r["route"]) != (h["verdict"], h["repair"], h["route"]):
            diffs.append(f"  {r['reportId']}: engine {r['verdict']}/{r.get('repair')}/{r['route']} ({r['confidence']})"
                         f"  vs audit {h['verdict']}/{h['repair']}/{h['route']}\n      audit: {h['why']}\n      engine: {r['evidence']}")
    n = len(hyp) - 1
    print(f"\nAGREEMENT with hand audit: verdict {agree['verdict']}/{n}, repair {agree['repair']}/{n}, route {agree['route']}/{n}")
    if diffs:
        print("DISAGREEMENTS (investigate, do not force):")
        print("\n".join(diffs))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
