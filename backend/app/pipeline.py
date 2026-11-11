"""Orchestration: precheck -> blind solvers -> numeric check -> group -> judge
-> schema validation -> guard -> deterministic routing -> Result rows.

Deterministic post-rules (SPEC §3) are applied here and recorded in
`details[...]["overrides"]` so every non-LLM decision is visible.
"""
from __future__ import annotations

import json
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

SOLVER_DISPUTE_CONF_CAP = 0.6   # both solvers agree with each other but contradict the key
SOLVER_DISAGREE_CONF_CAP = 0.7  # the two blind solvers disagree with each other (< auto-apply 0.85)

MISSING_CONTENT_REPAIRS = {"stem_data", "option_repair", "diagram"}
_MISSING_WORDS = re.compile(r"\b(missing|not given|not provided|not stated|blank|not present|absent)\b", re.I)


def solvers_dispute(agree: dict, solves: dict, verdict: str, repair: str | None) -> str | None:
    """SPEC §3 rule 5: two DEFINITE blind answers that differ. A solver abstains (is not counted) if
    it gave no usable answer, or if it reported missing content while the verdict is itself a
    missing-content defect - its failure is evidence for the defect, not a disagreement.
    Returns a short description of the dispute, or None."""
    if agree.get("agree"):  # solver.agreement: exact for integer answers (R033: 3113 vs 3114 is a dispute)
        return None
    definite = {}
    for name, ans in (agree.get("answers") or {}).items():
        if ans is None:
            continue
        s = solves.get(name, {})
        if verdict == "defect" and repair in MISSING_CONTENT_REPAIRS and \
                any(_MISSING_WORDS.search(p or "") for p in s.get("problems_noticed") or []):
            continue
        definite[name] = ans
    if len(definite) >= 2 and len(set(definite.values())) > 1:
        return ", ".join(f"{k}={v}" for k, v in sorted(definite.items()))
    return None

# Used only when a deterministic rule overrides the model's verdict, or the model's reply is unusable.
# Student replies may describe what happened, never commit to features or timelines nobody has
# promised (e.g. "we are working on Hindi support"). Such replies are replaced by the verdict template.
_PROMISE = re.compile(r"in the future|working on|will (be )?(add|support|launch|release|introduce)|coming soon|\bsoon\b"
                      r"|plan(ning)? to|\bwe will\b|\bwe'll\b|upcoming|roadmap", re.I)

FALLBACK_REPLY = {
    "already_fixed": "Thanks for flagging this! A teacher already corrected it after your report, so reopen the question and you'll see the fixed version.",
    "not_actionable": "Thanks for reaching out! We checked this question and found nothing wrong; if something still seems off, report it again with what you expected.",
    "defect": "You spotted a real problem - thank you! We've sent it to a teacher to review.",
    "language_mode": "Thanks for asking! This question is currently available only in English, so it can't be switched to another language here.",
    "syllabus": "Thanks for flagging this! We've sent it to a teacher to confirm whether it's in your syllabus; until then the question stays live, so it's fine to skip it if it's unfamiliar.",
    "_": "Thanks for flagging this! We checked the question carefully and it is correct as stored.",
}


# SPEC §3 rule 5 covers defects (-> faculty_review) and no_error (-> console priority 1) only.
# language_mode / display_issue / app_issue / already_fixed / not_actionable are outside it.
RULE5_NON_DEFECT_VERDICTS = {"no_error"}

# While faculty approval is pending, a reply must not say an action is happening or done.
_ACTION_CLAIM = re.compile(
    r"\ba teacher is\b|\bteacher is (now )?(restoring|adding|moving|updating|fixing|reviewing|correcting)"
    r"|\bwe are (now )?(updating|fixing|correcting|adding|restoring|moving)"
    r"|\bis being (corrected|updated|fixed|reviewed|restored)"
    r"|\b(has|have) been (updated|corrected|fixed|added|removed|restored)"
    r"|\b(we have|we've) (updated|corrected|fixed|added|removed|restored)"
    r"|\bnow updating\b", re.I)
PENDING_REVIEW_SENTENCE = "We've sent this to a teacher to review."


def pending_review_reply(reply: str) -> tuple[str, list[str]]:
    """Drop sentences that claim an action is underway/completed and state the true status instead."""
    parts = [x for x in re.split(r"(?<=[.!?])\s+", reply.strip()) if x.strip()]
    keep = [x for x in parts if not _ACTION_CLAIM.search(x)]
    dropped = [x for x in parts if _ACTION_CLAIM.search(x)]
    if not dropped:
        return reply, []
    return " ".join(keep[:2] + [PENDING_REVIEW_SENTENCE]), dropped


def override_evidence(rule: str, agree: dict, detail: str = "") -> str:
    """Evidence that supports a verdict set by a coded rule (not the judge's original reasoning)."""
    key = agree.get("stored_key")
    content = (f"Content check: both blind solvers chose the stored key {key}." if agree.get("agree") and agree.get("matches_key")
               else "Content check: the blind solvers did not both confirm the stored key.")
    if rule == "syllabus":
        return ("Student states the question is outside the syllabus. Syllabus scope is a faculty decision "
                "(taxonomy 'syllabus': faculty confirm, question stays live), so it is routed to faculty. " + content)
    if rule == "already_fixed":
        return f"{detail} {content}".strip()
    if rule == "malformed_key":
        return detail
    return detail


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
    pk_solves, pk_agree = S.judge_packet_view(q, solves)
    jo, jmeta = J.run_judge(J.build_packet(q, qcheck, rflags, pk_solves, pk_agree), client)
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
        evidence_override: str | None = None
        forced_edit: Edit | None = None

        # Rule: verified already-fixed history wins over the model.
        fx = next((f for f in r["flags"] if f["code"] == "already_fixed"), None)
        if fx and "no longer present" in fx["detail"] and verdict != "already_fixed":
            overrides.append(f"verdict {verdict}->already_fixed (errorHistory proves the fix)")
            verdict, repair = "already_fixed", None
            evidence_override = override_evidence("already_fixed", agree, fx["detail"])

        # Rule: a syllabus claim is confirmed by faculty, never ruled on by the AI
        # (taxonomy: "Student says it is outside the syllabus. Faculty confirm; question stays live").
        if "syllabus_claim" in codes and verdict != "defect":
            overrides.append(f"verdict {verdict}->defect/syllabus (syllabus scope is a faculty decision)")
            verdict, repair = "defect", "syllabus"
            evidence_override = override_evidence("syllabus", agree)

        # Rule: the deterministic precheck proves the stored key is malformed (e.g. mcq ["", "B"]).
        # Taxonomy: answer_key = "Answer key wrong or malformed"; type_mismatch needs evidence the
        # question is stored as the wrong type, and an mcq ("one or more correct") with one correct
        # option is valid. The repair edit is the stored key's own normalisation (nothing invented).
        malformed = qcheck.get("answer_malformed")
        if verdict == "defect" and repair == "type_mismatch" and malformed:
            norm = qcheck.normalized_answer
            if isinstance(norm, list) and norm:
                overrides.append("repair type_mismatch->answer_key (precheck: stored key malformed; "
                                 "taxonomy answer_key covers malformed keys; no evidence of a wrong question type)")
                repair = "answer_key"
                forced_edit = Edit(field="answer", find=N.answer_to_str(N.body(q).get("answer")),
                                   replace=json.dumps(norm))

        # SPEC §3 rule 5: disagreement lowers confidence and escalates; it never changes the verdict.
        needs_attention, attention_reason = False, None
        # 5a. solvers agree with each other but contradict the stored key while the verdict is a non-defect
        if verdict in RULE5_NON_DEFECT_VERDICTS and agree.get("agree") and not agree.get("matches_key") \
                and q["questionType"] != "mcq" and agree.get("numeric_ok") is not False:
            needs_attention, attention_reason = True, "both blind solvers dispute the stored key"
            if conf > SOLVER_DISPUTE_CONF_CAP:
                overrides.append(f"confidence {conf:.2f}->{SOLVER_DISPUTE_CONF_CAP} (both solvers dispute the key)")
                conf = SOLVER_DISPUTE_CONF_CAP
        # 5b. the two blind solvers disagree with each other (any verdict)
        dispute = solvers_dispute(agree, solves, verdict, repair)
        if dispute and verdict != "defect" and verdict not in RULE5_NON_DEFECT_VERDICTS:
            overrides.append(f"rule 5 not applied: verdict {verdict} is outside SPEC §3 rule 5 "
                             f"(defects and no_error only); solvers disagreed ({dispute})")
            dispute = None
        if dispute:
            if conf > SOLVER_DISAGREE_CONF_CAP:
                overrides.append(f"confidence {conf:.2f}->{SOLVER_DISAGREE_CONF_CAP} (blind solvers disagree: {dispute})")
                conf = SOLVER_DISAGREE_CONF_CAP
            if verdict != "defect":  # no_error stays no_change by schema -> escalate in the console instead
                needs_attention = True
                attention_reason = attention_reason or f"blind solvers disagree ({dispute})"
            # defects: the cap (< auto-apply threshold) makes guard.route send it to faculty_review

        edit, guard_log = None, []
        if verdict == "defect" and repair and taxonomy.repair_is_auto(repair):
            if forced_edit is not None:
                g = G.check_edit(q, repair, forced_edit)
                edit, guard_log = (forced_edit, ["deterministic malformed-key normalisation passed the guard"]) if g.ok \
                    else (None, [f"deterministic malformed-key edit rejected: {g.errors}"])
            else:
                if repair not in edit_cache:
                    edit_cache[repair] = J.guarded_edit(q, repair, jo.edit, client)
                edit, guard_log = edit_cache[repair]

        rd = G.route(q=q, verdict=verdict, repair=repair, edit=edit, confidence=conf,
                     injection_in_group=injection, solver_agreement=agree, solves=solves)
        reply = d.reply_if_fixed if rd.route == "auto_apply" else d.reply_if_review
        if verdict != d.verdict:  # a deterministic rule changed the outcome -> the model's reply no longer fits
            reply = FALLBACK_REPLY.get(repair if repair in FALLBACK_REPLY else verdict, FALLBACK_REPLY["_"])
            overrides.append("student_reply replaced by template (verdict overridden)")
        reply = _clip_sentences(reply)
        if _PROMISE.search(reply):
            overrides.append(f"student_reply replaced by template (unverified promise: {_PROMISE.search(reply).group(0)!r})")
            reply = FALLBACK_REPLY.get(verdict, FALLBACK_REPLY["_"])
        if rd.route == "faculty_review":
            reply, dropped = pending_review_reply(reply)
            if dropped:
                overrides.append(f"student_reply: removed action claim(s) while faculty approval is pending: {dropped}")
        if len(reply) < 10 or count_sentences(reply) < 1:
            reply = FALLBACK_REPLY.get(verdict, FALLBACK_REPLY["_"])
            overrides.append("student_reply replaced by template (model reply unusable)")
        evidence = re.sub(r"\s+", " ", evidence_override or d.evidence).strip()[:600]
        if evidence_override:
            overrides.append("evidence replaced to support the rule-set verdict (judge's original evidence kept in details)")

        res = Result(reportId=r["reportId"], questionId=q["_id"], verdict=verdict, repair=repair,
                     edit=rd.edit, route=rd.route, confidence=round(conf, 2), evidence=evidence,
                     student_reply=reply)
        results.append(res)
        per_report[r["reportId"]] = {
            "flags": r["flags"], "overrides": overrides, "route_reasons": rd.reasons,
            "guard_log": guard_log, "needs_attention": needs_attention, "attention_reason": attention_reason,
            "comment": r.get("comment"),
            "reply_if_fixed": d.reply_if_fixed, "reply_if_review": d.reply_if_review,
            "judge_verdict": d.verdict, "judge_repair": d.repair, "judge_confidence": d.confidence,
            "judge_evidence": d.evidence,
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
        packets = [J.build_packet(qmap[qid], prep[qid][0], prep[qid][1], *S.judge_packet_view(qmap[qid], solves_all[qid]))
                   for qid in qids]
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
