"""Judge: one call per QUESTION (reports grouped), structured evidence packet,
Pydantic-validated output, one schema-retry and one guarded edit-repair retry."""
from __future__ import annotations

import html
import json

from pydantic import ValidationError

from . import config
from . import guard as G
from . import normalize as N
from . import taxonomy
from .llm import prompts as P
from .llm.client import LLMClient
from .models import Edit, JudgeOutput


def build_packet(q: dict, qcheck, reports_with_flags: list[dict], solves: dict, agree: dict) -> dict:
    b = N.body(q)
    view = N.question_view(q)
    return {
        "question": view,
        "stored_answer_string": N.answer_to_str(b.get("answer")),
        "solution_text": N.to_text(b.get("solution", "")),
        "question_html": b.get("question", ""),
        "solution_html": b.get("solution", ""),
        "error_history": q.get("errorHistory") or [],
        "updated_at": q.get("updatedAt"),
        "question_flags": [f.as_dict() for f in qcheck.flags],
        "solves": {k: {kk: v.get(kk) for kk in ("final_answer", "numeric_value", "method", "confidence",
                                                  "problems_noticed", "numeric_check", "error")}
                   for k, v in solves.items()},
        "agreement": agree,
        "reports": [
            {
                "reportId": r["reportId"],
                "reportedAt": r["reportedAt"],
                "source": r.get("source"),
                "flags": [f["code"] for f in r["flags"]],
                # escaped so a comment can never close the <student_comment> tag
                "comment_escaped": html.escape(r.get("comment") or "", quote=False),
            }
            for r in reports_with_flags
        ],
    }


def run_judge(packet: dict, client: LLMClient) -> tuple[JudgeOutput, dict]:
    tax = taxonomy.load()
    system, user = P.judge_system(tax), P.judge_user(packet)
    meta: dict = {"model": config.JUDGE_MODEL, "attempts": []}
    expected = {r["reportId"] for r in packet["reports"]}
    version = P.JUDGE_VERSION
    last_err = ""
    for attempt in range(2):
        u = user if attempt == 0 else user + f"\n\nYour previous output was invalid: {last_err}. Return corrected JSON."
        data, resp = client.complete_json(model=config.JUDGE_MODEL, system=system, user=u,
                                          prompt_version=version + ("" if attempt == 0 else "+retry"))
        meta["attempts"].append({"cached": resp.cached})
        try:
            return _validate(data, expected), meta
        except (ValidationError, ValueError, TypeError) as e:
            last_err = str(e)[:500]
    raise RuntimeError(f"judge output invalid after retry: {last_err}")


def _validate(data: dict, expected: set[str]) -> JudgeOutput:
    jo = JudgeOutput(**_coerce(data))
    got = {d.reportId for d in jo.decisions}
    if got != expected:
        raise ValueError(f"decisions for {sorted(got)} but expected {sorted(expected)}")
    for d in jo.decisions:
        if not taxonomy.is_verdict(d.verdict):
            raise ValueError(f"unknown verdict {d.verdict!r}")
        if d.verdict == "defect" and not (d.repair and taxonomy.is_repair(d.repair)):
            raise ValueError(f"{d.reportId}: defect needs a taxonomy repair (got {d.repair!r})")
    return jo


def run_judge_batch(packets: list[dict], client: LLMClient, log=print) -> dict[str, tuple[JudgeOutput, dict]]:
    """Free-tier mode: JUDGE_BATCH_SIZE cases per call. Every case is validated on
    its own; a missing/invalid case is re-judged alone with the single-case prompt."""
    tax = taxonomy.load()
    system = P.judge_system(tax) + P.JUDGE_BATCH_SUFFIX
    out: dict[str, tuple[JudgeOutput, dict]] = {}
    size = max(1, config.JUDGE_BATCH_SIZE)
    for i in range(0, len(packets), size):
        chunk = packets[i:i + size]
        try:
            data, resp = client.complete_json(model=config.JUDGE_MODEL, system=system,
                                              user=P.judge_batch_user(chunk),
                                              prompt_version=P.JUDGE_VERSION + "+batch-v1")
            cases = (data or {}).get("cases", []) or []
        except (ValueError, TypeError) as e:
            log(f"    judge batch failed ({str(e)[:80]})")
            cases, resp = [], None
        for item in cases:
            idx = str(item.get("case", "")).lstrip("Cc")
            if not (idx.isdigit() and 1 <= int(idx) <= len(chunk)):
                continue
            p = chunk[int(idx) - 1]
            try:
                jo = _validate(item, {r["reportId"] for r in p["reports"]})
                out[p["question"]["_id"]] = (jo, {"model": config.JUDGE_MODEL, "batched": True,
                                                  "cached": bool(resp and resp.cached)})
            except (ValidationError, ValueError, TypeError) as e:
                log(f"    judge case {p['question']['_id'][:8]} invalid in batch: {str(e)[:100]}")
        for p in chunk:
            qid = p["question"]["_id"]
            if qid not in out:
                log(f"    re-judging {qid[:8]} alone")
                jo, meta = run_judge(p, client)
                out[qid] = (jo, {**meta, "batched": False})
    return out


def _coerce(data: dict) -> dict:
    """Small, safe normalisations of model output before validation."""
    if not isinstance(data, dict):
        raise ValueError("judge output is not an object")
    for d in data.get("decisions", []) or []:
        if d.get("repair") in ("", "null", "none", "None"):
            d["repair"] = None
        if d.get("verdict") != "defect":
            d["repair"] = None
        for k in ("reply_if_fixed", "reply_if_review"):
            if not d.get(k):
                d[k] = d.get("reply_if_review") or d.get("reply_if_fixed") or d.get("student_reply") or ""
    e = data.get("edit")
    if isinstance(e, dict) and not e.get("field"):
        data["edit"] = None
    if isinstance(e, dict) and e.get("field") == "answer":
        for k in ("find", "replace"):
            if isinstance(e.get(k), list):
                e[k] = json.dumps(e[k])
    return data


def fix_edit_once(q: dict, repair: str, edit: Edit, errors: list[str], client: LLMClient) -> Edit | None:
    """One LLM retry to repair a guard-rejected edit; result is re-guarded by the caller."""
    b = N.body(q)
    user = P.edit_fix_user(repair, taxonomy.repair_fields(repair), edit.model_dump(), errors,
                           {"question": b.get("question", ""), "solution": b.get("solution", "")})
    try:
        data, _ = client.complete_json(model=config.JUDGE_MODEL, system=P.EDIT_FIX_SYSTEM, user=user,
                                       prompt_version=P.EDIT_FIX_VERSION)
        e = (data or {}).get("edit")
        return Edit(**e) if e else None
    except (ValidationError, ValueError, TypeError):
        return None


def guarded_edit(q: dict, repair: str | None, proposal, client: LLMClient | None) -> tuple[Edit | None, list[str]]:
    """Validate the judge's proposal through the guard; allow one repair round."""
    log: list[str] = []
    if proposal is None or not repair or not taxonomy.repair_fields(repair):
        return None, log
    try:
        edit = Edit(**proposal.model_dump())
    except ValidationError as e:
        return None, [f"edit schema invalid: {e.errors()[0]['msg']}"]
    g = G.check_edit(q, repair, edit)
    if g.ok:
        return edit, log
    log += [f"guard rejected v1: {x}" for x in g.errors]
    if client is None:
        return None, log
    fixed = fix_edit_once(q, repair, edit, g.errors, client)
    if fixed is None:
        log.append("edit-fix returned no edit")
        return None, log
    g2 = G.check_edit(q, repair, fixed)
    if g2.ok:
        log.append("guard accepted repaired edit v2")
        return fixed, log
    log += [f"guard rejected v2: {x}" for x in g2.errors]
    return None, log
