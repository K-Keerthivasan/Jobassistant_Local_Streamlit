"""Parser for the ``noc_teer`` column the sourcing engine emits (brief section 3.1).

    22222 / TEER 2 | AIP: Nova Scotia | RELO+ | REMOTE | SRC: linkedin

Tags appear in this order when present:

    RCIP: <community>          Brandon, North Bay, Sault Ste. Marie, Steinbach, Altona
    AIP: <province> | AIP: unconfirmed
    PNP: <province>
    RELO+                      relocation support signalled
    REMOTE                     Canadian employer remote
    US-REMOTE                  Stream D only, always with a HIRE-CA value
    HIRE-CA: entity | eor | contractor
    SRC: <source>              always last

``parse_noc_teer`` returns first-class fields plus the raw string. ``validate_tags``
applies the stream rules: US-REMOTE and HIRE-CA travel together and only on
Stream D; REMOTE, RCIP, AIP and PNP never on Stream D. Violations are reported,
never silently accepted or silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

SOURCES = ("linkedin", "indeed", "careerbeacon", "jobbank", "careers", "remoteboard")
HIRE_TYPES = ("entity", "eor", "contractor")
RCIP_COMMUNITIES = ("Brandon", "North Bay", "Sault Ste. Marie", "Steinbach", "Altona")
STREAMS = ("streamA", "streamB", "streamC", "streamD")

_NOC_RE = re.compile(r"^\s*(\d{5})\s*(?:/\s*TEER\s*(\d))?\s*$", re.I)


@dataclass
class NocTags:
    noc: str = ""
    teer: int | None = None
    pathway_type: str = ""      # RCIP | AIP | PNP | ""
    pathway_detail: str = ""    # community / province / "unconfirmed"
    relocation: bool = False
    remote_type: str = ""       # "" | REMOTE | US-REMOTE
    hire_type: str = ""         # "" | entity | eor | contractor
    source: str = ""
    raw: str = ""
    flags: list[str] = field(default_factory=list)   # every tag key seen, in order
    unknown_tags: list[str] = field(default_factory=list)

    @property
    def pathway_tag(self) -> str:
        return f"{self.pathway_type}: {self.pathway_detail}" if self.pathway_type else ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pathway_tag"] = self.pathway_tag
        return d


def parse_noc_teer(raw: str) -> NocTags:
    """Parse the column. Never raises; anything unrecognised lands in unknown_tags."""
    t = NocTags(raw=(raw or "").strip())
    if not t.raw:
        return t
    parts = [p.strip() for p in t.raw.split("|")]
    head, tags = parts[0], parts[1:]
    m = _NOC_RE.match(head)
    if m:
        t.noc = m.group(1)
        t.teer = int(m.group(2)) if m.group(2) else None
    else:
        # A row without a NOC head: treat the whole thing as tags.
        tags = parts
    for tag in tags:
        if not tag:
            continue
        key, _, val = tag.partition(":")
        key_u, val = key.strip().upper(), val.strip()
        t.flags.append(key_u)
        if key_u == "RCIP":
            t.pathway_type, t.pathway_detail = "RCIP", val
        elif key_u == "AIP":
            t.pathway_type, t.pathway_detail = "AIP", val or "unconfirmed"
        elif key_u == "PNP":
            t.pathway_type, t.pathway_detail = "PNP", val
        elif key_u in ("RELO+", "RELO"):
            t.relocation = True
        elif key_u == "RELO-":
            t.relocation = False
        elif key_u == "REMOTE":
            t.remote_type = "REMOTE"
        elif key_u == "US-REMOTE":
            t.remote_type = "US-REMOTE"
        elif key_u == "HIRE-CA":
            t.hire_type = val.lower()
        elif key_u == "SRC":
            t.source = val.lower()
        else:
            t.unknown_tags.append(tag)
    return t


def validate_tags(tags: NocTags, stream: str) -> list[str]:
    """Stream rules from the brief. Returns human-readable violations (empty = ok)."""
    v: list[str] = []
    is_d = (stream or "").lower() == "streamd"
    if tags.remote_type == "US-REMOTE" and not tags.hire_type:
        v.append("US-REMOTE without a HIRE-CA value")
    if tags.hire_type and tags.remote_type != "US-REMOTE":
        v.append("HIRE-CA without US-REMOTE")
    if tags.hire_type and tags.hire_type not in HIRE_TYPES:
        v.append(f"HIRE-CA value {tags.hire_type!r} not one of {HIRE_TYPES}")
    if "REMOTE" in tags.flags and "US-REMOTE" in tags.flags:
        v.append("REMOTE and US-REMOTE on the same row")
    if is_d:
        if "REMOTE" in tags.flags:
            v.append("REMOTE on a Stream D row")
        if tags.remote_type != "US-REMOTE":
            v.append("Stream D row without US-REMOTE")
        if not tags.hire_type:
            v.append("Stream D row without HIRE-CA")
        if tags.pathway_type:
            v.append(f"{tags.pathway_type} tag on a Stream D row")
        if tags.relocation:
            v.append("RELO+ on a Stream D row")
    else:
        if tags.remote_type == "US-REMOTE":
            v.append(f"US-REMOTE on a {stream or 'non-D'} row")
        if tags.hire_type:
            v.append(f"HIRE-CA on a {stream or 'non-D'} row")
    if tags.pathway_type == "RCIP" and tags.pathway_detail not in RCIP_COMMUNITIES:
        v.append(f"RCIP community {tags.pathway_detail!r} is not a designated community")
    if tags.source and tags.source not in SOURCES:
        v.append(f"SRC {tags.source!r} not one of {SOURCES}")
    if not tags.source:
        v.append("missing SRC tag")
    if tags.raw and not tags.noc:
        v.append("no NOC code at the head of the column")
    for u in tags.unknown_tags:
        v.append(f"unknown tag {u!r}")
    # Order check: SRC must be last.
    parts = [p.strip() for p in tags.raw.split("|")]
    src_idx = next((i for i, p in enumerate(parts) if p.upper().startswith("SRC:")), None)
    if src_idx is not None and src_idx != len(parts) - 1:
        v.append("SRC tag is not last")
    return v
