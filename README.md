# Automatic Resume Generator

Self-hosted, **truth-only** job-application engine. Feed it a job; it produces a
tailored, ATS-friendly **resume**, **cover letter**, and **application email** —
generated locally via [Ollama](https://ollama.com), rendered to DOCX/PDF — and it
will never invent employers, dates, titles, degrees, certifications, metrics, or
skills. Everything is grounded in your master profile and enforced by a
deterministic truth-guard.

It ships with a web app (**Resume Studio**), a browser **scraper** (Tampermonkey →
local collector dashboard), role **personas**, and **n8n**-friendly HTTP APIs for
automation.

> This README is the overview. Full details live in [`docs/`](docs/).
> Recent changes are in [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

## What's in the box

| Piece | What it is | Where |
|------|------------|-------|
| **Resume Studio** | Web app: Generate, Bulk, Scraper, Library views | `web/index.html`, served by `api/server.py` at `:8088` |
| **Generation core** | profile + persona + job → resume/cover/email, truth-guarded | `src/resume_gen/` |
| **Personas** | Role-specific framings of your one true history | `data/profile/personas.yaml` |
| **Scraper collector** | Local dashboard + store fed by the userscript | separate app on `:8765` (`Resume_Scraper/Scraper.py`) |
| **Job-saver userscript** | Saves LinkedIn + Indeed jobs to Resume Studio | `tampermonkey/tampermonkey.user.js` |
| **Intake** | Pull jobs (collector / Apify / ATS boards) → review queue | `src/resume_gen/intake/` |

## Quick start

```powershell
# 1. install (editable so `resume_gen` imports cleanly)
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e .

# 2. configure
copy .env.example .env        # OLLAMA_MODEL, etc.
ollama list                   # ensure a model is pulled (qwen3:8b recommended)

# 3. add YOUR data (templates ship; your real files are gitignored)
copy data\profile\master_profile.sample.yaml data\profile\master_profile.yaml   # REQUIRED — edit it
copy data\apply_profile.sample.json          data\apply_profile.json            # autofill answers
copy data\profile\personas.sample.yaml       data\profile\personas.yaml         # optional
copy data\repeat_companies.sample.json       data\repeat_companies.json         # optional
#   (coming soon: `python -m resume_gen init` fills these in interactively)

# 4. run the app (Docker is the supported path; LibreOffice PDF inside the container)
docker compose -f docker/docker-compose.yml up -d --build
#   -> Resume Studio at http://localhost:8088/
```

Full install (profile, personas, sources, scraper collector, Tampermonkey, n8n) is
in [`docs/setup.md`](docs/setup.md). What's stored and how to back up / reset:
[`docs/data-and-privacy.md`](docs/data-and-privacy.md).

## The truth-only rule

The generator may **only** use facts in `data/profile/master_profile.yaml`. A
deterministic [truth-guard](docs/architecture.md#truth-guard) repairs identity,
education, skills, and links from the profile, flags (or strips) fabricated
metrics, and backfills a relevant skills section. Personas change *framing*, never
facts.

## Docs

- [`docs/chatgpt-codex-automation.md`](docs/chatgpt-codex-automation.md) — ChatGPT/Codex browser automation with a final yes/no gate

- [`docs/how-it-works.md`](docs/how-it-works.md) — **start here**: the whole flow end to end
- [`docs/setup.md`](docs/setup.md) — full setup, every component
- [`docs/architecture.md`](docs/architecture.md) — components, ports, data flow, truth-guard
- [`docs/scraper.md`](docs/scraper.md) — collector, userscript (LinkedIn + Indeed), and job intake
- [`docs/personas.md`](docs/personas.md) — role personas and how selection works
- [`docs/auto-apply.md`](docs/auto-apply.md) — semi-auto apply (email → n8n, Playwright portal autofill)
- [`docs/repeatable.md`](docs/repeatable.md) — repeatable roles (reapply templates) + email-alert intake
- [`docs/bulk-csv.md`](docs/bulk-csv.md) — bulk-generate from a CSV: columns/schema + the two import paths
- [`docs/storage.md`](docs/storage.md) — the SQLite store (jobs, runs, repeatable, companies)
- [`docs/data-and-privacy.md`](docs/data-and-privacy.md) — what's stored, what's gitignored, back up / reset
- [`docs/api.md`](docs/api.md) — HTTP API reference (for n8n and other devices)
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — updates & patches
