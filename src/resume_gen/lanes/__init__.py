"""Lane knowledge loader: the typed, validated view of ``data/``.

Everything that grades a job, picks a base resume, filters a skills section or
renders an outreach email reads through here. The loader:

* enumerates lanes from ``data/lanes.index.json`` (never a hardcoded list, so a
  lane 13 is a new JSON file plus an index entry plus a persona mapping);
* validates every file on first load and raises ``LaneDataError`` on any
  problem. ``api/server.py`` calls ``assert_valid()`` at startup so a malformed
  lane file fails the boot loudly instead of degrading quietly;
* caches the parsed set for the process lifetime; ``reload()`` clears it.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ..config import ROOT
from .schema import (CLAIMABLE, STATUSES, TIERS, Lane, LanesIndex, PortfolioLink,  # noqa: F401
                     Skill, slugify)

DATA_DIR = ROOT / "data"


class LaneDataError(RuntimeError):
    """A data file under data/ is missing, malformed or fails validation."""


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def _read_json(name: str) -> dict:
    p = DATA_DIR / name
    if not p.exists():
        raise LaneDataError(f"{name} is missing under data/")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise LaneDataError(f"{name} is not valid JSON: {e}") from e


@lru_cache(maxsize=1)
def load_index() -> LanesIndex:
    try:
        return LanesIndex.model_validate(_read_json("lanes.index.json"))
    except Exception as e:  # pydantic ValidationError included
        raise LaneDataError(f"lanes.index.json: {e}") from e


@lru_cache(maxsize=1)
def load_lanes() -> dict[str, Lane]:
    """{slug: Lane} for every lane in the index. Validates the whole set."""
    from .validate import validate_lane_set

    index = load_index()
    lanes: dict[str, Lane] = {}
    for entry in index.lanes:
        try:
            lanes[entry.slug] = Lane.model_validate(_read_json(entry.file))
        except LaneDataError:
            raise
        except Exception as e:
            raise LaneDataError(f"{entry.file}: {e}") from e
    errors = [p for p in validate_lane_set(lanes, index, load_noc().get("codes", {}))
              if p.level == "error"]
    if errors:
        raise LaneDataError("lane data failed validation:\n" + "\n".join(f"  {p}" for p in errors))
    return lanes


@lru_cache(maxsize=1)
def load_noc() -> dict:
    return _read_json("noc.json")


@lru_cache(maxsize=1)
def load_profile_data() -> dict:
    return _read_json("profile.json")


@lru_cache(maxsize=1)
def load_answer_bank() -> dict:
    return _read_json("answer-bank.json")


@lru_cache(maxsize=1)
def load_outreach_templates() -> dict:
    return _read_json("outreach-templates.json")


def reload() -> None:
    """Drop every cache (after a sync, or in tests)."""
    for fn in (load_index, load_lanes, load_noc, load_profile_data,
               load_answer_bank, load_outreach_templates):
        fn.cache_clear()


def use_data_dir(path: Path | None) -> Path:
    """Point the loader, converter and validator at another data directory
    (tests use a temp copy). ``None`` restores the repo's data/. Returns the
    directory now in use."""
    global DATA_DIR
    from . import sync as _sync, validate as _validate

    target = Path(path) if path else ROOT / "data"
    DATA_DIR = target
    _sync.DATA_DIR = target
    _sync.INDEX_PATH = target / "lanes.index.json"
    _validate.DATA_DIR = target
    reload()
    return target


def assert_valid() -> dict:
    """Load and validate everything. Raises LaneDataError; returns a summary."""
    index = load_index()
    lanes = load_lanes()
    load_noc(); load_profile_data(); load_answer_bank(); load_outreach_templates()
    return {"version": index.version, "lanes": len(lanes),
            "skills": sum(len(l.skills) for l in lanes.values())}


# --------------------------------------------------------------------------- #
# accessors
# --------------------------------------------------------------------------- #
def all_lanes() -> list[Lane]:
    return sorted(load_lanes().values(), key=lambda l: l.lane)


def get_lane(key: str | int | None) -> Lane | None:
    """Exact lookup by number or slug."""
    if key is None or key == "":
        return None
    lanes = load_lanes()
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        n = int(key)
        return next((l for l in lanes.values() if l.lane == n), None)
    return lanes.get(str(key).strip().lower())


_WORD = re.compile(r"[a-z0-9]+")


def resolve_lane(text: str | None) -> Lane | None:
    """Tolerant lookup for the free-text `lane` column the sourcing engine emits
    ("QA", "IT support", "Data analytics", "AI/automation", "lane 5", "vfx").
    Uses each index entry's `match` words; slug and title always count."""
    if not text:
        return None
    raw = str(text).strip().lower()
    exact = get_lane(raw)
    if exact:
        return exact
    m = re.fullmatch(r"lane\s*(\d+)", raw)
    if m:
        return get_lane(int(m.group(1)))
    words = set(_WORD.findall(raw))
    if not words:
        return None
    best, best_score = None, 0
    for entry in load_index().lanes:
        cand = set(_WORD.findall(entry.slug.replace("-", " "))) | set(_WORD.findall(entry.title.lower()))
        cand |= {w.lower() for w in entry.match}
        # phrase match on the whole string beats word overlap
        phrases = [entry.slug.replace("-", " "), entry.title.lower(), *[m.lower() for m in entry.match]]
        score = 0
        if any(p and p == raw for p in phrases):
            score = 100
        elif any(p and len(p) > 3 and p in raw for p in phrases):
            score = 50
        score += len(words & cand)
        if score > best_score:
            best, best_score = entry, score
    return get_lane(best.slug) if best and best_score > 0 else None


def lane_for_persona(persona_id: str) -> Lane | None:
    return next((l for l in load_lanes().values() if l.persona == persona_id), None)


def portfolio_links_for(lane: Lane | None) -> list[PortfolioLink]:
    """The resume/cover-letter link set for a lane (LinkedIn always first)."""
    index = load_index()
    keys = list(lane.links) if lane else ["linkedin", "dev", "agency"]
    if "linkedin" in index.portfolio_links and "linkedin" not in keys:
        keys.insert(0, "linkedin")
    return [index.portfolio_links[k] for k in keys if k in index.portfolio_links]


def noc_info(code: str) -> dict:
    return (load_noc().get("codes") or {}).get(str(code).strip(), {})


def find_skill(lane: Lane, text: str) -> Skill | None:
    """The lane skill whose name or alias equals ``text`` (case-insensitive)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    sid = slugify(t)
    s = lane.skill(sid)
    if s:
        return s
    for s in lane.skills:
        if t == s.name.lower() or t in (a.lower() for a in s.aliases):
            return s
    return None


def status_report() -> dict:
    """What the UI shows: version, lane count, per-lane drift, version disagreements."""
    from .sync import drift_report

    index = load_index()
    try:
        lanes = load_lanes()
        err = ""
    except LaneDataError as e:
        lanes, err = {}, str(e)
    versions = sorted({l.version for l in lanes.values()})
    return {
        "instruction_set_version": index.version,
        "source_updated": index.source_updated,
        "lanes": len(lanes),
        "lane_versions": versions,
        "version_mismatch": bool(versions) and versions != [index.version],
        "error": err,
        "drift": drift_report(index),
    }
