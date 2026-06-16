"""FastAPI service exposing the generation pipeline over HTTP, plus a small
single-page UI. n8n workflows and other devices (reachable via Tailscale) can
drive the JSON API; humans can use the web UI at the root URL.

Run:  uvicorn api.server:app --host 0.0.0.0 --port 8088
UI:   http://<host>:8088/
Docs: http://<host>:8088/docs
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Make the src/ package importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from resume_gen.config import settings  # noqa: E402
from resume_gen.llm import ollama_client  # noqa: E402
from resume_gen.models import TargetRole  # noqa: E402
from resume_gen.pipeline import run  # noqa: E402

app = FastAPI(title="Automatic Resume Generator", version="0.1.0")

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@app.on_event("startup")
def _init_db() -> None:
    """Initialize the SQLite store and run the one-time JSON->DB migration
    (idempotent: only backfills tables that are still empty)."""
    from resume_gen.intake import db

    db._ensure_init()


def _artifact(d: Path, generic: str, pattern: str) -> Path | None:
    old = d / generic
    if old.exists():
        return old
    matches = sorted(d.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


@app.middleware("http")
async def _no_store(request, call_next):
    """Never let the browser cache the UI or JSON — otherwise rebuilds show a stale
    page and generated results don't appear until a hard refresh."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def index():
    page = WEB_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="UI not found.")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/tampermonkey.user.js")
def tampermonkey_userscript():
    """Serve the browser job-saver userscript so Tampermonkey can install it and
    auto-update (the script's @downloadURL/@updateURL point here)."""
    script = Path(__file__).resolve().parents[1] / "tampermonkey" / "tampermonkey.user.js"
    if not script.exists():
        raise HTTPException(status_code=404, detail="Userscript not found.")
    # text/javascript so Tampermonkey recognizes it as an installable userscript.
    return FileResponse(str(script), media_type="text/javascript",
                        filename="tampermonkey.user.js")


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {
        "ollama": ollama_client.health(),
        "model": settings.ollama_model,
        "output_dir": str(settings.output_dir),
    }


@app.get("/models")
def models():
    """Local Ollama models + the Hermes agent engine (if HERMES_API_KEY is set)."""
    from resume_gen.llm import hermes_client

    cloud = [{"id": m, "label": lbl} for m, lbl in hermes_client.HERMES_MODELS()] \
        if hermes_client.available() else []
    return {
        "models": ollama_client.list_models(),
        "cloud": cloud,
        "default": settings.ollama_model,
    }


@app.get("/personas")
def personas():
    """Role personas for the UI picker (Auto + each role framing)."""
    from resume_gen.personas import list_personas

    return {"personas": list_personas()}


class GenerateOptions(BaseModel):
    """Per-run generation options (no TargetRole — used when the role comes from
    elsewhere, e.g. a queued job)."""

    pdf: bool = True
    strict: bool = False
    model: str | None = None
    persona: str | None = None  # persona id, "auto"/None = auto-detect
    skills_focus: list[str] | str | None = None  # résumé skills to emphasise this run


class GenerateRequest(TargetRole, GenerateOptions):
    """A TargetRole plus per-run generation options (for POST /generate)."""

    # If this generation came from a queued job (e.g. bulk pulled from the queue),
    # flip that job to 'generated' atomically here — so it never gets stranded as
    # 'new' by a failed follow-up call (and stops double-showing in the Library).
    key_id: str | None = None


class StatusRequest(BaseModel):
    status: str
    notes: str = ""


class ManualJob(BaseModel):
    """A job entered by hand in the Scraper view. Lands in the same review
    queue as Tampermonkey/Apify-sourced jobs."""

    company: str = ""
    title: str = ""
    location: str = ""
    description: str = ""
    contact_email: str = ""
    apply_url: str = ""


class BrowserCapture(BaseModel):
    """A job captured by the Tampermonkey userscript and POSTed straight to the
    queue (no separate collector app). Mirrors the userscript's payload."""

    job_title: str = ""
    company: str = ""
    location: str = ""
    job_type: str = ""
    salary: str = ""
    posted_date: str = ""
    description_summary: str = ""
    key_skills: str = ""
    contact_emails: list[str] | str = ""
    email_apply_required: str = ""
    application_channel: str = ""
    apply_url: str = ""
    source_url: str = ""
    scraped_at: str = ""
    status: str = "saved"
    allow_duplicate: bool = False


@app.post("/generate")
def generate(req: GenerateRequest):
    """Generate resume + cover letter + email for one role. Returns content,
    QA report, and file paths."""
    target = TargetRole(**req.model_dump(include=set(TargetRole.model_fields)))
    try:
        result = run(target, make_pdf=req.pdf, strict=req.strict, persona=req.persona,
                     model=req.model)
        if req.key_id:
            from resume_gen.intake.store import update_status
            try:
                update_status(req.key_id, "generated", result.get("folder", ""))
            except Exception:
                pass   # the run still exists in the Library even if the job is gone
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/outputs")
def outputs():
    """List generated applications, newest first, from the SQLite `runs` table.
    Nothing lives on disk — each run is downloadable (rendered on demand)."""
    from resume_gen.intake import runs as runs_store

    return {"outputs": runs_store.list_runs()}


@app.get("/run")
def get_run(folder: str):
    """Return the full content of a past run for preview, from the `runs` table.
    `folder` is the run id (kept as the param name for UI back-compat)."""
    from resume_gen.intake import runs as runs_store
    from resume_gen.render.ondemand import ARTIFACTS

    bundle = runs_store.get_run(folder)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    # Map each downloadable artifact to its /download URL, so the UI builds links
    # without knowing the catalogue. Keys are the artifact ids.
    files = {art: f"/download/{folder}/{art}" for art in ARTIFACTS}
    return {
        "folder": folder,
        "folder_name": folder,  # lets the UI target this run for review/rewrite-apply
        "run_id": folder,
        "target": bundle.get("target") or {},
        "resume": bundle.get("resume") or {},
        "cover_letter": bundle.get("cover_letter") or {},
        "email": bundle.get("email") or {},
        "qa": bundle.get("qa") or {},
        "qa_has_violations": bundle.get("qa_has_violations", False),
        "review": bundle.get("review"),
        "files": files,
    }


@app.get("/download/{run_id}/{artifact}")
def download_artifact(run_id: str, artifact: str):
    """Render one artifact of a stored run on demand and stream it. PDFs/DOCX are
    rendered into a temp dir and discarded — nothing is persisted to disk."""
    from fastapi import Response

    from resume_gen.intake import runs as runs_store
    from resume_gen.render.ondemand import render_artifact

    bundle = runs_store.get_run(run_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    try:
        content, filename, mime = render_artifact(bundle, artifact)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown artifact '{artifact}'.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {e}")
    # Serve as a generic binary (NOT application/pdf): browsers + the Adobe plugin
    # recognise application/pdf and open it in a tab / external viewer even with an
    # attachment disposition. octet-stream has no viewer, so it always downloads.
    return Response(
        content=content, media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/intake/run")
def intake_run(commit: bool = True, source_type: str | None = None):
    """Scrape configured sources, dedup, and (by default) queue new postings.
    Pass `source_type` (e.g. "collector") to fetch only that kind of source — used
    for the fast auto-sync of browser-saved jobs when the Jobs tab opens."""
    from resume_gen.intake.run import run_intake

    only = {source_type} if source_type else None
    return run_intake(commit_new=commit, only_types=only)


_SOURCES_PATH = Path(__file__).resolve().parents[1] / "data" / "sources.yaml"


def _load_sources_cfg() -> dict:
    import yaml

    if _SOURCES_PATH.exists():
        return yaml.safe_load(_SOURCES_PATH.read_text(encoding="utf-8")) or {}
    from resume_gen.intake.run import load_sources

    return load_sources()


def _save_sources_cfg(cfg: dict) -> None:
    import yaml

    _SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SOURCES_PATH.write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


@app.get("/source-types")
def source_types():
    """Every supported job-source type (from the adapter registry), with the
    metadata the UI needs to build the Add-source form dynamically. Adding a new
    job site is a one-line entry in intake/sources.py — it shows up here
    automatically."""
    from resume_gen.intake.sources import source_types as _types

    return {"types": _types(), "addable": _types(addable_only=True)}


@app.get("/sources")
def sources():
    """The configured job sources + filters, so the UI can show/manage where jobs
    come from (data/sources.yaml)."""
    cfg = _load_sources_cfg()
    out = []
    for s in cfg.get("sources", []):
        label = s.get("search") or s.get("company") or s.get("url") or s.get("actor") \
            or s.get("base") or s.get("type", "")
        if s.get("type") == "jobbank" and s.get("location"):
            label += f" · {s['location']}"
        out.append({"type": s.get("type", ""), "label": label})
    return {"sources": out, "filters": cfg.get("filters", {})}


class SourceIn(BaseModel):
    type: str                 # jobbank | rss | greenhouse | lever | workday | generic | apify
    url: str = ""
    company: str = ""
    search: str = ""          # jobbank keyword
    location: str = ""        # jobbank location


@app.post("/sources/add")
def add_source(s: SourceIn):
    """Append a job source to data/sources.yaml (Job Bank keyword, RSS feed, etc.)."""
    t = (s.type or "").strip().lower()
    if not t:
        raise HTTPException(status_code=400, detail="type is required.")
    entry: dict = {"type": t}
    if t == "jobbank":
        if not s.search.strip():
            raise HTTPException(status_code=400, detail="Job Bank needs a search keyword.")
        entry["search"] = s.search.strip()
        if s.location.strip():
            entry["location"] = s.location.strip()
    else:
        if s.url.strip():
            entry["url"] = s.url.strip()
        if s.company.strip():
            entry["company"] = s.company.strip()
        if t in ("rss", "workday", "generic") and "url" not in entry:
            raise HTTPException(status_code=400, detail=f"'{t}' needs a url.")
        if t in ("greenhouse", "lever") and "company" not in entry:
            raise HTTPException(status_code=400, detail=f"'{t}' needs a company token.")
    cfg = _load_sources_cfg()
    cfg.setdefault("sources", []).append(entry)
    _save_sources_cfg(cfg)
    return {"added": entry, "count": len(cfg["sources"])}


@app.delete("/sources/{index}")
def remove_source(index: int):
    """Remove the source at the given position (matches GET /sources order)."""
    cfg = _load_sources_cfg()
    srcs = cfg.get("sources", [])
    if index < 0 or index >= len(srcs):
        raise HTTPException(status_code=404, detail="Source index out of range.")
    removed = srcs.pop(index)
    _save_sources_cfg(cfg)
    return {"removed": removed, "count": len(srcs)}


@app.get("/jobs")
def jobs(status: str | None = None):
    """List jobs in the review queue, each enriched with `repeat` (repeat company),
    `repeatable_role` (a saved template exists), and `company_email` (saved HR email).

    Everything the enrichment needs is loaded ONCE up front — repeat list, the set of
    repeatable role keys, and the saved companies — then matched in memory. (Doing it
    per-job meant a fresh SQLite connection + file read + full company scan for every
    row, which made this endpoint take seconds on a large queue.)"""
    import re as _re

    from resume_gen.intake import db
    from resume_gen.intake.companies import load_repeat_companies, list_companies, slug as _slug
    from resume_gen.intake.repeatable import role_key
    from resume_gen.intake.store import list_queue

    queue = list_queue(status=status)

    repeat_names = [(n or "").lower().strip() for n in load_repeat_companies() if n]
    with db.connect() as conn:
        repeatable_keys = {r["key"] for r in conn.execute("SELECT key FROM repeatable_roles")}
    saved = list_companies()
    saved_by_slug = {_slug(c.get("company", "")): c for c in saved}
    saved_norm = [((c.get("company") or "").lower().strip(), c) for c in saved]

    def _wmatch(name_lc: str, target_lc: str) -> bool:
        return bool(name_lc) and (
            name_lc == target_lc
            or _re.search(rf"(?<![a-z]){_re.escape(name_lc)}(?![a-z])", target_lc) is not None
        )

    def _repeat(company: str) -> bool:
        c = (company or "").lower().strip()
        return bool(c) and any(_wmatch(n, c) for n in repeat_names)

    def _hr_email(company: str) -> str:
        rec = saved_by_slug.get(_slug(company))
        if not rec:
            c = (company or "").lower().strip()
            rec = next((r for n, r in saved_norm if _wmatch(n, c)), None)
        return (rec.get("hr_email") or rec.get("contact_email") or "").strip() if rec else ""

    out = []
    for q in queue:
        d = q.model_dump()
        d["repeat"] = _repeat(q.company)
        d["repeatable_role"] = role_key(q.company, q.title) in repeatable_keys
        d["company_email"] = _hr_email(q.company)
        out.append(d)
    return {"jobs": out}


@app.get("/apply-profile")
def apply_profile():
    """The autofill answers + repeat-company list (for the Playwright assistant)."""
    from resume_gen.intake.companies import load_apply_profile, load_repeat_companies

    return {"profile": load_apply_profile(), "repeat_companies": load_repeat_companies()}


@app.get("/companies")
def companies_list():
    """All saved company records (reused for repeat applications)."""
    from resume_gen.intake.companies import list_companies

    return {"companies": list_companies()}


@app.get("/companies/{company}")
def company_get(company: str):
    from resume_gen.intake.companies import get_company

    return get_company(company) or {"company": company}


# NOTE: this static route MUST be declared before "/companies/{company}" — otherwise
# the dynamic route captures "import" as a company name.
@app.post("/companies/import")
def import_companies_csv(payload: dict):
    """Import per-company HR details from CSV text. Columns are matched flexibly:
    company (required), hr_name, hr_email, hr_phone, ats, careers_url, notes.
    Each row is merged into that company's saved record (stamping updated_at)."""
    import csv
    import io

    from resume_gen.intake.companies import save_company

    text = (payload or {}).get("csv", "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty CSV.")

    def g(row: dict, *names: str) -> str:
        for n in names:
            for k, v in row.items():
                if k and k.strip().lower().replace(" ", "_") == n:
                    return (v or "").strip()
        return ""

    reader = csv.DictReader(io.StringIO(text))
    saved = 0
    for row in reader:
        company = g(row, "company", "employer", "organization", "business")
        if not company:
            continue
        data = {
            "hr_name": g(row, "hr_name", "hr", "contact_name", "recruiter", "name"),
            "hr_email": g(row, "hr_email", "email", "contact_email", "hr_contact"),
            "hr_phone": g(row, "hr_phone", "phone"),
            "ats": g(row, "ats", "system"),
            "careers_url": g(row, "careers_url", "careers", "url", "website"),
            "notes": g(row, "notes", "note"),
        }
        save_company(company, {k: v for k, v in data.items() if v})
        saved += 1
    return {"rows": saved, "saved": saved}


@app.post("/companies/{company}")
def company_save(company: str, data: dict):
    """Save/merge details for a company, so the next posting reuses them."""
    from resume_gen.intake.companies import save_company

    return save_company(company, data)


class JobUpdate(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    description: str | None = None
    apply_url: str | None = None
    contact_email: str | None = None


@app.post("/jobs/{key_id}/update")
def update_job(key_id: str, req: JobUpdate):
    """Edit a queued job's fields (e.g. add/fix an HR email)."""
    from resume_gen.intake.companies import is_repeat
    from resume_gen.intake.store import update_fields

    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    q = update_fields(key_id, fields)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    d = q.model_dump()
    d["repeat"] = is_repeat(q.company)
    return d


@app.post("/jobs/import")
def import_jobs_csv(payload: dict):
    """Import jobs from CSV text (e.g. collected via n8n) into the queue. Columns
    are matched flexibly (company, title, location, description, contact_email,
    apply_url, …)."""
    import csv
    import io

    from resume_gen.intake.models import JobPosting
    from resume_gen.intake.store import commit, filter_new

    text = (payload or {}).get("csv", "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty CSV.")

    def g(row: dict, *names: str) -> str:
        for n in names:
            for k, v in row.items():
                if k and k.strip().lower() == n:
                    return (v or "").strip()
        return ""

    reader = csv.DictReader(io.StringIO(text))
    postings = []
    for row in reader:
        company = g(row, "company", "employer", "organization", "business")
        title = g(row, "title", "job_title", "position", "role")
        if not (company or title):
            continue
        apply_url = g(row, "apply_url", "url", "link", "source_url", "job_url")
        postings.append(JobPosting(
            source="csv", source_company=company or "csv",
            job_id=apply_url or title, company=company, title=title,
            location=g(row, "location", "city", "place"),
            description=g(row, "description", "description_summary", "summary", "jd"),
            apply_url=apply_url,
            contact_email=g(row, "contact_email", "email", "contact_emails", "hr_email"),
            posted=g(row, "posted", "posted_date", "date"),
        ))
    new = filter_new(postings)
    committed = commit(new)
    return {"rows": len(postings), "new": len(new), "committed": len(committed)}


@app.post("/jobs/manual")
def add_manual_job(req: ManualJob):
    """Add a hand-entered job to the review queue (manual scraping)."""
    from resume_gen.intake.models import JobPosting
    from resume_gen.intake.store import commit, filter_new

    if not (req.title.strip() or req.company.strip()):
        raise HTTPException(status_code=400, detail="A title or company is required.")

    posting = JobPosting(
        source="manual",
        source_company=req.company or "manual",
        job_id=req.apply_url or "",
        company=req.company,
        title=req.title,
        location=req.location,
        description=req.description,
        apply_url=req.apply_url,
        contact_email=req.contact_email,
    )
    new = filter_new([posting])
    if not new:
        return {"queued": False, "duplicate": True, "key_id": posting.key}
    q = commit(new)[0]
    return {"queued": True, "duplicate": False, "job": q.model_dump()}


def _na(value: str) -> str:
    """The userscript writes the literal 'N/A' for empty fields — treat as blank."""
    v = (value or "").strip()
    return "" if v.upper() == "N/A" else v


@app.post("/api/jobs")
def capture_browser_job(req: BrowserCapture):
    """Accept a job captured by the Tampermonkey userscript and commit it straight
    to the review queue. Replaces the old standalone collector app on :8765 — the
    browser now saves directly into this app. The response shape matches what the
    userscript expects (results[].stored/duplicate + summary)."""
    from datetime import date
    from urllib.parse import urlparse

    from resume_gen.intake.models import JobPosting
    from resume_gen.intake.store import commit, filter_new, list_queue

    title = _na(req.job_title)
    company = _na(req.company)
    if not (title or company):
        raise HTTPException(status_code=400, detail="A title or company is required.")

    emails = req.contact_emails
    if isinstance(emails, str):
        emails = [e.strip() for e in emails.split(",") if e.strip()]
    contact_email = (emails[0] if emails else "").strip()

    source_url = (req.source_url or req.apply_url or "").strip()
    host = (urlparse(source_url).hostname or "browser").replace("www.", "")

    posting = JobPosting(
        source="collector",
        source_company=host,
        job_id=source_url,          # canonical URL -> stable dedup key across saves
        company=company,
        title=title,
        location=_na(req.location),
        description=_na(req.description_summary),
        apply_url=(req.apply_url or source_url),
        contact_email=contact_email,
        posted=_na(req.posted_date),
        salary=_na(req.salary),
        job_type=_na(req.job_type),
        key_skills=_na(req.key_skills),
    )

    today = date.today().isoformat()

    def _saved_today() -> int:
        return sum(1 for q in list_queue() if (q.found_at or "").startswith(today))

    new = filter_new([posting])
    if not new:
        if req.allow_duplicate:
            # Force a unique key so a deliberate second entry is stored.
            posting.job_id = f"{source_url}#{date.today().isoformat()}-{_saved_today()}"
            q = commit([posting])[0]
            return {"results": [{"stored": True, "duplicate": True}],
                    "summary": {"file": "review queue", "saved_today": _saved_today()}}
        existing = next((q for q in list_queue() if q.key_id == posting.key), None)
        return {"results": [{"stored": False, "duplicate": True,
                             "existing": {"file": "review queue",
                                          "scraped_at": (existing.found_at if existing else ""),
                                          "flagged": "no"}}],
                "summary": {"file": "review queue", "saved_today": _saved_today()}}

    commit(new)
    return {"results": [{"stored": True, "duplicate": False}],
            "summary": {"file": "review queue", "saved_today": _saved_today()}}


@app.post("/jobs/{key_id}/status")
def job_status(key_id: str, req: StatusRequest):
    """Update a queued job status after review/generation."""
    from resume_gen.intake.store import update_status

    q = update_status(key_id, req.status, req.notes)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return q.model_dump()


@app.post("/jobs/{key_id}/generate")
def generate_queued_job(key_id: str, req: GenerateOptions | None = None):
    """Generate artifacts directly from a queued scraper job."""
    from resume_gen.intake.store import get_job, update_status

    q = get_job(key_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    target = q.to_target_role()
    pdf = True if req is None else req.pdf
    strict = False if req is None else req.strict
    persona = None if req is None else req.persona
    model = None if req is None else req.model
    try:
        result = run(target, make_pdf=pdf, strict=strict, persona=persona, model=model)
        update_status(key_id, "generated", result["folder"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AnswerRequest(BaseModel):
    """Answer one application screening question, grounded in profile + job.
    The job is identified by `job_key` (a queued job) or by inline fields."""

    question: str
    draft: str = ""           # optional: user's own answer to rephrase
    model: str | None = None
    max_words: int | None = None   # cap answer length; None = prompt default
    job_key: str = ""
    company: str = ""
    title: str = ""
    description: str = ""
    location: str = ""


class AnswerItem(BaseModel):
    question: str
    draft: str = ""


class MultiAnswerRequest(BaseModel):
    """Answer several screening questions at once against one target role."""

    items: list[AnswerItem] = []
    model: str | None = None
    max_words: int | None = None
    job_key: str = ""
    company: str = ""
    title: str = ""
    description: str = ""
    location: str = ""


@app.post("/answer")
def answer(req: AnswerRequest):
    """Generate a truthful first-person answer to a screening question."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="A question is required.")
    from resume_gen.generate import generate_answer
    from resume_gen.intake.store import get_job

    target = None
    if req.job_key:
        q = get_job(req.job_key)
        if q is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        target = q.to_target_role()
    elif req.company or req.title or req.description:
        target = TargetRole(
            company=req.company, title=req.title,
            description=req.description, location=req.location,
        )
    try:
        text = generate_answer(
            req.question, target, draft=req.draft, model=req.model,
            max_words=req.max_words,
        )
        return {"answer": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _resolve_answer_target(job_key: str, company: str, title: str,
                           description: str, location: str):
    """Shared target resolution for the answer endpoints."""
    from resume_gen.intake.store import get_job
    if job_key:
        q = get_job(job_key)
        if q is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return q.to_target_role()
    if company or title or description:
        return TargetRole(company=company, title=title,
                          description=description, location=location)
    return None


@app.post("/answers")
def answers(req: MultiAnswerRequest):
    """Answer several screening questions at once, each grounded in profile + job.
    Per-question failures are returned inline so one bad item doesn't sink the batch."""
    from resume_gen.generate import generate_answer

    items = [it for it in (req.items or []) if it.question.strip()]
    if not items:
        raise HTTPException(status_code=400, detail="At least one question is required.")

    target = _resolve_answer_target(req.job_key, req.company, req.title,
                                    req.description, req.location)
    out = []
    for it in items:
        try:
            text = generate_answer(it.question, target, draft=it.draft,
                                   model=req.model, max_words=req.max_words)
            out.append({"question": it.question, "answer": text, "error": ""})
        except Exception as e:
            out.append({"question": it.question, "answer": "", "error": str(e)})
    return {"answers": out}


class AppliedRequest(BaseModel):
    applied: bool = True


@app.post("/jobs/{key_id}/applied")
def mark_applied(key_id: str, req: AppliedRequest):
    """Mark a job applied / not applied (independent of generation status)."""
    from resume_gen.intake.store import set_applied

    q = set_applied(key_id, req.applied)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return q.model_dump()


class PriorityRequest(BaseModel):
    priority: bool = True


@app.post("/jobs/{key_id}/priority")
def mark_priority(key_id: str, req: PriorityRequest):
    """Flag a job ⭐ priority (Auto engine generates priority jobs with Hermes)."""
    from resume_gen.intake.store import set_priority

    q = set_priority(key_id, req.priority)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return q.model_dump()


class IrrelevantRequest(BaseModel):
    irrelevant: bool = True


@app.post("/jobs/{key_id}/irrelevant")
def mark_irrelevant(key_id: str, req: IrrelevantRequest):
    """Flag a job 🚫 not relevant (hidden from the active lists) or restore it."""
    from resume_gen.intake.store import set_irrelevant

    q = set_irrelevant(key_id, req.irrelevant)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return q.model_dump()


class RepeatableRequest(BaseModel):
    repeatable: bool = True


@app.post("/jobs/{key_id}/repeatable")
def mark_repeatable(key_id: str, req: RepeatableRequest):
    """Flag a queued job 🔁 as a recurring role: creates (or removes) a reusable
    template under data/repeatable keyed by company + title."""
    from resume_gen.intake import repeatable as rp
    from resume_gen.intake.store import set_repeatable

    q = set_repeatable(key_id, req.repeatable)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    key = rp.role_key(q.company, q.title)
    if req.repeatable:
        rp.upsert_role(
            q.company, q.title, location=q.location, description=q.description,
            apply_url=q.apply_url, contact_email=q.contact_email,
            job_id=q.job_id, priority=q.priority, source=q.source or "manual",
        )
    else:
        rp.delete_role(key)
    return {**q.model_dump(), "repeatable_key": key}


@app.get("/repeatable")
def repeatable_list():
    """All saved recurring-role templates, most-recently-applied first, plus the
    sector/status/tag facets present in the data (for the filter dropdowns)."""
    from resume_gen.intake.companies import load_sectors
    from resume_gen.intake.repeatable import list_roles

    roles = list_roles()
    sectors = sorted({r.sector for r in roles if r.sector} | set(load_sectors()))
    statuses = sorted({r.status for r in roles if r.status})
    tags = sorted({t for r in roles for t in (r.tags or [])}, key=str.lower)
    return {
        "roles": [r.model_dump() for r in roles],
        "sectors": sectors,
        "statuses": statuses,
        "tags": tags,
    }


class RepeatableUpdate(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    job_id: str | None = None
    sector: str | None = None
    tags: list[str] | str | None = None
    status: str | None = None
    description: str | None = None
    apply_url: str | None = None
    contact_email: str | None = None
    persona: str | None = None
    priority: bool | None = None
    notes: str | None = None


@app.post("/repeatable/{key}/update")
def repeatable_update(key: str, req: RepeatableUpdate):
    """Edit a template (e.g. paste a refreshed JD before regenerating)."""
    from resume_gen.intake.repeatable import update_fields

    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    role = update_fields(key, fields)
    if role is None:
        raise HTTPException(status_code=404, detail="Repeatable role not found.")
    return role.model_dump()


@app.delete("/repeatable/{key}")
def repeatable_delete(key: str):
    """Stop tracking a recurring role."""
    from resume_gen.intake.repeatable import delete_role

    return {"deleted": delete_role(key)}


@app.post("/repeatable/{key}/generate")
def repeatable_generate(key: str, req: GenerateOptions | None = None):
    """Regenerate a freshly tuned application from the role's saved JD, and bump
    its applied-count / last-folder so you can download and reapply."""
    from resume_gen.intake.repeatable import get_role, mark_applied

    role = get_role(key)
    if role is None:
        raise HTTPException(status_code=404, detail="Repeatable role not found.")
    target = TargetRole(
        company=role.company, title=role.title, description=role.description,
        location=role.location, apply_url=role.apply_url,
        contact_email=role.contact_email,
    )
    pdf = True if req is None else req.pdf
    strict = False if req is None else req.strict
    # Per-run persona overrides the saved one; fall back to the template's persona.
    persona = (req.persona if req and req.persona else None) or (role.persona or None)
    model = None if req is None else req.model
    # Per-run skills emphasis (accept a list or a comma/semicolon string).
    raw_focus = req.skills_focus if req else None
    if isinstance(raw_focus, str):
        raw_focus = [s.strip() for s in raw_focus.replace(";", ",").split(",") if s.strip()]
    skills_focus = raw_focus or None
    try:
        result = run(target, make_pdf=pdf, strict=strict, persona=persona, model=model,
                     skills_focus=skills_focus)
        mark_applied(key, folder=result["folder"], folder_name=result["folder_name"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class EmailJobRequest(BaseModel):
    """Parse a job-alert email (or pasted job text) into a posting. Used by the
    in-app 'From email' box and by n8n (Gmail → POST here)."""

    text: str
    model: str | None = None
    repeatable: bool = False   # also save the parsed job as a recurring template


@app.post("/jobs/from-email")
def job_from_email(req: EmailJobRequest):
    """Extract a job from email text, queue it (dedup), and match/save it as a
    recurring role. Returns the parsed job + whether it matched an existing template."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Email text is required.")
    from resume_gen.generate import extract_job_from_email
    from resume_gen.intake import repeatable as rp
    from resume_gen.intake.models import JobPosting
    from resume_gen.intake.store import commit, filter_new

    try:
        ex = extract_job_from_email(req.text, model=req.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not parse the email: {e}")
    if not (ex.title.strip() or ex.company.strip()):
        raise HTTPException(status_code=422,
                            detail="No job could be found in that text.")

    matched = rp.match_role(ex.company, ex.title)
    # Refresh an existing template's JD (the posting came round again).
    if matched:
        rp.upsert_role(ex.company, ex.title, location=ex.location,
                       description=ex.description or matched.description,
                       apply_url=ex.apply_url, contact_email=ex.contact_email,
                       source="email")
    elif req.repeatable:
        rp.upsert_role(ex.company, ex.title, location=ex.location,
                       description=ex.description, apply_url=ex.apply_url,
                       contact_email=ex.contact_email, source="email")

    posting = JobPosting(
        source="email", source_company=ex.company or "email",
        job_id=ex.apply_url or "", company=ex.company, title=ex.title,
        location=ex.location, description=ex.description,
        apply_url=ex.apply_url, contact_email=ex.contact_email,
    )
    new = filter_new([posting])
    queued = None
    duplicate = not new
    if new:
        q = commit(new)[0]
        if matched or req.repeatable:
            from resume_gen.intake.store import set_repeatable
            set_repeatable(q.key_id, True)
        queued = q.model_dump()

    return {
        "parsed": ex.model_dump(),
        "queued": bool(queued),
        "duplicate": duplicate,
        "job": queued,
        "matched_repeatable": matched.key if matched else "",
        "repeatable_key": rp.role_key(ex.company, ex.title),
    }


@app.get("/usage")
def usage():
    """AI engine usage + timing, for the resource monitor."""
    from resume_gen.llm import hermes_client
    from resume_gen.usage import summary

    return {"enabled": hermes_client.available(), **summary()}


class ReviewRequest(BaseModel):
    folder_name: str | None = None   # review a saved run by its output folder
    resume: dict | None = None       # ...or pass the resume + target inline
    cover_letter: dict | None = None
    target: dict | None = None
    model: str | None = None         # defaults to the Hermes engine


def _doc_base(folder: Path, target: dict, suffix: str) -> str:
    """Document base name for a run (e.g. 'Acme_Dev_KK'); falls back to the file name."""
    base = (target or {}).get("document_base_name")
    if base:
        return base
    m = list(folder.glob(f"*_{suffix}.docx"))
    return m[0].name[: -len(f"_{suffix}.docx")] if m else suffix


@app.post("/review")
def review(req: ReviewRequest):
    """Have the Hermes agent review a generated application against its job description:
    the résumé AND the cover letter (recruiter-style critique each). When Hermes judges a
    rewrite warranted, it also returns a rewritten résumé / cover letter — each run through
    the deterministic truth-guard so it can improve wording/ordering/keywords but never
    fabricate facts. Also reports deterministic page validation (count + Letter/A4 size).
    Pass a `folder_name` of a past run, or `resume`+`target` inline. Applying a rewrite is a
    separate explicit step (POST /review/apply)."""
    from resume_gen.llm import hermes_client
    from resume_gen.review import (
        review_cover_letter, review_resume, rewrite_cover_letter, rewrite_resume,
    )

    if not hermes_client.available():
        raise HTTPException(status_code=400, detail="HERMES_API_KEY is not set — the Hermes review engine is off.")

    from resume_gen.intake import runs as runs_store

    resume, cover, target, run_id = req.resume, req.cover_letter, req.target, None
    if req.folder_name:
        bundle = runs_store.get_run(req.folder_name)
        if bundle is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        run_id = req.folder_name
        resume = bundle.get("resume") or {}
        cover = bundle.get("cover_letter") or {}
        target = bundle.get("target") or {}
    if not resume or not target:
        raise HTTPException(status_code=400, detail="Provide folder_name, or both resume and target.")

    from resume_gen.guard import enforce, enforce_cover_letter, has_violations
    from resume_gen.personas import select_persona
    from resume_gen.profile import load_profile

    tr = TargetRole(**{k: v for k, v in (target or {}).items() if k in TargetRole.model_fields})
    profile = load_profile()

    # --- Résumé review (+ truth-guarded rewrite when warranted) ---------------
    try:
        result = review_resume(resume, target, model=req.model)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    data = result.model_dump()

    if result.rewrite_recommended:
        try:
            rw = rewrite_resume(resume, target, review=result, model=req.model)
            guarded, rw_qa = enforce(rw.resume, profile, persona=select_persona(tr),
                                     target_location=tr.location)
            data["rewrite"] = guarded.model_dump()
            data["rewrite_changes"] = rw.changes
            data["rewrite_qa"] = rw_qa
            data["rewrite_qa_has_violations"] = has_violations(rw_qa)
        except Exception as e:
            data["rewrite_error"] = str(e)

    # --- Cover letter review (+ truth-guarded rewrite when warranted) ---------
    if cover:
        try:
            c_result = review_cover_letter(cover, target, model=req.model)
            data["cover_review"] = c_result.model_dump()
            if c_result.rewrite_recommended:
                crw = rewrite_cover_letter(cover, target, review=c_result, model=req.model)
                c_guarded, c_qa = enforce_cover_letter(crw.cover_letter, profile,
                                                       target_location=tr.location)
                data["cover_rewrite"] = c_guarded.model_dump()
                data["cover_rewrite_changes"] = crw.changes
                data["cover_rewrite_qa"] = c_qa
        except Exception as e:
            data["cover_review_error"] = str(e)

    # Persist the review (incl. any proposed rewrite) into the stored run, so the
    # UI can show it again and /review/apply can act on it.
    if run_id is not None:
        runs_store.update_run(run_id, review=data)
    return data


class ApplyRewriteRequest(BaseModel):
    folder_name: str
    kind: str = "resume"   # "resume" | "cover"


@app.post("/review/apply")
def apply_rewrite(req: ApplyRewriteRequest):
    """Apply a saved Hermes rewrite into the stored run: swap the resume/cover JSON
    for the rewritten version (kept in the run's `review`). Reversible — the previous
    content is stashed under the run's `pre_rewrite` key. No files; the new DOCX/PDF
    are rendered on demand at download as usual."""
    if req.kind not in ("resume", "cover"):
        raise HTTPException(status_code=400, detail="kind must be 'resume' or 'cover'.")

    from resume_gen.intake import runs as runs_store
    from resume_gen.models import CoverLetter, Resume

    bundle = runs_store.get_run(req.folder_name)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    review = bundle.get("review") or {}

    field = "resume" if req.kind == "resume" else "cover_letter"
    rewrite = review.get("rewrite" if req.kind == "resume" else "cover_rewrite")
    if not rewrite:
        raise HTTPException(status_code=400,
                            detail=f"No {req.kind} rewrite saved — run Review first.")
    Model = Resume if req.kind == "resume" else CoverLetter
    try:
        obj = Model(**rewrite)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Saved rewrite is invalid: {e}")

    pre = dict(bundle.get("pre_rewrite") or {})
    pre[field] = bundle.get(field)  # stash the current version for undo
    runs_store.update_run(req.folder_name, **{field: obj.model_dump(), "pre_rewrite": pre})
    return {"applied": True, "kind": req.kind, field: obj.model_dump()}


class HermesScrape(BaseModel):
    role: str
    location: str = ""
    limit: int = 15


@app.post("/scrape/hermes")
def scrape_hermes(req: HermesScrape):
    """Have the Hermes agent find current jobs and queue the new ones."""
    from resume_gen.intake.models import JobPosting
    from resume_gen.intake.store import commit, filter_new
    from resume_gen.llm import hermes_client

    if not hermes_client.available():
        raise HTTPException(status_code=400, detail="HERMES_API_KEY is not set.")
    if not req.role.strip():
        raise HTTPException(status_code=400, detail="A role/keyword is required.")
    try:
        found = hermes_client.find_jobs(req.role, req.location, limit=max(1, min(req.limit, 30)))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Hermes-found jobs are curated (you searched for them) — no keyword/Canada filter.
    postings = []
    for j in found:
        url = (j.get("apply_url") or "").strip()
        postings.append(JobPosting(
            source="hermes", source_company="hermes",
            job_id=url or j.get("title", ""),
            company=(j.get("company") or "").strip(),
            title=(j.get("title") or "").strip(),
            location=(j.get("location") or "").strip(),
            description=(j.get("description") or "").strip(),
            apply_url=url,
            contact_email=(j.get("contact_email") or "").strip(),
        ))
    committed = commit(filter_new(postings))
    return {"found": len(found), "queued": len(committed),
            "new_jobs": [{"key_id": q.key_id, "company": q.company, "title": q.title,
                          "location": q.location} for q in committed]}


@app.post("/jobs/dedupe")
def dedupe_queue():
    """Remove duplicate queued jobs (same company + title + location), keeping the
    most valuable copy of each. Deleted keys stay in `seen` so they don't return."""
    from resume_gen.intake.store import dedupe_jobs

    return dedupe_jobs()


@app.delete("/jobs/{key_id}")
def delete_queued_job(key_id: str, forget_seen: bool = True):
    """Delete a queued scraped job. By default, also remove its dedupe key so it
    can be queued again if a future scrape still finds it."""
    from resume_gen.intake.store import delete_job

    q = delete_job(key_id, forget_seen=forget_seen)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"deleted": key_id, "job": q.model_dump(), "forget_seen": forget_seen}


@app.get("/jobs/{key_id}/download")
def download_job(key_id: str):
    """Download one queued job as a JSON file (its full record)."""
    from fastapi import Response

    from resume_gen.intake.store import get_job

    q = get_job(key_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    content = q.model_dump_json(indent=2).encode("utf-8")
    return Response(
        content=content, media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="job_{key_id}.json"'},
    )


@app.get("/jobs/export")
def export_jobs(status: str | None = None):
    """Download the whole review queue as one JSON file (optionally filtered)."""
    from fastapi import Response

    from resume_gen.intake.store import list_queue

    jobs = [q.model_dump() for q in list_queue(status=status)]
    content = json.dumps({"jobs": jobs}, indent=2, ensure_ascii=False).encode("utf-8")
    return Response(
        content=content, media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="jobs.json"'},
    )


@app.post("/jobs/{key_id}/send-n8n")
def send_to_n8n(key_id: str):
    """Send an EMAIL-APPLY job's generated package to the n8n webhook (n8n sends
    the actual email). Requires the job to be generated and to have a contact
    email, and N8N_WEBHOOK_URL to be set."""
    import json as _json

    import httpx

    from resume_gen.intake.companies import hr_email_for
    from resume_gen.intake.store import get_job, set_applied, update_status

    if not settings.n8n_webhook_url:
        raise HTTPException(status_code=400, detail="N8N_WEBHOOK_URL is not set (.env).")
    q = get_job(key_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    # Fall back to the company's saved HR email when the job itself has none.
    to_email = (q.contact_email or "").strip() or hr_email_for(q.company)
    if not to_email:
        raise HTTPException(status_code=400, detail="No contact email on the job or saved for the company.")
    if q.status != "generated" or not q.notes:
        raise HTTPException(status_code=400, detail="Generate the application first.")

    import base64

    from resume_gen.intake import runs as runs_store
    from resume_gen.render.ondemand import render_artifact

    bundle = runs_store.get_run(q.notes)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Generated application not found.")

    email = bundle.get("email") or {}

    # Render the resume + cover PDFs on demand (temp dir, discarded) for the email.
    files = {}
    for key, artifact in (("resume", "resume.pdf"), ("cover_letter", "cover.pdf")):
        try:
            content, filename, _ = render_artifact(bundle, artifact)
            files[key] = {"filename": filename,
                          "content_base64": base64.b64encode(content).decode()}
        except Exception:
            pass  # best-effort; an email with no attachment is still better than a 500

    payload = {
        "company": q.company, "title": q.title, "location": q.location,
        "contact_email": to_email, "apply_url": q.apply_url,
        "email": email, "folder": q.notes, "files": files,
    }
    try:
        r = httpx.post(settings.n8n_webhook_url, json=payload, timeout=60.0)
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"n8n webhook failed: {e}")

    set_applied(key_id, True)
    update_status(key_id, "sent")
    return {"sent": True, "to": "n8n", "job": get_job(key_id).model_dump()}


@app.delete("/run")
def delete_run(folder: str):
    """Delete a generated run from the DB. Also removes any legacy on-disk folder
    of the same name (left over from the file-based era), if present."""
    from resume_gen.intake import runs as runs_store

    removed = runs_store.delete_run(folder)
    out = settings.output_dir.resolve()
    d = (settings.output_dir / folder).resolve()
    if d != out and out in d.parents and d.is_dir():
        shutil.rmtree(d)
        removed = True
    if not removed:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"deleted": folder}


@app.get("/file")
def get_file(path: str):
    """Legacy: download a file from a pre-SQLite output folder still on disk.
    New runs are downloaded via /download/{run_id}/{artifact}."""
    p = Path(path).resolve()
    if not str(p).startswith(str(settings.output_dir.resolve())):
        raise HTTPException(status_code=403, detail="Path outside output directory.")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(str(p), filename=p.name)
