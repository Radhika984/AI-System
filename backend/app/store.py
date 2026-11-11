"""Case store: precomputed triage results + a separate patch layer.

* Original questions (data/) are read-only and never written.
* Approved/auto-applied edits live in state/patches.json; the "live" question is
  original + patches, computed on read.
* Every action appends to state/audit.jsonl.
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import guard as G
from . import normalize as N
from . import taxonomy
from .audit import AuditLog
from .models import Edit

SYSTEM_ACTOR = "system:auto_apply"
DECIDED = ("approved", "edited", "rejected")  # faculty decisions; a new decision needs a reopen first


class StateFileError(RuntimeError):
    """A state file exists but cannot be read. The store refuses to start rather than treat
    it as empty, so existing faculty decisions are never silently dropped or overwritten."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, state_dir: Path | None = None, results_path: Path | None = None,
                 details_path: Path | None = None, bootstrap_auto_apply: bool = True):
        self.state_dir = Path(state_dir or config.STATE_DIR)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.results_path = Path(results_path or config.ROOT / "results.json")
        self.details_path = Path(details_path or config.ARTIFACTS_DIR / "triage_details.json")
        self.audit = AuditLog(self.state_dir / "audit.jsonl")
        self._lock = threading.RLock()
        self.questions = N.questions_by_id()
        self.reports = {r["reportId"]: r for r in N.reports()}
        self.results = self._load_json(self.results_path, [])
        self.details = self._load_json(self.details_path, {})
        self._patches_path = self.state_dir / "patches.json"
        self._status_path = self.state_dir / "case_status.json"
        self.patches: dict[str, list[dict]] = self._load_state(self._patches_path)
        self.status: dict[str, dict] = self._load_state(self._status_path)
        if bootstrap_auto_apply:
            self._bootstrap_auto_apply()

    # ------------------------------------------------------------ persistence
    @staticmethod
    def _load_json(p: Path, default):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return copy.deepcopy(default)

    @staticmethod
    def _load_state(p: Path) -> dict:
        """Faculty state (patches / case status). A missing file is a fresh state; a file that exists
        but is empty, truncated, not JSON or not an object is an error. Nothing is written."""
        p = Path(p)
        if not p.exists():
            return {}
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise StateFileError(
                f"State file {p} exists but could not be read ({type(e).__name__}: {e}). Faculty decisions were "
                f"not loaded and nothing was overwritten. Restore the file (or move it aside to start fresh), "
                f"then restart the server.") from e
        if not isinstance(obj, dict):
            raise StateFileError(
                f"State file {p} must contain a JSON object but contains {type(obj).__name__}. Faculty decisions "
                f"were not loaded and nothing was overwritten. Restore the file, then restart the server.")
        return obj

    def _save(self):
        """Write both state files to temp files first, then swap them in (no half-written state)."""
        staged = []
        for path, obj in ((self._patches_path, self.patches), (self._status_path, self.status)):
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
            staged.append((tmp, path))
        for tmp, path in staged:
            tmp.replace(path)

    # ------------------------------------------------------------ grouping
    def groups(self) -> dict[str, list[dict]]:
        g: dict[str, list[dict]] = {}
        for r in self.results:
            g.setdefault(r["questionId"], []).append(r)
        return g

    def live_question(self, qid: str, exclude_actor: str | None = None) -> dict:
        """Original + active patches. `exclude_actor` previews the question without that actor's
        patches (used to validate a faculty edit that would replace the system auto-apply)."""
        q = self.questions[qid]
        for p in self.patches.get(qid, []):
            if not p.get("reverted") and p["actor"] != exclude_actor:
                q = G.apply_edit(q, Edit(**p["edit"]))
        return q

    def _bootstrap_auto_apply(self):
        """auto_apply results are written to the patch layer once, by the system actor."""
        with self._lock:
            for qid, rows in self.groups().items():
                if qid in self.status:
                    continue
                auto = [r for r in rows if r["route"] == "auto_apply" and r.get("edit")]
                if not auto:
                    continue
                edit = auto[0]["edit"]
                q = self.live_question(qid)
                g = G.check_edit(q, auto[0]["repair"], edit)
                if not g.ok:  # never trust a stale results file blindly
                    self.status[qid] = {"state": "pending", "at": _now(), "by": "system",
                                        "note": "auto-apply blocked by guard at load: " + "; ".join(g.errors)}
                    continue
                self._apply_patch(qid, edit, SYSTEM_ACTOR, "auto_apply", [r["reportId"] for r in auto], q)
                self.status[qid] = {"state": "auto_applied", "at": _now(), "by": SYSTEM_ACTOR}
            self._save()

    def _stage_patch(self, qid, edit: dict, actor, action, report_ids, q_before, note="") -> dict:
        """Add a patch in memory and return the audit record to write once the action commits."""
        q_after = G.apply_edit(q_before, Edit(**edit))
        fb = edit["field"]
        before = N.body(q_before).get(fb) if fb != "questionType" else q_before["questionType"]
        after = N.body(q_after).get(fb) if fb != "questionType" else q_after["questionType"]
        self.patches.setdefault(qid, []).append({"edit": edit, "actor": actor, "at": _now(), "action": action})
        return dict(actor=actor, action=action, question_id=qid, report_ids=report_ids,
                    before=before, after=after, edit=edit, note=note)

    def _apply_patch(self, qid, edit: dict, actor, action, report_ids, q_before, note=""):
        self.audit.append(**self._stage_patch(qid, edit, actor, action, report_ids, q_before, note))

    # ------------------------------------------------------------ views
    def case_summary(self, qid: str, rows: list[dict]) -> dict:
        det = self.details.get(qid, {})
        tiers = [taxonomy.tier(r["verdict"], r.get("repair")) for r in rows]
        attention = any(v.get("needs_attention") for v in det.get("reports", {}).values())
        tier = min(tiers)
        if attention and tier == 5:
            tier = 1
        routes = {r["route"] for r in rows}
        route = "auto_apply" if "auto_apply" in routes else "faculty_review" if "faculty_review" in routes else "no_change"
        lead = sorted(rows, key=lambda r: (taxonomy.tier(r["verdict"], r.get("repair")), r["confidence"]))[0]
        q = self.questions[qid]
        reported = sorted(self.reports[r["reportId"]]["reportedAt"] for r in rows)
        st = self.status.get(qid, {"state": "pending"})
        return {
            "questionId": qid,
            "subject": q.get("subject"), "chapter": q.get("chapter"), "type": q["questionType"],
            "stem_preview": N.split_options(N.body(q).get("question", ""))[0][:140],
            "tier": tier, "tier_label": taxonomy.TIER_LABEL[tier],
            "verdict": lead["verdict"], "repair": lead.get("repair"), "route": route,
            "confidence": min(r["confidence"] for r in rows),
            "reporters": len({self.reports[r["reportId"]]["studentId"] for r in rows}),
            "reportIds": [r["reportId"] for r in rows],
            "oldest_report": reported[0], "newest_report": reported[-1],
            "status": st.get("state", "pending"),
            "needs_attention": attention,
            "attention_reason": next((v.get("attention_reason") for v in det.get("reports", {}).values()
                                      if v.get("attention_reason")), None),
            "headline": lead["evidence"][:160],
        }

    def queue(self) -> list[dict]:
        items = [self.case_summary(qid, rows) for qid, rows in self.groups().items()]
        items.sort(key=lambda c: (c["tier"], -c["reporters"], c["confidence"], c["oldest_report"]))
        for i, c in enumerate(items, 1):
            c["rank"] = i
        return items

    def suggestion(self, qid: str, rows: list[dict]) -> tuple[dict | None, dict | None]:
        """N1: decide whether the AI-proposed edit may be offered for one-click approval.

        Returns (approvable_edit, withheld). A proposal is withheld - shown as evidence, never
        approvable - when any report on the question is injection-flagged, or when an answer
        change is not confirmed by BOTH blind solvers (a solver disagrees or gave no definite answer).
        Faculty can still enter their own correction deliberately via the edit action."""
        proposed = next((r["edit"] for r in rows if r.get("edit")), None)
        if not proposed:
            return None, None
        det = self.details.get(qid, {})
        reasons = []
        flagged = det.get("injection_in_group") or any(
            any(f.get("code") == "injection" for f in (rd.get("flags") or []))
            for rd in (det.get("reports") or {}).values())
        if flagged:
            reasons.append("a report on this question tried to give the AI instructions (manipulation attempt)")
        if proposed["field"] == "answer":
            q = self.questions[qid]
            try:
                new = json.loads(proposed["replace"]) if q["questionType"] == "mcq" else proposed["replace"]
            except json.JSONDecodeError:
                new = None
            new_norm, _ = N.normalize_answer(q["questionType"], new)
            answers = (det.get("agreement") or {}).get("answers") or {}
            for name in ("A", "B"):
                a = answers.get(name)
                if a is None:
                    reasons.append(f"blind solver {name} did not confirm the proposed key")
                    continue
                a_norm, _ = N.normalize_answer(q["questionType"], a.split(",") if q["questionType"] == "mcq" else a)
                if q["questionType"] == "integerQuestion":
                    try:
                        same = abs(float(a_norm) - float(new_norm)) <= 1e-6
                    except (TypeError, ValueError):
                        same = False
                else:
                    same = a_norm == new_norm
                if not same:
                    reasons.append(f"blind solver {name} answered {a}, not the proposed {proposed['replace']}")
        if reasons:
            return None, {"proposed": proposed, "reasons": reasons}
        return proposed, None

    def case(self, qid: str) -> dict:
        rows = self.groups().get(qid)
        if not rows:
            raise KeyError(qid)
        q = self.questions[qid]
        live = self.live_question(qid)
        det = self.details.get(qid, {})
        b, lb = N.body(q), N.body(live)
        edit, withheld = self.suggestion(qid, rows)
        diff = self._diff(q, edit) if edit else None
        reports = []
        for r in sorted(rows, key=lambda r: self.reports[r["reportId"]]["reportedAt"]):
            raw = self.reports[r["reportId"]]
            rd = det.get("reports", {}).get(r["reportId"], {})
            reports.append({**r, "comment": raw["comment"], "studentId": raw["studentId"], "source": raw["source"],
                            "reportedAt": raw["reportedAt"], "flags": rd.get("flags", []),
                            "route_reasons": rd.get("route_reasons", []), "overrides": rd.get("overrides", []),
                            "guard_log": rd.get("guard_log", []),
                            "reply_if_fixed": rd.get("reply_if_fixed"), "reply_if_review": rd.get("reply_if_review")})
        _, opts = N.split_options(b.get("question", ""))
        return {
            **self.case_summary(qid, rows),
            "question_html": b.get("question", ""),
            "solution_html": b.get("solution", ""),
            "live_question_html": lb.get("question", ""),
            "live_solution_html": lb.get("solution", ""),
            "answer": N.answer_to_str(b.get("answer")),
            "live_answer": N.answer_to_str(lb.get("answer")),
            "options": opts,
            "has_images": bool(b.get("quesImages")),
            "errorHistory": q.get("errorHistory") or [],
            "edit": edit,
            "diff": diff,
            "solves": {k: {kk: v.get(kk) for kk in ("final_answer", "method", "confidence", "problems_noticed",
                                                      "numeric_check", "model", "error")}
                       for k, v in det.get("solves", {}).items()},
            "agreement": det.get("agreement"),
            "analysis": (det.get("judge") or {}).get("question_analysis"),
            "question_flags": det.get("question_flags", []),
            "injection_in_group": det.get("injection_in_group", False),
            "reports": reports,
            "patches": [p for p in self.patches.get(qid, []) if not p.get("reverted")],  # N2: history lives in the audit
            "suggestion_withheld": withheld,
            "status_detail": self.status.get(qid, {"state": "pending"}),
            "audit": self.audit.entries(qid),
        }

    @staticmethod
    def _diff(q: dict, edit: dict) -> dict:
        b = N.body(q)
        f = edit["field"]
        if f == "answer":
            _, opts = N.split_options(b.get("question", ""))
            return {"field": "answer", "before": edit["find"], "after": edit["replace"], "options": opts}
        if f == "questionType":
            return {"field": f, "before": edit["find"], "after": edit["replace"]}
        src = b.get(f) or ""
        return {
            "field": f,
            "find": edit["find"], "replace": edit["replace"],
            "before_html": src.replace(edit["find"], f'<del class="diff-del">{edit["find"]}</del>', 1),
            "after_html": src.replace(edit["find"], f'<ins class="diff-ins">{edit["replace"]}</ins>', 1),
        }

    # ------------------------------------------------------------ actions
    def act(self, qid: str, action: str, actor: str, note: str = "", edit: dict | None = None) -> dict:
        """Transactional: validate first, stage every change in memory, save state, and only then
        write audit entries. Any failure restores the previous in-memory state, so a refused request
        leaves the live question, status, patch file and audit trail exactly as they were."""
        actor = (actor or "").strip()[:60] or "faculty"
        with self._lock:
            rows = self.groups().get(qid)
            if not rows:
                raise KeyError(qid)
            rids = [r["reportId"] for r in rows]
            st = self.status.get(qid, {"state": "pending"})
            proposed, withheld = self.suggestion(qid, rows)  # N1: a withheld proposal is never applied
            q_live = self.live_question(qid)
            snapshot = (copy.deepcopy(self.patches), copy.deepcopy(self.status))
            pending_audit: list[dict] = []
            try:
                # Decision-state rules: one decision per case until it is reopened; only a decided case
                # can be reopened. Refused before anything is staged, so no state or audit changes.
                if action in ("approve", "edit", "reject") and st["state"] in DECIDED:
                    raise ValueError(f"case already {st['state']}; reopen it before making a new decision")
                if action == "reopen" and st["state"] not in DECIDED:
                    raise ValueError(f"case is {st['state'].replace('_', '-')}, not decided; there is nothing to reopen")
                if action == "approve":
                    if proposed and st["state"] != "auto_applied":
                        g = G.check_faculty_edit(q_live, proposed)
                        if not g.ok:
                            raise ValueError("proposed edit no longer valid: " + "; ".join(g.errors))
                        pending_audit.append(self._stage_patch(qid, proposed, actor, "approve", rids, q_live, note))
                    else:
                        default_note = "verdict confirmed"
                        if withheld:
                            default_note += "; AI suggestion withheld (not applied): " + "; ".join(withheld["reasons"])
                        pending_audit.append(dict(actor=actor, action="approve", question_id=qid, report_ids=rids,
                                                  before=st["state"], after="approved",
                                                  note=(note + " | " if note else "") + default_note if withheld else (note or default_note)))
                    self.status[qid] = {"state": "approved", "at": _now(), "by": actor}

                elif action == "edit":
                    if not edit:
                        raise ValueError("edit action needs an edit {field, find, replace}")
                    new_edit = Edit(**edit).model_dump()  # schema check (ValidationError is a ValueError)
                    replacing_auto = st["state"] == "auto_applied"
                    # 1. validate against the question as it will be once the system patch is replaced
                    base = self.live_question(qid, exclude_actor=SYSTEM_ACTOR) if replacing_auto else q_live
                    g = G.check_faculty_edit(base, new_edit)
                    if not g.ok:
                        raise ValueError("; ".join(g.errors))
                    # 2. only now stage the revert + the new patch (committed together below)
                    if replacing_auto:
                        pending_audit += self._stage_revert_system_patch(qid, actor, rids)
                    pending_audit.append(self._stage_patch(qid, new_edit, actor, "edit", rids, base, note))
                    self.status[qid] = {"state": "edited", "at": _now(), "by": actor}

                elif action == "reject":
                    if st["state"] == "auto_applied":
                        pending_audit += self._stage_revert_system_patch(qid, actor, rids)
                    pending_audit.append(dict(actor=actor, action="reject", question_id=qid, report_ids=rids,
                                              before=st["state"], after="rejected", note=note or "AI suggestion rejected"))
                    self.status[qid] = {"state": "rejected", "at": _now(), "by": actor}

                elif action == "reopen":
                    for p in self.patches.get(qid, []):
                        if not p.get("reverted") and p["actor"] != SYSTEM_ACTOR:
                            p["reverted"] = True
                    pending_audit.append(dict(actor=actor, action="reopen", question_id=qid, report_ids=rids,
                                              before=st["state"], after="pending", note=note))
                    self.status[qid] = {"state": "pending", "at": _now(), "by": actor}
                else:
                    raise ValueError(f"unknown action {action!r}")
                self._save()
            except Exception:
                self.patches, self.status = snapshot  # roll back every staged change
                raise
            for rec in pending_audit:  # the action is committed: now (and only now) record it
                self.audit.append(**rec)
            return self.case(qid)

    def reset_demo(self, actor: str, note: str = "") -> dict:
        """Restore the clean demo state. Nothing is deleted: current state files are moved to
        state/archive/<timestamp>/, a fresh audit log starts with a `demo_reset` entry that names
        the archive, and the precomputed auto-applies are re-applied. data/ is never touched."""
        with self._lock:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive = self.state_dir / "archive" / stamp
            archive.mkdir(parents=True, exist_ok=True)
            moved = []
            for name in ("audit.jsonl", "patches.json", "case_status.json"):
                src = self.state_dir / name
                if src.exists():
                    src.replace(archive / name)
                    moved.append(name)
            self.patches, self.status = {}, {}
            self.audit = AuditLog(self.state_dir / "audit.jsonl")
            entry = self.audit.append(actor=(actor or "admin")[:60], action="demo_reset", question_id="*",
                                      report_ids=[], before=f"archived to state/archive/{stamp}", after="clean",
                                      note=note[:200])
            self._bootstrap_auto_apply()
            return {"reset_at": entry["at"], "archived": f"state/archive/{stamp}", "files": moved,
                    "auto_applied_again": sum(1 for s in self.status.values() if s.get("state") == "auto_applied")}

    def _stage_revert_system_patch(self, qid, actor, rids) -> list[dict]:
        """Mark the system auto-apply patch reverted in memory; return audit records for commit."""
        recs = []
        for p in self.patches.get(qid, []):
            if p["actor"] == SYSTEM_ACTOR and not p.get("reverted"):
                p["reverted"] = True
                recs.append(dict(actor=actor, action="revert_auto_apply", question_id=qid, report_ids=rids,
                                 before=p["edit"].get("replace"), after=p["edit"].get("find"), edit=p["edit"]))
        return recs
