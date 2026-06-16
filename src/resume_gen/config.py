"""Runtime configuration, loaded from environment (.env) with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project root = three levels up from this file (src/resume_gen/config.py).
ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")


def _path(env_value: str) -> Path:
    p = Path(env_value)
    return p if p.is_absolute() else ROOT / p


def _normalize_ollama_host(value: str) -> str:
    """Ollama's own OLLAMA_HOST is often a bind address like '0.0.0.0:11434'
    (no scheme). As a CLIENT we need a real URL: add http:// and turn the
    unconnectable 0.0.0.0 into localhost."""
    v = (value or "").strip()
    if "://" not in v:
        v = "http://" + v
    return v.replace("://0.0.0.0", "://localhost").rstrip("/")


@dataclass
class Settings:
    # Ollama
    ollama_host: str = _normalize_ollama_host(os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    ollama_temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))

    # Hermes (local agent) — the secondary engine, via its OpenAI-compatible
    # gateway. HERMES_API_KEY is the gateway's API_SERVER_KEY; the engine is only
    # offered when it's set. In Docker, point HERMES_BASE_URL at host.docker.internal.
    hermes_base_url: str = os.getenv("HERMES_BASE_URL", "http://localhost:8642/v1")
    hermes_api_key: str = os.getenv("HERMES_API_KEY", os.getenv("API_SERVER_KEY", ""))
    hermes_model: str = os.getenv("HERMES_MODEL", "hermes-agent")

    # Max seconds any single AI request (Ollama or Hermes) may run before it is
    # aborted with a clean error. Local models on CPU can be slow — keep generous.
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "300"))

    # Hermes-led QA: a semantic truthfulness pass over the generated résumé BEFORE the
    # deterministic truth-guard (which always runs last as the hard backstop). Only runs
    # when Hermes is available; set HERMES_QA=0 to disable and use the guard alone.
    hermes_qa: bool = os.getenv("HERMES_QA", "1").strip().lower() not in ("0", "false", "no", "off")

    # Hermes-chosen persona: let the Hermes agent pick the best-fit résumé persona per job
    # (semantic) instead of keyword matching. Falls back to keyword matching when off or
    # Hermes is unavailable. Set HERMES_PERSONA=0 to always use keyword matching.
    hermes_persona: bool = os.getenv("HERMES_PERSONA", "1").strip().lower() not in ("0", "false", "no", "off")

    # Paths
    profile_path: Path = field(
        default_factory=lambda: _path(os.getenv("PROFILE_PATH", "data/profile/master_profile.yaml"))
    )
    output_dir: Path = field(
        default_factory=lambda: _path(os.getenv("OUTPUT_DIR", "output"))
    )
    # Scraper intake: source config + dedup store + job queue live here.
    intake_dir: Path = field(
        default_factory=lambda: _path(os.getenv("INTAKE_DIR", "data/intake"))
    )
    # SQLite database: review queue, dedup set, repeatable roles, company memory,
    # and the output-run index. Lives under data/ (mounted in Docker) so it
    # persists. The JSON stores are migrated into it once, on first start.
    db_path: Path = field(
        default_factory=lambda: _path(os.getenv("DB_PATH", "data/resume.db"))
    )

    # PDF export
    pdf_engine: str = os.getenv("PDF_ENGINE", "auto")  # auto | docx2pdf | libreoffice
    libreoffice_bin: str = os.getenv("LIBREOFFICE_BIN", "soffice")

    # Page validation: physical page size + max page count per document.
    page_size: str = os.getenv("PAGE_SIZE", "letter").lower()  # letter | a4
    resume_max_pages: int = int(os.getenv("RESUME_MAX_PAGES", "2"))
    cover_max_pages: int = int(os.getenv("COVER_MAX_PAGES", "1"))

    # API
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8088"))

    # n8n webhook for the email-apply path. Email-apply jobs are POSTed here
    # (with the generated resume/cover/email) after generation.
    n8n_webhook_url: str = os.getenv("N8N_WEBHOOK_URL", "")


settings = Settings()
