# Architecture & Roadmap

## Principle: truth-only

The only source of facts is `data/profile/master_profile.yaml`. The LLM receives a
serialized, facts-only view of it (`profile.py`) and is instructed (`prompts.py`)
to use nothing else. Output is constrained to a JSON schema (Ollama `format`) and
validated with pydantic (`models.py`) before anything is rendered. This makes
fabrication structurally hard rather than relying on the model to "behave".

## Data flow (Phase 1 — implemented)

```
master_profile.yaml ─┐
                     ├─► profile_to_prompt_block ─► prompts ─► Ollama (/api/chat,
TargetRole (job) ────┘                                         format=JSON schema)
                                                                     │
                                          pydantic validate ◄────────┘
                                                  │
                       ┌──────────────────────────┼──────────────────────────┐
                   Resume                     CoverLetter               ApplicationEmail
                       │                          │                          │
                docx_renderer              docx_renderer                 email.txt
                       │                          │
                  pdf_export (LibreOffice / docx2pdf)
                       │
        output/<Company>_<Title>_<date>/{resume,cover_letter}.{docx,pdf}, email.txt, *.json
```

## Modules

| Path | Responsibility |
|------|----------------|
| `src/resume_gen/models.py` | Pydantic schemas (Resume mirrors the prompt SCHEMA exactly) |
| `src/resume_gen/profile.py` | Load master profile; serialize to a facts-only prompt block |
| `src/resume_gen/prompts.py` | System prompts (resume prompt = user's exact spec) + user-message builder |
| `src/resume_gen/llm/ollama_client.py` | Schema-constrained `/api/chat` call + validation |
| `src/resume_gen/generate.py` | profile + role → validated objects |
| `src/resume_gen/render/docx_renderer.py` | Styled DOCX (acts as the template) |
| `src/resume_gen/render/pdf_export.py` | DOCX → PDF (LibreOffice or docx2pdf) |
| `src/resume_gen/pipeline.py` | Generate + render + write a full application folder |
| `src/resume_gen/cli.py` | `check`, `generate` commands |
| `api/server.py` | FastAPI: `/generate`, `/health`, `/file` for n8n + remote |
| `src/resume_gen/automation/` | Phase 3 scaffolds: `email_sender.py`, `apply.py` (Selenium) |

## Roadmap

- **Phase 1 — Generation core** ✅ resume + cover letter + email, DOCX/PDF, CLI + API.
- **Phase 2 — Job intake.** Custom scrapers (Indeed/LinkedIn/company boards) →
  normalized `TargetRole` JSON dropped into `data/jobs/`. n8n watches a queue and
  calls `POST /generate`.
- **Phase 3 — Auto-apply.** Per-site Selenium adapters (`automation/apply.py`
  registry) for form-fill + submit; SMTP direct-email path
  (`automation/email_sender.py`). Human-in-the-loop review gate before submit.
- **Phase 4 — Self-host & reach.** Docker compose (api + n8n) up; Tailscale
  sidecar so other devices/phone can trigger and review applications.

## Decisions

- **Stack:** Python — single language across Ollama, rendering, Selenium, scraping.
- **Render:** styled DOCX in code (reproducible, ATS-safe) → PDF. Swappable for a
  `docxtpl` template later if you want WYSIWYG editing of the layout.
- **Structured output:** Ollama `format=<json schema>` + pydantic, not regex
  parsing — invalid output fails loudly instead of producing garbage.
- **Ollama on host, not in a container:** keeps GPU access simple; the API
  container reaches it via `host.docker.internal`.

## Notes on models

`qwen3:8b` (default) follows JSON-schema constraints well and is fast. `gemma4:12b`
tends to write richer prose — try it for cover letters if you want more warmth:
`--model` support can be added to the CLI, or set `OLLAMA_MODEL` per run.
