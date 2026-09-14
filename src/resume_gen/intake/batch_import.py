"""Three-file batch import for one sourcing run (brief section 3).

    jobs_import_<stream>_<YYYY-MM-DD>.csv     exactly ten columns, in order
    hr_companies_<stream>_<YYYY-MM-DD>.csv    one row per company
    fit_report_<stream>_<YYYY-MM-DD>.csv      keyed on company + title

A whole day's twelve files can be passed in one call. Behaviour:

* File 1 first, then File 2, then File 3 joins onto both, whatever order the
  files arrive in.
* Dedupe on normalised company + title (legal suffixes stripped, lowercase,
  whitespace collapsed). Never on any upstream id.
* Cross-stream dedupe on the same day keeps the stronger pathway: C over B over
  A over D.
* Additive. A role already in the queue is not overwritten; the new batch id is
  appended to its `batches` list and blank fields are filled. Re-importing the
  same day changes nothing.
* `description` is restored to readable text; the pipe-joined raw is kept.
* Every row is graded against its lane matrix and run through the seniority
  guard on the way in.
* The report lists rows in, deduped, rejected and why, tag violations, and
  companies new versus known.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from collections import Counter
from datetime import datetime

from . import db
from .companies import save_company
from .models import JobPosting, QueuedJob
from .noc_tags import STREAMS, parse_noc_teer, validate_tags
from .store import _norm_company, _norm_title, get_job

JOBS_COLUMNS = ["company", "title", "location", "description", "contact_email",
                "apply_url", "posted", "priority", "lane", "noc_teer"]
COMPANIES_COLUMNS = ["company", "hr_name", "hr_email", "hr_phone", "ats", "careers_url", "notes"]
FIT_COLUMNS = ["company", "title", "verified_on", "posting_live", "years_line",
               "fit_evidence", "gap_flags", "track"]
ATS_VALUES = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "bamboohr",
              "workday", "icims", "taleo", "indeed", "linkedin", "other")
STREAM_STRENGTH = {"streamC": 3, "streamB": 2, "streamA": 1, "streamD": 0, "": -1}

_FILENAME = re.compile(r"^(jobs_import|hr_companies|fit_report)_(stream[ABCD])_(\d{4}-\d{2}-\d{2})\.csv$", re.I)


class BatchFile:
    def __init__(self, name: str, text: str):
        self.name = name
        self.text = text.lstrip("﻿")
        m = _FILENAME.match((name or "").strip().split("/")[-1].split("\\")[-1])
        if m:
            self.kind = {"jobs_import": "jobs", "hr_companies": "companies", "fit_report": "fit"}[m.group(1).lower()]
            self.stream = "stream" + m.group(2)[-1].upper()
            self.run_date = m.group(3)
            self.named = True
        else:
            self.kind, self.stream, self.run_date, self.named = self._sniff(), "", "", False
        self.rows: list[dict] = []
        self.header: list[str] = []
        self.errors: list[str] = []

    def _sniff(self) -> str:
        first = self.text.splitlines()[0].strip().lower() if self.text.strip() else ""
        cols = [c.strip().strip('"') for c in first.split(",")]
        if cols[:3] == ["company", "title", "location"] and "noc_teer" in cols:
            return "jobs"
        if cols[:3] == ["company", "hr_name", "hr_email"]:
            return "companies"
        if cols[:3] == ["company", "title", "verified_on"]:
            return "fit"
        return "unknown"

    def parse(self) -> None:
        reader = csv.reader(io.StringIO(self.text))
        try:
            self.header = [h.strip().lstrip("﻿") for h in next(reader)]
        except StopIteration:
            self.errors.append("empty file")
            return
        expected = {"jobs": JOBS_COLUMNS, "companies": COMPANIES_COLUMNS, "fit": FIT_COLUMNS}.get(self.kind)
        if expected is None:
            self.errors.append("not a jobs_import, hr_companies or fit_report file")
            return
        if [h.lower() for h in self.header] != expected:
            self.errors.append(f"header must be exactly {','.join(expected)}; got {','.join(self.header)}")
            return
        for i, cells in enumerate(reader, start=2):
            if not any(c.strip() for c in cells):
                continue
            if len(cells) != len(expected):
                self.errors.append(f"row {i}: {len(cells)} columns, expected {len(expected)}")
                continue
            row = {k: (v or "").strip() for k, v in zip(expected, cells)}
            row["_line"] = i
            self.rows.append(row)


def restore_description(raw: str) -> str:
    """The engine replaced newlines with ' | '. Put them back for display."""
    t = re.sub(r"\s\|\s", "\n", raw or "")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def dedupe_key(company: str, title: str) -> str:
    return f"{_norm_company(company)}|{_norm_title(title)}"


def _posting_from_row(row: dict, stream: str, run_date: str) -> JobPosting:
    company, title = row["company"], row["title"]
    # Key on normalised company + title so the same role from any stream or day
    # lands on the same row. Upstream ids are session-scoped and never used.
    return JobPosting(
        source="batch", source_company=_norm_company(company), job_id=_norm_title(title),
        company=company, title=title, location=row.get("location", ""),
        description=restore_description(row.get("description", "")),
        apply_url=row.get("apply_url", ""), contact_email=row.get("contact_email", ""),
        posted=row.get("posted", ""),
    )


def import_batch(files: list[tuple[str, str]], *, grade: bool = True, actor: str = "keerthi") -> dict:
    """Import a set of (filename, csv_text) pairs. Returns the import report."""
    from ..grading import grade_job
    from ..outreach.contacts import upsert_contact
    from .. import lanes as lane_data

    batch_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat(timespec="seconds")
    parsed = [BatchFile(n, t) for n, t in files]
    for f in parsed:
        f.parse()

    report: dict = {
        "batch_id": batch_id, "imported_at": now,
        "files": [{"name": f.name, "kind": f.kind, "stream": f.stream, "run_date": f.run_date,
                   "rows": len(f.rows), "errors": f.errors} for f in parsed],
        "jobs": {"rows_in": 0, "new": 0, "already_known": 0, "deduped_within_stream": 0,
                 "deduped_cross_stream": 0, "rejected": [], "tag_violations": [],
                 "seniority_warnings": 0, "lane_unresolved": 0, "tiers": {}},
        "companies": {"rows_in": 0, "new": 0, "known": 0, "contacts_new": 0, "contacts_upgraded": 0,
                      "contacts_unchanged": 0, "rejected": []},
        "fit": {"rows_in": 0, "joined": 0, "unmatched": []},
        "new_job_keys": [], "streams": sorted({f.stream for f in parsed if f.stream}),
        "run_dates": sorted({f.run_date for f in parsed if f.run_date}),
    }

    # ---- File 1: collect every jobs row across streams, then dedupe ----------
    candidates: dict[str, dict] = {}   # dedupe key -> best candidate
    jobs_files = [f for f in parsed if f.kind == "jobs" and not f.errors]
    for f in jobs_files:
        seen_in_file: set[str] = set()
        for row in f.rows:
            report["jobs"]["rows_in"] += 1
            if not row["company"] or not row["title"]:
                report["jobs"]["rejected"].append({"file": f.name, "line": row["_line"], "reason": "company or title blank"})
                continue
            if len(row.get("description", "")) < 200:
                report["jobs"]["rejected"].append({"file": f.name, "line": row["_line"],
                                                   "reason": f"description under 200 characters ({len(row.get('description', ''))})"})
                continue
            key = dedupe_key(row["company"], row["title"])
            if key in seen_in_file:
                report["jobs"]["deduped_within_stream"] += 1
                continue
            seen_in_file.add(key)
            tags = parse_noc_teer(row.get("noc_teer", ""))
            violations = validate_tags(tags, f.stream)
            if violations:
                report["jobs"]["tag_violations"].append({"file": f.name, "line": row["_line"],
                                                         "company": row["company"], "title": row["title"],
                                                         "noc_teer": row.get("noc_teer", ""), "violations": violations})
            cand = {"row": row, "file": f, "tags": tags, "violations": violations, "key": key}
            prev = candidates.get(key)
            if prev is None:
                candidates[key] = cand
            else:
                # Cross-stream on the same day: keep the stronger pathway (C > B > A > D).
                if STREAM_STRENGTH.get(f.stream, -1) > STREAM_STRENGTH.get(prev["file"].stream, -1):
                    candidates[key] = cand
                report["jobs"]["deduped_cross_stream"] += 1

    new_jobs: dict[str, QueuedJob] = {}
    known_jobs: dict[str, QueuedJob] = {}
    tier_counter: Counter = Counter()
    with db.connect() as conn:
        for key, cand in candidates.items():
            row, f, tags = cand["row"], cand["file"], cand["tags"]
            posting = _posting_from_row(row, f.stream, f.run_date)
            existing = get_job(posting.key)
            lane = lane_data.resolve_lane(row.get("lane", "")) or lane_data.resolve_lane(row.get("title", ""))
            if existing is not None:
                report["jobs"]["already_known"] += 1
                changed = False
                if batch_id not in existing.batches:
                    existing.batches = [*existing.batches, batch_id]
                    changed = True
                # Fill blanks only: never overwrite a prior batch's content.
                fills = {"stream": f.stream, "run_date": f.run_date, "priority_tag": row.get("priority", ""),
                         "lane": row.get("lane", ""), "lane_slug": lane.slug if lane else "",
                         "noc": tags.noc, "teer": tags.teer, "noc_teer_raw": tags.raw,
                         "pathway_type": tags.pathway_type, "pathway_detail": tags.pathway_detail,
                         "remote_type": tags.remote_type, "hire_type": tags.hire_type,
                         "source_tag": tags.source, "description_raw": row.get("description", ""),
                         "apply_url": posting.apply_url, "contact_email": posting.contact_email,
                         "posted": posting.posted}
                for k, v in fills.items():
                    if v not in ("", None) and getattr(existing, k, None) in ("", None, 0, False):
                        setattr(existing, k, v); changed = True
                if tags.relocation and not existing.relocation:
                    existing.relocation = True; changed = True
                if changed:
                    db._upsert_job_row(conn, json.loads(existing.model_dump_json()))
                known_jobs[key] = existing
                continue

            q = QueuedJob(**posting.model_dump(), key_id=posting.key, status="new", found_at=now,
                          lane=row.get("lane", ""), lane_slug=lane.slug if lane else "",
                          track=(lane.track if lane else ""), stream=f.stream, run_date=f.run_date,
                          batches=[batch_id], priority_tag=row.get("priority", ""),
                          noc=tags.noc, teer=tags.teer, noc_teer_raw=tags.raw,
                          pathway_type=tags.pathway_type, pathway_detail=tags.pathway_detail,
                          relocation=tags.relocation, remote_type=tags.remote_type,
                          hire_type=tags.hire_type, source_tag=tags.source,
                          tag_violations=cand["violations"], description_raw=row.get("description", ""),
                          ledger_status="pending")
            if not lane:
                report["jobs"]["lane_unresolved"] += 1
            new_jobs[key] = q
            report["jobs"]["new"] += 1
            report["new_job_keys"].append(q.key_id)

    # ---- File 3: join fit report onto new + known rows (before grading) -------
    fit_by_key: dict[str, dict] = {}
    for f in [x for x in parsed if x.kind == "fit" and not x.errors]:
        for row in f.rows:
            report["fit"]["rows_in"] += 1
            fit_by_key[dedupe_key(row["company"], row["title"])] = {k: row.get(k, "") for k in FIT_COLUMNS[2:]}
    for key, fit in fit_by_key.items():
        target = new_jobs.get(key) or known_jobs.get(key)
        if target is None:
            # Maybe it matches a job from an earlier batch.
            posting = JobPosting(source="batch", source_company=key.split("|")[0], job_id=key.split("|")[1])
            target = get_job(posting.key)
            if target is not None:
                known_jobs[key] = target
        if target is None:
            report["fit"]["unmatched"].append(key.replace("|", " / "))
            continue
        if not target.fit:
            target.fit = fit
            if not target.track and fit.get("track"):
                target.track = fit["track"]
        report["fit"]["joined"] += 1

    # ---- grade + seniority, then persist jobs -------------------------------
    with db.connect() as conn:
        for key, q in list(new_jobs.items()) + [(k, j) for k, j in known_jobs.items() if k in fit_by_key]:
            if grade:
                g, sen = grade_job(q)
                q.grade, q.seniority = g, sen
                if q in new_jobs.values():
                    tier_counter[g.get("tier") or "ungraded"] += 1
                    if sen.get("warning"):
                        report["jobs"]["seniority_warnings"] += 1
            db._upsert_job_row(conn, json.loads(q.model_dump_json()))
            conn.execute("INSERT OR IGNORE INTO seen(key) VALUES (?)", (q.key_id,))
    report["jobs"]["tiers"] = dict(tier_counter)

    # ---- File 2: companies + outreach contacts --------------------------------
    for f in [x for x in parsed if x.kind == "companies" and not x.errors]:
        for row in f.rows:
            report["companies"]["rows_in"] += 1
            if not row["company"]:
                report["companies"]["rejected"].append({"file": f.name, "line": row["_line"], "reason": "company blank"})
                continue
            ats = row.get("ats", "").strip().lower()
            if ats and ats not in ATS_VALUES:
                report["companies"]["rejected"].append({"file": f.name, "line": row["_line"],
                                                        "reason": f"ats {ats!r} not in {ATS_VALUES}"})
                ats = "other"
            from .companies import get_company
            existed = get_company(row["company"]) is not None
            data = {k: row[k] for k in ("hr_name", "hr_phone", "careers_url", "notes") if row.get(k)}
            if ats:
                data["ats"] = ats
            emails = [e.strip() for e in re.split(r"[;,]", row.get("hr_email", "")) if "@" in e]
            if emails:
                existing_contacts = (get_company(row["company"]) or {}).get("hr_contacts") or []
                merged, seen_e = [], set()
                for c in existing_contacts + [{"name": row.get("hr_name", ""), "email": e} for e in emails]:
                    e = (c.get("email") or "").strip().lower()
                    if e and e not in seen_e:
                        seen_e.add(e); merged.append({"name": (c.get("name") or "").strip(), "email": c["email"].strip()})
                data["hr_contacts"] = merged
            data["last_batch"] = batch_id
            data["stream"] = f.stream
            save_company(row["company"], data)
            report["companies"]["known" if existed else "new"] += 1
            for e in emails:
                _, outcome = upsert_contact(company=row["company"], hr_email=e, hr_name=row.get("hr_name", ""),
                                            hr_phone=row.get("hr_phone", ""), ats=ats,
                                            careers_url=row.get("careers_url", ""), notes=row.get("notes", ""),
                                            source=f"{f.stream}:{f.run_date}" if f.stream else "import")
                if outcome == "new":
                    report["companies"]["contacts_new"] += 1
                elif outcome in ("upgraded", "updated", "overridden"):
                    report["companies"]["contacts_upgraded"] += 1
                else:
                    report["companies"]["contacts_unchanged"] += 1

    # ---- record the batch ----------------------------------------------------
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO import_batches (batch_id, stream, run_date, imported_at, data) VALUES (?, ?, ?, ?, ?)",
            (batch_id, ",".join(report["streams"]), ",".join(report["run_dates"]), now,
             json.dumps({**report, "actor": actor}, ensure_ascii=False)))
    return report


def list_batches(limit: int = 50) -> list[dict]:
    with db.connect() as conn:
        cur = conn.execute("SELECT data FROM import_batches ORDER BY imported_at DESC LIMIT ?", (limit,))
        out = []
        for r in cur.fetchall():
            try:
                d = json.loads(r["data"])
            except ValueError:
                continue
            out.append({"batch_id": d.get("batch_id"), "imported_at": d.get("imported_at"),
                        "streams": d.get("streams"), "run_dates": d.get("run_dates"),
                        "jobs": {k: v for k, v in (d.get("jobs") or {}).items() if k in ("rows_in", "new", "already_known", "tiers")},
                        "companies": {k: v for k, v in (d.get("companies") or {}).items() if k in ("rows_in", "new", "known")},
                        "files": [f["name"] for f in d.get("files", [])]})
        return out


def get_batch(batch_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT data FROM import_batches WHERE batch_id = ?", (batch_id,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["data"])
    except ValueError:
        return None


def regrade_all(only_keys: list[str] | None = None) -> dict:
    """Re-run grading + seniority over queued jobs (after a matrix update)."""
    from ..grading import grade_job
    from .store import list_queue

    n = Counter()
    with db.connect() as conn:
        for q in list_queue():
            if only_keys and q.key_id not in only_keys:
                continue
            if not (q.lane_slug or q.lane):
                from .. import lanes as lane_data
                lane = lane_data.resolve_lane(q.title)
                if lane is None:
                    n["skipped_no_lane"] += 1
                    continue
                q.lane_slug = lane.slug
            g, sen = grade_job(q)
            q.grade, q.seniority = g, sen
            db._upsert_job_row(conn, json.loads(q.model_dump_json()))
            n[g.get("tier") or "ungraded"] += 1
    return dict(n)
