"""FastAPI service exposing the generation pipeline over HTTP, so n8n workflows
and other devices (reachable via Tailscale) can drive it.

Run:  uvicorn api.server:app --host 0.0.0.0 --port 8088
Docs: http://<host>:8088/docs
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the src/ package importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from resume_gen.config import settings  # noqa: E402
from resume_gen.llm import ollama_client  # noqa: E402
from resume_gen.models import TargetRole  # noqa: E402
from resume_gen.pipeline import run  # noqa: E402

app = FastAPI(title="Automatic Resume Generator", version="0.1.0")


@app.get("/health")
def health():
    return {
        "ollama": ollama_client.health(),
        "model": settings.ollama_model,
        "output_dir": str(settings.output_dir),
    }


@app.post("/generate")
def generate(target: TargetRole, pdf: bool = True):
    """Generate resume + cover letter + email for one role. Returns file paths."""
    try:
        return run(target, make_pdf=pdf)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/file")
def get_file(path: str):
    """Download a generated artifact. Restricted to the output directory."""
    p = Path(path).resolve()
    if not str(p).startswith(str(settings.output_dir.resolve())):
        raise HTTPException(status_code=403, detail="Path outside output directory.")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(str(p), filename=p.name)
