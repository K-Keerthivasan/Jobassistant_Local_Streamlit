# Resume Studio upgrade | Phase 0 recon

Date: 2026-09-14. Branch: `upgrade/lanes-grading-outreach`. Instruction set target: v3.5.

## Stack and entry points

- Python 3.11, FastAPI, SQLite (stdlib), pydantic v2, python-docx, httpx. No Node build step. `web/index.html` is a single 3,800-line vanilla JS page served by FastAPI.
- Package: `pyproject.toml` (setuptools, `src/` layout, `pip install -e .`). No lockfile. `requirements.txt` is the dependency list.
- Local run: `.venv\Scripts\python -m uvicorn api.server:app --port 8088`. Docker is the supported path (`docker/docker-compose.yml`, two containers: `resume-api` on 8088 and `resume-mcp` on 8090). `web/` and `src/` are baked into the image, so code changes need a rebuild.
- CLI: `python -m resume_gen.cli` (typer): `check`, `generate`, `intake`, `queue`.
- Node 24 and npm 11 are installed on the machine but not used by the project. There is no `package.json`. The brief's `npm run validate:data` and `npm run sync:lanes` become thin `package.json` scripts that call the Python CLI, so the names in the brief work as written.

## Data layer

- One SQLite file, `data/resume.db` (27 MB, gitignored), WAL mode, one connection per operation. Schema in `src/resume_gen/intake/db.py`. Every table stores the full record as JSON in a `data` column plus a few indexed columns, so pydantic models evolve without migrations.
- Tables and live counts: `jobs` 1,855 (130 new, 1,551 generated, 147 applied, 27 sent), `seen` 2,084, `runs` 1,686 (generated applications, rendered to DOCX/PDF on demand), `companies` 60, `answers` 7, `apply_sessions` 6, `form_templates` 3, `repeatable_roles` 14.
- No migration framework. Schema is `CREATE TABLE IF NOT EXISTS`; a one-time JSON-to-SQLite backfill runs on startup.
- Personal config stays as gitignored files with `*.sample.*` templates: `data/profile/master_profile.yaml` (the truth-only profile), `data/profile/personas.yaml`, `data/apply_profile.json`, `data/repeat_companies.json`, `data/sources.yaml`.

## What already exists against each phase

| Phase | Exists today | Gap |
|---|---|---|
| 1 Lanes as data | Nothing. `QueuedJob.lane` is a free-text string that is never populated (all 200 sampled rows have `lane: None`). No NOC, no skill status anywhere. | Everything in section 2. |
| 2 Intake | `POST /jobs/import` takes a flexible CSV (company, title, location, description, apply_url, contact_email, posted). `POST /companies/import` takes the hr_companies shape and merges multi-email contacts. Dedupe by posting key, plus content dedupe for Job Bank/RSS. `store.dedupe_jobs()` already has the legal-suffix company normaliser. | `priority`, `lane`, `noc_teer` are dropped. No tag grammar. No fit report import. No batch/run-date/stream tracking. No import report. No Stream D validation. |
| 3 Grading | Priority auto-score (repeat company, has email, freshness). `review.find_skill_gaps` asks an LLM for gaps after generation. | No matrix, no tiering, no evidence-traced fit sentence, no seniority guard. |
| 4 Materials | Full pipeline: profile + persona + job to resume, cover letter, email via Ollama or Hermes, deterministic truth-guard (`guard.py`), two-page auto-fit, DOCX renderer with Arial, ruled headings, tab-stop dates, ATS bullets, PDF via LibreOffice or docx2pdf. Google XYZ bullet formula is already in `prompts.py` (uncommitted working-tree change carried onto this branch). Answers bank with fuzzy reuse and approval-gated banking. | Persona choice is keyword or Hermes, not lane. No game-dev or VFX persona. Header colour is `#1F4E79` not `#1F3864`. Date ranges render with an en dash. Filenames are `<Company>_<Title>_K_Resume.pdf` not `kk_[Company]_[Role]`. Cover letter spec is 2 to 3 paragraphs. No status-aware skill filter. Links are the same three on every resume. |
| 5 Outreach | Company HR contacts (`hr_contacts` list, no confidence), single and batch HR follow-up templates posted to n8n `bulk-hr` webhook, Google Sheet logging, daily follow-up workflow in n8n. `generate_hr_followup` templates. | No queue, no approval gate, no message rows, no callback, no guardrails (cap, cooldown, suppression, kill switch), no confidence model, no audit log. Sends fire immediately from a button. |
| 6 Ledger | `jobs` row carries `applied`, `sent_at`, `sent_to`, `followups`, `sent_log`; Library view lists every job. | No lane, NOC, tier, pathway, outreach status columns; no dashboard. |
| 7 Currency | `docs/CHANGELOG.md` for app changes. | No data versioning, no sync, no drift check. |

## Where hardcoded knowledge lives

- `data/profile/personas.yaml` (gitignored): the nine role personas with keyword lists, lead-with roles and foreground skills. This is the closest thing to lanes today. Lines 1 to 320.
- `data/profile/master_profile.yaml` (gitignored): identity, links, skill inventory, experience facts, education. The truth-guard grounds every claim against this.
- `data/apply_profile.json` (gitignored): address, authorisation answers, `commonAnswers` screening answers (seeded into the `answers` table once).
- `src/resume_gen/render/docx_renderer.py` lines 19 to 39: colours, font, and `SKILL_GROUP_LABELS` (the profile skill-group names are hardcoded here).
- `src/resume_gen/guard.py` lines 120 to 160: `_SKILL_STOPWORDS` and `_PROSE_STOP` word lists that decide grounding.
- `src/resume_gen/generate.py` lines 165 to 200: link resolution by label substring (`linkedin`, `k2`, `portfolio`), the email templates and fallback hook lines.
- `src/resume_gen/intake/store.py` lines 240 to 275: company legal-suffix, title and location normalisers (reusable for Phase 2).
- `src/resume_gen/intake/run.py` line 26: `_CURATED_SOURCES` set. `src/resume_gen/intake/sources.py` line 555: source type list.
- `src/resume_gen/automation/autoapply.py` lines 60 to 135: profile field keyword table and the sensitive-question list.
- `api/server.py` lines 430 to 460: priority auto-score weights.
- No hardcoded lane list exists anywhere, because lanes do not exist yet. Personas are enumerated from YAML, which is the pattern the loader follows.

## Auth, secrets and config

- `.env` at the repo root, loaded by `src/resume_gen/config.py` into a `Settings` dataclass. Docker loads the same file via `env_file`.
- Outbound HTTP is `httpx` called inline in route handlers. n8n webhooks: `N8N_WEBHOOK_URL`, `N8N_BULK_HR_WEBHOOK_URL`, `N8N_JOBS_WEBHOOK_URL`, `N8N_FOLLOWUP_WEBHOOK_URL`. A production/test URL switch exists (`_n8n_url`). Sends require a structured JSON acknowledgement carrying the request id back (`_n8n_ack`), which is a good pattern to keep for outreach.
- No inbound auth on the API. No shared-secret header anywhere. No queue, scheduler or job runner. Generation runs synchronously inside the request.
- `SMTP_*` variables exist for an abandoned direct-send path (`automation/email_sender.py`, 53 lines, unused by the API).

## Test setup

- `tests/` has three unittest files (8 tests). All pass with `python -m unittest discover -s tests`. pytest is not installed in `.venv`; new tests stay unittest-compatible so both runners work.
- No CI configuration in the repo.

## Dead weight to route around

- `automation/email_sender.py` (SMTP direct send) and `automation/apply.py` (Selenium form-fill): superseded by n8n and by the Playwright/MCP apply path. Left untouched.
- `data/intake/queue/*.json` and `data/intake/seen.json`: legacy JSON store already migrated into SQLite, kept only for the one-time backfill.
- `data/companies/td.json`, `data/repeatable/`: same.
- `docs/REBUILD_MASTER_PROMPT.md`, `tools/generate_project_overview.py`, `resume-studio-mobile.png`: documentation artefacts, not code paths.
- `.pw-profile/`, `.playwright-mcp/`, `tmp/`, `data/job-applications/outbox/`: transient browser and apply artefacts, gitignored.
- `docs/architecture.md` still describes a separate `Resume_Scraper` collector on port 8765 and a `Phase 3 Auto-apply (in progress)`. The collector is not in this repo.

## Conflicts between the brief and the app

1. **Node scripts.** The app is Python. `npm run validate:data` and `npm run sync:lanes` are provided by a small `package.json` that shells to `python -m resume_gen.lanes ...`. Same names, no Node dependency.
2. **Skill grounding has two authorities.** Today the truth-guard grounds skills against `master_profile.yaml`. The brief makes the lane matrices the authority on what can be claimed. Resolution: both must agree. A skill reaches a document only if the lane status is `held` or `partial` AND it is in the profile inventory or the lane's own held list. Held matrix skills are added to the profile-derived grounding set so a confirmed `held` skill that is missing from the YAML inventory is not stripped, and a `building` or `not_yet` lane skill is stripped even if the YAML lists it.
3. **File naming.** The brief asks for `kk_[Company]_[Role].docx` and `_CL.docx`. The stored `document_files` map on every existing run uses the old names. New runs use the new names; old runs keep theirs.
4. **Cover letter length.** The brief's four-paragraph structure replaces the current "under 180 words, 2 to 3 paragraphs" prompt.
5. **Import contract.** The existing `/jobs/import` is a flexible aliased importer used by the Bulk tab. It stays. The three-file batch import is a new endpoint with the exact ten-column contract, so the two do not fight.
6. **`priority` column.** The brief's CSV always says `HIGH`; the app already has a manual `priority_override` and an auto score. The imported value is stored as `priority_tag` and does not overwrite the user's pin.
7. **Portfolio links.** The brief lists four surfaces. Today every resume carries the same three links. Links now come from the lane's `links` list in `lanes.index.json` (technical lanes: dev.kkvasan.ca and GitHub; business lanes 6 to 8: k2digitalmedia.ca; video, VFX and design: film.kkvasan.ca and k2digitalmedia.ca). LinkedIn is always included.

## Decisions taken without asking (the user is not present)

- Lane loader runs at API startup and fails the boot on a malformed file. The CLI and tests use the same loader lazily.
- `partial` limits are parsed out of the markdown Evidence column: the sentences that carry a negation ("Not against a formal test plan") become the `limit`; when no such sentence exists the whole evidence text is the limit.
- Aliases and sourcing keywords live in the source markdown under `## Aliases` and `## Sourcing vocabulary` headings, so the markdown stays the single thing Keerthi edits. The converter reads both.
- The social-content lane (8) links to k2digitalmedia.ca, because that is the business site the social work is sold through. Video, VFX and design link to film.kkvasan.ca first. Flip the lists in `lanes.index.json` if that is wrong.
- Outreach dispatch and callback use one shared secret, `OUTREACH_SHARED_SECRET`, in the `X-Outreach-Secret` header both directions.
- Attachments to n8n stay inline base64 (the existing pattern), not signed URLs, because the app has no public URL. The payload field is named `content_base64` alongside `filename` and `sha256`.

## Phased plan and effort

| Phase | Work | Estimate |
|---|---|---|
| 1 | 12 lane JSON files, index, profile.json, noc.json, answer-bank.json, outreach-templates.json, loader, validator, converter, tests | 1 day |
| 2 | Tag grammar parser, three-file batch importer, dedupe, report, endpoint, CLI, UI uploader, tests | 1 day |
| 3 | Requirement extraction, tiering, gap flags, evidence-traced fit sentence, seniority guard, job list badges, tests | 1 day |
| 4 | Lane-aware persona selection, status guard in the pipeline, cover letter structure, colour, dates, naming, per-lane links, game-dev and VFX personas, tests | 1 day |
| 5 | Outreach tables, templates, guardrails, approval screen, dispatch, callback, audit, n8n workflows, test guide, tests | 2 days |
| 6 | Ledger view and dashboard | 0.5 day |
| 7 | Versioning, drift check, CHANGELOG backfill, migrations, README | 0.5 day |
