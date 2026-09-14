"""Phase 1: lane data files, validator, converter, loader.

Definition-of-done items covered here:
* validate:data passes on all twelve lane files and fails loudly on a broken one;
* sync:lanes is idempotent and refuses to write when the markdown does not parse;
* a thirteenth lane needs only a markdown/JSON file, an index entry and a persona
  mapping (no code change), and the loader enumerates it.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from resume_gen import lanes
from resume_gen.config import ROOT
from resume_gen.lanes import sync as lane_sync
from resume_gen.lanes import validate as lane_validate

REAL_DATA = ROOT / "data"


def _copy_data(tmp: Path) -> Path:
    """A throwaway copy of data/ holding only the files the loader reads."""
    target = tmp / "data"
    (target / "lanes" / "source").mkdir(parents=True)
    for name in ("lanes.index.json", "noc.json", "profile.json", "answer-bank.json",
                 "outreach-templates.json"):
        shutil.copy(REAL_DATA / name, target / name)
    for f in (REAL_DATA / "lanes").glob("*.json"):
        shutil.copy(f, target / "lanes" / f.name)
    for f in (REAL_DATA / "lanes" / "source").glob("*.md"):
        shutil.copy(f, target / "lanes" / "source" / f.name)
    return target


class RealDataTests(unittest.TestCase):
    def setUp(self):
        lanes.use_data_dir(None)

    def test_validate_data_passes_on_shipped_files(self):
        problems = lane_validate.validate_data_dir(REAL_DATA)
        errors = [p for p in problems if p.level == "error"]
        self.assertEqual(errors, [], "\n".join(map(str, errors)))

    def test_twelve_lanes_load_and_every_status_is_a_known_value(self):
        all_lanes = lanes.all_lanes()
        self.assertEqual([l.lane for l in all_lanes], list(range(1, 13)))
        for lane in all_lanes:
            for s in lane.skills:
                self.assertIn(s.status, lanes.STATUSES)
                self.assertIn(s.tier, lanes.TIERS)
                if s.status in ("held", "partial"):
                    self.assertTrue(s.evidence.strip(), f"{lane.slug}/{s.id} lacks evidence")
                if s.status == "partial":
                    self.assertTrue(s.limit.strip(), f"{lane.slug}/{s.id} lacks limit")
                else:
                    self.assertFalse(s.evidence.strip() and not s.claimable,
                                     f"{lane.slug}/{s.id}: non-claimable skill carries evidence")

    def test_sync_is_idempotent(self):
        report = lane_sync.sync_all(check_only=True)
        self.assertEqual(report["would_change"], [])
        self.assertEqual(len(report["unchanged"]), 12)

    def test_no_drift_between_markdown_and_json(self):
        self.assertTrue(all(r["status"] == "ok" for r in lane_sync.drift_report()))

    def test_resolve_lane_accepts_the_short_names_the_engine_emits(self):
        for text, slug in (("QA", "qa-testing"), ("IT support", "it-support"),
                           ("AI/automation", "ai-automation"), ("Data analytics", "data-analytics"),
                           ("Game dev", "game-development"), ("VFX", "vfx"), ("lane 7", "digital-marketing")):
            self.assertEqual(lanes.resolve_lane(text).slug, slug, text)
        self.assertIsNone(lanes.resolve_lane("zzz nothing"))

    def test_claimable_is_only_held_or_partial(self):
        lane = lanes.get_lane(1)
        by_status = {s.status: s for s in lane.skills}
        self.assertTrue(by_status["held"].claimable)
        self.assertTrue(by_status["partial"].claimable)
        self.assertFalse(by_status["not_yet"].claimable)
        self.assertFalse(by_status["not_yet"].fit_sentence_source)


class BrokenDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = _copy_data(self.tmp)
        lanes.use_data_dir(self.data)

    def tearDown(self):
        lanes.use_data_dir(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lane_json(self, n: int) -> Path:
        return next((self.data / "lanes").glob(f"lane-{n:02d}-*.json"))

    def test_held_skill_without_evidence_fails_validation(self):
        p = self._lane_json(5)
        d = json.loads(p.read_text(encoding="utf-8"))
        d["skills"][0]["evidence"] = ""
        p.write_text(json.dumps(d), encoding="utf-8")
        errors = [x for x in lane_validate.validate_data_dir(self.data) if x.level == "error"]
        self.assertTrue(any("has no evidence" in str(e) for e in errors))
        with self.assertRaises(lanes.LaneDataError):
            lanes.reload(); lanes.load_lanes()

    def test_unknown_status_value_fails_loudly(self):
        p = self._lane_json(2)
        d = json.loads(p.read_text(encoding="utf-8"))
        d["skills"][0]["status"] = "expert"
        p.write_text(json.dumps(d), encoding="utf-8")
        with self.assertRaises(lanes.LaneDataError):
            lanes.reload(); lanes.load_lanes()

    def test_unknown_noc_code_fails(self):
        p = self._lane_json(3)
        d = json.loads(p.read_text(encoding="utf-8"))
        d["noc"][0]["code"] = "99999"
        p.write_text(json.dumps(d), encoding="utf-8")
        errors = [x for x in lane_validate.validate_data_dir(self.data) if x.level == "error"]
        self.assertTrue(any("99999" in str(e) for e in errors))

    def test_us_work_authorization_must_be_false(self):
        p = self.data / "profile.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["us_work_authorization"] = True
        p.write_text(json.dumps(d), encoding="utf-8")
        errors = [x for x in lane_validate.validate_data_dir(self.data) if x.level == "error"]
        self.assertTrue(any("us_work_authorization" in str(e) for e in errors))

    def test_sync_refuses_to_write_when_markdown_does_not_parse(self):
        md = next((self.data / "lanes" / "source").glob("lane-04-*.md"))
        text = md.read_text(encoding="utf-8")
        md.write_text(text + "\n## Aliases\n\n- Not A Real Skill: foo, bar\n", encoding="utf-8")
        before = {p.name: p.read_bytes() for p in (self.data / "lanes").glob("*.json")}
        with self.assertRaises(lane_sync.LaneSyncError):
            lane_sync.sync_all()
        after = {p.name: p.read_bytes() for p in (self.data / "lanes").glob("*.json")}
        self.assertEqual(before, after, "a failed sync must write nothing")

    def test_drift_is_detected_when_markdown_changes(self):
        md = next((self.data / "lanes" / "source").glob("lane-06-*.md"))
        md.write_text(md.read_text(encoding="utf-8") + "\nEdited by hand.\n", encoding="utf-8")
        rows = {r["lane"]: r["status"] for r in lane_sync.drift_report()}
        self.assertEqual(rows[6], "drift")
        self.assertEqual(rows[5], "ok")


LANE_13_MD = """# Lane 13 | Throwaway test lane

NOC 21232, TEER 1. Test lane.

**PR note.** None.

## Must

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| Widget wrangling | Wrangling widgets | held | Wrangled widgets at Example Co. |
| Gadget tuning | Tuning gadgets | not yet | |

## Optional

| Skill | Note | Status |
|---|---|---|
| Sprocket polishing | Rare | not yet |

## Not required

Nothing.

## Sourcing vocabulary

- **Core:** widget wrangler, junior widget wrangler.

## Honest positioning

A test lane.

## Interview watch

None.

## Aliases

- Widget wrangling: widgets, widget ops
"""


class ThirteenthLaneTests(unittest.TestCase):
    """Adding a lane is a markdown file, an index entry and a persona mapping."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = _copy_data(self.tmp)
        lanes.use_data_dir(self.data)

    def tearDown(self):
        lanes.use_data_dir(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lane_13_needs_no_code_change(self):
        (self.data / "lanes" / "source" / "lane-13-throwaway.md").write_text(LANE_13_MD, encoding="utf-8")
        idx_path = self.data / "lanes.index.json"
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        idx["lanes"].append({
            "lane": 13, "slug": "throwaway", "file": "lanes/lane-13-throwaway.json",
            "source": "lanes/source/lane-13-throwaway.md", "title": "Throwaway test lane",
            "track": "technical", "set": "opportunistic", "noc": ["21232"],
            "match": ["widgets"], "persona": "software", "links": ["linkedin", "code"],
        })
        idx_path.write_text(json.dumps(idx, indent=2), encoding="utf-8")

        report = lane_sync.sync_all()
        self.assertIn("lanes/lane-13-throwaway.json", report["written"])
        errors = [x for x in lane_validate.validate_data_dir(self.data) if x.level == "error"]
        self.assertEqual(errors, [], "\n".join(map(str, errors)))

        lanes.reload()
        loaded = lanes.all_lanes()
        self.assertEqual(len(loaded), 13)
        l13 = lanes.get_lane("throwaway")
        self.assertEqual(l13.lane, 13)
        self.assertEqual(l13.skill("widget-wrangling").aliases, ["widgets", "widget ops"])
        self.assertEqual(l13.skill("gadget-tuning").status, "not_yet")
        self.assertEqual(lanes.resolve_lane("widgets").slug, "throwaway")
        self.assertEqual([p.label for p in lanes.portfolio_links_for(l13)], ["LinkedIn", "GitHub"])


if __name__ == "__main__":
    unittest.main()
