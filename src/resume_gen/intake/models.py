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
    lane: str = ""            # job category / stream (Full Stack, IT Support, Digital Marketing…)
    found_at: str = ""
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
