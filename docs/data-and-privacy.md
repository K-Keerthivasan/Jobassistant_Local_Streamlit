# Data & privacy

This app is **single-user per install**: you run your own copy, and all of your
data stays on your machine (and inside your own Docker volume). There are no
accounts, no multi-tenant server, and nothing is sent anywhere except to the AI
engines you configure (local [Ollama](https://ollama.com) by default).

## Your personal data is never committed

The repo ships only `*.sample.*` **templates**. Your real data lives in gitignored
files that you create from those templates (or, soon, via `python -m resume_gen init`):

| You create | From template | Holds | Required |
|---|---|---|---|
| `data/profile/master_profile.yaml` | `master_profile.sample.yaml` | identity, contact, experience, skills | **yes** |
| `data/apply_profile.json` | `apply_profile.sample.json` | autofill answers (email, phone, screening) | no |
| `data/profile/personas.yaml` | `personas.sample.yaml` | role framings | no |
| `data/repeat_companies.json` | `repeat_companies.sample.json` | repeat companies + sectors | no |
| `data/sources.yaml` | `sources.sample.yaml` | scraper sources + filters | no |

Everything in the table is listed in [`.gitignore`](../.gitignore), so a
`git add .` will never stage your personal data. Only the master profile is
mandatory — every other loader degrades gracefully (empty defaults) if its file is
absent, so the app runs as soon as you have a master profile.

## Where the rest lives

- **`data/resume.db`** (SQLite, gitignored) — the job queue, dedup set, repeatable
  roles, saved company details, and every generated application. This is the single
  source of truth for everything you generate. See [`storage.md`](storage.md).
- **`data/companies/`** — legacy per-company JSON (now DB-backed); gitignored except
  `.gitkeep`.
- **`output/`** — empty. Generation writes nothing to disk; PDFs/DOCX render on
  demand at download and are discarded. Only `.gitkeep` is tracked.
- **`.env`** (gitignored) — your engine/host config and any tokens (`APIFY_TOKEN`,
  `HERMES_API_KEY`, `N8N_WEBHOOK_URL`). See [`configuration`](setup.md#environment-variables-env).

## Where your data goes at generation time

Job text + your profile facts are sent to the **AI engine you configured**:
- Default: **local Ollama** on your own machine — nothing leaves your computer.
- Optional: the **Hermes** local agent gateway (also yours).
- If you point an engine at a hosted API, your data goes there — that's your choice
  via `.env`. Out of the box, generation is fully local.

## Back up / move your data

Everything you care about is two paths:

```powershell
# Back up the database (jobs, runs, repeatable roles, company memory)
copy data\resume.db  backups\resume.db

# Back up your editable config
copy data\profile\master_profile.yaml  backups\
copy data\apply_profile.json           backups\
copy data\profile\personas.yaml        backups\
copy data\repeat_companies.json        backups\
copy data\sources.yaml                 backups\
```

To move to a new machine, copy `data/` across and `docker compose ... up -d --build`.

## Reset

```powershell
# Wipe generated/queue state but keep your profile/config
del data\resume.db data\resume.db-wal data\resume.db-shm

# Full reset to a clean install: delete data\resume.db and your created files above,
# then re-copy from the *.sample.* templates.
```

The DB is recreated empty on next start; your `*.yaml` / `*.json` config is reloaded
as-is.
