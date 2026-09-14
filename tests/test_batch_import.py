"""Phase 2: a full day's twelve CSVs import cleanly with a report, and re-importing
the same day changes nothing. Also exercises dedupe, Stream D validation, the
fit-report join and the contact confidence merge."""

from __future__ import annotations

import csv
import io
import unittest

from resume_gen.intake import batch_import as bi
from resume_gen.intake.store import get_job, list_queue
from resume_gen.outreach import contacts as oc

from tests._dbtmp import TempDB

LONG = ("We are looking for someone to join the team. " * 8).strip()


def _csv(cols, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    return buf.getvalue()


def jobs_file(stream, date, rows):
    return (f"jobs_import_{stream}_{date}.csv", _csv(bi.JOBS_COLUMNS, rows))


def companies_file(stream, date, rows):
    return (f"hr_companies_{stream}_{date}.csv", _csv(bi.COMPANIES_COLUMNS, rows))


def fit_file(stream, date, rows):
    return (f"fit_report_{stream}_{date}.csv", _csv(bi.FIT_COLUMNS, rows))


def job(company, title, lane, noc_teer, desc=LONG, **kw):
    d = {"company": company, "title": title, "location": "London, ON", "description": desc,
         "contact_email": "", "apply_url": f"https://{company.lower().replace(' ', '')}.example/jobs/1",
         "posted": "2026-09-14", "priority": "HIGH", "lane": lane, "noc_teer": noc_teer}
    d.update(kw)
    return d


DA_DESC = ("About the role | We need a junior data analyst. | Requirements | SQL (joins, CTEs, window functions) required | "
           "Power BI dashboards and DAX | Excel with pivot tables | 1 to 2 years of experience | "
           "Nice to have | Tableau | Snowflake is an asset")
QA_DESC = ("Responsibilities | Test our web app. | Requirements | Test case design from requirements | "
           "Jira and TestRail | Playwright or Cypress automation required | SQL for test data | 2+ years experience | " + LONG)
DAY = "2026-09-14"


def a_day():
    """Twelve files: four streams x three files."""
    files = []
    files += [jobs_file("streamA", DAY, [
        job("Acme Analytics Inc", "Junior Data Analyst", "Data analytics", "21223 / TEER 1 | REMOTE | SRC: linkedin", DA_DESC),
        job("Globex Corp", "QA Analyst", "QA", "22222 / TEER 2 | SRC: indeed", QA_DESC),
        job("Globex Corp", "QA Analyst", "QA", "22222 / TEER 2 | SRC: indeed", QA_DESC),   # within-stream dup
    ]), companies_file("streamA", DAY, [
        {"company": "Acme Analytics Inc", "hr_name": "Jane Doe", "hr_email": "jane.doe@acme.example", "ats": "greenhouse",
         "careers_url": "https://acme.example/careers", "notes": "linkedin recruiter; enriched via Vibe"},
        {"company": "Globex Corp", "hr_name": "", "hr_email": "careers@globex.example", "ats": "workday", "notes": "pattern guess"},
    ]), fit_file("streamA", DAY, [
        {"company": "Acme Analytics Inc", "title": "Junior Data Analyst", "verified_on": DAY, "posting_live": "yes",
         "years_line": "1 to 2 years of experience", "fit_evidence": "SQL and Power BI", "gap_flags": "none", "track": "technical"},
        {"company": "Globex Corp", "title": "QA Analyst", "verified_on": DAY, "posting_live": "yes",
         "years_line": "2+ years experience", "fit_evidence": "x", "gap_flags": "Playwright", "track": "technical"},
    ])]
    files += [jobs_file("streamB", DAY, [
        job("Initech Ltd", "IT Support Technician", "IT support", "22221 / TEER 2 | RCIP: Brandon | RELO+ | SRC: careers",
            "Requirements | Windows 10 support | Active Directory | Microsoft 365 | ticketing and SLAs | " + LONG),
    ]), companies_file("streamB", DAY, [
        {"company": "Initech Ltd", "hr_email": "hr@initech.example", "ats": "bamboohr", "notes": "designated RCIP employer confirmed 2026-09-10"},
    ]), fit_file("streamB", DAY, [])]
    files += [jobs_file("streamC", DAY, [
        # Same role as Stream A: C must win.
        job("Acme Analytics, Inc.", "Junior Data Analyst", "Data analytics", "21223 / TEER 1 | AIP: Nova Scotia | RELO+ | SRC: careerbeacon", DA_DESC),
    ]), companies_file("streamC", DAY, [
        # Verified address for Acme: should upgrade the enriched one, never be downgraded later.
        {"company": "Acme Analytics Inc", "hr_name": "Jane Doe", "hr_email": "jane.doe@acme.example", "ats": "greenhouse", "notes": "email verified by reply"},
    ]), fit_file("streamC", DAY, [])]
    files += [jobs_file("streamD", DAY, [
        job("Umbrella LLC", "Senior QA Engineer", "QA", "22222 / TEER 2 | US-REMOTE | HIRE-CA: eor | SRC: remoteboard", QA_DESC,
            location="Remote (US employer)"),
        # Violation: REMOTE on a Stream D row and no HIRE-CA.
        job("Hooli", "Support Engineer", "IT support", "22221 / TEER 2 | REMOTE | US-REMOTE | SRC: linkedin",
            "Requirements | Windows support | " + LONG, location="Remote (US employer)"),
    ]), companies_file("streamD", DAY, [
        {"company": "Umbrella LLC", "hr_email": "talent@umbrella.example", "ats": "lever", "notes": "hire-in-Canada: ATS picker offers Canada, checked 2026-09-14"},
    ]), fit_file("streamD", DAY, [
        {"company": "Umbrella LLC", "title": "Senior QA Engineer", "verified_on": DAY, "posting_live": "yes",
         "years_line": "2+ years experience", "fit_evidence": "x", "gap_flags": "no PR pathway", "track": "technical"},
    ])]
    return files


class BatchImportTests(unittest.TestCase):
    def test_full_day_imports_and_reimport_is_a_no_op(self):
        with TempDB():
            rep = bi.import_batch(a_day())
            self.assertEqual(len(rep["files"]), 12)
            self.assertTrue(all(not f["errors"] for f in rep["files"]), rep["files"])
            j = rep["jobs"]
            self.assertEqual(j["rows_in"], 7)
            self.assertEqual(j["deduped_within_stream"], 1)
            self.assertEqual(j["deduped_cross_stream"], 1)
            self.assertEqual(j["new"], 5)
            self.assertEqual(sorted(rep["streams"]), ["streamA", "streamB", "streamC", "streamD"])

            queue = list_queue()
            self.assertEqual(len(queue), 5)
            acme = next(q for q in queue if q.company.startswith("Acme"))
            self.assertEqual(acme.stream, "streamC", "C over A on the same day")
            self.assertEqual((acme.pathway_type, acme.pathway_detail), ("AIP", "Nova Scotia"))
            self.assertTrue(acme.relocation)
            self.assertEqual(acme.lane_slug, "data-analytics")
            self.assertEqual(acme.noc, "21223"); self.assertEqual(acme.teer, 1)
            self.assertIn("\n", acme.description); self.assertIn(" | ", acme.description_raw)
            self.assertEqual(acme.fit.get("years_line"), "1 to 2 years of experience")
            self.assertEqual(acme.grade["tier"], "A", acme.grade)
            self.assertEqual(acme.grade["gap_flags"], [])
            self.assertTrue(acme.grade["fit_sentence"])
            self.assertTrue(acme.grade["evidence_skill_ids"])
            self.assertFalse(acme.seniority["warning"])

            glob = next(q for q in queue if q.company.startswith("Globex"))
            self.assertEqual(glob.grade["tier"], "C", glob.grade["tier_reason"])   # 3+ Must gaps in lane 1
            self.assertTrue(any(g.startswith("Test automation") or g.startswith("Test case design") for g in glob.grade["gap_flags"]))

            umb = next(q for q in queue if q.company.startswith("Umbrella"))
            self.assertEqual((umb.remote_type, umb.hire_type), ("US-REMOTE", "eor"))
            self.assertEqual(umb.tag_violations, [])
            self.assertTrue(umb.seniority["warning"], "Senior title with 2+ must warn")
            hooli = next(q for q in queue if q.company == "Hooli")
            self.assertTrue(hooli.tag_violations)
            self.assertEqual(len(rep["jobs"]["tag_violations"]), 1)

            # companies + contacts
            self.assertEqual(rep["companies"]["rows_in"], 5)
            acme_contacts = oc.contacts_for_company("Acme Analytics Inc")
            self.assertEqual(len(acme_contacts), 1)
            self.assertEqual(acme_contacts[0]["confidence"], "verified", "C's verified row upgrades A's enriched row")
            self.assertEqual(oc.contacts_for_company("Globex Corp")[0]["confidence"], "pattern_guess")
            self.assertEqual(oc.contacts_for_company("Initech Ltd")[0]["designated_employer_status"], "confirmed")
            self.assertEqual(rep["fit"]["joined"], 3)

            # ---- re-import the same twelve files: nothing changes -------------
            before = {q.key_id: q.model_dump_json() for q in list_queue()}
            rep2 = bi.import_batch(a_day())
            self.assertEqual(rep2["jobs"]["new"], 0)
            self.assertEqual(rep2["jobs"]["already_known"], 5)
            after = list_queue()
            self.assertEqual(len(after), 5)
            for q in after:
                b = before[q.key_id]
                # Only the batches list and the graded_at timestamps may move.
                self.assertEqual(q.description, get_job(q.key_id).description)
                self.assertEqual(q.stream, next(x for x in after if x.key_id == q.key_id).stream)
                self.assertIn(rep["batch_id"], q.batches)
                self.assertIn(rep2["batch_id"], q.batches)
            self.assertEqual(oc.contacts_for_company("Acme Analytics Inc")[0]["confidence"], "verified")
            self.assertEqual(len(bi.list_batches()), 2)

    def test_verified_address_is_never_downgraded_by_a_guess(self):
        with TempDB():
            oc.upsert_contact(company="Acme", hr_email="jane@acme.example", confidence="verified", set_by="keerthi")
            c, outcome = oc.upsert_contact(company="Acme Inc.", hr_email="jane@acme.example", notes="pattern guess")
            self.assertEqual(outcome, "kept_existing")
            self.assertEqual(c["confidence"], "verified")
            c2, outcome2 = oc.upsert_contact(company="Acme", hr_email="jane@acme.example", notes="pattern guess",
                                             confidence="pattern_guess", override=True)
            self.assertEqual(c2["confidence"], "pattern_guess")

    def test_wrong_header_is_rejected_with_a_reason(self):
        with TempDB():
            bad = ("jobs_import_streamA_2026-09-14.csv", "company,title,location\nA,B,C\n")
            rep = bi.import_batch([bad])
            self.assertTrue(rep["files"][0]["errors"])
            self.assertIn("header must be exactly", rep["files"][0]["errors"][0])
            self.assertEqual(rep["jobs"]["new"], 0)

    def test_short_description_and_blank_company_are_rejected(self):
        with TempDB():
            rep = bi.import_batch([jobs_file("streamA", DAY, [
                job("X Co", "Dev", "software", "21232 / TEER 1 | SRC: linkedin", desc="too short"),
                job("", "Dev", "software", "21232 / TEER 1 | SRC: linkedin"),
            ])])
            reasons = [r["reason"] for r in rep["jobs"]["rejected"]]
            self.assertEqual(len(reasons), 2)
            self.assertTrue(any("200 characters" in r for r in reasons))
            self.assertTrue(any("blank" in r for r in reasons))

    def test_unnamed_file_is_sniffed_from_its_header(self):
        with TempDB():
            name, text = jobs_file("streamA", DAY, [job("Y Co", "Data Analyst", "Data analytics", "21223 / TEER 1 | SRC: indeed", DA_DESC)])
            rep = bi.import_batch([("upload.csv", text)])
            self.assertEqual(rep["files"][0]["kind"], "jobs")
            self.assertEqual(rep["jobs"]["new"], 1)

    def test_fit_report_row_without_a_job_is_reported(self):
        with TempDB():
            rep = bi.import_batch([fit_file("streamA", DAY, [
                {"company": "Nobody", "title": "Nothing", "verified_on": DAY, "posting_live": "yes",
                 "years_line": "none stated", "fit_evidence": "", "gap_flags": "none", "track": "technical"}])])
            self.assertEqual(rep["fit"]["unmatched"], ["nobody / nothing"])


if __name__ == "__main__":
    unittest.main()
