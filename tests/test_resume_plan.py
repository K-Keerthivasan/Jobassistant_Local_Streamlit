"""The resume version a job is generated with is decided up front and is the
one generation uses; incomplete descriptions are flagged; the application email
says why it was sent and backs it with proof points."""

import unittest
from unittest import mock

from resume_gen import personas, resume_plan
from resume_gen.generate import generate_email
from resume_gen.intake.models import QueuedJob
from resume_gen.models import EmailHook, ExperienceItem, Resume, Contact, TargetRole

PERSONAS = [
    {"id": "data_analyst", "label": "Data Analyst", "keywords": ["data analyst", "reporting"]},
    {"id": "business_analyst", "label": "Business & Systems Analyst", "keywords": ["business analyst"]},
]
PROFILE = {
    "full_name": "Keerthivasan Kalaivanan", "resume_name": "Keerthivasan", "preferred_name": "Keerthi",
    "contact": {"email": "k@example.com", "phone": "555-0100", "location": "London, ON",
                "links": [{"label": "LinkedIn", "url": "https://linkedin.com/in/kkvasan/"}]},
}


def job(**kw):
    base = dict(key_id="k1", company="Acme", title="IT Business Analyst", description="x" * 1200)
    base.update(kw)
    return QueuedJob(**base)


class ResumeVersion(unittest.TestCase):
    def setUp(self):
        for name, value in (("load_personas", PERSONAS), ("hermes_select", None)):
            patcher = mock.patch.object(personas, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_title_pick_and_reason(self):
        plan = resume_plan.resume_version(job())
        self.assertEqual((plan["persona"], plan["source"], plan["pinned"]), ("business_analyst", "title", False))

    def test_pinned_version_wins(self):
        plan = resume_plan.resume_version(job(resume_version="data_analyst"))
        self.assertEqual((plan["persona"], plan["source"], plan["pinned"]), ("data_analyst", "pinned", True))


class Description(unittest.TestCase):
    def test_old_collector_cut_is_flagged(self):
        status = resume_plan.description_status(job(source="collector", description="y" * 800))
        self.assertFalse(status["complete"])
        self.assertIn("800", status["reason"])

    def test_short_and_summary_are_flagged(self):
        self.assertFalse(resume_plan.description_status(job(description="short"))["complete"])
        self.assertFalse(resume_plan.description_status(
            job(description="[UNVERIFIED SUMMARY] blocked " + "z" * 600))["complete"])

    def test_full_posting_is_complete(self):
        self.assertTrue(resume_plan.description_status(job(source="collector", description="y" * 3000))["complete"])


class Activity(unittest.TestCase):
    def test_running_then_recent(self):
        gid = resume_plan.started("Acme", "Analyst")
        resume_plan.chose(gid, {"label": "Data Analyst"})
        self.assertTrue(any(i["id"] == gid for i in resume_plan.activity()["running"]))
        resume_plan.finished(gid, ok=True, run_id="r1")
        recent = resume_plan.activity()["recent"][0]
        self.assertEqual((recent["id"], recent["ok"], recent["resume_version"]), (gid, True, "Data Analyst"))


class ApplicationEmail(unittest.TestCase):
    target = TargetRole(company="Acme", title="Data Analyst", description="SQL and Power BI reporting")

    def test_says_why_and_lists_proof(self):
        lines = EmailHook(why="The role centres on Power BI reporting. I build the same reports at K2 Digital Media.",
                          proof_points=["**SQL**: queried SQL Server for daily ops dashboards at Certify Technologies.",
                                        "Power BI: client reports with recommendations at K2 Digital Media."])
        email = generate_email(self.target, PROFILE, lines=lines)
        self.assertIn("I'm applying for the Data Analyst position at Acme", email.body)
        self.assertIn("attached", email.body)
        self.assertIn("What I'd bring:\n- SQL: queried", email.body)
        self.assertNotIn("**", email.body)
        self.assertEqual(email.subject, "Application for Data Analyst at Acme - Keerthi")

    def test_falls_back_to_the_resume_not_boilerplate(self):
        resume = Resume(fullName="K", contact=Contact(email="k@example.com", phone="555", location="London, ON"),
                        summaryPoints=["Build **Power BI** reports for decision makers"],
                        experience=[ExperienceItem(company="Certify Technologies", role="Associate Developer", start="2021", end="2023",
                                                   bullets=["Built **dashboards** used daily by ops."]),
                                    ExperienceItem(company="K2 Digital Media", role="Owner", start="2023", end="Present",
                                                   bullets=["Build Excel reports with recommendations."])])
        email = generate_email(self.target, PROFILE, lines=EmailHook(), resume=resume)
        self.assertIn("I build Power BI reports for decision makers.", email.body)
        self.assertIn("- Built dashboards used daily by ops.", email.body)


if __name__ == "__main__":
    unittest.main()
