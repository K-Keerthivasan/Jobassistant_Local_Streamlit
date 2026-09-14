"""Typed shape of the lane data files (``data/lanes/*.json``) and the index.

The JSON is what the app reads; the markdown under ``data/lanes/source/`` is what
Keerthi edits. ``sync.py`` converts one to the other, ``validate.py`` gates it.

The four status values and the rule that governs them (brief section 2.4):

    held      can do it today, evidence names where          -> usable as evidence
    partial   real but incomplete exposure                   -> usable only with `limit`
    building  actively learning, not demonstrable            -> never evidence, always a gap
    not_yet   no exposure                                    -> never evidence, always a gap

Nothing in the app may upgrade a status. ``Skill.claimable`` is the single place
that answers "may this skill appear as experience", and every generation path
asks it.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Status = Literal["held", "partial", "building", "not_yet"]
Tier = Literal["must", "important", "optional", "later", "not_required"]
Track = Literal["technical", "creative"]
LaneSet = Literal["priority", "secondary", "opportunistic"]

STATUSES: tuple[str, ...] = ("held", "partial", "building", "not_yet")
TIERS: tuple[str, ...] = ("must", "important", "optional", "later", "not_required")
CLAIMABLE: frozenset[str] = frozenset({"held", "partial"})


def slugify(text: str) -> str:
    """Stable id for a skill or lane name. Keeps C++ / C# / .NET distinct."""
    t = (text or "").strip().lower()
    t = t.replace("c++", "cpp").replace("c#", "csharp").replace(".net", "dotnet")
    t = t.replace("&", " and ").replace("/", " ").replace("+", " plus ")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "x"


def normalize_status(raw: str) -> str:
    s = re.sub(r"[*`_]", "", raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return {"notyet": "not_yet", "not_yet": "not_yet", "held": "held",
            "partial": "partial", "building": "building"}.get(s, s)


class NocRef(BaseModel):
    code: str
    title: str = ""
    teer: int | None = None
    applies_when: str = ""

    @field_validator("code")
    @classmethod
    def _five_digits(cls, v: str) -> str:
        v = (v or "").strip()
        if not re.fullmatch(r"\d{5}", v):
            raise ValueError(f"NOC code must be five digits, got {v!r}")
        return v


class Keywords(BaseModel):
    core: list[str] = Field(default_factory=list)
    tool_anchored: list[str] = Field(default_factory=list)
    adjacent: list[str] = Field(default_factory=list)

    def all(self) -> list[str]:
        return [*self.core, *self.tool_anchored, *self.adjacent]


class Skill(BaseModel):
    id: str
    name: str
    tier: Tier
    asked_for: str = ""
    status: Status
    evidence: str = ""
    limit: str = ""
    aliases: list[str] = Field(default_factory=list)
    updated: str = ""
    # Free text about a gap (what would close it). Never evidence.
    note: str = ""
    # True when the evidence text came from an Optional/Later table's Note column
    # rather than a real Evidence column. Such evidence never feeds a fit sentence.
    evidence_from_note: bool = False

    @property
    def claimable(self) -> bool:
        """May this skill be presented as experience at all?"""
        return self.status in CLAIMABLE

    @property
    def is_gap_when_required(self) -> bool:
        """A hard requirement for this skill is a gap flag unless it is fully held."""
        return self.status != "held"

    @property
    def fit_sentence_source(self) -> bool:
        """May the evidence text be used to build a fit sentence?"""
        return self.claimable and bool(self.evidence.strip()) and not self.evidence_from_note

    def match_terms(self) -> list[str]:
        """Every phrase that should match this skill in a posting, longest first."""
        terms = {self.name.strip().lower()}
        terms.update(a.strip().lower() for a in self.aliases if a.strip())
        return sorted((t for t in terms if t), key=len, reverse=True)


class LaneNote(BaseModel):
    heading: str
    text: str


class Lane(BaseModel):
    lane: int
    slug: str
    title: str
    track: Track
    set: LaneSet
    noc: list[NocRef] = Field(default_factory=list)
    keywords: Keywords = Field(default_factory=Keywords)
    skills: list[Skill] = Field(default_factory=list)
    positioning: str = ""
    interview_watch: str = ""
    pr_note: str = ""
    not_required: str = ""
    notes: list[LaneNote] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    persona: str = ""
    version: str
    source_updated: str = ""
    source_file: str = ""
    source_sha256: str = ""

    # --- accessors ---------------------------------------------------------
    def skill(self, skill_id: str) -> Skill | None:
        for s in self.skills:
            if s.id == skill_id:
                return s
        return None

    def by_tier(self, tier: str) -> list[Skill]:
        return [s for s in self.skills if s.tier == tier]

    def claimable_skills(self) -> list[Skill]:
        return [s for s in self.skills if s.claimable]

    def unclaimable_skills(self) -> list[Skill]:
        return [s for s in self.skills if not s.claimable]

    def home_noc(self) -> str:
        return self.noc[0].code if self.noc else ""

    def noc_codes(self) -> list[str]:
        return [n.code for n in self.noc]


class LaneIndexEntry(BaseModel):
    lane: int
    slug: str
    file: str
    source: str
    title: str
    track: Track
    set: LaneSet
    noc: list[str] = Field(default_factory=list)
    persona: str = ""
    links: list[str] = Field(default_factory=list)
    match: list[str] = Field(default_factory=list)


class PortfolioLink(BaseModel):
    label: str
    url: str


class LanesIndex(BaseModel):
    version: str
    source_updated: str = ""
    portfolio_links: dict[str, PortfolioLink] = Field(default_factory=dict)
    lanes: list[LaneIndexEntry] = Field(default_factory=list)

    def entry(self, key: str | int) -> LaneIndexEntry | None:
        for e in self.lanes:
            if e.lane == key or e.slug == key:
                return e
        return None
