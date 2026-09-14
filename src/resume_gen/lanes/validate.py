"""Standalone validator for everything under ``data/``: ``npm run validate:data``
(or ``python -m resume_gen.lanes validate``).

Checks (errors fail the run, warnings are printed):

* index: unique lane numbers and slugs, files present, NOC codes exist in
  noc.json, link keys exist in portfolio_links, persona set;
* each lane: schema-valid, enum values, every ``held``/``partial`` skill has
  evidence, every ``partial`` has a limit, unique skill ids, NOC codes known,
  lane number and slug agree with the index, version agrees across lanes
  (warning) and with the index (error);
* noc.json: five-digit codes, TEER 0 to 5;
* profile.json: required fields, ``us_work_authorization`` is false;
* answer-bank.json: unique ids, no empty answers, the US authorisation answer is "No";
* outreach-templates.json: unique ids, subject template within 60 characters,
  body under 150 words, never-mention words absent except in the pathway template.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ..config import ROOT
from .schema import Lane, LanesIndex

DATA_DIR = ROOT / "data"


@dataclass
class Problem:
    level: str      # error | warning
    file: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.file}: {self.message}"


def _load_json(path: Path, problems: list[Problem]) -> dict | None:
    if not path.exists():
        problems.append(Problem("error", str(path.relative_to(ROOT)), "file missing"))
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        problems.append(Problem("error", str(path.relative_to(ROOT)), f"invalid JSON: {e}"))
        return None


# --------------------------------------------------------------------------- #
def validate_lane_set(lanes: dict[str, Lane], index: LanesIndex,
                      noc_codes: dict | None = None) -> list[Problem]:
    """Semantic checks over already-parsed lanes (used by sync before writing)."""
    problems: list[Problem] = []
    if noc_codes is None:
        p = DATA_DIR / "noc.json"
        noc_codes = (json.loads(p.read_text(encoding="utf-8")).get("codes", {}) if p.exists() else {})

    nums, slugs = set(), set()
    for e in index.lanes:
        if e.lane in nums:
            problems.append(Problem("error", "lanes.index.json", f"duplicate lane number {e.lane}"))
        if e.slug in slugs:
            problems.append(Problem("error", "lanes.index.json", f"duplicate slug {e.slug}"))
        nums.add(e.lane); slugs.add(e.slug)
        for code in e.noc:
            if code not in noc_codes:
                problems.append(Problem("error", "lanes.index.json", f"lane {e.lane}: NOC {code} not in noc.json"))
        for key in e.links:
            if key not in index.portfolio_links:
                problems.append(Problem("error", "lanes.index.json", f"lane {e.lane}: link key {key!r} not in portfolio_links"))
        if not e.persona:
            problems.append(Problem("error", "lanes.index.json", f"lane {e.lane}: persona (base resume mapping) missing"))

    versions = set()
    for slug, lane in lanes.items():
        f = lane.source_file or slug
        entry = index.entry(slug)
        if entry is None:
            problems.append(Problem("error", f, "lane not listed in lanes.index.json"))
            continue
        if entry.lane != lane.lane:
            problems.append(Problem("error", f, f"lane number {lane.lane} disagrees with index {entry.lane}"))
        versions.add(lane.version)
        if lane.version != index.version:
            problems.append(Problem("error", f, f"version {lane.version} != index version {index.version}"))
        if not lane.noc:
            problems.append(Problem("error", f, "no NOC codes"))
        for n in lane.noc:
            if n.code not in noc_codes:
                problems.append(Problem("error", f, f"NOC {n.code} not in noc.json"))
        ids = set()
        for s in lane.skills:
            if s.id in ids:
                problems.append(Problem("error", f, f"duplicate skill id {s.id}"))
            ids.add(s.id)
            if s.status in ("held", "partial") and not s.evidence.strip():
                problems.append(Problem("error", f, f"skill '{s.name}' is {s.status} but has no evidence"))
            if s.status == "partial" and not s.limit.strip():
                problems.append(Problem("error", f, f"skill '{s.name}' is partial but has no limit sentence"))
            if s.status in ("building", "not_yet") and s.evidence.strip():
                problems.append(Problem("warning", f, f"skill '{s.name}' is {s.status} but carries evidence text (ignored, never used)"))
            if any(not a.strip() for a in s.aliases):
                problems.append(Problem("error", f, f"skill '{s.name}' has an empty alias"))
        if not lane.by_tier("must"):
            problems.append(Problem("warning", f, "no Must-tier skills; every posting will grade Tier A"))
        if not lane.keywords.core:
            problems.append(Problem("warning", f, "no core sourcing keywords"))
    if len(versions) > 1:
        problems.append(Problem("warning", "lanes", f"lane files disagree on version: {sorted(versions)}"))
    return problems


# --------------------------------------------------------------------------- #
def validate_data_dir(data_dir: Path | None = None) -> list[Problem]:
    """Validate everything under data/ from the files on disk."""
    global DATA_DIR
    if data_dir is not None:
        DATA_DIR = data_dir
    problems: list[Problem] = []

    raw_index = _load_json(DATA_DIR / "lanes.index.json", problems)
    if raw_index is None:
        return problems
    try:
        index = LanesIndex.model_validate(raw_index)
    except ValidationError as e:
        problems.append(Problem("error", "lanes.index.json", str(e)))
        return problems

    noc_raw = _load_json(DATA_DIR / "noc.json", problems) or {}
    noc_codes = noc_raw.get("codes", {})
    for code, info in noc_codes.items():
        if not re.fullmatch(r"\d{5}", code):
            problems.append(Problem("error", "noc.json", f"code {code!r} is not five digits"))
        teer = info.get("teer")
        if not isinstance(teer, int) or not 0 <= teer <= 5:
            problems.append(Problem("error", "noc.json", f"code {code}: teer must be 0 to 5"))
        if not info.get("title"):
            problems.append(Problem("error", "noc.json", f"code {code}: title missing"))

    lanes: dict[str, Lane] = {}
    for entry in index.lanes:
        path = DATA_DIR / entry.file
        raw = _load_json(path, problems)
        if raw is None:
            continue
        try:
            lanes[entry.slug] = Lane.model_validate(raw)
        except ValidationError as e:
            problems.append(Problem("error", entry.file, str(e)))
    problems += validate_lane_set(lanes, index, noc_codes)

    # profile.json
    prof = _load_json(DATA_DIR / "profile.json", problems)
    if prof is not None:
        for key in ("name", "known_as", "location", "work_authorization", "credentials", "portfolio"):
            if key not in prof:
                problems.append(Problem("error", "profile.json", f"missing {key}"))
        if prof.get("us_work_authorization") is not False:
            problems.append(Problem("error", "profile.json", "us_work_authorization must be false (non-negotiable 5)"))
        for c in prof.get("credentials", []):
            if not all(k in c for k in ("name", "institution", "from", "to")):
                problems.append(Problem("error", "profile.json", f"credential incomplete: {c}"))

    # answer-bank.json
    bank = _load_json(DATA_DIR / "answer-bank.json", problems)
    if bank is not None:
        ids = set()
        for a in bank.get("answers", []):
            if a.get("id") in ids:
                problems.append(Problem("error", "answer-bank.json", f"duplicate id {a.get('id')}"))
            ids.add(a.get("id"))
            if not (a.get("question") or "").strip() or not (a.get("answer") or "").strip():
                problems.append(Problem("error", "answer-bank.json", f"empty question or answer in {a.get('id')}"))
            if len((a.get("answer") or "").split()) > 80:
                problems.append(Problem("warning", "answer-bank.json", f"{a.get('id')}: answer is paragraph-length"))
            q = (a.get("question") or "").lower()
            if "united states" in q and "authoriz" in q and a.get("answer", "").strip().lower() != "no":
                problems.append(Problem("error", "answer-bank.json", f"{a.get('id')}: US work authorisation must be 'No'"))
            if "sponsor" in q and a.get("answer", "").strip().lower() != "no":
                problems.append(Problem("error", "answer-bank.json", f"{a.get('id')}: sponsorship answer must be 'No'"))

    # outreach-templates.json
    tpl = _load_json(DATA_DIR / "outreach-templates.json", problems)
    if tpl is not None:
        rules = tpl.get("rules", {})
        never = [w.lower() for w in rules.get("never_mention", [])]
        allowed = set(rules.get("immigration_pathway_allowed_in", []))
        ids = set()
        for t in tpl.get("templates", []):
            tid = t.get("id", "")
            if tid in ids:
                problems.append(Problem("error", "outreach-templates.json", f"duplicate template id {tid}"))
            ids.add(tid)
            subj = re.sub(r"\{\{.*?\}\}", "X", t.get("subject", ""))
            if len(subj) > rules.get("subject_max_chars", 60):
                problems.append(Problem("error", "outreach-templates.json", f"{tid}: subject template longer than 60 characters"))
            body = t.get("body", "")
            if len(re.sub(r"\{\{.*?\}\}", "", body).split()) > rules.get("body_max_words", 150):
                problems.append(Problem("error", "outreach-templates.json", f"{tid}: body over 150 words before variables"))
            low = body.lower()
            for w in never:
                if w in low and tid not in allowed:
                    problems.append(Problem("error", "outreach-templates.json", f"{tid}: mentions '{w}'"))
            if re.search(r"[–—]", body + t.get("subject", "")):
                problems.append(Problem("error", "outreach-templates.json", f"{tid}: contains an em or en dash"))
        for t in tpl.get("templates", []):
            for step in t.get("sequence", []):
                if step.get("template_id") not in ids:
                    problems.append(Problem("error", "outreach-templates.json", f"{t.get('id')}: sequence step names unknown template {step.get('template_id')}"))
    return problems


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    data_dir = Path(args[0]) if args else None
    problems = validate_data_dir(data_dir)
    errors = [p for p in problems if p.level == "error"]
    for p in problems:
        print(p)
    n_lanes = len(list((data_dir or DATA_DIR).glob("lanes/lane-*.json")))
    if errors:
        print(f"\nvalidate:data FAILED with {len(errors)} error(s) across {n_lanes} lane file(s).")
        return 1
    print(f"\nvalidate:data OK: {n_lanes} lane file(s), {len(problems)} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
