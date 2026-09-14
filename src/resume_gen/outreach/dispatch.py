"""Hand approved messages to n8n, and take n8n's callbacks (brief 6.4).

Outbound: POST to OUTREACH_WEBHOOK_URL with ``X-Outreach-Secret``. n8n must
acknowledge with ``{"accepted": true, "batch_id": <the batch_id we sent>}`` or the
messages stay `approved` and the failure is recorded and shown. A message that
was posted moves to `sending`; only n8n's `sent` callback makes it `sent`.

Inbound: ``handle_callback(payload)`` is idempotent on (message_id, event). A
`replied` stops every pending step for that contact immediately; a `bounced`
marks the address bad and stops the sequence; `failed` records the error and
stops the sequence; `opened` only stamps the time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import date, datetime

import httpx

from ..config import settings
from . import store
from .contacts import get_contact, mark_bad_address
from .guardrails import check

CALLBACK_EVENTS = ("sent", "bounced", "failed", "replied", "opened")


def secret_ok(header_value: str | None) -> bool:
    """Constant-time check; an unset secret refuses everything (never open by default)."""
    want = (settings.outreach_shared_secret or "").strip()
    if not want:
        return False
    return hmac.compare_digest(want, (header_value or "").strip())


def _attachment(m: dict) -> list[dict]:
    """Resume PDF for the job's stored run, inline (the app has no public URL)."""
    if not m.get("attach_resume") or not m.get("run_id"):
        return []
    try:
        from ..intake import runs as runs_store
        from ..render.ondemand import render_artifact
        bundle = runs_store.get_run(m["run_id"])
        if not bundle:
            return []
        content, filename, _ = render_artifact(bundle, "resume.pdf")
        return [{"filename": filename, "content_base64": base64.b64encode(content).decode(),
                 "sha256": hashlib.sha256(content).hexdigest(), "url": None}]
    except Exception as e:  # visible, never silent
        store.log_event("attachment_failed", message_id=m["id"], contact_id=m.get("contact_id", ""),
                        data={"error": str(e)})
        return []


def build_payload(messages: list[dict]) -> dict:
    batch_id = uuid.uuid4().hex
    return {
        "batch_id": batch_id,
        "sent_at": datetime.now().isoformat(timespec="seconds"),
        "messages": [{
            "message_id": m["id"],
            "to": {"email": m.get("to_email", ""), "name": m.get("to_name", "")},
            "company": m.get("company", ""),
            "subject": m.get("subject", ""),
            "body_text": m.get("body", ""),
            "body_html": None,
            "attachments": _attachment(m),
            "thread_id": m.get("thread_id") or None,
            "sequence_step": int(m.get("sequence_step") or 1),
            "scheduled_for": m.get("scheduled_for", ""),
            "meta": {"job_id": m.get("job_id", ""), "lane": m.get("lane", ""),
                     "pathway": m.get("pathway", ""), "template_id": m.get("template_id", ""),
                     "sequence_id": m.get("sequence_id", "")},
        } for m in messages],
    }


def dispatch_due(*, actor: str = "keerthi", now: datetime | None = None, post=None,
                 message_ids: list[str] | None = None, test: bool = False) -> dict:
    """Send every dispatchable approved message (or just ``message_ids``).

    ``post`` lets tests inject a fake webhook; it receives (url, payload, headers)
    and returns a dict. Returns a report: sent, blocked (with reasons), deferred,
    and any webhook error. Nothing is dropped: blocked and deferred rows stay
    `approved` and keep their reasons on the row for the UI."""
    now = now or datetime.now()
    url = settings.outreach_webhook_url
    report = {"sent": [], "blocked": [], "deferred": [], "error": "", "batch_id": ""}
    if store.kill_switch_on():
        report["error"] = "kill switch is on; nothing dispatched"
        store.log_event("dispatch_blocked", actor=actor, data={"reason": "kill switch"})
        return report
    if not url and post is None:
        report["error"] = "OUTREACH_WEBHOOK_URL is not set"
        return report

    candidates = store.list_messages("approved")
    if message_ids:
        candidates = [m for m in candidates if m["id"] in set(message_ids)]
    sent_today = store.sent_count_on(now.date())
    ready: list[dict] = []
    companies_in_batch: set[str] = set()
    for m in sorted(candidates, key=lambda x: (x.get("scheduled_for") or "", x.get("created_at") or "")):
        v = check(m, now=now, sent_today=sent_today + len(ready))
        # One live sequence per company also applies inside a single batch.
        co = (m.get("company") or "").strip().lower()
        if v.ok and co in companies_in_batch:
            v.ok = False
            v.blocked.append(f"another message to {m.get('company')} is already in this batch")
        if v.blocked:
            report["blocked"].append({"message_id": m["id"], "company": m.get("company"), "reasons": v.blocked})
            store.set_status(m["id"], "approved", actor="guardrails", reason=v.reason,
                             patch={"last_guardrail": v.reason}, force=True)
            continue
        if v.deferred:
            report["deferred"].append({"message_id": m["id"], "company": m.get("company"), "reasons": v.deferred})
            store.set_status(m["id"], "approved", actor="guardrails", reason=v.reason,
                             patch={"last_guardrail": v.reason}, force=True)
            continue
        ready.append(m)
        companies_in_batch.add(co)

    if not ready:
        return report

    payload = build_payload(ready)
    report["batch_id"] = payload["batch_id"]
    headers = {"X-Outreach-Secret": settings.outreach_shared_secret or "", "Content-Type": "application/json"}
    if test:
        payload["test"] = True
    try:
        if post is not None:
            ack = post(url, payload, headers)
        else:
            r = httpx.post(url, json=payload, headers=headers, timeout=60.0)
            r.raise_for_status()
            ack = r.json()
        if not (isinstance(ack, dict) and ack.get("accepted") is True and ack.get("batch_id") == payload["batch_id"]):
            raise RuntimeError(f"n8n did not acknowledge batch {payload['batch_id']}: {json.dumps(ack)[:200]}")
    except Exception as e:
        report["error"] = f"dispatch failed, messages stay approved: {e}"
        for m in ready:
            store.set_status(m["id"], "approved", actor="dispatch", reason=str(e),
                             patch={"error": str(e), "last_guardrail": ""}, force=True)
        store.log_event("dispatch_failed", actor=actor, data={"batch_id": payload["batch_id"], "error": str(e),
                                                              "message_ids": [m["id"] for m in ready]})
        return report

    stamp = now.isoformat(timespec="seconds")
    for m in ready:
        store.set_status(m["id"], "sending", actor=actor, reason=f"batch {payload['batch_id']}",
                         patch={"sent_at": stamp, "batch_id": payload["batch_id"], "error": "", "last_guardrail": ""})
        store.log_event("dispatched", message_id=m["id"], contact_id=m.get("contact_id", ""), actor=actor,
                        data={"batch_id": payload["batch_id"], "to": m.get("to_email"), "subject": m.get("subject"),
                              "test": test})
        report["sent"].append({"message_id": m["id"], "company": m.get("company"), "to": m.get("to_email")})
    return report


def handle_callback(payload: dict, *, actor: str = "n8n") -> dict:
    """Apply one n8n event. Idempotent on (message_id, event)."""
    mid = str(payload.get("message_id") or "").strip()
    event = str(payload.get("event") or "").strip().lower()
    if not mid or event not in CALLBACK_EVENTS:
        raise ValueError(f"callback needs message_id and event in {CALLBACK_EVENTS}")
    m = store.get_message(mid)
    if m is None:
        raise KeyError(mid)
    if store.callback_seen(mid, event):
        return {"message_id": mid, "event": event, "duplicate": True, "status": m["status"]}

    at = payload.get("at") or datetime.now().isoformat(timespec="seconds")
    detail = payload.get("detail") or {}
    patch = {"provider_message_id": payload.get("provider_message_id") or m.get("provider_message_id", ""),
             "thread_id": payload.get("thread_id") or m.get("thread_id", "")}
    stopped = 0
    if event == "sent":
        patch["sent_at"] = m.get("sent_at") or at
        if m["status"] in ("approved", "sending"):
            store.set_status(mid, "sent", actor=actor, patch=patch, force=(m["status"] == "approved"))
        else:
            store.set_status(mid, m["status"], actor=actor, patch=patch, force=True)
    elif event == "opened":
        patch["opened_at"] = at
        store.set_status(mid, m["status"], actor=actor, patch=patch, force=True)
    elif event == "replied":
        patch.update(replied_at=at, reply_sentiment=detail.get("sentiment", ""),
                     reply_snippet=detail.get("reply_snippet", ""))
        store.set_status(mid, "replied", actor=actor, patch=patch, force=True)
        stopped = store.cancel_pending_for_contact(m["contact_id"], reason=f"reply received on {mid}", actor=actor)
    elif event == "bounced":
        patch.update(bounce_reason=detail.get("bounce_reason", "") or detail.get("error", ""))
        store.set_status(mid, "bounced", actor=actor, patch=patch, force=True)
        mark_bad_address(m.get("to_email", ""), reason=f"bounced: {patch['bounce_reason']}"[:200])
        stopped = store.cancel_pending_in_sequence(m["sequence_id"], reason="address bounced", actor=actor)
        stopped += store.cancel_pending_for_contact(m["contact_id"], reason="address bounced", actor=actor)
    elif event == "failed":
        patch.update(error=detail.get("error", "") or "n8n reported failure")
        store.set_status(mid, "failed", actor=actor, patch=patch, force=True)
        stopped = store.cancel_pending_in_sequence(m["sequence_id"], reason="delivery failed", actor=actor)
    store.log_event(f"callback:{event}", message_id=mid, contact_id=m.get("contact_id", ""), actor=actor,
                    data={"at": at, "detail": detail, "provider_message_id": patch.get("provider_message_id"),
                          "stopped": stopped})
    return {"message_id": mid, "event": event, "duplicate": False,
            "status": store.get_message(mid)["status"], "stopped_pending": stopped}
