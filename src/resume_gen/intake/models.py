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
    found_at: str = ""
    notes: str = Field(default="")
