# Automatic Resume Generator

Self-hosted, **truth-only** job-application engine. Feed it a job description; it
generates a tailored, ATS-friendly **resume**, **cover letter**, and **application
email** — locally via [Ollama](https://ollama.com) — then renders them to DOCX/PDF.
The longer-term goal is a full auto-apply pipeline (custom scraper → n8n →
Selenium / direct email), Dockerized and reachable across devices via Tailscale.

The generator may **only** use facts from your master profile
(`data/profile/master_profile.yaml`). It never invents employers, dates, titles,
degrees, certifications, metrics, or skills.

## Quick start

```powershell
# 1. install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. configure
copy .env.example .env       # edit OLLAMA_MODEL etc. if needed

# 3. make sure Ollama is running and a model is pulled
ollama list                  # qwen3:8b or gemma4:12b recommended

# 4. sanity check
python -m resume_gen.cli check

# 5. generate from the sample job
python -m resume_gen.cli generate --job data/jobs/opg_sample.json
```

Set `PYTHONPATH=src` (or `pip install -e .`) so `resume_gen` is importable.
Output lands in `output/<Company>_<Title>_<date>/`.

## Usage

```powershell
# from a JSON target_role file
python -m resume_gen.cli generate --job data/jobs/opg_sample.json

# from flags + a plain-text JD
python -m resume_gen.cli generate --company "Acme" --title "Backend Developer" `
    --jd-file path\to\jd.txt

# skip PDF export (DOCX + JSON only — fastest)
python -m resume_gen.cli generate --job data/jobs/opg_sample.json --no-pdf
```

Each run produces: `resume.json` (validated schema output), `resume.docx`/`.pdf`,
`cover_letter.docx`/`.pdf`, `email.txt`.

## HTTP API (for n8n / other devices)

```powershell
uvicorn api.server:app --host 0.0.0.0 --port 8088
# POST /generate  {company,title,description,...}  ->  file paths
# GET  /health
# docs at http://localhost:8088/docs
```

## Docker

```bash
docker compose -f docker/docker-compose.yml up -d
# resume-api on :8088 (LibreOffice PDF), n8n on :5678
# Ollama runs on the host; containers reach it via host.docker.internal
```

## Architecture & roadmap

See [`docs/architecture.md`](docs/architecture.md). Phase 1 (generation core) is
implemented; Phases 2–4 (scraping, n8n orchestration, Selenium auto-apply,
Tailscale) are scaffolded and built incrementally.
