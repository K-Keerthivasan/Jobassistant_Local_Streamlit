"""Draft an outreach sequence for one contact (brief 6.2, 6.3).

A sequence is one or more message rows. Step 1 is rendered now; later steps are
rendered now too (so Keerthi reviews the exact text) and scheduled by their
delay. Every row starts `queued`, which means "waiting for approval": nothing in
here can approve, and nothing can dispatch a row that was never approved.

A `pattern_guess` address gets step 1 only, and only from templates that allow
a single touch to a guessed address.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .. import lanes as lane_data
from ..grading.grader import build_fit_sentence
from ..intake.store import get_job
from . import store, templates
from .contacts import get_contact


def lane_fit_sentence(lane_slug: str) -> str:
    """For a cold approach with no posting: the strongest evidence-traced sentence
    the lane's Must-tier held skills can support. Empty when the lane has none."""
    lane = lane_data.get_lane(lane_slug)
    if lane is None:
        return ""
    matched = [{"skill": s, "where": "hard", "terms": [s.name]}
               for s in lane.skills if s.tier in ("must", "important") and s.fit_sentence_source]
    sentence, _ = build_fit_sentence(lane.title, matched)
    return sentence


def draft_sequence(*, contact_id: str, template_id: str, job_key: str = "", lane_slug: str = "",
                   applied_on: str = "", actor: str = "keerthi", start_at: datetime | None = None) -> list[dict]:
    contact = get_contact(contact_id)
    if contact is None:
        raise KeyError(f"contact {contact_id} not found")
    if contact.get("do_not_contact"):
        raise templates.TemplateError("contact is marked do_not_contact")
    if store.is_suppressed(email=contact.get("hr_email", ""), company=contact.get("company", "")):
        raise templates.TemplateError("contact or company is on the suppression list")

    job = None
    if job_key:
        q = get_job(job_key)
        if q is None:
            raise KeyError(f"job {job_key} not found")
        job = q.model_dump()
    elif lane_slug:
        lane = lane_data.get_lane(lane_slug)
        if lane is None:
            raise templates.TemplateError(f"unknown lane {lane_slug}")
        job = {"company": contact.get("company", ""), "title": "", "lane_slug": lane.slug, "lane": lane.title,
               "grade": {"fit_sentence": lane_fit_sentence(lane.slug), "tier": "", "gap_flags": []},
               "pathway_type": "", "pathway_detail": ""}
        # A designated employer's programme lives on the contact record.
        ds = (contact.get("designated_employer_status") or "")
        notes = (contact.get("notes") or "").lower()
        if ds:
            job["pathway_type"] = "RCIP" if "rcip" in notes else "AIP" if "aip" in notes or "atlantic" in notes else "designated employer"
            job["pathway_detail"] = "Rural Community Immigration Pilot" if job["pathway_type"] == "RCIP" else \
                "Atlantic Immigration Program" if job["pathway_type"] == "AIP" else "designated employer"

    t = templates.get_template(template_id)
    if contact.get("confidence") == "pattern_guess" and not t.get("allowed_for_pattern_guess", True):
        raise templates.TemplateError("this template is never sent to a pattern_guess address")

    start = start_at or datetime.now()
    steps = t.get("sequence") or [{"step": 1, "delay_days": 0, "template_id": template_id}]
    if contact.get("confidence") == "pattern_guess":
        steps = steps[:1]          # single touch, ever
    seq_id = None
    out = []
    run_id = (job or {}).get("notes", "") if job else ""
    for st in steps:
        r = templates.render(st["template_id"], job, contact, applied_on=applied_on)
        when = (start + timedelta(days=int(st.get("delay_days") or 0))).isoformat(timespec="seconds")
        m = store.create_message(contact=contact, job=job, template_id=st["template_id"],
                                 subject=r["subject"], body=r["body"], sequence_id=seq_id or "",
                                 sequence_step=int(st.get("step") or 1), scheduled_for=when,
                                 attach_resume=r["attach_resume"], run_id=run_id if r["attach_resume"] else "",
                                 meta={"variables": r["variables_used"], "word_count": r["word_count"]}, actor=actor)
        seq_id = m["sequence_id"]
        out.append(store.set_status(m["id"], "queued", actor=actor, reason="drafted, awaiting approval"))
    return out


def rerender(message_id: str, *, subject: str | None = None, body: str | None = None,
             actor: str = "keerthi") -> dict:
    """Keerthi edits a queued message before approving. Edits are checked against
    the same rules as a render and recorded."""
    m = store.get_message(message_id)
    if m is None:
        raise KeyError(message_id)
    if m["status"] not in ("draft", "queued"):
        raise templates.TemplateError("only draft or queued messages can be edited")
    r = templates.rules()
    new_subject = (subject if subject is not None else m["subject"]).strip()
    new_body = (body if body is not None else m["body"]).strip()
    if len(new_subject) > r.get("subject_max_chars", 60):
        raise templates.TemplateError("subject longer than 60 characters")
    if len(new_body.split()) > r.get("body_max_words", 150):
        raise templates.TemplateError("body over 150 words")
    low = (new_subject + " " + new_body).lower()
    allowed = set(r.get("immigration_pathway_allowed_in", []))
    for w in r.get("never_mention", []):
        if w.lower() in low and m.get("template_id") not in allowed:
            raise templates.TemplateError(f"message mentions '{w}'")
    return store.set_status(message_id, m["status"], actor=actor, reason="edited",
                            patch={"subject": new_subject, "body": new_body, "edited_by": actor}, force=True)
