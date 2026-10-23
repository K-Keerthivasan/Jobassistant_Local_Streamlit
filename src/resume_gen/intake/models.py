"""Normalized job posting + its dedup key. One JobPosting -> one TargetRole."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from ..models import TargetRole


class JobPosting(BaseModel):
    source: str = ""          # greenhouse | lever | workday | generic
    source_company: str = ""  # board token / tenant / domain used to fetch
    job_id: str = ""          # stable id from the source
    company: str = ""
    title: str = ""
    location: str = ""
    description: str = ""
    apply_url: str = ""
    contact_email: str = ""
    posted: str = ""
    # Extra metadata captured by the browser saver (not used for generation, kept
    # for reference/filtering).
    salary: str = ""
    job_type: str = ""
    key_skills: str = ""

    @property
    def key(self) -> str:
        """Stable dedup key across runs."""
        raw = f"{self.source}:{self.source_company}:{self.job_id or self.apply_url or self.title}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_target_role(self) -> TargetRole:
        return TargetRole(
            company=self.company,
            title=self.title,
            description=self.description,
            location=self.location,
            apply_url=self.apply_url,
            contact_email=self.contact_email,
        )


class QueuedJob(JobPosting):
    """A JobPosting persisted in the review queue, with status tracking."""

    key_id: str = ""
    status: str = "new"       # new | generated | approved | sent | applied | skipped
    applied: bool = False     # marked applied (independent of generation status)
    priority: bool = False    # legacy ⭐ flag (superseded by priority_override)
    priority_override: str = ""  # manual priority pin: "" (auto) | high | medium | low
    repeatable: bool = False  # 🔁 saved as a recurring-role template (reapply often)
    irrelevant: bool = False  # 🚫 not a relevant job — hidden from the active lists
    resume_version: str = ""  # pinned persona id for this job; "" = picked automatically
    lane: str = ""            # free-text lane name as the sourcing engine wrote it
    found_at: str = ""
    # --- batch import (jobs_import_<stream>_<date>.csv) ------------------------
    lane_slug: str = ""       # resolved lane (data/lanes.index.json), "" when unresolved
    track: str = ""           # technical | creative (from File 3, else the lane)
    stream: str = ""          # streamA | streamB | streamC | streamD
    run_date: str = ""        # the batch run date (ISO), not the posting date
    batches: list[str] = Field(default_factory=list)   # every batch_id this role appeared in
    priority_tag: str = ""    # the CSV `priority` column (always HIGH upstream)
    noc: str = ""
    teer: int | None = None
    noc_teer_raw: str = ""
    pathway_type: str = ""    # RCIP | AIP | PNP
    pathway_detail: str = ""
    relocation: bool = False
    remote_type: str = ""     # REMOTE | US-REMOTE
    hire_type: str = ""       # entity | eor | contractor (Stream D)
    source_tag: str = ""      # SRC: value
    tag_violations: list[str] = Field(default_factory=list)
    description_raw: str = "" # the pipe-joined form as imported (kept for search)
    # File 3 (fit_report) joined on company + title.
    fit: dict = Field(default_factory=dict)        # verified_on, posting_live, years_line, fit_evidence, gap_flags, track
    # Matrix grading (grading/grader.py): tier, gap_flags, fit_sentence, evidence_skill_ids, ...
    grade: dict = Field(default_factory=dict)
    seniority: dict = Field(default_factory=dict)  # seniority guard result (warning, never a filter)
    # Application ledger fields Keerthi sets by hand (Phase 6).
    date_sent: str = ""
    ledger_status: str = ""   # pending | sent | no_response | screening | interview | offer | rejected | withdrawn
    last_touch: str = ""
    notes: str = Field(default="")
    # Email-apply tracking (set when the application is actually emailed via n8n).
    sent_at: str = ""              # ISO datetime the application email was sent
    sent_to: str = ""             # recipient address it went to
    followups: list[str] = Field(default_factory=list)  # ISO datetimes of follow-ups sent
    hr_emailed_at: str = ""        # ISO datetime an "I applied" note was emailed to HR
    # Log of everything emailed via n8n, so it can be reviewed later.
    # Each entry: {at, kind: application|followup|hr, to, subject, body}.
    sent_log: list[dict] = Field(default_factory=list)

    @property
    def has_email(self) -> bool:
        return bool((self.contact_email or "").strip())
