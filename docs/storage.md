# Storage: SQLite

Accumulating intake data lives in a single embedded SQLite database at
`data/resume.db` (override with `DB_PATH`). SQLite needs no install or server —
the app uses Python's stdlib `sqlite3`. The file sits under `data/`, which is
mounted into the container, so it persists across rebuilds. It's gitignored.

## What's in the DB

| Table | Replaces | Written by |
|-------|----------|-----------|
| `jobs` | `data/intake/queue/*.json` | `intake/store.py` |
| `seen` | `data/intake/seen.json` | `intake/store.py` |
| `repeatable_roles` | `data/repeatable/*.json` | `intake/repeatable.py` |
| `companies` | `data/companies/*.json` | `intake/companies.py` |
| `runs` | `output/<run>/` folders (resume/cover/email/qa) | `pipeline.run` → `intake/runs.py` |

Each record is stored as its full JSON in a `data` column, with a few columns
duplicated out (`status`, `applied`, `found_at`, `key`, …) for indexing/sorting.
Readers reconstruct the pydantic models from `data`, so the models can evolve
without a schema migration.

## Generation writes nothing to disk

`pipeline.run` no longer creates `output/<run>/` folders or renders any files. It
stores the whole application (validated resume + cover-letter + email JSON, QA
report, target) as one row in `runs` and returns it. PDFs and DOCX are rendered
**on demand only when you download them** (`render/ondemand.py`), into a temp dir
that is deleted right after streaming — nothing is persisted as output.

Download routes (served by `api/server.py`):

- `GET /download/{run_id}/{artifact}` — `artifact` ∈ `resume.pdf`, `resume.docx`,
  `cover.pdf`, `cover.docx`, `resume.json`, `cover_letter.json`, `qa_report.json`,
  `target_role.json`, `email.txt`. JSON/email come straight from the row; PDF/DOCX
  are rendered fresh.
- `GET /jobs/{key_id}/download` — one queued job as JSON. `GET /jobs/export` — the
  whole queue as JSON.
- `GET /outputs` lists runs from the DB; `GET /run?folder=<run_id>` previews one
  and returns a `files` map of download URLs; `DELETE /run?folder=<run_id>` removes it.

Legacy `output/<run>/` folders from before this change are imported into `runs` on
first start (and stay on disk, harmless).

## What stays as files (your personal config)

These are **per-user** and **gitignored** — create each from its `*.sample.*`
template (see [`data-and-privacy.md`](data-and-privacy.md)):

- `data/profile/master_profile.yaml` — your master profile (required).
- `data/profile/personas.yaml` — role framings (optional).
- `data/apply_profile.json`, `data/repeat_companies.json` — autofill answers + repeat companies.
- `data/sources.yaml` — scraper source list.
- `data/usage.json` — token/usage counters (regenerated automatically).

(Generated applications are **not** files anymore — they live in the `runs` table
and are rendered to PDF/DOCX only at download time.)

## Migration (automatic, one-time, idempotent)

On startup (`@app.on_event("startup")` → `db._ensure_init()`) the app creates the
schema and backfills any **empty** table from the legacy JSON files. It only fills
tables with zero rows, so it never duplicates or clobbers DB-native data, and the
original JSON files are left untouched. Force a re-import with
`python -c "import sys; sys.path.insert(0,'src'); from resume_gen.intake import db; print(db.migrate_json(force=True))"`.

## Inspecting

The DB is one file; open it with any SQLite tool (optional):

```bash
sqlite3 data/resume.db "SELECT status, COUNT(*) FROM jobs GROUP BY status;"
```

## Concurrency

WAL mode + a busy timeout; one short-lived connection per operation (thread-safe
under FastAPI's threadpool).
