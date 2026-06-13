# Architecture

## Principle: truth-only

The only source of facts is `data/profile/master_profile.yaml`. The LLM receives a
serialized, facts-only view of it (`profile.py`) plus an optional **persona**
framing, and is instructed (`prompts.py`) to use nothing else. Output is
constrained to a JSON schema (Ollama `format`) and validated with pydantic
(`models.py`). A deterministic **truth-guard** (`guard.py`) then repairs the parts
that must never be model-invented. Fabrication is structurally hard, not a matter
of the model "behaving".

## Components & ports

| Component | Port | Runs as | Talks to |
|-----------|------|---------|----------|
| **Resume Studio API** (`api/server.py`) | `8088` | Docker (`docker/docker-compose.yml`) | Ollama (host), collector (`:8765`) |
| **Ollama** | `11434` | Host (GPU) | — |
| **Scraper collector** (`Resume_Scraper/Scraper.py`) | `8765` | Docker (own compose) | CSV store `job_data/` |
| **n8n** | `5678` | Docker (separate project) | Resume Studio API |
| **Tampermonkey userscript** | — | Browser | collector `:8765` |

> **Networking gotcha:** the containers live on **separate Docker networks**, so
> they reach each other through the **host gateway**, not `localhost`:
> - Resume API → Ollama: `host.docker.internal:11434`
> - Resume API → collector: `host.docker.internal:8765`
> - n8n → Resume API: `host.docker.internal:8088`
> - The userscript runs in your browser, so it uses `127.0.0.1:8765` directly.

## Data flow — generation

```
master_profile.yaml ─┐
personas.yaml ───────┤
                     ├─► profile_block + persona_directive ─► prompts ─► Ollama
TargetRole (job) ────┘                                       (format=JSON schema)
                                                                     │
                                          pydantic validate ◄────────┘
                                                  │
                                   truth-guard (guard.py): repair identity/
                                   education/skills/links, backfill skills,
                                   flag/strip fabricated metrics
                                                  │
                  ┌───────────────────────────────┼───────────────────────────┐
              Resume                         CoverLetter               ApplicationEmail
                  │ docx_renderer                │ docx_renderer              │ email.txt
              pdf_export (LibreOffice / docx2pdf)
                  │
    output/<Company>_<Title>_<date>/{resume,cover_letter}.{docx,pdf}, email.txt, *.json
```

## Data flow — scrape & intake

```
Tampermonkey (LinkedIn/Indeed)  ──POST /api/jobs──►  Collector (:8765, CSV store)
                                                          │  dashboard at /
Resume Studio "Scraper" tab embeds the dashboard ◄────────┘  (iframe, theme-synced)

POST /intake/run  ──►  fetch sources (collector / Apify / Greenhouse / Lever / Workday)
                  ──►  filter (title keywords, canada_only, require_email)
                  ──►  dedup (seen.json)  ──►  review queue (data/intake/queue/*.json)
                  ──►  Bulk "Generate from queue"  ──►  generation pipeline
```

## Truth-guard

`src/resume_gen/guard.py` runs after generation, before rendering:

- **Identity / contact / education** — overwritten verbatim from the profile.
- **Links** — set from `master_profile.contact.links` (keep this list short; every
  link shows on every resume).
- **Skills** — filtered to those grounded in the profile; **backfilled** from the
  profile (persona-ordered) if the model returns too few, so a relevant Skills
  section always renders.
- **Experience** — company/dates/location forced to the matched profile role; a
  role marked `preserve: true` is kept as its real function (not recast).
- **Metrics** — numbers not present in the source facts are flagged (and stripped
  in `strict` mode).

Everything it changes is reported in `qa_report.json`.

## Modules

| Path | Responsibility |
|------|----------------|
| `src/resume_gen/models.py` | Pydantic schemas (Resume mirrors the prompt SCHEMA) |
| `src/resume_gen/profile.py` | Load master profile; serialize to facts-only prompt block (emits `preserve`) |
| `src/resume_gen/personas.py` | Load personas; auto-select/override; render persona directive |
| `src/resume_gen/prompts.py` | System prompts + user-message builder |
| `src/resume_gen/llm/ollama_client.py` | Schema-constrained `/api/chat` + validation |
| `src/resume_gen/generate.py` | profile + persona + role → validated objects |
| `src/resume_gen/guard.py` | Truth-guard (identity, skills, metrics, backfill) |
| `src/resume_gen/render/docx_renderer.py` | Styled DOCX (acts as the template) |
| `src/resume_gen/render/pdf_export.py` | DOCX → PDF (LibreOffice or docx2pdf) |
| `src/resume_gen/pipeline.py` | Generate + guard + render + write the app folder |
| `src/resume_gen/intake/` | Sources, models, dedup store, `run_intake` (see scraper.md) |
| `api/server.py` | FastAPI + Resume Studio web app |
| `web/index.html` | Resume Studio single-page app |

## Decisions

- **Python everywhere** — one language across Ollama, rendering, scraping, intake.
- **Styled DOCX in code → PDF** — reproducible and ATS-safe.
- **Structured output** — Ollama `format=<json schema>` + pydantic, not regex.
- **Ollama on the host, not containerized** — keeps GPU access simple.
- **Scraper collector is a separate app** — it owns the scraped-jobs store and its
  own dashboard; Resume Studio embeds that dashboard and adds generation on top.

## Roadmap

- **Phase 1 — Generation core** ✅ resume + cover + email, DOCX/PDF, CLI + API, web UI.
- **Phase 2 — Intake** ✅ collector + userscript (LinkedIn/Indeed), Apify/ATS sources,
  Canada filter, review queue, embedded dashboard.
- **Phase 3 — Auto-apply** (in progress) — email-to-HR path (`automation/email_sender.py`,
  SMTP) and per-site Selenium form-fill (`automation/apply.py`), behind a review gate.
- **Phase 4 — Reach** — Tailscale so phone/other devices can trigger and review.
