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


def _artifact(d: Path, generic: str, pattern: str) -> Path | None:
    old = d / generic
    if old.exists():
        return old
    matches = sorted(d.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _document_pair(d: Path, kind: str) -> Path | None:
    if kind == "resume":
        return _artifact(d, "resume.pdf", "*_Resume.pdf") or _artifact(d, "resume.docx", "*_Resume.docx")
    if kind == "cover_letter":
        return _artifact(d, "cover_letter.pdf", "*_Cover.pdf") or _artifact(d, "cover_letter.docx", "*_Cover.docx")
    return None


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
    """Local Ollama models + Claude cloud models (if ANTHROPIC_API_KEY is set)."""
    from resume_gen.llm import anthropic_client

    cloud = [{"id": m, "label": lbl} for m, lbl in anthropic_client.CLAUDE_MODELS] \
        if anthropic_client.available() else []
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


class GenerateRequest(TargetRole, GenerateOptions):
    """A TargetRole plus per-run generation options (for POST /generate)."""


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
    if req.model:
        settings.ollama_model = req.model
    try:
        return run(target, make_pdf=req.pdf, strict=req.strict, persona=req.persona)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/outputs")
def outputs():
    """List previously generated application folders, newest first."""
    out = settings.output_dir
    if not out.exists():
        return {"outputs": []}
    items = []
    for d in out.iterdir():
        if not d.is_dir():
            continue
        target = {}
        tr = d / "target_role.json"
        if tr.exists():
            try:
                target = json.loads(tr.read_text(encoding="utf-8"))
            except ValueError:
                pass
        items.append({
            "folder": d.name,
            "mtime": d.stat().st_mtime,
            "company": target.get("company", ""),
            "title": target.get("title", ""),
            "persona": target.get("persona_label", ""),
            "has_pdf": bool(_artifact(d, "resume.pdf", "*_Resume.pdf")),
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {"outputs": items}


def _read_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


@app.get("/run")
def get_run(folder: str):
    """Return the full content of a past run for preview."""
    d = (settings.output_dir / folder).resolve()
    if not str(d).startswith(str(settings.output_dir.resolve())) or not d.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")
    email_txt = d / "email.txt"
    email = {}
    if email_txt.exists():
        raw = email_txt.read_text(encoding="utf-8")
        subject = ""
        body = raw
        if raw.startswith("Subject:"):
            first, _, rest = raw.partition("\n")
            subject = first[len("Subject:"):].strip()
            body = rest.lstrip("\n")
        email = {"subject": subject, "body": body}
    files = {
        f.name: str(f) for f in d.iterdir()
        if f.suffix in (".docx", ".pdf", ".txt")
    }
    return {
        "folder": folder,
        "target": _read_json(d / "target_role.json") or {},
        "resume": _read_json(d / "resume.json") or {},
        "cover_letter": _read_json(d / "cover_letter.json") or {},
        "email": email,
        "qa": _read_json(d / "qa_report.json") or {},
        "files": files,
    }


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
    """List jobs in the review queue (with a `repeat` flag for repeat companies)."""
    from resume_gen.intake.companies import is_repeat
    from resume_gen.intake.repeatable import is_repeatable
    from resume_gen.intake.store import list_queue

    out = []
    for q in list_queue(status=status):
        d = q.model_dump()
        d["repeat"] = is_repeat(q.company)
        # True when a saved template exists for this exact company+title.
        d["repeatable_role"] = is_repeatable(q.company, q.title)
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
    if req and req.model:
        settings.ollama_model = req.model
    try:
        result = run(target, make_pdf=pdf, strict=strict, persona=persona)
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
    """Flag a job ⭐ priority (Auto engine generates priority jobs with Claude)."""
    from resume_gen.intake.store import set_priority

    q = set_priority(key_id, req.priority)
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
            priority=q.priority, source=q.source or "manual",
        )
    else:
        rp.delete_role(key)
    return {**q.model_dump(), "repeatable_key": key}


@app.get("/repeatable")
def repeatable_list():
    """All saved recurring-role templates, most-recently-applied first."""
    from resume_gen.intake.repeatable import list_roles

    return {"roles": [r.model_dump() for r in list_roles()]}


class RepeatableUpdate(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
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
    if req and req.model:
        settings.ollama_model = req.model
    try:
        result = run(target, make_pdf=pdf, strict=strict, persona=persona)
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
    """Claude (cloud) usage + estimated cost, for the resource monitor."""
    from resume_gen.llm import anthropic_client
    from resume_gen.usage import summary

    return {"enabled": anthropic_client.available(), **summary()}


class ClaudeScrape(BaseModel):
    role: str
    location: str = ""
    limit: int = 15


@app.post("/scrape/claude")
def scrape_claude(req: ClaudeScrape):
    """Have Claude search the web for current jobs and queue the new ones."""
    from resume_gen.intake.models import JobPosting
    from resume_gen.intake.store import commit, filter_new
    from resume_gen.llm import anthropic_client

    if not anthropic_client.available():
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY is not set.")
    if not req.role.strip():
        raise HTTPException(status_code=400, detail="A role/keyword is required.")
    try:
        found = anthropic_client.find_jobs(req.role, req.location, limit=max(1, min(req.limit, 30)))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Claude-found jobs are curated (you searched for them) — no keyword/Canada filter.
    postings = []
    for j in found:
        url = (j.get("apply_url") or "").strip()
        postings.append(JobPosting(
            source="claude", source_company="claude",
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


@app.delete("/jobs/{key_id}")
def delete_queued_job(key_id: str, forget_seen: bool = True):
    """Delete a queued scraped job. By default, also remove its dedupe key so it
    can be queued again if a future scrape still finds it."""
    from resume_gen.intake.store import delete_job

    q = delete_job(key_id, forget_seen=forget_seen)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"deleted": key_id, "job": q.model_dump(), "forget_seen": forget_seen}


def _b64_file(p: Path) -> dict | None:
    import base64

    if not p.exists():
        return None
    return {"filename": p.name, "content_base64": base64.b64encode(p.read_bytes()).decode()}


@app.post("/jobs/{key_id}/send-n8n")
def send_to_n8n(key_id: str):
    """Send an EMAIL-APPLY job's generated package to the n8n webhook (n8n sends
    the actual email). Requires the job to be generated and to have a contact
    email, and N8N_WEBHOOK_URL to be set."""
    import json as _json

    import httpx

    from resume_gen.intake.store import get_job, set_applied, update_status

    if not settings.n8n_webhook_url:
        raise HTTPException(status_code=400, detail="N8N_WEBHOOK_URL is not set (.env).")
    q = get_job(key_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if not q.has_email:
        raise HTTPException(status_code=400, detail="This job has no contact email (not an email-apply job).")
    if q.status != "generated" or not q.notes:
        raise HTTPException(status_code=400, detail="Generate the application first.")

    folder = (settings.output_dir / Path(q.notes).name).resolve()
    if not str(folder).startswith(str(settings.output_dir.resolve())) or not folder.is_dir():
        raise HTTPException(status_code=404, detail="Generated output not found.")

    email = {}
    et = folder / "email.txt"
    if et.exists():
        raw = et.read_text(encoding="utf-8")
        subject, body = "", raw
        if raw.startswith("Subject:"):
            first, _, rest = raw.partition("\n")
            subject, body = first[len("Subject:"):].strip(), rest.lstrip("\n")
        email = {"subject": subject, "body": body}

    files = {}
    for key in ("resume", "cover_letter"):
        doc = _document_pair(folder, key)
        if doc:
            f = _b64_file(doc)
            if f:
                files[key] = f

    payload = {
        "company": q.company, "title": q.title, "location": q.location,
        "contact_email": q.contact_email, "apply_url": q.apply_url,
        "email": email, "folder": folder.name, "files": files,
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
    """Delete a past output folder. Restricted to the output directory."""
    out = settings.output_dir.resolve()
    d = (settings.output_dir / folder).resolve()
    if d == out or out not in d.parents or not d.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")
    shutil.rmtree(d)
    return {"deleted": folder}


@app.get("/file")
def get_file(path: str):
    """Download a generated artifact. Restricted to the output directory."""
    p = Path(path).resolve()
    if not str(p).startswith(str(settings.output_dir.resolve())):
        raise HTTPException(status_code=403, detail="Path outside output directory.")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(str(p), filename=p.name)
