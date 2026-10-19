"""A resume fills its page: every role shows at least 4 real bullets, a short
resume grows from the profile, and trimming never drops a role below 4."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document

from resume_gen.guard import MIN_ROLE_BULLETS, enforce
from resume_gen.models import Contact, EducationItem, ExperienceItem, Resume
from resume_gen.render.docx_renderer import render_resume
from resume_gen.render.length import TARGET_FILL, MAX_K, _fill, fit_length

FACTS = {
    "K2 Digital Media": [
        "Produce Instagram Reels and short-form video for client social channels.",
        "Write creative briefs and copy direction for designers and editors.",
        "Review deliverables against brand guidelines before publishing.",
        "Build Excel and Power BI campaign reports for decision makers.",
        "Lead client kick-offs and manage content timelines with vendors.",
        "Design posters and brand collateral in Photoshop, Illustrator and Canva.",
        "Integrate Stripe, Google Maps and YouTube into client websites.",
        "Automate repetitive data handling with n8n and LLM workflows.",
    ],
    "Bill Gosling Outsourcing": [
        "Handle inbound and outbound customer calls against daily targets.",
        "Negotiate payment commitments with accuracy and diplomacy.",
        "Document every interaction in CRM systems, audit-ready.",
        "Work across several software systems and adapt to new platforms.",
        "Stay calm and empathetic in difficult conversations.",
    ],
    "Certify Technologies": [
        "Maintained a 95% first-contact resolution rate on support tickets.",
        "Imaged Windows 11 machines for new hires with drivers and hardening.",
        "Managed Active Directory, Microsoft 365 and Entra ID accounts.",
        "Built React dashboards used daily by operations teams.",
        "Partnered with QA and product on validation and release sign-off.",
        "Joined production support rotations and post-incident reviews.",
    ],
    "Best Buy": [
        "Merchandised computing products through promotional periods.",
        "Fed customer demand and product feedback back to the team.",
        "Advised customers and processed transactions accurately.",
    ],
}
PROFILE = {
    "full_name": "Keerthivasan Kalaivanan",
    "contact": {"email": "k@example.com", "phone": "555", "location": "London, ON", "links": []},
    "skills": {"creative_media": ["Premiere Pro", "After Effects"]},
    "experience": [
        {"company": c, "role": "Role", "start": "2023", "end": "Present", "facts": f,
         "always_include": c in ("K2 Digital Media", "Bill Gosling Outsourcing", "Certify Technologies")}
        for c, f in FACTS.items()
    ],
    "education": [{"institution": "Fanshawe College, London, ON",
                   "credential": "Visual Effects and Editing for Contemporary Media", "year": "2024 to 2025"}],
    "certifications": [],
}


def _resume(bullets_per_role: int) -> Resume:
    return Resume(
        fullName="x", contact=Contact(email="", phone="", location=""),
        summaryPoints=["Produces short-form video for client channels.", "Writes creative briefs.", "Uses Premiere Pro."],
        experience=[ExperienceItem(company=c, role="Role", start="", end="", bullets=FACTS[c][:bullets_per_role])
                    for c in ("K2 Digital Media", "Bill Gosling Outsourcing", "Certify Technologies")],
    )


class MinimumBulletsTests(unittest.TestCase):
    def test_every_role_is_topped_up_to_four_real_bullets(self):
        out, _ = enforce(_resume(1), PROFILE, target_title="Video Content Intern")
        for e in out.experience:
            self.assertGreaterEqual(len(e.bullets), MIN_ROLE_BULLETS, e.company)
            for b in e.bullets:
                self.assertIn(b, FACTS[e.company], "top-ups come only from that role's own facts")
        self.assertGreaterEqual(len(out.experience[0].bullets), 5, "the lead role gets 5")

    def test_a_role_with_fewer_facts_keeps_what_is_real(self):
        r = _resume(1)
        r.experience.append(ExperienceItem(company="Best Buy", role="Role", start="", end="", bullets=FACTS["Best Buy"][:1]))
        out, _ = enforce(r, PROFILE, target_title="X")
        best_buy = next(e for e in out.experience if e.company == "Best Buy")
        self.assertEqual(len(best_buy.bullets), 3, "never invents a fourth bullet")


class PageFillTests(unittest.TestCase):
    def test_a_short_resume_grows_from_the_profile_to_fill_the_page(self):
        short = _resume(2)
        self.assertLess(_fill(short, MAX_K, PROFILE), TARGET_FILL)
        grown, k, rep = fit_length(short, PROFILE)
        self.assertTrue(rep.get("grown"))
        self.assertGreater(sum(len(e.bullets) for e in grown.experience), 6)
        for e in grown.experience:
            for b in e.bullets:
                self.assertIn(b, FACTS[e.company])
        self.assertEqual(rep["pages_target"], 1)
        self.assertLessEqual(rep["estimated_fill"], 1.0)

    def test_trimming_keeps_four_bullets_per_role(self):
        long = ("Built and maintained weekly client reporting in Excel and Power BI for business owners "
                "across several accounts, consolidating campaign results into one view. ") * 2
        roles = [ExperienceItem(company=f"Co {i}", role="Analyst", start="2020", end="2021", bullets=[long] * 6)
                 for i in range(4)]
        r, k, rep = fit_length(_resume(4).model_copy(update={"experience": roles}), {"experience": []})
        if rep["pages_target"] == 1 and rep["trimmed"]:
            for e in r.experience:
                self.assertGreaterEqual(len(e.bullets), 4)


class EducationLineTests(unittest.TestCase):
    def test_a_long_education_line_is_shrunk_not_wrapped(self):
        r = _resume(4)
        r.education = [EducationItem(institution="Fanshawe College, London, ON",
                                     credential="Visual Effects and Editing for Contemporary Media", year="2024 to 2025")]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.docx"
            render_resume(r, path, PROFILE, density=1.3)
            p = next(p for p in Document(path).paragraphs if "Contemporary Media" in p.text)
            sizes = {run.font.size.pt for run in p.runs if run.font.size}
        self.assertLess(min(sizes), 12.0, "the long line is set smaller than the body size")


if __name__ == "__main__":
    unittest.main()
