"""Orchestrate one intake run: read source config -> fetch every source ->
filter by title keywords / email requirement -> dedup -> queue the new jobs."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..config import ROOT
from .models import JobPosting
from .sources import fetch_source
from .store import commit, filter_new

_CONFIG = ROOT / "data" / "sources.yaml"
_SAMPLE = ROOT / "data" / "sources.sample.yaml"


def load_sources(path: Path | None = None) -> dict:
    """Load data/sources.yaml, falling back to the shipped sample."""
    p = path or (_CONFIG if _CONFIG.exists() else _SAMPLE)
    if not p.exists():
        return {"sources": [], "filters": {}}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _keep(job: JobPosting, keywords: list[str], require_email: bool) -> bool:
    if keywords and not any(k in job.title.lower() for k in keywords):
        return False
    if require_email and not job.contact_email:
        return False
    return True


def run_intake(*, commit_new: bool = True, config_path: Path | None = None) -> dict:
    cfg = load_sources(config_path)
    filters = cfg.get("filters") or {}
    keywords = [k.lower() for k in (filters.get("title_keywords") or [])]
    require_email = bool(filters.get("require_email"))

    fetched: list[JobPosting] = []
    errors: list[dict] = []
    for src in cfg.get("sources", []):
        label = f"{src.get('type')}:{src.get('company') or src.get('url')}"
        try:
            fetched.extend(fetch_source(src))
        except Exception as e:  # one bad source must not kill the run
            errors.append({"source": label, "error": str(e)})

    matched = [j for j in fetched if _keep(j, keywords, require_email)]
    new = filter_new(matched)
    queued = commit(new) if commit_new else []

    return {
        "fetched": len(fetched),
        "matched": len(matched),
        "new": len(new),
        "committed": len(queued),
        "new_jobs": [
            {"key_id": j.key, "company": j.company, "title": j.title,
             "location": j.location, "email": j.contact_email, "apply_url": j.apply_url,
             "source": j.source}
            for j in new
        ],
        "errors": errors,
    }
