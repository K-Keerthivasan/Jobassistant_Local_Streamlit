"""Which resume version a posting gets: a broad lane keeps its base resume
unless the job title names another version more strongly, and generic words in
lane titles ("junior") never decide the lane."""

from types import SimpleNamespace
import unittest
from unittest import mock

from resume_gen import lanes, personas

PERSONAS = [
    {"id": "data_analyst", "keywords": ["data analyst", "analytics", "reporting"]},
    {"id": "business_analyst", "keywords": ["business analyst", "systems analyst"]},
    {"id": "finance_analyst", "keywords": ["project finance", "finance"], "lane": "data-analytics"},
]


def job(title, description=""):
    return SimpleNamespace(title=title, description=description, company="Acme")


class LaneMatching(unittest.TestCase):
    def test_junior_does_not_pick_the_vfx_lane(self):
        for title in ("Junior Project Finance Analyst", "Junior System Integration Analyst"):
            lane = lanes.resolve_lane(title)
            self.assertNotEqual(getattr(lane, "slug", None), "vfx", title)

    def test_real_vfx_titles_still_match(self):
        self.assertEqual(lanes.resolve_lane("Junior Compositor").slug, "vfx")


class PersonaSelection(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(personas, "load_personas", return_value=PERSONAS)
        patcher.start()
        self.addCleanup(patcher.stop)
        hermes = mock.patch.object(personas, "hermes_select", return_value=None)
        hermes.start()
        self.addCleanup(hermes.stop)

    def lane(self, persona):
        return SimpleNamespace(persona=persona)

    def test_title_beats_the_lane_base_resume(self):
        chosen = personas.select_persona(job("IT Business Analyst"), lane=self.lane("data_analyst"))
        self.assertEqual(chosen["id"], "business_analyst")

    def test_lane_base_resume_kept_when_title_does_not_name_another(self):
        chosen = personas.select_persona(job("Reporting Data Analyst"), lane=self.lane("data_analyst"))
        self.assertEqual(chosen["id"], "data_analyst")

    def test_title_decides_before_description_keywords_without_a_lane(self):
        posting = job("Business Analyst, Commercial", "analytics reporting analytics reporting")
        self.assertEqual(personas.select_persona(posting)["id"], "business_analyst")

    def test_override_still_wins(self):
        chosen = personas.select_persona(job("IT Business Analyst"), "finance_analyst",
                                         lane=self.lane("data_analyst"))
        self.assertEqual(chosen["id"], "finance_analyst")

    def test_version_without_its_own_lane_uses_its_named_lane(self):
        self.assertEqual(lanes.lane_for_persona("finance_analyst").slug, "data-analytics")


if __name__ == "__main__":
    unittest.main()
