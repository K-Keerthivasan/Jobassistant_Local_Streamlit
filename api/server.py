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


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def index():
    page = WEB_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="UI not found.")
    return HTMLResponse(page.read_text(encoding="utf-8"))


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
    """Locally installed Ollama models, for the UI picker."""
    return {"models": ollama_client.list_models(), "default": settings.ollama_model}


class GenerateRequest(TargetRole):
    """A TargetRole plus per-run generation options."""

    pdf: bool = True
    strict: bool = False
    model: str | None = None


class StatusRequest(BaseModel):
    status: str
    notes: str = ""


@app.post("/generate")
def generate(req: GenerateRequest):
    """Generate resume + cover letter + email for one role. Returns content,
    QA report, and file paths."""
    target = TargetRole(**req.model_dump(include=set(TargetRole.model_fields)))
    if req.model:
        settings.ollama_model = req.model
    try:
        return run(target, make_pdf=req.pdf, strict=req.strict)
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
            "has_pdf": (d / "resume.pdf").exists(),
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
def intake_run(commit: bool = True):
    """Scrape configured sources, dedup, and (by default) queue new postings."""
    from resume_gen.intake.run import run_intake

    return run_intake(commit_new=commit)


@app.get("/jobs")
def jobs(status: str | None = None):
    """List jobs in the review queue."""
    from resume_gen.intake.store import list_queue

    return {"jobs": [q.model_dump() for q in list_queue(status=status)]}


@app.post("/jobs/{key_id}/status")
def job_status(key_id: str, req: StatusRequest):
    """Update a queued job status after review/generation."""
    from resume_gen.intake.store import update_status

    q = update_status(key_id, req.status, req.notes)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return q.model_dump()


@app.post("/jobs/{key_id}/generate")
def generate_queued_job(key_id: str, req: GenerateRequest | None = None):
    """Generate artifacts directly from a queued scraper job."""
    from resume_gen.intake.store import get_job, update_status

    q = get_job(key_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    target = q.to_target_role()
    pdf = True if req is None else req.pdf
    strict = False if req is None else req.strict
    if req and req.model:
        settings.ollama_model = req.model
    try:
        result = run(target, make_pdf=pdf, strict=strict)
        update_status(key_id, "generated", result["folder"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
