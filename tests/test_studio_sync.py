"""Resume Studio and the Chrome application workspace stay in step: the status
an engine application follows, cancel marking the job skipped, a regenerated
job re-entering the queue, and recording a job you applied to yourself."""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import application_engine_routes as routes
from resume_gen.automation import autoapply
from resume_gen.intake import apply_sessions, store
from resume_gen.intake.models import JobPosting
from tests._dbtmp import TempDB


def _job(run_id="run1"):
    [q] = store.commit([JobPosting(source="greenhouse", job_id="1", company="Acme",
                                   title="Data Analyst", apply_url="https://jobs.acme.com/1")])
    store.update_status(q.key_id, "generated", notes=run_id)
    return q.key_id


class StudioSyncTests(unittest.TestCase):
    def setUp(self):
        self.db = TempDB()
        self.db.__enter__()
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.db.__exit__(None, None, None)

    def _session(self, key, run_id="run1"):
        return apply_sessions.new_session(job_url="https://jobs.acme.com/1", company="Acme",
                                          title="Data Analyst", job_key=key, run_id=run_id)["session_id"]

    def _status(self, sid):
        r = self.client.get(f"/application-engine/{sid}/status")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_status_follows_applied_dismissed_regenerated_and_deleted(self):
        key = _job()
        sid = self._session(key)
        s = self._status(sid)
        self.assertEqual((s["applied"], s["dismissed"], s["regenerated"], s["job_exists"]), (False, False, False, True))
        store.update_status(key, "generated", notes="run2")
        self.assertTrue(self._status(sid)["regenerated"])
        self.assertEqual(self._status(sid)["current_run_id"], "run2")
        store.set_irrelevant(key, True)
        self.assertTrue(self._status(sid)["dismissed"])
        store.set_applied(key, True)
        self.assertTrue(self._status(sid)["applied"])
        store.delete_job(key)
        self.assertFalse(self._status(sid)["job_exists"])
        self.assertEqual(self.client.get("/application-engine/nope/status").status_code, 404)

    def test_cancel_marks_the_job_skipped_and_regenerating_queues_it_again(self):
        key = _job()
        sid = self._session(key)
        self.assertEqual([c["key_id"] for c in autoapply.candidates()], [key])
        autoapply.log_outcome(sid, status="rejected", note="Automation cancelled by you.")
        self.assertEqual(store.get_job(key).status, "skipped")
        self.assertEqual(autoapply.candidates(), [])
        store.update_status(key, "generated", notes="run2")      # regenerated in Studio
        self.assertEqual([c["run_id"] for c in autoapply.candidates()], ["run2"])

    def test_a_failure_keeps_the_status_for_a_retry(self):
        key = _job()
        sid = self._session(key)
        autoapply.log_outcome(sid, status="failed", note="Portal error")
        self.assertEqual(store.get_job(key).status, "generated")

    def test_applied_by_me_records_and_leaves_the_queue(self):
        key = _job()
        r = self.client.post(f"/application-engine/jobs/{key}/applied-by-me", json={"note": "Applied on the site"})
        self.assertEqual(r.status_code, 200, r.text)
        job = store.get_job(key)
        self.assertTrue(job.applied)
        self.assertEqual(job.status, "applied")
        self.assertEqual(job.sent_log[-1]["submitted_by"], "me")
        self.assertEqual(autoapply.candidates(), [])
        self.assertEqual(self.client.post("/application-engine/jobs/missing/applied-by-me", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
