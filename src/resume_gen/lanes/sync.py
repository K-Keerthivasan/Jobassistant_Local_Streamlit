"""Markdown -> JSON converter for the lane matrices, plus the drift check.

``sync_all()`` parses every ``data/lanes/source/lane-NN-*.md`` named in the index
into the ``Lane`` shape and writes ``data/lanes/lane-NN-*.json``. It is:

* **idempotent** - the same markdown always produces byte-identical JSON;
* **all-or-nothing** - every file is parsed and validated first; if any one of
  them fails, nothing is written.

The markdown layout it understands is the one the matrices already use:

    # Lane N | Title
    <intro paragraphs>                        -> notes["Intro"], "Status updated" date
    **PR note.** ...                          -> pr_note
    ## NOC map           (4-col table)        -> noc
    ## Must / ## Important (4-col table: Skill | asked for | Status | Evidence)
    ## Optional / ## Later (3-col table: Skill | Note | Status)
    ## Not required      (prose)              -> not_required
    ## Sourcing vocabulary (bullets)          -> keywords
    ## Honest positioning (prose)             -> positioning
    ## Interview watch   (prose)              -> interview_watch
    ## Aliases           (- Name: a, b, c)    -> Skill.aliases
    ## anything else     (prose)              -> notes
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..config import ROOT
from .schema import Lane, LanesIndex, NocRef, Skill, normalize_status, slugify

DATA_DIR = ROOT / "data"
INDEX_PATH = DATA_DIR / "lanes.index.json"

_TABLE_TIERS = {"must": "must", "important": "important",
                "optional": "optional", "later": "later"}
_NEGATION = re.compile(r"\b(not|never|no|without|rather than|lacks?|missing|unproven|gap)\b", re.I)


class LaneSyncError(RuntimeError):
    """The markdown did not parse cleanly. Nothing was written."""


# --------------------------------------------------------------------------- #
# markdown primitives
# --------------------------------------------------------------------------- #
def _strip_md(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s or "")
    s = re.sub(r"`(.+?)`", r"\1", s)
    return s.strip()


def _sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split on '## ' headings. Returns (preamble, [(heading, body), ...])."""
    parts = re.split(r"^## +", text, flags=re.M)
    preamble = parts[0]
    out = []
    for chunk in parts[1:]:
        heading, _, body = chunk.partition("\n")
        out.append((heading.strip(), body.strip()))
    return preamble, out


def _table_rows(body: str) -> list[list[str]]:
    """Cells of every data row in the first pipe table found in ``body``."""
    rows: list[list[str]] = []
    in_table = False
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            if in_table:
                break
            continue
        in_table = True
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue  # separator row
        rows.append(cells)
    return rows[1:] if rows else []  # drop the header row


def _prose(body: str) -> str:
    """Paragraph text with markdown emphasis removed and single newlines joined."""
    paras = [re.sub(r"\s+", " ", _strip_md(p)) for p in re.split(r"\n\s*\n", body) if p.strip()]
    return "\n\n".join(p for p in paras if p)


def _limit_from_evidence(evidence: str) -> str:
    """For a `partial` skill: the sentence(s) in the evidence that state what is
    NOT covered. Falls back to the whole evidence text so the limit is never empty."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", evidence or "") if s.strip()]
    neg = [s for s in sentences if _NEGATION.search(s)]
    return " ".join(neg) if neg else (evidence or "").strip()


# --------------------------------------------------------------------------- #
# one lane
# --------------------------------------------------------------------------- #
def parse_lane_markdown(text: str, entry, index: LanesIndex, *, source_file: str = "") -> Lane:
    m = re.search(r"^# +Lane +(\d+) *\| *(.+)$", text, flags=re.M)
    if not m:
        raise LaneSyncError(f"{source_file}: missing '# Lane N | Title' heading")
    lane_no = int(m.group(1))
    title = _strip_md(m.group(2))
    if lane_no != entry.lane:
        raise LaneSyncError(f"{source_file}: heading says lane {lane_no}, index says {entry.lane}")

    preamble, sections = _sections(text)

    # PR note + intro + "Status updated" date
    pr_note = ""
    intro_paras = []
    updated = index.source_updated
    for para in re.split(r"\n\s*\n", preamble):
        p = para.strip()
        if not p or p.startswith("# "):
            continue
        if p.startswith("**PR note.**"):
            pr_note = _prose(p[len("**PR note.**"):])
            continue
        mu = re.search(r"Status updated (\d{4}-\d{2}-\d{2})", p)
        if mu:
            updated = mu.group(1)
        intro_paras.append(_prose(p))

    noc: list[NocRef] = []
    skills: list[Skill] = []
    keywords = {"core": [], "tool_anchored": [], "adjacent": []}
    positioning = interview = not_required = ""
    aliases: dict[str, list[str]] = {}
    notes: list[dict] = []
    if intro_paras:
        notes.append({"heading": "Intro", "text": "\n\n".join(intro_paras)})
    seen_ids: set[str] = set()

    for heading, body in sections:
        h = heading.lower().strip()
        if h == "noc map":
            for cells in _table_rows(body):
                if len(cells) < 4:
                    raise LaneSyncError(f"{source_file}: NOC map row needs 4 cells: {cells}")
                code = re.sub(r"\D", "", cells[0])
                teer_m = re.search(r"\d", cells[2])
                noc.append(NocRef(code=code, title=_strip_md(cells[1]),
                                  teer=int(teer_m.group()) if teer_m else None,
                                  applies_when=_strip_md(cells[3])))
        elif h in _TABLE_TIERS:
            tier = _TABLE_TIERS[h]
            for cells in _table_rows(body):
                if tier in ("must", "important"):
                    if len(cells) < 4:
                        raise LaneSyncError(f"{source_file}: {heading} row needs 4 cells: {cells}")
                    name, asked, status, evidence = cells[:4]
                    from_note = False
                else:
                    if len(cells) < 3:
                        raise LaneSyncError(f"{source_file}: {heading} row needs 3 cells: {cells}")
                    name, asked, status = cells[:3]
                    evidence, from_note = "", False
                status_n = normalize_status(status)
                name_c = _strip_md(name)
                sid = slugify(name_c)
                if sid in seen_ids:
                    raise LaneSyncError(f"{source_file}: duplicate skill '{name_c}'")
                seen_ids.add(sid)
                evidence_c = _strip_md(evidence)
                note = ""
                if status_n in ("building", "not_yet") and evidence_c:
                    # Evidence is empty unless the skill is claimable; the text in the
                    # column for a gap is a note about the gap, kept as such.
                    note, evidence_c = evidence_c, ""
                if tier in ("optional", "later") and status_n in ("held", "partial") and not evidence_c:
                    # Optional/Later tables carry no Evidence column. The Note is the
                    # row's own justification; mark it so it never sources a fit sentence.
                    evidence_c, from_note = _strip_md(asked), True
                skills.append(Skill(
                    id=sid, name=name_c, tier=tier, asked_for=_strip_md(asked),
                    status=status_n, evidence=evidence_c,
                    limit=_limit_from_evidence(evidence_c) if status_n == "partial" else "",
                    aliases=[], updated=updated, evidence_from_note=from_note, note=note,
                ))
        elif h == "not required":
            not_required = _prose(body)
        elif h == "sourcing vocabulary":
            extra = []
            for line in body.splitlines():
                ln = line.strip()
                if not ln.startswith("-"):
                    continue
                ln = _strip_md(ln.lstrip("- ").strip())
                label, _, rest = ln.partition(":")
                label_l = label.strip().lower()
                items = [i.strip().rstrip(".") for i in rest.split(",") if i.strip()]
                if label_l.startswith("core"):
                    keywords["core"] += items
                elif label_l.startswith("tool"):
                    keywords["tool_anchored"] += items
                elif label_l.startswith("adjacent"):
                    keywords["adjacent"] += items
                else:
                    extra.append(_strip_md(ln))
            if extra:
                notes.append({"heading": "Sourcing notes", "text": "\n\n".join(extra)})
        elif h == "honest positioning":
            positioning = _prose(body)
        elif h == "interview watch":
            interview = _prose(body)
        elif h == "aliases":
            for line in body.splitlines():
                ln = line.strip()
                if not ln.startswith("-"):
                    continue
                name, _, rest = ln.lstrip("- ").partition(":")
                aliases[slugify(_strip_md(name))] = [
                    a.strip() for a in rest.split(",") if a.strip()]
        else:
            notes.append({"heading": _strip_md(heading), "text": _prose(body)})

    # Aliases must name a real skill row, otherwise the markdown is out of sync.
    unknown = sorted(set(aliases) - seen_ids)
    if unknown:
        raise LaneSyncError(f"{source_file}: Aliases name skills not in the tables: {unknown}")
    for s in skills:
        s.aliases = aliases.get(s.id, [])

    # No NOC map table -> take the codes from the index, titles from noc.json.
    if not noc:
        noc_table = load_noc_table()
        for code in entry.noc:
            info = noc_table.get(code, {})
            noc.append(NocRef(code=code, title=info.get("title", ""), teer=info.get("teer")))

    return Lane(
        lane=entry.lane, slug=entry.slug, title=title, track=entry.track, set=entry.set,
        noc=noc, keywords=keywords, skills=skills, positioning=positioning,
        interview_watch=interview, pr_note=pr_note, not_required=not_required,
        notes=notes, links=list(entry.links), persona=entry.persona,
        version=index.version, source_updated=updated, source_file=entry.source,
        source_sha256=sha256_text(text),
    )


# --------------------------------------------------------------------------- #
# whole set
# --------------------------------------------------------------------------- #
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def load_index(path: Path | None = None) -> LanesIndex:
    p = path or INDEX_PATH
    return LanesIndex.model_validate(json.loads(p.read_text(encoding="utf-8")))


def load_noc_table() -> dict:
    p = DATA_DIR / "noc.json"
    if not p.exists():
        return {}
    return (json.loads(p.read_text(encoding="utf-8")) or {}).get("codes", {})


def lane_json_text(lane: Lane) -> str:
    return json.dumps(lane.model_dump(), indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def parse_all(index: LanesIndex | None = None) -> dict[str, Lane]:
    """Parse every lane named in the index. Raises LaneSyncError on the first
    problem; returns {slug: Lane} when everything parses."""
    index = index or load_index()
    out: dict[str, Lane] = {}
    for entry in index.lanes:
        src = DATA_DIR / entry.source
        if not src.exists():
            raise LaneSyncError(f"{entry.source}: source markdown not found")
        out[entry.slug] = parse_lane_markdown(src.read_text(encoding="utf-8"), entry, index,
                                             source_file=entry.source)
    return out


def sync_all(*, check_only: bool = False, index: LanesIndex | None = None) -> dict:
    """Parse all, validate all, then write all. With ``check_only`` nothing is
    written; the report says which files would change."""
    from .validate import validate_lane_set

    index = index or load_index()
    lanes = parse_all(index)                       # raises before any write
    problems = validate_lane_set(lanes, index)
    errors = [p for p in problems if p.level == "error"]
    if errors:
        raise LaneSyncError("validation failed:\n" + "\n".join(f"  {p}" for p in errors))

    report = {"written": [], "unchanged": [], "would_change": [], "warnings": [str(p) for p in problems if p.level == "warning"]}
    for entry in index.lanes:
        lane = lanes[entry.slug]
        target = DATA_DIR / entry.file
        new_text = lane_json_text(lane)
        old_text = target.read_text(encoding="utf-8") if target.exists() else None
        if old_text == new_text:
            report["unchanged"].append(entry.file)
            continue
        if check_only:
            report["would_change"].append(entry.file)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_text, encoding="utf-8", newline="\n")
        report["written"].append(entry.file)
    return report


def drift_report(index: LanesIndex | None = None) -> list[dict]:
    """Compare each lane JSON's recorded source hash with the markdown on disk.
    A mismatch means one side was edited without re-running the sync."""
    index = index or load_index()
    out = []
    for entry in index.lanes:
        src = DATA_DIR / entry.source
        js = DATA_DIR / entry.file
        row = {"lane": entry.lane, "slug": entry.slug, "status": "ok", "detail": ""}
        if not js.exists():
            row.update(status="missing_json", detail=f"{entry.file} not generated yet; run sync:lanes")
        elif not src.exists():
            row.update(status="missing_source", detail=f"{entry.source} missing")
        else:
            try:
                recorded = json.loads(js.read_text(encoding="utf-8")).get("source_sha256", "")
            except ValueError:
                recorded = ""
            actual = sha256_text(src.read_text(encoding="utf-8"))
            if recorded != actual:
                row.update(status="drift", detail="markdown changed since the JSON was generated; run sync:lanes")
        out.append(row)
    return out
