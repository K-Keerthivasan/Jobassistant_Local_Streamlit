"""Phase 3: tiering, gap flags, evidence-traced fit sentences, seniority guard."""

import unittest

from resume_gen import lanes
from resume_gen.grading import check_seniority, extract_requirements, grade
from resume_gen.grading.grader import build_fit_sentence
from resume_gen.lanes.schema import Skill


class RequirementsTests(unittest.TestCase):
    def test_sections_and_inline_markers(self):
        r = extract_requirements(
            "About us\nWe build things.\nRequirements\nSQL required\nPower BI\n"
            "Nice to have\nTableau\nResponsibilities\nBuild dashboards with Looker Studio\n"
            "Experience with dbt is an asset")
        self.assertEqual(r.hard, ["SQL required", "Power BI"])
        self.assertIn("Tableau", r.nice)
        self.assertTrue(any("dbt" in n for n in r.nice))
        self.assertTrue(any("Looker" in c for c in r.context))


class TierTests(unittest.TestCase):
    def setUp(self):
        lanes.use_data_dir(None)
        self.l5 = lanes.get_lane("data-analytics")
        self.l1 = lanes.get_lane("qa-testing")

    def test_tier_a_when_every_hard_required_must_is_held(self):
        g = grade("Junior Data Analyst", "Requirements\nSQL\nPower BI and DAX\nExcel pivot tables", self.l5)
        self.assertEqual(g["tier"], "A")
        self.assertEqual(g["gap_flags"], [])
        self.assertEqual({h["skill_id"] for h in g["hard_required"]}, {"sql", "power-bi", "excel"})

    def test_tier_c_when_a_later_tier_item_is_hard_required(self):
        g = grade("Analytics Engineer", "Requirements\nSQL\ndbt required\nSnowflake", self.l5)
        self.assertEqual(g["tier"], "C")
        self.assertIn("dbt", g["later_prerequisites"])
        self.assertTrue(any(f.startswith("dbt") for f in g["gap_flags"]))

    def test_later_item_as_an_asset_does_not_drop(self):
        g = grade("Data Analyst", "Requirements\nSQL\nPower BI\nNice to have\ndbt and Snowflake", self.l5)
        self.assertEqual(g["tier"], "A")
        self.assertEqual(g["later_prerequisites"], [])

    def test_tier_b_with_one_or_two_must_gaps_and_names_them(self):
        # Lane 1: test case design and SDLC are not_yet; programming is held.
        g = grade("QA Analyst", "Requirements\nTest case design\nAgile scrum\nJavaScript", self.l1)
        self.assertEqual(g["tier"], "B")
        self.assertEqual(len(g["must_missing"]), 2)
        self.assertTrue(any(f.startswith("Test case design (not yet)") for f in g["gap_flags"]))
        self.assertTrue(any(f.startswith("SDLC and Agile") for f in g["gap_flags"]))

    def test_tier_c_with_three_must_gaps(self):
        g = grade("QA Analyst", "Requirements\nTest case design\nAgile\nTestRail\nSQL", self.l1)
        self.assertEqual(g["tier"], "C")
        self.assertGreaterEqual(len(g["must_missing"]), 3)

    def test_partial_skill_is_a_named_gap_with_its_limit(self):
        g = grade("QA Analyst", "Requirements\nManual testing and regression testing\nJavaScript", self.l1)
        self.assertEqual(g["tier"], "B")
        flag = next(f for f in g["gap_flags"] if f.startswith("Manual testing execution (partial:"))
        self.assertIn("formal test plan", flag)

    def test_adjacent_experience_never_stands_in(self):
        # n8n pipelines are not SQL: lane 1's SQL is not_yet, regardless of what lane 3 holds.
        g = grade("QA Analyst", "Requirements\nSQL for test data\nJavaScript", self.l1)
        self.assertIn("SQL for test data", g["must_missing"])

    def test_fit_sentence_traces_to_evidence_only(self):
        g = grade("Junior Data Analyst", "Requirements\nSQL\nPower BI\nAPIs and JSON", self.l5)
        self.assertTrue(g["fit_sentence"])
        for sid in g["evidence_skill_ids"]:
            s = self.l5.skill(sid)
            self.assertIn(s.status, ("held", "partial"))
            self.assertTrue(s.evidence)
        self.assertNotIn("—", g["fit_sentence"]); self.assertNotIn("–", g["fit_sentence"])

    def test_not_yet_skill_can_never_reach_the_fit_sentence(self):
        s_bad = Skill(id="x", name="Tableau", tier="must", status="not_yet", evidence="", aliases=[])
        s_build = Skill(id="y", name="Rust", tier="must", status="building", evidence="", aliases=[])
        sentence, ids = build_fit_sentence("Analyst", [{"skill": s_bad, "where": "hard", "terms": ["tableau"]},
                                                       {"skill": s_build, "where": "hard", "terms": ["rust"]}])
        self.assertEqual((sentence, ids), ("", []))
        # Even if someone wrote evidence text onto a not_yet skill, it stays unusable.
        s_bad2 = Skill(id="z", name="Tableau", tier="must", status="not_yet", evidence="Used Tableau daily", aliases=[])
        sentence2, ids2 = build_fit_sentence("Analyst", [{"skill": s_bad2, "where": "hard", "terms": ["tableau"]}])
        self.assertEqual((sentence2, ids2), ("", []))

    def test_optional_tier_evidence_from_note_is_not_a_fit_source(self):
        s = Skill(id="q", name="ML fundamentals", tier="optional", status="partial", evidence="Enough to talk about it",
                  limit="Enough to talk about it", evidence_from_note=True)
        self.assertEqual(build_fit_sentence("x", [{"skill": s, "where": "hard", "terms": ["ml"]}]), ("", []))


class SeniorityTests(unittest.TestCase):
    def test_band_rules(self):
        self.assertFalse(check_seniority("Data Analyst", "1 to 3 years of experience")["warning"])
        self.assertFalse(check_seniority("Data Analyst", "2 to 4 years of experience")["warning"])
        self.assertTrue(check_seniority("Data Analyst", "3 to 5 years of experience")["warning"])
        self.assertTrue(check_seniority("Data Analyst", "4+ years of experience")["warning"])
        self.assertTrue(check_seniority("Data Analyst", "5+ years experience")["warning"])
        self.assertTrue(check_seniority("Data Analyst", "minimum of 4 years experience")["warning"])
        self.assertFalse(check_seniority("Data Analyst", "minimum 2 years experience")["warning"])
        self.assertFalse(check_seniority("Data Analyst", "no years mentioned")["warning"])

    def test_title_words_need_an_explicit_low_figure(self):
        self.assertTrue(check_seniority("Senior QA Engineer", "Great team, apply now.")["warning"])
        self.assertTrue(check_seniority("QA Lead", "5+ years")["warning"])
        self.assertFalse(check_seniority("Senior Analyst", "2 years of experience with SQL")["warning"])
        self.assertTrue(check_seniority("Analyst III", "3+ years")["warning"])
        self.assertFalse(check_seniority("Analyst", "")["title_flag"])

    def test_years_line_from_fit_report_takes_precedence(self):
        r = check_seniority("Analyst", "body says 5+ years somewhere old", years_line="1 to 2 years")
        self.assertFalse(r["warning"])


if __name__ == "__main__":
    unittest.main()
