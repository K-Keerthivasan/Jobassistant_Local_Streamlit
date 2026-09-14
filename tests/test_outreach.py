"""Phase 5: a message can be drafted, personalised, approved, dispatched to a mock
webhook, and moved through sent, replied and bounced by callback, with the
sequence stopping correctly on each. Every guardrail in 6.5 has a test that
proves it blocks."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from resume_gen import lanes
from resume_gen.config import settings
from resume_gen.intake import batch_import as bi
from resume_gen.intake.store import list_queue
from resume_gen.outreach import contacts as oc
from resume_gen.outreach import dispatch, draft, guardrails, store, templates

from tests._dbtmp import TempDB
from tests.test_batch_import import DA_DESC, DAY, companies_file, fit_file, job, jobs_file


def _seed(confidence_notes="email verified by reply"):
    """One graded Tier A job at Acme with a contact."""
    bi.import_batch([
        jobs_file("streamC", DAY, [job("Acme Analytics Inc", "Junior Data Analyst", "Data analytics",
                                       "21223 / TEER 1 | AIP: Nova Scotia | SRC: careerbeacon", DA_DESC)]),
        companies_file("streamC", DAY, [{"company": "Acme Analytics Inc", "hr_name": "Jane Doe",
                                         "hr_email": "jane.doe@acme.example", "ats": "greenhouse",
                                         "notes": confidence_notes}]),
        fit_file("streamC", DAY, []),
    ])
    q = next(j for j in list_queue() if j.company.startswith("Acme"))
    c = oc.contacts_for_company("Acme Analytics Inc")[0]
    return q, c


class FakeWebhook:
    def __init__(self, accept=True):
        self.calls = []
        self.accept = accept

    def __call__(self, url, payload, headers):
        self.calls.append((url, payload, headers))
        if not self.accept:
            return {"accepted": False}
        return {"accepted": True, "batch_id": payload["batch_id"]}


class OutreachLifecycleTests(unittest.TestCase):
    def setUp(self):
        lanes.use_data_dir(None)
        self._old = (settings.outreach_webhook_url, settings.outreach_shared_secret)
        settings.outreach_webhook_url = "http://n8n.test/webhook/outreach"
        settings.outreach_shared_secret = "s3cret"

    def tearDown(self):
        settings.outreach_webhook_url, settings.outreach_shared_secret = self._old

    def test_draft_approve_dispatch_sent_replied(self):
        with TempDB():
            q, c = _seed()
            msgs = draft.draft_sequence(contact_id=c["id"], template_id="application-followup", job_key=q.key_id,
                                        applied_on="2026-09-13")
            self.assertEqual([m["status"] for m in msgs], ["queued", "queued"])
            self.assertEqual([m["sequence_step"] for m in msgs], [1, 2])
            m1, m2 = msgs
            self.assertIn("Junior Data Analyst", m1["subject"])
            self.assertLessEqual(len(m1["subject"]), 60)
            self.assertIn("Jane", m1["body"])
            self.assertIn("2026-09-13", m1["body"])
            self.assertIn("dev.kkvasan.ca", m1["body"])
            self.assertNotIn("sponsor", m1["body"].lower())
            self.assertIn(q.grade["fit_sentence"][:40], m1["body"])

            # Unapproved: dispatch sends nothing.
            hook = FakeWebhook()
            rep = dispatch.dispatch_due(post=hook)
            self.assertEqual(rep["sent"], [])
            self.assertEqual(hook.calls, [])

            # Approve step 1 only. Step 2 stays queued and must never go out.
            store.approve([m1["id"]])
            rep = dispatch.dispatch_due(post=hook)
            self.assertEqual([s["message_id"] for s in rep["sent"]], [m1["id"]])
            self.assertEqual(hook.calls[0][2]["X-Outreach-Secret"], "s3cret")
            sent_payload = hook.calls[0][1]["messages"][0]
            self.assertEqual(sent_payload["to"]["email"], "jane.doe@acme.example")
            self.assertEqual(sent_payload["meta"]["lane"], "data-analytics")
            self.assertEqual(store.get_message(m1["id"])["status"], "sending")
            self.assertEqual(store.get_message(m2["id"])["status"], "queued")

            # n8n says sent, then replied. Reply stops the pending step 2.
            r = dispatch.handle_callback({"message_id": m1["id"], "event": "sent", "provider_message_id": "gm-1", "thread_id": "th-1"})
            self.assertEqual(r["status"], "sent")
            self.assertEqual(store.get_message(m1["id"])["provider_message_id"], "gm-1")
            dup = dispatch.handle_callback({"message_id": m1["id"], "event": "sent"})
            self.assertTrue(dup["duplicate"])
            r2 = dispatch.handle_callback({"message_id": m1["id"], "event": "replied", "detail": {"reply_snippet": "Thanks, let's talk"}})
            self.assertEqual(r2["status"], "replied")
            self.assertEqual(store.get_message(m2["id"])["status"], "cancelled")
            kinds = [e["kind"] for e in store.events(message_id=m1["id"])]
            self.assertIn("approved", kinds); self.assertIn("dispatched", kinds); self.assertIn("callback:replied", kinds)

    def test_bounce_marks_address_bad_and_stops_sequence(self):
        with TempDB():
            q, c = _seed()
            m1, m2 = draft.draft_sequence(contact_id=c["id"], template_id="application-followup", job_key=q.key_id)
            store.approve([m1["id"], m2["id"]])
            dispatch.dispatch_due(post=FakeWebhook())
            r = dispatch.handle_callback({"message_id": m1["id"], "event": "bounced", "detail": {"bounce_reason": "550 no such user"}})
            self.assertEqual(r["status"], "bounced")
            self.assertEqual(store.get_message(m2["id"])["status"], "cancelled")
            c2 = oc.get_contact(c["id"])
            self.assertTrue(c2["do_not_contact"]); self.assertTrue(c2["bad_address"])
            # Nothing further can be drafted to it.
            with self.assertRaises(templates.TemplateError):
                draft.draft_sequence(contact_id=c["id"], template_id="referral-informational", job_key=q.key_id)

    def test_failed_callback_records_error_and_stops_sequence(self):
        with TempDB():
            q, c = _seed()
            m1, m2 = draft.draft_sequence(contact_id=c["id"], template_id="application-followup", job_key=q.key_id)
            store.approve([m1["id"]])
            dispatch.dispatch_due(post=FakeWebhook())
            r = dispatch.handle_callback({"message_id": m1["id"], "event": "failed", "detail": {"error": "smtp 421"}})
            self.assertEqual(r["status"], "failed")
            self.assertEqual(store.get_message(m1["id"])["error"], "smtp 421")
            self.assertEqual(store.get_message(m2["id"])["status"], "cancelled")

    def test_webhook_rejection_leaves_messages_approved_and_visible(self):
        with TempDB():
            q, c = _seed()
            m1, _ = draft.draft_sequence(contact_id=c["id"], template_id="application-followup", job_key=q.key_id)
            store.approve([m1["id"]])
            rep = dispatch.dispatch_due(post=FakeWebhook(accept=False))
            self.assertIn("did not acknowledge", rep["error"])
            self.assertEqual(store.get_message(m1["id"])["status"], "approved")
            self.assertTrue(any(e["kind"] == "dispatch_failed" for e in store.events()))

    def test_callback_secret_is_never_open_by_default(self):
        self.assertTrue(dispatch.secret_ok("s3cret"))
        self.assertFalse(dispatch.secret_ok("nope"))
        settings.outreach_shared_secret = ""
        self.assertFalse(dispatch.secret_ok(""))

    def test_cold_approach_uses_lane_evidence_and_may_name_the_pathway(self):
        with TempDB():
            oc.upsert_contact(company="Atlantic Widgets", hr_email="hr@atlantic.example", hr_name="Sam Lee",
                              notes="designated AIP employer confirmed 2026-09-10", confidence="enriched")
            c = oc.contacts_for_company("Atlantic Widgets")[0]
            msgs = draft.draft_sequence(contact_id=c["id"], template_id="cold-approach-pathway", lane_slug="data-analytics")
            self.assertEqual(len(msgs), 1)
            body = msgs[0]["body"]
            self.assertIn("Atlantic Immigration Program", body)
            self.assertIn("Data and analytics", body)
            self.assertLessEqual(len(body.split()), 150)

    def test_never_mention_rule_blocks_edits(self):
        with TempDB():
            q, c = _seed()
            m1, _ = draft.draft_sequence(contact_id=c["id"], template_id="application-followup", job_key=q.key_id)
            with self.assertRaises(templates.TemplateError):
                draft.rerender(m1["id"], body="I will need sponsorship for this role.")
            edited = draft.rerender(m1["id"], subject="Hello Jane")
            self.assertEqual(edited["subject"], "Hello Jane")


class GuardrailTests(unittest.TestCase):
    def setUp(self):
        lanes.use_data_dir(None)
        self._old = (settings.outreach_webhook_url, settings.outreach_shared_secret)
        settings.outreach_webhook_url = "http://n8n.test/webhook/outreach"
        settings.outreach_shared_secret = "s3cret"

    def tearDown(self):
        settings.outreach_webhook_url, settings.outreach_shared_secret = self._old

    def _approved(self, q, c, template="application-followup"):
        msgs = draft.draft_sequence(contact_id=c["id"], template_id=template, job_key=q.key_id)
        store.approve([msgs[0]["id"]])
        return store.get_message(msgs[0]["id"]), msgs

    def test_unapproved_never_dispatches_even_when_parent_was_approved(self):
        with TempDB():
            q, c = _seed()
            m1, m2 = draft.draft_sequence(contact_id=c["id"], template_id="application-followup", job_key=q.key_id)
            store.approve([m1["id"]])
            v = guardrails.check(store.get_message(m2["id"]))
            self.assertFalse(v.ok); self.assertTrue(any("not approved" in b for b in v.blocked))
            # Even forced into the future window with the parent sent, step 2 stays put.
            dispatch.dispatch_due(post=FakeWebhook())
            dispatch.handle_callback({"message_id": m1["id"], "event": "sent"})
            rep = dispatch.dispatch_due(post=FakeWebhook(), now=datetime.now() + timedelta(days=30))
            self.assertEqual(rep["sent"], [])

    def test_kill_switch_freezes_everything(self):
        with TempDB():
            q, c = _seed()
            m, _ = self._approved(q, c)
            store.set_state("kill_switch", "1")
            self.assertTrue(any("kill switch" in b for b in guardrails.check(m).blocked))
            hook = FakeWebhook()
            rep = dispatch.dispatch_due(post=hook)
            self.assertEqual(hook.calls, []); self.assertIn("kill switch", rep["error"])
            store.set_state("kill_switch", "0")
            self.assertEqual(len(dispatch.dispatch_due(post=hook)["sent"]), 1)

    def test_daily_cap_defers_and_never_drops(self):
        with TempDB():
            q, c = _seed()
            m, _ = self._approved(q, c)
            store.set_state("daily_cap", "0")
            rep = dispatch.dispatch_due(post=FakeWebhook())
            self.assertEqual(rep["sent"], [])
            self.assertTrue(any("daily cap" in r for d in rep["deferred"] for r in d["reasons"]))
            self.assertEqual(store.get_message(m["id"])["status"], "approved")
            store.set_state("daily_cap", "20")
            self.assertEqual(len(dispatch.dispatch_due(post=FakeWebhook())["sent"]), 1)

    def test_per_contact_cooldown(self):
        with TempDB():
            q, c = _seed()
            m1, m2 = draft.draft_sequence(contact_id=c["id"], template_id="application-followup", job_key=q.key_id)
            store.approve([m1["id"], m2["id"]])
            dispatch.dispatch_due(post=FakeWebhook())
            dispatch.handle_callback({"message_id": m1["id"], "event": "sent"})
            # Step 2 is scheduled 7 days out; cooldown is 21 days -> blocked at day 8.
            v = guardrails.check(store.get_message(m2["id"]), now=datetime.now() + timedelta(days=8))
            self.assertTrue(any("cooldown" in b for b in v.blocked))
            v2 = guardrails.check(store.get_message(m2["id"]), now=datetime.now() + timedelta(days=22),
                                  company_sequences_live=[])
            self.assertFalse(any("cooldown" in b for b in v2.blocked))

    def test_one_live_sequence_per_company(self):
        with TempDB():
            q, c = _seed()
            oc.upsert_contact(company="Acme Analytics Inc", hr_email="bob@acme.example", hr_name="Bob", confidence="verified")
            c2 = next(x for x in oc.contacts_for_company("Acme Analytics Inc") if x["hr_email"] == "bob@acme.example")
            a1, _ = draft.draft_sequence(contact_id=c["id"], template_id="application-followup", job_key=q.key_id)
            b1 = draft.draft_sequence(contact_id=c2["id"], template_id="referral-informational", job_key=q.key_id)[0]
            store.approve([a1["id"], b1["id"]])
            rep = dispatch.dispatch_due(post=FakeWebhook())
            self.assertEqual(len(rep["sent"]), 1)
            self.assertEqual(len(rep["blocked"]), 1)
            dispatch.handle_callback({"message_id": rep["sent"][0]["message_id"], "event": "sent"})
            v = guardrails.check(store.get_message(b1["id"]))
            self.assertTrue(any("another live sequence" in b for b in v.blocked))

    def test_pattern_guess_gets_one_touch_ever_and_no_follow_up(self):
        with TempDB():
            q, c = _seed(confidence_notes="pattern guess from domain")
            self.assertEqual(c["confidence"], "pattern_guess")
            msgs = draft.draft_sequence(contact_id=c["id"], template_id="application-followup", job_key=q.key_id)
            self.assertEqual(len(msgs), 1, "no follow-up step for a guessed address")
            with self.assertRaises(templates.TemplateError):
                draft.draft_sequence(contact_id=c["id"], template_id="application-nudge", job_key=q.key_id)
            store.approve([msgs[0]["id"]])
            dispatch.dispatch_due(post=FakeWebhook())
            dispatch.handle_callback({"message_id": msgs[0]["id"], "event": "sent"})
            again = draft.draft_sequence(contact_id=c["id"], template_id="referral-informational", job_key=q.key_id)[0]
            store.approve([again["id"]])
            v = guardrails.check(again, now=datetime.now() + timedelta(days=60), company_sequences_live=[])
            self.assertTrue(any("already contacted once; never again" in b for b in v.blocked))

    def test_suppression_list_blocks_by_email_domain_and_company(self):
        with TempDB():
            q, c = _seed()
            m, _ = self._approved(q, c)
            store.suppress("jane.doe@acme.example", "email", "asked to stop")
            self.assertTrue(any("suppressed" in b for b in guardrails.check(m).blocked))
            store.unsuppress("jane.doe@acme.example")
            store.suppress("@acme.example", "domain")
            self.assertTrue(any("suppressed" in b for b in guardrails.check(m).blocked))
            store.unsuppress("@acme.example")
            store.suppress(oc.norm_company("Acme Analytics Inc"), "company", "leave alone")
            self.assertTrue(any("suppressed" in b for b in guardrails.check(m).blocked))
            with self.assertRaises(templates.TemplateError):
                draft.draft_sequence(contact_id=c["id"], template_id="referral-informational", job_key=q.key_id)

    def test_do_not_contact_blocks(self):
        with TempDB():
            q, c = _seed()
            m, _ = self._approved(q, c)
            oc.set_do_not_contact(c["id"], True, "asked")
            self.assertTrue(any("do_not_contact" in b for b in guardrails.check(m).blocked))

    def test_audit_log_records_approval_dispatch_and_callbacks_with_actor(self):
        with TempDB():
            q, c = _seed()
            m, _ = self._approved(q, c)
            dispatch.dispatch_due(post=FakeWebhook(), actor="keerthi")
            dispatch.handle_callback({"message_id": m["id"], "event": "sent"})
            ev = store.events(message_id=m["id"])
            by_kind = {e["kind"]: e for e in ev}
            self.assertEqual(by_kind["approved"]["actor"], "keerthi")
            self.assertEqual(by_kind["dispatched"]["actor"], "keerthi")
            self.assertEqual(by_kind["callback:sent"]["actor"], "n8n")
            self.assertTrue(all(e["at"] for e in ev))


if __name__ == "__main__":
    unittest.main()
