"""Tag grammar (brief 3.1): every tag combination, plus the Stream D exclusivity rules."""

import unittest

from resume_gen.intake.noc_tags import parse_noc_teer, validate_tags


class ParseTests(unittest.TestCase):
    def test_full_stream_a_example(self):
        t = parse_noc_teer("22222 / TEER 2 | AIP: Nova Scotia | RELO+ | REMOTE | SRC: linkedin")
        self.assertEqual((t.noc, t.teer), ("22222", 2))
        self.assertEqual((t.pathway_type, t.pathway_detail), ("AIP", "Nova Scotia"))
        self.assertTrue(t.relocation)
        self.assertEqual(t.remote_type, "REMOTE")
        self.assertEqual(t.source, "linkedin")
        self.assertEqual(t.pathway_tag, "AIP: Nova Scotia")
        self.assertEqual(validate_tags(t, "streamA"), [])

    def test_bare_noc_with_source_only(self):
        t = parse_noc_teer("21232 / TEER 1 | SRC: jobbank")
        self.assertEqual(t.noc, "21232")
        self.assertEqual(t.pathway_type, "")
        self.assertFalse(t.relocation)
        self.assertEqual(validate_tags(t, "streamA"), [])

    def test_rcip_community(self):
        t = parse_noc_teer("22221 / TEER 2 | RCIP: Brandon | RELO+ | SRC: careers")
        self.assertEqual((t.pathway_type, t.pathway_detail), ("RCIP", "Brandon"))
        self.assertEqual(validate_tags(t, "streamB"), [])

    def test_rcip_unknown_community_is_flagged(self):
        t = parse_noc_teer("22221 / TEER 2 | RCIP: Toronto | SRC: careers")
        self.assertTrue(any("not a designated community" in v for v in validate_tags(t, "streamB")))

    def test_aip_unconfirmed(self):
        t = parse_noc_teer("11202 / TEER 1 | AIP: unconfirmed | SRC: careerbeacon")
        self.assertEqual(t.pathway_detail, "unconfirmed")
        self.assertEqual(validate_tags(t, "streamC"), [])

    def test_pnp(self):
        t = parse_noc_teer("21223 / TEER 1 | PNP: Ontario | REMOTE | SRC: indeed")
        self.assertEqual((t.pathway_type, t.pathway_detail), ("PNP", "Ontario"))
        self.assertEqual(validate_tags(t, "streamA"), [])

    def test_stream_d_full(self):
        for hire in ("entity", "eor", "contractor"):
            t = parse_noc_teer(f"22222 / TEER 2 | US-REMOTE | HIRE-CA: {hire} | SRC: remoteboard")
            self.assertEqual(t.remote_type, "US-REMOTE")
            self.assertEqual(t.hire_type, hire)
            self.assertEqual(validate_tags(t, "streamD"), [], hire)

    def test_stream_d_missing_hire_ca_is_a_violation(self):
        t = parse_noc_teer("22222 / TEER 2 | US-REMOTE | SRC: linkedin")
        v = validate_tags(t, "streamD")
        self.assertTrue(any("without a HIRE-CA" in x for x in v))

    def test_hire_ca_without_us_remote_is_a_violation(self):
        t = parse_noc_teer("22222 / TEER 2 | HIRE-CA: eor | SRC: linkedin")
        self.assertTrue(any("HIRE-CA without US-REMOTE" in x for x in validate_tags(t, "streamD")))

    def test_stream_d_never_carries_pathway_or_remote_tags(self):
        for bad in ("REMOTE", "RCIP: Brandon", "AIP: NS", "PNP: Ontario", "RELO+"):
            t = parse_noc_teer(f"22222 / TEER 2 | {bad} | US-REMOTE | HIRE-CA: entity | SRC: linkedin")
            v = validate_tags(t, "streamD")
            self.assertTrue(v, bad)
            self.assertTrue(any("Stream D" in x for x in v), (bad, v))

    def test_us_remote_never_appears_outside_stream_d(self):
        t = parse_noc_teer("22222 / TEER 2 | US-REMOTE | HIRE-CA: entity | SRC: linkedin")
        for stream in ("streamA", "streamB", "streamC"):
            v = validate_tags(t, stream)
            self.assertTrue(any("US-REMOTE on a" in x for x in v), stream)
            self.assertTrue(any("HIRE-CA on a" in x for x in v), stream)

    def test_missing_source_and_bad_source(self):
        self.assertTrue(any("missing SRC" in x for x in validate_tags(parse_noc_teer("22222 / TEER 2 | REMOTE"), "streamA")))
        self.assertTrue(any("SRC 'monster'" in x for x in validate_tags(parse_noc_teer("22222 / TEER 2 | SRC: monster"), "streamA")))

    def test_source_must_be_last(self):
        t = parse_noc_teer("22222 / TEER 2 | SRC: linkedin | REMOTE")
        self.assertTrue(any("not last" in x for x in validate_tags(t, "streamA")))

    def test_unknown_tag_is_reported_not_swallowed(self):
        t = parse_noc_teer("22222 / TEER 2 | FOO: bar | SRC: linkedin")
        self.assertEqual(t.unknown_tags, ["FOO: bar"])
        self.assertTrue(any("unknown tag" in x for x in validate_tags(t, "streamA")))

    def test_empty_and_garbage_never_raise(self):
        self.assertEqual(parse_noc_teer("").noc, "")
        t = parse_noc_teer("garbage")
        self.assertEqual(t.noc, "")
        self.assertTrue(validate_tags(t, "streamA"))

    def test_raw_is_kept(self):
        raw = "62100 / TEER 2 | RCIP: Altona | RELO+ | SRC: jobbank"
        self.assertEqual(parse_noc_teer(raw).raw, raw)


if __name__ == "__main__":
    unittest.main()
