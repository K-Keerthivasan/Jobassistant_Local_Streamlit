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

    # Max seconds any single AI request (Ollama or Claude) may run before it is
    # aborted with a clean error. Local models on CPU can be slow — keep generous.
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "300"))

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

    # PDF export
    pdf_engine: str = os.getenv("PDF_ENGINE", "auto")  # auto | docx2pdf | libreoffice
    libreoffice_bin: str = os.getenv("LIBREOFFICE_BIN", "soffice")

    # API
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8088"))

    # n8n webhook for the email-apply path. Email-apply jobs are POSTed here
    # (with the generated resume/cover/email) after generation.
    n8n_webhook_url: str = os.getenv("N8N_WEBHOOK_URL", "")


settings = Settings()
