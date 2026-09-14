"""Phase 4: the status guard in the generation path, plus document standard checks.

The failure mode this protects against is a fabricated claim in a screen: a
skill the matrix marks `building` or `not_yet` must never reach a document, no
matter what the model wrote or what the profile inventory lists."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document

from resume_gen import lanes
from resume_gen.generate import _context
from resume_gen.guard import enforce, enforce_cover_letter
from resume_gen.lanes.guard import apply_to_resume, directive, lane_context, scan_text
from resume_gen.models import Contact, CoverLetter, EducationItem, ExperienceItem, Resume, TargetRole
from resume_gen.pipeline import _document_base
from resume_gen.render.docx_renderer import render_resume

PROFILE = {
    "full_name": "Keerthivasan", "preferred_name": "Keerthivasan",
    "contact": {"email": "k@example.com", "phone": "000", "location": "London, ON, Canada",
                "location_general": "Ontario, Canada",
                "links": [{"label": "LinkedIn", "url": "https://linkedin.com/in/x"}]},
    # Tableau is deliberately IN the profile inventory to prove the matrix wins.
    "skills": {"data": ["SQL", "Power BI", "Excel", "Tableau", "dbt"], "code": ["Python", "Git"]},
    "experience": [{"company": "K2 Digital Media", "role": "Freelance Web Developer", "location": "Remote",
                    "start": "2023", "end": "Present",
                    "facts": ["Built LLM-assisted automation workflows in n8n with structured outputs.",
                              "Reported campaign performance to clients with Power BI dashboards and SQL queries."]}],
    "education": [{"institution": "Anna University", "credential": "MCA", "year": "2020-2022"}],
    "certifications": [],
}


def _resume(skills, bullets, summary="Data analyst who builds dashboards."):
    return Resume(fullName="Keerthivasan", contact=Contact(email="", phone="", location=""),
                  summary=summary, skills=skills,
                  experience=[ExperienceItem(company="K2 Digital Media", role="Freelance Web Developer",
                                             start="2023", end="Present", bullets=bullets)],
                  education=[EducationItem(institution="x", credential="y", year="z")])


class LaneGuardTests(unittest.TestCase):
    def setUp(self):
        lanes.use_data_dir(None)
        self.l5 = lanes.get_lane("data-analytics")
        self.ctx = lane_context(self.l5, {"tier": "A", "gap_flags": [], "fit_sentence": "x"})

    def test_not_yet_skill_never_reaches_the_resume_even_if_the_profile_lists_it(self):
        r = _resume(["SQL", "Power BI", "Tableau", "dbt", "Python"],
                    ["Built Power BI dashboards from SQL queries for client reporting.",
                     "Modelled analytics transformations in dbt for a client warehouse."])
        out, qa = enforce(r, PROFILE, strict=False, lane_ctx=self.ctx)
        self.assertNotIn("Tableau", out.skills)
        self.assertNotIn("dbt", out.skills)
        self.assertIn("SQL", out.skills)
        blocked = {b["matrix_skill"] for b in qa["lane_guard"]["skills_blocked"]}
        self.assertEqual(blocked, {"Tableau", "dbt"})
        # Non-strict flags the bullet; strict drops it.
        self.assertTrue(any("dbt" in b["bullet"] for b in qa["lane_guard"]["bullets_flagged"]))
        out_s, qa_s = enforce(_resume(["SQL"], ["Modelled dbt transformations behind the Power BI client reporting dashboards.",
                                                 "Built Power BI dashboards from SQL queries for client reporting."]),
                              PROFILE, strict=True, lane_ctx=self.ctx)
        self.assertFalse(any("dbt" in b for e in out_s.experience for b in e.bullets))
        self.assertTrue(qa_s["lane_guard"]["bullets_dropped"])

    def test_held_matrix_skill_missing_from_profile_inventory_survives(self):
        # "DAX" is a Power BI alias in lane 5 (held) but not in this profile's inventory.
        out, qa = enforce(_resume(["DAX", "SQL"], ["Built Power BI dashboards from SQL queries for client reporting."]),
                          PROFILE, lane_ctx=self.ctx)
        self.assertIn("DAX", out.skills)

    def test_summary_sentence_claiming_a_forbidden_skill_is_removed_in_strict(self):
        r = _resume(["SQL"], ["Built Power BI dashboards from SQL queries for client reporting."],
                    summary="Analyst who builds Power BI dashboards. Expert in Tableau and Snowflake.")
        out, qa = enforce(r, PROFILE, strict=True, lane_ctx=self.ctx)
        self.assertNotIn("Tableau", out.summary)
        self.assertIn("Power BI", out.summary)
        self.assertEqual(qa["lane_guard"]["summary_flagged"], ["Tableau"])

    def test_no_lane_means_no_lane_guard(self):
        out, qa = enforce(_resume(["Tableau"], ["Built Power BI dashboards from SQL queries."]), PROFILE)
        self.assertIn("Tableau", out.skills)
        self.assertNotIn("lane_guard", qa)

    def test_links_come_from_the_lane(self):
        links = lanes.portfolio_links_for(self.l5)
        out, _ = enforce(_resume(["SQL"], ["Built Power BI dashboards from SQL queries."]), PROFILE, links=links)
        self.assertEqual([l.label for l in out.contact.links], [l.label for l in links])
        self.assertIn("dev.kkvasan.ca", " ".join(l.url for l in out.contact.links))
        vfx_links = lanes.portfolio_links_for(lanes.get_lane("vfx"))
        self.assertIn("film.kkvasan.ca", " ".join(l.url for l in vfx_links))
        self.assertIn("k2digitalmedia.ca", " ".join(l.url for l in lanes.portfolio_links_for(lanes.get_lane("social-content"))))

    def test_cover_letter_claim_of_a_forbidden_skill_is_removed_but_naming_the_gap_is_kept(self):
        cl = CoverLetter(fullName="Keerthivasan", contactLine="x", greeting="Hi,",
                         body=["SQL and Power BI are daily tools for me.",
                               "I have three years of hands-on Tableau experience. I also ran client reporting.",
                               "Tableau is a gap: I have not used it, and the concepts carry over from Power BI.",
                               "I am in London, Ontario on an open work permit."],
                         signOff="Thanks,", signature="Keerthivasan")
        out, qa = enforce_cover_letter(cl, PROFILE, lane_ctx=self.ctx)
        text = " ".join(out.body)
        self.assertNotIn("hands-on Tableau experience", text)
        self.assertIn("Tableau is a gap", text)
        self.assertEqual(len(qa["lane_guard"]["sentences_removed"]), 1)

    def test_directive_names_held_partial_limits_forbidden_and_gaps(self):
        l1 = lanes.get_lane("qa-testing")
        ctx = lane_context(l1, {"tier": "B", "gap_flags": ["Test case design (not yet)"], "fit_sentence": "Matches x."})
        d = directive(ctx, for_cover_letter=True)
        self.assertIn("NEVER PRESENT AS EXPERIENCE", d)
        self.assertIn("Test case design", d)
        self.assertIn("PARTIAL", d)
        self.assertIn("formal test plan", d)
        self.assertIn("GAPS THE POSTING HARD-REQUIRES", d)
        msg = _context(PROFILE, TargetRole(company="A", title="QA Analyst", description="x"), None, ctx,
                       for_cover_letter=True)
        self.assertIn("LANE MATRIX", msg)

    def test_scan_text_finds_forbidden_mentions(self):
        hits = scan_text("I would bring Tableau dashboards to the team.", self.ctx)
        self.assertEqual(hits[0]["name"], "Tableau")
        self.assertEqual(scan_text("SQL and Power BI every day.", self.ctx), [])


class DocumentStandardTests(unittest.TestCase):
    def test_filenames_follow_kk_company_role(self):
        base = _document_base(TargetRole(company="Acme Analytics Inc.", title="Junior Data Analyst", description=""))
        self.assertTrue(base.startswith("kk_Acme_Analytics_"), base)
        self.assertTrue(base.endswith("Data_Analyst"), base)
        self.assertNotIn("__", base)

    def test_dates_use_to_and_headers_are_navy(self):
        r = _resume(["SQL"], ["Built dashboards."])
        r.experience[0].start, r.experience[0].end = "2024-01", "present"
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.docx"
            render_resume(r, path)
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs)
            import zipfile
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8")
        self.assertIn("Jan 2024 to Present", text)
        self.assertFalse(re.search(r"[–—]", text), "no em or en dashes in the resume")
        self.assertIn('w:color w:val="1F3864"', xml)
        self.assertNotIn("1F4E79", xml)


if __name__ == "__main__":
    unittest.main()
