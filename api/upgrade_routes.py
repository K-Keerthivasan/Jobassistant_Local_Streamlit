"""Routes added by the v3.5 upgrade: lane data, batch import, grading, outreach,
ledger and dashboard. Registered onto the main FastAPI app from api/server.py
(``register(app)``) so the 2,000-line server module is touched as little as
possible.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Body, Header, HTTPException
from pydantic import BaseModel

from resume_gen import lanes as lane_data
from resume_gen import ledger
from resume_gen.intake import batch_import as bi
from resume_gen.intake.store import get_job
from resume_gen.outreach import contacts as oc
from resume_gen.outreach import dispatch, draft, store, templates


# --------------------------------------------------------------------------- #
# request bodies
# --------------------------------------------------------------------------- #
class BatchFileIn(BaseModel):
    name: str
    csv: str


class BatchImportIn(BaseModel):
    files: list[BatchFileIn]
    grade: bool = True


class LaneSetIn(BaseModel):
    lane: str            # slug, number or short name


class DraftIn(BaseModel):
    contact_id: str
    template_id: str
    job_key: str = ""
    lane: str = ""
    applied_on: str = ""


class IdsIn(BaseModel):
    ids: list[str]


class EditIn(BaseModel):
    subject: str | None = None
    body: str | None = None


class ContactIn(BaseModel):
    company: str
    hr_email: str
    hr_name: str = ""
    hr_phone: str = ""
    ats: str = ""
    careers_url: str = ""
    notes: str = ""
    confidence: str = "verified"     # a hand entry is verified by definition
    set_by: str = "keerthi"


class SuppressIn(BaseModel):
    key: str
    kind: str = "email"       # email | domain | company
    reason: str = ""


class StateIn(BaseModel):
    value: str


class LedgerIn(BaseModel):
    date_sent: str | None = None
    status: str | None = None
    notes: str | None = None


class CallbackIn(BaseModel):
    message_id: str
    event: str
    at: str = ""
    provider_message_id: str = ""
    thread_id: str = ""
    detail: dict = {}


def register(app) -> None:
    from pathlib import Path as _P

    from fastapi.responses import FileResponse

    _web = _P(__file__).resolve().parents[1] / "web"

    @app.get("/upgrade.js", include_in_schema=False)
    def _upgrade_js():
        return FileResponse(_web / "upgrade.js", media_type="application/javascript")

    @app.get("/upgrade.css", include_in_schema=False)
    def _upgrade_css():
        return FileResponse(_web / "upgrade.css", media_type="text/css")

    # ------------------------------------------------------------------ lanes
    @app.get("/lanes")
    def lanes_list():
        return {"instruction_set_version": lane_data.load_index().version,
                "lanes": [{"lane": l.lane, "slug": l.slug, "title": l.title, "track": l.track, "set": l.set,
                           "noc": l.noc_codes(), "persona": l.persona, "links": l.links, "version": l.version,
                           "skills": len(l.skills), "held": sum(1 for s in l.skills if s.status == "held"),
                           "partial": sum(1 for s in l.skills if s.status == "partial")}
                          for l in lane_data.all_lanes()]}

    @app.get("/lanes/status")
    def lanes_status():
        return lane_data.status_report()

    @app.post("/lanes/sync")
    def lanes_sync(check: bool = False):
        from resume_gen.lanes.sync import LaneSyncError, sync_all
        try:
            rep = sync_all(check_only=check)
        except LaneSyncError as e:
            raise HTTPException(status_code=400, detail=str(e))
        lane_data.reload()
        return rep

    @app.get("/lanes/{slug}")
    def lane_get(slug: str):
        lane = lane_data.get_lane(slug) or lane_data.resolve_lane(slug)
        if lane is None:
            raise HTTPException(status_code=404, detail="Lane not found.")
        return lane.model_dump()

    # ----------------------------------------------------------------- import
    @app.post("/import/batch")
    def import_batch(req: BatchImportIn):
        if not req.files:
            raise HTTPException(status_code=400, detail="No files.")
        return bi.import_batch([(f.name, f.csv) for f in req.files], grade=req.grade)

    @app.get("/import/batches")
    def import_batches(limit: int = 50):
        return {"batches": bi.list_batches(limit)}

    @app.get("/import/batches/{batch_id}")
    def import_batch_get(batch_id: str):
        b = bi.get_batch(batch_id)
        if b is None:
            raise HTTPException(status_code=404, detail="Batch not found.")
        return b

    # ---------------------------------------------------------------- grading
    @app.post("/jobs/regrade")
    def regrade_all():
        return bi.regrade_all()

    @app.post("/jobs/{key_id}/grade")
    def grade_one(key_id: str):
        q = get_job(key_id)
        if q is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        out = bi.regrade_all(only_keys=[key_id])
        return {"result": out, "job": get_job(key_id).model_dump()}

    @app.post("/jobs/{key_id}/lane")
    def set_lane(key_id: str, req: LaneSetIn):
        import json
        from resume_gen.intake import db
        q = get_job(key_id)
        if q is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        lane = lane_data.get_lane(req.lane) or lane_data.resolve_lane(req.lane)
        if lane is None:
            raise HTTPException(status_code=400, detail=f"No lane matches {req.lane!r}.")
        q.lane_slug, q.lane, q.track = lane.slug, lane.title, lane.track
        with db.connect() as conn:
            db._upsert_job_row(conn, json.loads(q.model_dump_json()))
        bi.regrade_all(only_keys=[key_id])
        return get_job(key_id).model_dump()

    # --------------------------------------------------------------- outreach
    @app.get("/outreach/templates")
    def outreach_templates():
        return lane_data.load_outreach_templates()

    @app.get("/outreach/contacts")
    def outreach_contacts(company: str = ""):
        return {"contacts": oc.list_contacts(company or None)}

    @app.get("/outreach/contacts/missing")
    def outreach_contacts_missing():
        companies = sorted({r["company"] for r in ledger.rows()})
        return {"companies": oc.companies_without_contacts(companies)}

    @app.post("/outreach/contacts")
    def outreach_contact_save(req: ContactIn):
        c, outcome = oc.upsert_contact(company=req.company, hr_email=req.hr_email, hr_name=req.hr_name,
                                       hr_phone=req.hr_phone, ats=req.ats, careers_url=req.careers_url,
                                       notes=req.notes, source="manual", confidence=req.confidence,
                                       set_by=req.set_by, override=True)
        store.log_event("contact_edited", contact_id=c["id"], actor=req.set_by, data={"outcome": outcome})
        return {"contact": c, "outcome": outcome}

    @app.post("/outreach/contacts/{contact_id}/do-not-contact")
    def outreach_contact_dnc(contact_id: str, flag: bool = True, reason: str = ""):
        c = oc.set_do_not_contact(contact_id, flag, reason)
        if c is None:
            raise HTTPException(status_code=404, detail="Contact not found.")
        return c

    @app.post("/outreach/draft")
    def outreach_draft(req: DraftIn):
        try:
            msgs = draft.draft_sequence(contact_id=req.contact_id, template_id=req.template_id,
                                        job_key=req.job_key, lane_slug=req.lane, applied_on=req.applied_on)
        except (templates.TemplateError, KeyError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"messages": msgs}

    @app.get("/outreach/messages")
    def outreach_messages(status: str = "", company: str = ""):
        sts = [s for s in status.split(",") if s] or None
        msgs = store.list_messages(sts, company=company)
        # Group by company for the review screen.
        grouped: dict[str, list] = {}
        for m in msgs:
            grouped.setdefault(m.get("company") or "", []).append(m)
        return {"messages": msgs, "by_company": grouped,
                "kill_switch": store.kill_switch_on(), "daily_cap": store.daily_cap(),
                "sent_today": store.sent_count_on(datetime.now().date()), "cooldown_days": store.cooldown_days()}

    @app.get("/outreach/messages/{mid}")
    def outreach_message(mid: str):
        m = store.get_message(mid)
        if m is None:
            raise HTTPException(status_code=404, detail="Message not found.")
        return {"message": m, "events": store.events(message_id=mid),
                "contact": oc.get_contact(m.get("contact_id", "")),
                "job": (get_job(m["job_id"]).model_dump() if m.get("job_id") and get_job(m["job_id"]) else None)}

    @app.post("/outreach/messages/{mid}/edit")
    def outreach_edit(mid: str, req: EditIn):
        try:
            return draft.rerender(mid, subject=req.subject, body=req.body)
        except (templates.TemplateError, KeyError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/outreach/approve")
    def outreach_approve(req: IdsIn):
        """The approval gate. Only this flips queued -> approved."""
        return {"approved": store.approve(req.ids, actor="keerthi")}

    @app.post("/outreach/cancel")
    def outreach_cancel(req: IdsIn):
        out = []
        for mid in req.ids:
            try:
                out.append(store.set_status(mid, "cancelled", actor="keerthi", reason="cancelled in review"))
            except (KeyError, ValueError) as e:
                out.append({"id": mid, "error": str(e)})
        return {"cancelled": out}

    @app.post("/outreach/dispatch")
    def outreach_dispatch(req: IdsIn | None = None, test: bool = False):
        ids = req.ids if req and req.ids else None
        return dispatch.dispatch_due(actor="keerthi", message_ids=ids, test=test)

    @app.post("/outreach/preview")
    def outreach_preview(req: IdsIn | None = None):
        """What would go, and what would not, without sending anything."""
        from resume_gen.outreach.guardrails import check
        msgs = store.list_messages("approved")
        if req and req.ids:
            msgs = [m for m in msgs if m["id"] in set(req.ids)]
        return {"preview": [{"message_id": m["id"], "company": m.get("company"), "to": m.get("to_email"),
                             **check(m).__dict__} for m in msgs]}

    @app.post("/api/outreach/callback")
    def outreach_callback(req: CallbackIn, x_outreach_secret: str | None = Header(default=None)):
        if not dispatch.secret_ok(x_outreach_secret):
            store.log_event("callback_rejected", data={"reason": "bad or missing secret", "message_id": req.message_id})
            raise HTTPException(status_code=401, detail="Bad or missing X-Outreach-Secret.")
        try:
            return dispatch.handle_callback(req.model_dump())
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown message_id.")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/outreach/events")
    def outreach_events(kind: str = "", message_id: str = "", limit: int = 200):
        return {"events": store.events(kind=kind, message_id=message_id, limit=limit)}

    @app.get("/outreach/suppression")
    def outreach_suppression():
        return {"suppression": store.suppression_list()}

    @app.post("/outreach/suppression")
    def outreach_suppress(req: SuppressIn):
        key = req.key.strip().lower()
        if req.kind == "company":
            key = oc.norm_company(req.key)
        elif req.kind == "domain" and not key.startswith("@"):
            key = "@" + key
        store.suppress(key, req.kind, req.reason)
        return {"suppression": store.suppression_list()}

    @app.delete("/outreach/suppression/{key:path}")
    def outreach_unsuppress(key: str):
        store.unsuppress(key)
        return {"suppression": store.suppression_list()}

    @app.get("/outreach/state")
    def outreach_state():
        return {"kill_switch": store.kill_switch_on(), "daily_cap": store.daily_cap(),
                "cooldown_days": store.cooldown_days(),
                "sent_today": store.sent_count_on(datetime.now().date()),
                "webhook_configured": bool(__import__("resume_gen.config", fromlist=["settings"]).settings.outreach_webhook_url),
                "secret_configured": bool(__import__("resume_gen.config", fromlist=["settings"]).settings.outreach_shared_secret)}

    @app.post("/outreach/state/{key}")
    def outreach_state_set(key: str, req: StateIn):
        if key not in ("kill_switch", "daily_cap", "cooldown_days"):
            raise HTTPException(status_code=400, detail="Unknown setting.")
        store.set_state(key, req.value)
        return outreach_state()

    # ----------------------------------------------------------------- ledger
    @app.get("/ledger")
    def ledger_rows(include_irrelevant: bool = False, all_jobs: bool = False):
        return {"rows": ledger.rows(include_irrelevant=include_irrelevant, only_batches=not all_jobs),
                "statuses": list(ledger.LEDGER_STATUSES)}

    @app.post("/ledger/{key_id}")
    def ledger_set(key_id: str, req: LedgerIn):
        try:
            return ledger.set_ledger(key_id, date_sent=req.date_sent, status=req.status, notes=req.notes)
        except KeyError:
            raise HTTPException(status_code=404, detail="Job not found.")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/dashboard")
    def dashboard():
        return ledger.dashboard()
