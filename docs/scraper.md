# Scraper & Intake

Two cooperating pieces: a **collector** (the scraped-jobs store + dashboard) and
the generator's **intake** (pulls jobs from sources into a review queue).

## Collector (`Resume_Scraper`, port 8765)

A small stdlib HTTP app that the Tampermonkey userscript posts to.

- Store: `job_data/jobs_YYYY-MM-DD.csv` + `job_index.json` (dedup) + `blacklist.json`.
- Dashboard at `/` — search, filters, sortable table, details drawer, status/applied/
  flag, blacklist, CSV export. Restyled to match the Resume Studio theme and
  theme-synced via `?theme=light|dark`.
- API: `GET /api/jobs`, `POST /api/jobs` (save), `POST /api/jobs/update`,
  `POST /api/jobs/delete`, `GET/POST /api/blacklist*`, `GET /health`.

Resume Studio's **Scraper** tab embeds this dashboard in an iframe, and adds:
- **Add manually** — a modal that POSTs to the collector (so it shows in the
  dashboard like a capture).
- **Fetch new jobs** — runs `POST /intake/run`.
- **Generate from queue** — loads queued jobs into Bulk.

## Userscript (LinkedIn + Indeed)

`tampermonkey/tampermonkey.user.js` (`@version 1.1`).

- Matches `*.linkedin.com/jobs/*` and `*.indeed.com/*`.
- Scrapes title/company/location/description/skills/contact-emails via per-site
  selectors + JSON-LD `JobPosting` fallback.
- Detects the **apply channel**: if an email or "send your resume" language is
  present → `email`, else `platform`. Email-apply jobs are the auto-apply target.
- **Save Job** / `Alt+Shift+S` → POST to `127.0.0.1:8765/api/jobs`. Duplicates
  prompt before saving a second entry.
- Also auto-fills common application fields from `MY_INFO` (set your real values).

To add another site: add an entry to `SITE_CONFIG` (selectors + `hostPattern` +
`jobPathPattern`) and a matching `@match`/`@connect` line.

## Intake (`src/resume_gen/intake/`)

`run_intake()` reads `data/sources.yaml` (falls back to `sources.sample.yaml`),
fetches every source, filters, dedups, and queues new postings.

### Sources (`sources.yaml`)

| `type` | Pulls from |
|--------|-----------|
| `collector` | Your collector `/api/jobs` (browser-saved jobs). Base defaults to `host.docker.internal:8765`. |
| `apify` | An Apify actor run (Indeed/LinkedIn/etc.) or an existing dataset. Needs `APIFY_TOKEN`. |
| `greenhouse` / `lever` / `workday` | ATS JSON APIs. |
| `generic` | Best-effort HTML scrape of a careers page. |

### Filters

```yaml
filters:
  title_keywords: ["developer", "engineer", ...]   # keep titles containing one
  require_email: false                              # keep only jobs with a contact email
  canada_only: true                                 # keep Canadian postings only
  keep_unknown_location: true                       # keep blank/"remote" (false = strict)
  location_keywords: []                             # optional substring allow-list
```

**Canada filter:** `_in_canada()` matches "Canada", province names/codes (whole-word,
so California's "CA" does **not** match), and major metros. Applies to *all* sources.
It only affects **new** commits — it does not retroactively purge an existing queue.

### Queue

- `data/intake/seen.json` — keys already processed (dedup across runs).
- `data/intake/queue/<key>.json` — one `QueuedJob` (status: `new` → `generated` →
  `approved` → `sent`/`applied`/`skipped`).
- Surfaced via `GET /jobs?status=new`; generate with `POST /jobs/{key}/generate`.

## Reset to a clean slate

```python
# collector: delete job_data/jobs_*.csv and reset job_index.json (keep blacklist.json)
# intake:    delete data/intake/queue/*.json and reset data/intake/seen.json to []
```
