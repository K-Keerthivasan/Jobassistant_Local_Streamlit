"""Application ledger and dashboard (brief section 7).

The ledger is a view over the queue (`jobs`), generated runs and outreach
messages. The app records `date_built` and everything derived; Keerthi sets
`date_sent`, `status` and `notes`. Outreach status is derived and read-only.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from .intake import db
from .intake.store import get_job, list_queue
from .outreach import store as ostore
from .outreach.contacts import list_contacts, norm_company

LEDGER_STATUSES = ("pending", "sent", "no_response", "screening", "interview", "offer", "rejected", "withdrawn")
LIVE = {"sent", "no_response", "screening", "interview"}


def _runs_index() -> dict[str, str]:
    with db.connect() as conn:
        return {r["run_id"]: r["created_at"] for r in conn.execute("SELECT run_id, created_at FROM runs")}


def _outreach_by_job() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for m in ostore.list_messages(limit=5000):
        if m.get("job_id"):
            out[m["job_id"]].append(m)
    return out


def _best_contact_email() -> dict[str, str]:
    rank = {"verified": 2, "enriched": 1, "pattern_guess": 0}
    best: dict[str, tuple[int, str]] = {}
    for c in list_contacts():
        if not c.get("hr_email") or c.get("do_not_contact"):
            continue
        key = c.get("company_norm") or norm_company(c.get("company", ""))
        r = rank.get(c.get("confidence"), 0)
        if key not in best or r > best[key][0]:
            best[key] = (r, c["hr_email"])
    return {k: v[1] for k, v in best.items()}


def _derive_status(q) -> str:
    if q.ledger_status:
        return q.ledger_status
    if q.applied or q.status in ("sent", "applied"):
        return "sent"
    return "pending"


def _outreach_status(msgs: list[dict]) -> str:
    if not msgs:
        return ""
    order = ["replied", "bounced", "failed", "sent", "sending", "approved", "queued", "draft", "cancelled"]
    for s in order:
        if any(m["status"] == s for m in msgs):
            return s
    return msgs[0]["status"]


def rows(*, include_irrelevant: bool = False, only_batches: bool = True) -> list[dict]:
    runs = _runs_index()
    outreach = _outreach_by_job()
    emails = _best_contact_email()
    out = []
    for q in list_queue():
        if q.irrelevant and not include_irrelevant:
            continue
        if only_batches and not (q.batches or q.lane_slug or q.grade):
            continue
        msgs = outreach.get(q.key_id, [])
        sent_dates = [m.get("sent_at", "") for m in msgs if m.get("sent_at")]
        touches = [d for d in [q.date_sent, q.sent_at, *(q.followups or []), *sent_dates, q.last_touch] if d]
        last_touch = max(touches)[:10] if touches else ""
        status = _derive_status(q)
        days_since = (date.today() - date.fromisoformat(last_touch)).days if last_touch else None
        out.append({
            "key_id": q.key_id, "company": q.company, "role_title": q.title, "lane": q.lane_slug or q.lane,
            "noc_code": q.noc, "teer": q.teer,
            "pathway_tag": f"{q.pathway_type}: {q.pathway_detail}" if q.pathway_type else "",
            "pathway_type": q.pathway_type, "remote_type": q.remote_type, "hire_type": q.hire_type,
            "stream": q.stream, "run_date": q.run_date, "apply_url": q.apply_url,
            "hr_email": q.contact_email or emails.get(norm_company(q.company), ""),
            "tier": (q.grade or {}).get("tier", ""), "gap_flags": (q.grade or {}).get("gap_flags_text", ""),
            "seniority_warning": bool((q.seniority or {}).get("warning")),
            "date_built": (runs.get(q.notes, "") or "")[:10] if q.notes else "",
            "date_sent": q.date_sent or (q.sent_at or "")[:10], "status": status,
            "outreach_status": _outreach_status(msgs), "outreach_count": len(msgs),
            "last_touch": last_touch, "days_since_last_touch": days_since,
            "notes": q.notes if not q.notes.startswith(q.company.split(" ")[0] if q.company else "\x00") else "",
            "run_id": q.notes, "applied": q.applied,
        })
    return out


def set_ledger(key_id: str, *, date_sent: str | None = None, status: str | None = None,
               notes: str | None = None) -> dict:
    q = get_job(key_id)
    if q is None:
        raise KeyError(key_id)
    if status is not None:
        if status not in LEDGER_STATUSES:
            raise ValueError(f"status must be one of {LEDGER_STATUSES}")
        q.ledger_status = status
        if status == "sent" and not q.date_sent:
            q.date_sent = date.today().isoformat()
        if status in ("sent", "screening", "interview", "offer"):
            q.applied = True
    if date_sent is not None:
        q.date_sent = date_sent
        if date_sent and not q.ledger_status:
            q.ledger_status = "sent"
            q.applied = True
    if notes is not None:
        q.ledger_notes = notes  # type: ignore[attr-defined]
    q.last_touch = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        db._upsert_job_row(conn, json.loads(q.model_dump_json()))
    return q.model_dump()


def dashboard() -> dict:
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    all_rows = rows()
    sent_week = [r for r in all_rows if r["date_sent"] and r["date_sent"] >= week_ago]
    by_lane = Counter(r["lane"] or "unresolved" for r in sent_week)
    by_pathway = Counter(r["pathway_type"] or "none" for r in sent_week)
    tier_mix = Counter(r["tier"] or "ungraded" for r in all_rows)

    msgs = ostore.list_messages(limit=5000)
    delivered = [m for m in msgs if m["status"] in ("sent", "replied", "bounced")]
    by_template: dict[str, dict] = defaultdict(lambda: {"sent": 0, "replied": 0})
    by_conf: dict[str, dict] = defaultdict(lambda: {"sent": 0, "replied": 0, "bounced": 0})
    for m in delivered:
        by_template[m.get("template_id", "")]["sent"] += 1
        by_conf[m.get("contact_confidence") or "unknown"]["sent"] += 1
        if m["status"] == "replied":
            by_template[m.get("template_id", "")]["replied"] += 1
            by_conf[m.get("contact_confidence") or "unknown"]["replied"] += 1
        if m["status"] == "bounced":
            by_conf[m.get("contact_confidence") or "unknown"]["bounced"] += 1

    def _rate(d):
        return {k: {**v, "reply_rate": round(v["replied"] / v["sent"], 3) if v["sent"] else 0.0} for k, v in d.items()}

    live = [r for r in all_rows if r["status"] in LIVE]
    stale = sorted([r for r in live if r["days_since_last_touch"] is not None],
                   key=lambda r: -r["days_since_last_touch"])
    designated_untouched = [r for r in all_rows if r["pathway_type"] in ("AIP", "RCIP")
                            and not r["date_sent"] and not r["outreach_count"]]
    return {
        "as_of": today.isoformat(),
        "applications_this_week": len(sent_week),
        "by_lane_this_week": dict(by_lane),
        "by_pathway_this_week": dict(by_pathway),
        "tier_mix": dict(tier_mix),
        "reply_rate_by_template": _rate(by_template),
        "reply_rate_by_confidence": _rate(by_conf),
        "live_applications": len(live),
        "days_since_last_touch": [{"company": r["company"], "role_title": r["role_title"], "status": r["status"],
                                   "days": r["days_since_last_touch"]} for r in stale[:25]],
        "designated_untouched": [{"company": r["company"], "role_title": r["role_title"], "pathway": r["pathway_tag"],
                                  "tier": r["tier"], "key_id": r["key_id"], "hr_email": r["hr_email"]}
                                 for r in sorted(designated_untouched, key=lambda r: (r["tier"] or "Z", r["company"]))],
        "outreach": {"queued": sum(1 for m in msgs if m["status"] == "queued"),
                     "approved": sum(1 for m in msgs if m["status"] == "approved"),
                     "sent_today": ostore.sent_count_on(today), "daily_cap": ostore.daily_cap(),
                     "kill_switch": ostore.kill_switch_on()},
        "totals": {"rows": len(all_rows), "graded": sum(1 for r in all_rows if r["tier"]),
                   "seniority_warnings": sum(1 for r in all_rows if r["seniority_warning"])},
    }
