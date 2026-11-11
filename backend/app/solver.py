"""Two independent blind solvers + restricted numeric verification.

Blindness is structural: solvers receive `normalize.question_view()` only —
stem + options. No answer key, no stored solution, no student comment.
"""
from __future__ import annotations

import re

from pydantic import ValidationError

from . import config
from . import normalize as N
from .llm import prompts as P
from .llm.client import LLMClient
from .models import SolverOutput
from .safe_eval import UnsafeExpression, close, first_number, safe_eval

SOLVERS = [
    ("A", lambda: config.SOLVER_A_MODEL, P.SOLVER_A_SYSTEM, P.SOLVER_A_VERSION, 0.0),
    ("B", lambda: config.SOLVER_B_MODEL, P.SOLVER_B_SYSTEM, P.SOLVER_B_VERSION, 0.0),
]


def run_solvers(view: dict, client: LLMClient) -> dict:
    user = P.solver_user(view)
    assert "answer" not in view and "solution" not in view  # blindness invariant
    out: dict[str, dict] = {}
    for name, model_fn, system, version, temp in SOLVERS:
        model = model_fn()
        try:
            data, resp = client.complete_json(model=model, system=system, user=user,
                                              prompt_version=version, temperature=temp)
            so = SolverOutput(**data)
            rec = so.model_dump()
            rec.update(model=resp.model, cached=resp.cached)
        except (ValidationError, ValueError, TypeError) as e:
            rec = {"error": f"invalid solver output: {str(e)[:200]}", "model": model}
        out[name] = rec
        out[name]["numeric_check"] = numeric_check(rec)
    return out


def run_solvers_batch(views: list[dict], client: LLMClient, log=print) -> dict[str, dict]:
    """Free-tier mode: each solver sees SOLVER_BATCH_SIZE questions per call (still blind).
    A question missing/invalid in a batch answer is re-solved alone."""
    for v in views:
        assert "answer" not in v and "solution" not in v  # blindness invariant
    out: dict[str, dict] = {v["_id"]: {} for v in views}
    size = max(1, config.SOLVER_BATCH_SIZE)
    for name, model_fn, system, version, temp in SOLVERS:
        model = model_fn()
        for i in range(0, len(views), size):
            chunk = views[i:i + size]
            got: dict[str, dict] = {}
            try:
                data, resp = client.complete_json(
                    model=model, system=system + P.SOLVER_BATCH_SUFFIX, user=P.solver_batch_user(chunk),
                    prompt_version=f"{version}+{P.SOLVER_BATCH_SUFFIX_VERSION}", temperature=temp)
                for item in (data or {}).get("solutions", []) or []:
                    idx = str(item.get("id", "")).lstrip("Qq")
                    if idx.isdigit() and 1 <= int(idx) <= len(chunk):
                        try:
                            rec = SolverOutput(**item).model_dump()
                            rec.update(model=resp.model, cached=resp.cached, batched=True)
                            got[chunk[int(idx) - 1]["_id"]] = rec
                        except (ValidationError, TypeError):
                            pass
            except (ValueError, TypeError) as e:
                log(f"    solver {name} batch failed ({str(e)[:80]}); falling back to single calls")
            for v in chunk:
                rec = got.get(v["_id"])
                if rec is None:  # re-solve this one question alone (same free model)
                    try:
                        data, resp = client.complete_json(model=model, system=system, user=P.solver_user(v),
                                                          prompt_version=version, temperature=temp)
                        rec = SolverOutput(**data).model_dump()
                        rec.update(model=resp.model, cached=resp.cached, batched=False)
                    except (ValidationError, ValueError, TypeError) as e:
                        rec = {"error": f"invalid solver output: {str(e)[:200]}", "model": model}
                rec["numeric_check"] = numeric_check(rec)
                out[v["_id"]][name] = rec
    return out


def numeric_check(rec: dict) -> dict:
    """Re-evaluate the solver's own expression with the restricted evaluator."""
    expr = rec.get("expression")
    if not expr:
        return {"status": "no_expression"}
    try:
        val = safe_eval(expr)
    except UnsafeExpression as e:
        return {"status": "rejected", "reason": str(e)}
    claimed = rec.get("numeric_value")
    if claimed is None:
        return {"status": "evaluated", "value": val}
    return {"status": "match" if close(val, claimed, rel=0.03) else "mismatch", "value": val, "claimed": claimed}


def canon_answer(qtype: str, raw: str | None, options: dict | None = None):
    if raw is None:
        return None
    s = str(raw).strip()
    if qtype == "integerQuestion":
        v = first_number(s)
        return None if v is None else v
    letters = re.findall(r"\b([A-D])\b", s.upper().replace("(", " ").replace(")", " "))
    if qtype == "mcq":
        return sorted(set(letters)) or None
    return letters[0] if letters else None


def same(qtype: str, a, b) -> bool:
    if a is None or b is None:
        return False
    if qtype == "integerQuestion":
        return close(float(a), float(b), rel=0.01)
    return a == b


def agreement(q: dict, solves: dict) -> dict:
    qtype = q["questionType"]
    b = N.body(q)
    key, _ = N.normalize_answer(qtype, b.get("answer"))
    key_c = float(key) if qtype == "integerQuestion" and re.fullmatch(r"-?\d+(\.\d+)?", str(key)) else key
    ans = {k: canon_answer(qtype, v.get("final_answer")) for k, v in solves.items() if "error" not in v}
    vals = list(ans.values())
    agree = len(vals) == 2 and same(qtype, vals[0], vals[1])
    agreed = vals[0] if agree else None
    checks = [v.get("numeric_check", {}).get("status") for v in solves.values()]
    # numeric_ok: True  = at least one solver's own arithmetic, re-evaluated by the restricted
    #                     evaluator, reproduces its claimed value (one mismatch is tolerated
    #                     only because both final answers must also agree);
    #             False = arithmetic was evaluated and never reproduced the claim -> blocks auto-apply;
    #             None  = nothing evaluable (conceptual question, or expression refused as unsafe).
    numeric_ok = None
    if "match" in checks:
        numeric_ok = True
    elif "mismatch" in checks:
        numeric_ok = False
    return {
        "agree": agree,
        "answer": _fmt(qtype, agreed),
        "answers": {k: _fmt(qtype, v) for k, v in ans.items()},
        "stored_key": _fmt(qtype, key_c),
        "matches_key": agree and same(qtype, agreed, key_c),
        "numeric_ok": numeric_ok,
    }


def _fmt(qtype: str, v):
    if v is None:
        return None
    if qtype == "mcq":
        return ",".join(v)
    if qtype == "integerQuestion":
        return str(int(v)) if float(v).is_integer() else str(v)
    return v
