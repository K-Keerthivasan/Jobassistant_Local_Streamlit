"""What a queued job will be generated with, decided before generation so the
Jobs list, the collector and the generator always agree: the resume version
(persona), why it was picked, and whether the job's description is complete
enough to tailor a resume from."""
from __future__ import annotations

import threading
import time

from . import lanes as lane_data
from .personas import explain_persona

# Where the pick came from, in words the Jobs list shows.
SOURCES = {
    "pinned": "pinned by you",
    "title": "matched from the job title",
    "lane": "the job's lane",
    "keywords": "matched from the description",
    "hermes": "chosen by Hermes",
    "none": "no version matched",
}


def job_lane(job):
    """The lane generation will use, resolved exactly as the pipeline does."""
    slug = (getattr(job, "lane_slug", "") or "").strip()
    text = (getattr(job, "lane", "") or "").strip()
    lane = lane_data.get_lane(slug) if slug else None
    if lane is None and (slug or text):
        lane = lane_data.resolve_lane(slug or text)
    return lane or lane_data.resolve_lane(job.title)


def resume_version(job) -> dict:
    """The resume version this job gets. Never asks Hermes, so it is cheap
    enough for every row of the Jobs list and is exactly what generation uses."""
    persona, source = explain_persona(job.to_target_role(), getattr(job, "resume_version", "") or None,
                                      lane=job_lane(job), use_hermes=False)
    return {
        "persona": (persona or {}).get("id", ""),
        "label": (persona or {}).get("label", ""),
        "source": source,
        "why": SOURCES.get(source, source),
        "pinned": source == "pinned",
    }


# The old collector cut every posting at 800 characters; those land a few
# characters either side of it once whitespace and markup are cleaned.
_CUT_LOW, _CUT_HIGH = 790, 840
SHORT = 400


def description_status(job) -> dict:
    """Whether the stored description is the whole posting."""
    text = (job.description or "").strip()
    n = len(text)
    reason = ""
    if not text or text.upper() == "N/A":
        reason = "No description was saved."
    elif text.startswith("[UNVERIFIED SUMMARY]"):
        reason = "Only a short summary: the posting could not be read."
    elif getattr(job, "source", "") == "collector" and _CUT_LOW <= n <= _CUT_HIGH:
        reason = "Cut off at 800 characters by the old collector."
    elif n < SHORT:
        reason = f"Only {n} characters, probably a summary."
    return {
        "chars": n,
        "complete": not reason,
        "reason": reason,
        "fix": "" if not reason else "Open the posting and save it again with the collector to fetch the full text.",
    }


# --- generations in progress (for the collector and the Studio banner) --------

_LOCK = threading.Lock()
_RUNNING: dict[str, dict] = {}
_RECENT: list[dict] = []


def started(company: str, title: str) -> str:
    gid = f"{time.time():.6f}"
    with _LOCK:
        _RUNNING[gid] = {"id": gid, "company": company, "title": title, "resume_version": "",
                         "started_at": time.time()}
    return gid


def chose(gid: str, persona: dict | None) -> None:
    with _LOCK:
        if gid in _RUNNING:
            _RUNNING[gid]["resume_version"] = (persona or {}).get("label", "")


def finished(gid: str, *, ok: bool, run_id: str = "", error: str = "") -> None:
    with _LOCK:
        item = _RUNNING.pop(gid, None)
        if item is None:
            return
        item.update(finished_at=time.time(), ok=ok, run_id=run_id, error=error[:300])
        _RECENT.insert(0, item)
        del _RECENT[20:]


def activity() -> dict:
    with _LOCK:
        return {"running": list(_RUNNING.values()), "recent": list(_RECENT), "now": time.time()}
