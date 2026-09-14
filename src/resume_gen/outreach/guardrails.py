"""Dispatch guardrails (brief 6.5), as code. Every rule returns a named reason so
the UI can show exactly why a message did not go, and every rule has a test.

    approval        only `approved` is dispatchable; nothing else, ever
    kill switch     one toggle freezes all dispatch
    suppression     manual and permanent, by email, domain or company
    do_not_contact  set by a bounce, or by hand
    pattern_guess   a guessed address gets one touch, ever, and never a follow-up step
    cooldown        no contact receives anything inside N days of the last send
    one per company one live sequence per company in the window
    daily cap       reaching it defers the rest (never drops them)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..config import settings
from . import store
from .contacts import get_contact


@dataclass
class Verdict:
    ok: bool
    blocked: list[str] = field(default_factory=list)   # hard reasons
    deferred: list[str] = field(default_factory=list)  # try again later

    @property
    def reason(self) -> str:
        return "; ".join(self.blocked + self.deferred)


def check(message: dict, *, now: datetime | None = None, sent_today: int | None = None,
          company_sequences_live: list[str] | None = None) -> Verdict:
    """Evaluate one message for dispatch right now."""
    now = now or datetime.now()
    v = Verdict(ok=True)

    if message.get("status") != "approved":
        v.blocked.append(f"not approved (status {message.get('status')})")
    if store.kill_switch_on():
        v.blocked.append("kill switch is on")

    contact = get_contact(message.get("contact_id", "")) or {}
    email = (message.get("to_email") or contact.get("hr_email") or "").strip().lower()
    company = message.get("company") or contact.get("company", "")
    if not email:
        v.blocked.append("no recipient address")
    if contact.get("do_not_contact"):
        v.blocked.append("contact is marked do_not_contact" + (f" ({contact.get('bad_reason')})" if contact.get("bad_reason") else ""))
    key = store.is_suppressed(email=email, company=company)
    if key:
        v.blocked.append(f"suppressed ({key})")

    if (contact.get("confidence") or message.get("contact_confidence")) == "pattern_guess":
        if int(message.get("sequence_step") or 1) > 1:
            v.blocked.append("pattern_guess address: follow-up steps are never sent")
        if store.sends_to_address(email) >= 1:
            v.blocked.append("pattern_guess address already contacted once; never again")

    last = store.last_send_to_contact(message.get("contact_id", ""))
    if last:
        cool = store.cooldown_days()
        try:
            since = now - datetime.fromisoformat(last)
        except ValueError:
            since = timedelta(days=10_000)
        if since < timedelta(days=cool):
            v.blocked.append(f"contact inside {cool}-day cooldown (last send {last[:10]})")

    live = company_sequences_live if company_sequences_live is not None else \
        store.live_sequences_for_company(company, within_days=settings.outreach_company_window_days)
    others = [s for s in live if s != message.get("sequence_id")]
    if others:
        v.blocked.append(f"another live sequence at {company} in the last {settings.outreach_company_window_days} days")

    sched = message.get("scheduled_for") or ""
    if sched and sched > now.isoformat(timespec="seconds"):
        v.deferred.append(f"scheduled for {sched}")

    count = sent_today if sent_today is not None else store.sent_count_on(date.today())
    cap = store.daily_cap()
    if count >= cap:
        v.deferred.append(f"daily cap of {cap} reached; deferred to tomorrow")

    v.ok = not v.blocked and not v.deferred
    return v
