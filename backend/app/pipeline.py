"""Orchestration: precheck -> blind solvers -> numeric check -> group -> judge
-> schema validation -> guard -> deterministic routing -> Result rows.

Deterministic post-rules (SPEC §3) are applied here and recorded in
`details[...]["overrides"]` so every non-LLM decision is visible.
"""
from __future__ import annotations

import re
from collections import OrderedDict

from . import config
from . import guard as G
from . import judge as J
from . import normalize as N
from . import precheck as PC
from . import solver as S
from . import taxonomy
from .llm.client import LLMClient
from .models import Edit, Result, count_sentences

SOLVER_DISPUTE_CONF_CAP = 0.6

# Used only when a deterministic rule overrides the model's verdict, or the model's reply is unusable.
FALLBACK_REPLY = {
    "already_fixed": "Thanks for flagging this! A teacher already corrected it after your report, so reopen the question and you'll see the fixed version.",
    "not_actionable": "Thanks for reaching out! We checked this question and it looks correct; if something still seems off, tell us what you expected and we'll look again.",
    "defect": "You spotted a real problem - thank you! A teacher is verifying the fix now and the question will be updated shortly.",
    "_": "Thanks for flagging this! We checked the question carefully and it is correct as stored.",
}


def group_reports(reports: list[dict]) -> "OrderedDict[str, list[dict]]":
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for r in sorted(reports, key=lambda r: r["reportedAt"]):
        groups.setdefault(r["questionId"], []).append(r)
    return groups


def _clip_sentences(text: str, n: int = 3) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    out = " ".join(parts[:n])
    if out and out[-1] not in ".!?":
        out += "."
    return out


def prepare(q: dict, reports: list[dict]):
    qcheck = PC.check_question(q)
    rflags = [{**r, "flags": [f.as_dict() for f in PC.check_report(r, q)]} for r in reports]
    return qcheck, rflags


def process_question(q: dict, reports: list[dict], client: LLMClient) -> tuple[list[Result], dict]:
    """Unbatched path: 3 calls for this question."""
    qcheck, rflags = prepare(q, reports)
    solves = S.run_solvers(N.question_view(q), client)
    agree = S.agreement(q, solves)
    jo, jmeta = J.run_judge(J.build_packet(q, qcheck, rflags, solves, agree), client)
    return finalize(q, qcheck, rflags, solves, agree, jo, jmeta, client)


def finalize(q, qcheck, rflags, solves, agree, jo, jmeta, client) -> tuple[list[Result], dict]:
    """Deterministic post-rules, guard and routing (no LLM except one edit-fix retry)."""
    injection = any(any(f["code"] == "injection" for f in r["flags"]) for r in rflags)
    results: list[Result] = []
    per_report: dict[str, dict] = {}
    edit_cache: dict[str, tuple[Edit | None, list[str]]] = {}

    for r in rflags:
        d = next(x for x in jo.decisions if x.reportId == r["reportId"])
        verdict, repair, conf = d.verdict, d.repair if d.verdict == "defect" else None, float(d.confidence)
        overrides: list[str] = []
        codes = {f["code"] for f in r["flags"]}

        # Rule: verified already-fixed history wins over the model.
        fx = next((f for f in r["flags"] if f["code"] == "already_fixed"), None)
        if fx and "no longer present" in fx["detail"] and verdict != "already_fixed":
            overrides.append(f"verdict {verdict}->already_fixed (errorHistory proves the fix)")
            verdict, repair = "already_fixed", None

        # Rule: solvers agree with each other but contradict the stored key while the
        # judge calls it fine -> keep verdict, cap confidence, flag for attention.
        needs_attention = False
        if verdict != "defect" and agree.get("agree") and not agree.get("matches_key") \
                and q["questionType"] != "mcq" and agree.get("numeric_ok") is not False:
            needs_attention = True
            if conf > SOLVER_DISPUTE_CONF_CAP:
                overrides.append(f"confidence {conf:.2f}->{SOLVER_DISPUTE_CONF_CAP} (both solvers dispute the key)")
                conf = SOLVER_DISPUTE_CONF_CAP

        # Rule: solvers disagree on an answer-key change -> cap confidence.
        if verdict == "defect" and repair == "answer_key" and not agree.get("agree") and conf > 0.75:
            overrides.append(f"confidence {conf:.2f}->0.75 (blind solvers disagree)")
            conf = 0.75

        edit, guard_log = None, []
        if verdict == "defect" and repair and taxonomy.repair_is_auto(repair):
            if repair not in edit_cache:
                edit_cache[repair] = J.guarded_edit(q, repair, jo.edit, client)
            edit, guard_log = edit_cache[repair]

        rd = G.route(q=q, verdict=verdict, repair=repair, edit=edit, confidence=conf,
                     injection_in_group=injection, solver_agreement=agree)
        reply = d.reply_if_fixed if rd.route == "auto_apply" else d.reply_if_review
        if verdict != d.verdict:  # a deterministic rule changed the outcome -> the model's reply no longer fits
            reply = FALLBACK_REPLY.get(verdict, FALLBACK_REPLY["_"])
            overrides.append("student_reply replaced by template (verdict overridden)")
        reply = _clip_sentences(reply)
        if len(reply) < 10 or count_sentences(reply) < 1:
            reply = FALLBACK_REPLY.get(verdict, FALLBACK_REPLY["_"])
            overrides.append("student_reply replaced by template (model reply unusable)")
        evidence = re.sub(r"\s+", " ", d.evidence).strip()[:600]

        res = Result(reportId=r["reportId"], questionId=q["_id"], verdict=verdict, repair=repair,
                     edit=rd.edit, route=rd.route, confidence=round(conf, 2), evidence=evidence,
                     student_reply=reply)
        results.append(res)
        per_report[r["reportId"]] = {
            "flags": r["flags"], "overrides": overrides, "route_reasons": rd.reasons,
            "guard_log": guard_log, "needs_attention": needs_attention, "comment": r.get("comment"),
            "reply_if_fixed": d.reply_if_fixed, "reply_if_review": d.reply_if_review,
            "judge_verdict": d.verdict, "judge_repair": d.repair, "judge_confidence": d.confidence,
        }

    details = {
        "questionId": q["_id"],
        "question_flags": [f.as_dict() for f in qcheck.flags],
        "solves": solves,
        "agreement": agree,
        "judge": {"question_analysis": jo.question_analysis, "correct_answer": jo.correct_answer,
                  "edit_proposal": jo.edit.model_dump() if jo.edit else None, **jmeta},
        "injection_in_group": injection,
        "reports": per_report,
    }
    return results, details


def run(report_ids: list[str] | None = None, client: LLMClient | None = None, log=print):
    client = client or LLMClient()
    qmap = N.questions_by_id()
    reps = N.reports()
    if report_ids:
        wanted = set(report_ids)
        target_q = {r["questionId"] for r in reps if r["reportId"] in wanted}
        reps = [r for r in reps if r["questionId"] in target_q]  # keep whole groups together
    results: list[Result] = []
    details: dict[str, dict] = {}
    groups = group_reports(reps)
    batched = config.SOLVER_BATCH_SIZE > 1 or config.JUDGE_BATCH_SIZE > 1
    if not batched:
        for qid, group in groups.items():
            log(f"  {qid} <- {[r['reportId'] for r in group]}")
            res, det = process_question(qmap[qid], group, client)
            results += res
            details[qid] = det
            for x in res:
                log(f"    {x.reportId}: {x.verdict}/{x.repair} -> {x.route} ({x.confidence})")
    else:
        # Free-tier mode: questions batched per call; every question still gets its own
        # blind solves, its own judged case and its own deterministic post-processing.
        qids = list(groups)
        prep = {qid: prepare(qmap[qid], groups[qid]) for qid in qids}
        log(f"  solving {len(qids)} questions in batches of {config.SOLVER_BATCH_SIZE} x 2 solvers")
        solves_all = S.run_solvers_batch([N.question_view(qmap[qid]) for qid in qids], client, log)
        agrees = {qid: S.agreement(qmap[qid], solves_all[qid]) for qid in qids}
        packets = [J.build_packet(qmap[qid], prep[qid][0], prep[qid][1], solves_all[qid], agrees[qid]) for qid in qids]
        log(f"  judging {len(qids)} cases in batches of {config.JUDGE_BATCH_SIZE}")
        judged = J.run_judge_batch(packets, client, log)
        for qid in qids:
            jo, jmeta = judged[qid]
            res, det = finalize(qmap[qid], prep[qid][0], prep[qid][1], solves_all[qid], agrees[qid], jo, jmeta, client)
            results += res
            details[qid] = det
            for x in res:
                log(f"    {x.reportId}: {x.verdict}/{x.repair} -> {x.route} ({x.confidence})")
    results.sort(key=lambda r: r.reportId)
    return results, details, client.stats
