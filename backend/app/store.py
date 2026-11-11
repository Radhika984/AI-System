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
        self.patches: dict[str, list[dict]] = self._load_json(self._patches_path, {})
        self.status: dict[str, dict] = self._load_json(self._status_path, {})
        if bootstrap_auto_apply:
            self._bootstrap_auto_apply()

    # ------------------------------------------------------------ persistence
    @staticmethod
    def _load_json(p: Path, default):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return copy.deepcopy(default)

    def _save(self):
        for path, obj in ((self._patches_path, self.patches), (self._status_path, self.status)):
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)

    # ------------------------------------------------------------ grouping
    def groups(self) -> dict[str, list[dict]]:
        g: dict[str, list[dict]] = {}
        for r in self.results:
            g.setdefault(r["questionId"], []).append(r)
        return g

    def live_question(self, qid: str) -> dict:
        q = self.questions[qid]
        for p in self.patches.get(qid, []):
            if not p.get("reverted"):
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

    def _apply_patch(self, qid, edit: dict, actor, action, report_ids, q_before, note=""):
        q_after = G.apply_edit(q_before, Edit(**edit))
        fb = edit["field"]
        before = N.body(q_before).get(fb) if fb != "questionType" else q_before["questionType"]
        after = N.body(q_after).get(fb) if fb != "questionType" else q_after["questionType"]
        self.patches.setdefault(qid, []).append({"edit": edit, "actor": actor, "at": _now(), "action": action})
        self.audit.append(actor=actor, action=action, question_id=qid, report_ids=report_ids,
                          before=before, after=after, edit=edit, note=note)

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
            "tier": tier, "tier_label": taxonomy.TIER_LABEL[tier] if not (attention and min(tiers) == 5) else "AI unsure - solvers dispute the key",
            "verdict": lead["verdict"], "repair": lead.get("repair"), "route": route,
            "confidence": min(r["confidence"] for r in rows),
            "reporters": len({self.reports[r["reportId"]]["studentId"] for r in rows}),
            "reportIds": [r["reportId"] for r in rows],
            "oldest_report": reported[0], "newest_report": reported[-1],
            "status": st.get("state", "pending"),
            "needs_attention": attention,
            "headline": lead["evidence"][:160],
        }

    def queue(self) -> list[dict]:
        items = [self.case_summary(qid, rows) for qid, rows in self.groups().items()]
        items.sort(key=lambda c: (c["tier"], -c["reporters"], c["confidence"], c["oldest_report"]))
        for i, c in enumerate(items, 1):
            c["rank"] = i
        return items

    def case(self, qid: str) -> dict:
        rows = self.groups().get(qid)
        if not rows:
            raise KeyError(qid)
        q = self.questions[qid]
        live = self.live_question(qid)
        det = self.details.get(qid, {})
        b, lb = N.body(q), N.body(live)
        edit = next((r["edit"] for r in rows if r.get("edit")), None)
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
            "patches": self.patches.get(qid, []),
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
        actor = (actor or "").strip()[:60] or "faculty"
        with self._lock:
            rows = self.groups().get(qid)
            if not rows:
                raise KeyError(qid)
            rids = [r["reportId"] for r in rows]
            st = self.status.get(qid, {"state": "pending"})
            proposed = next((r["edit"] for r in rows if r.get("edit")), None)
            q_live = self.live_question(qid)

            if action == "approve":
                if st["state"] in ("approved", "edited"):
                    raise ValueError(f"case already {st['state']}")
                if proposed and st["state"] != "auto_applied":
                    g = G.check_faculty_edit(q_live, proposed)
                    if not g.ok:
                        raise ValueError("proposed edit no longer valid: " + "; ".join(g.errors))
                    self._apply_patch(qid, proposed, actor, "approve", rids, q_live, note)
                else:
                    self.audit.append(actor=actor, action="approve", question_id=qid, report_ids=rids,
                                      before=st["state"], after="approved", note=note or "verdict confirmed")
                self.status[qid] = {"state": "approved", "at": _now(), "by": actor}

            elif action == "edit":
                if not edit:
                    raise ValueError("edit action needs an edit {field, find, replace}")
                if st["state"] == "auto_applied":  # replace the system patch with the faculty one
                    self._revert_system_patch(qid, actor, rids)
                    q_live = self.live_question(qid)
                g = G.check_faculty_edit(q_live, edit)
                if not g.ok:
                    raise ValueError("; ".join(g.errors))
                self._apply_patch(qid, Edit(**edit).model_dump(), actor, "edit", rids, q_live, note)
                self.status[qid] = {"state": "edited", "at": _now(), "by": actor}

            elif action == "reject":
                if st["state"] == "auto_applied":
                    self._revert_system_patch(qid, actor, rids)
                self.audit.append(actor=actor, action="reject", question_id=qid, report_ids=rids,
                                  before=st["state"], after="rejected", note=note or "AI suggestion rejected")
                self.status[qid] = {"state": "rejected", "at": _now(), "by": actor}

            elif action == "reopen":
                for p in self.patches.get(qid, []):
                    if not p.get("reverted") and p["actor"] != SYSTEM_ACTOR:
                        p["reverted"] = True
                self.audit.append(actor=actor, action="reopen", question_id=qid, report_ids=rids,
                                  before=st["state"], after="pending", note=note)
                self.status[qid] = {"state": "pending", "at": _now(), "by": actor}
            else:
                raise ValueError(f"unknown action {action!r}")
            self._save()
            return self.case(qid)

    def _revert_system_patch(self, qid, actor, rids):
        for p in self.patches.get(qid, []):
            if p["actor"] == SYSTEM_ACTOR and not p.get("reverted"):
                p["reverted"] = True
                self.audit.append(actor=actor, action="revert_auto_apply", question_id=qid, report_ids=rids,
                                  before=p["edit"].get("replace"), after=p["edit"].get("find"), edit=p["edit"])
