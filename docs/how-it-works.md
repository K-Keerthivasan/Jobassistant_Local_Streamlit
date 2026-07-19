# How it works (end to end)

A walkthrough of the whole system — what happens from "find a job" to "application
ready" — and how the parts fit together. For per-subsystem detail see
[architecture](architecture.md), [scraper](scraper.md), [personas](personas.md),
[auto-apply](auto-apply.md), and the [API reference](api.md).

## The big picture

```
  SOURCES                INTAKE                  REVIEW + GENERATE            APPLY
  ───────                ──────                  ─────────────────            ─────
  Tampermonkey ─┐
  (LinkedIn/     │   POST /intake/run        ┌─ ungenerated → Generate ─┐   has email →
   Indeed) ──────┤→  fetch → apply filters →  │   (persona + truth-guard) │   📧 n8n sends
  Job Bank RSS ──┤   → dedup → review queue  └─ generated → Preview ─────┘   the email
  Greenhouse/    │        (data/intake/queue)        ↓                       (review gate)
  Lever/Workday ─┤                              output/<folder>/            no email →
  Apify ─────────┘                              resume + cover + email      Playwright
  Manual add ────┘                              .docx / .pdf / .json        autofill, you
                                                      ↓                      submit
                                                  the "Jobs" tab
```

Three apps cooperate (all local):

- **Resume Studio** (`:8088`) — the web app + generation engine + APIs.
- **Collector** (`:8765`) — the scraped-jobs dashboard the Tampermonkey userscript
  feeds.
- **Ollama** (`:11434`, host) — the local LLM that writes the drafts.

(Plus **n8n** for the email-apply path and **Playwright** on your host for portal
autofill.) They live on separate Docker networks, so they reach each other through
the host gateway (`host.docker.internal`), never `localhost`.

## Stage 1 — Sources find jobs

Jobs come from several places, all normalized to the same shape:

- **Tampermonkey userscript** (LinkedIn + Indeed) → saves to the **collector**.
- **Job Bank RSS** (`type: rss`), **Greenhouse / Lever / Workday**, **Apify**, and
  **manual add** → pulled by intake.

You configure these in `data/sources.yaml`. Filters there keep it relevant:
`title_keywords`, `location_keywords`, and `require_email`.

## Stage 2 — Intake builds the queue

`POST /intake/run` (the **🔄 Fetch new jobs** button) fetches every source, applies
the filters, de-duplicates against what you've seen, and writes new postings to the
**review queue** (`data/intake/queue/*.json`). Each job carries: title, company,
location, source, date, a contact email if found, and a `repeat` flag if the company
is on your repeat list.

## Stage 3 — The Jobs tab (one place for everything)

The **Jobs** tab is the hub — a sortable, filterable table of *every* job and every
generated application together:

- **Filters**: search, status, source, **📧 has-email / no-email**, **applied**, and
  a date filter defaulting to *this month*.
- **Ungenerated** rows show **Generate** (one-click) and a checkbox for **bulk
  generate**.
- **Generated** rows show **Preview** (the docs + truth-guard report), **Regenerate**,
  **🗑 Delete**, an **Applied** checkbox, and — for email-apply jobs — **📧 n8n**.

## Stage 4 — Generation (truthful, tailored)

When you generate, for each job:

1. **Persona** is auto-picked from the title/description (Sales, Software,
   Full-Stack, Marketing, …) — or you override it in the sidebar. It reframes your
   *one true history* for the role.
2. **Ollama** drafts a resume, cover letter, and outreach email from your
   `master_profile.yaml` + the persona framing.
3. The **truth-guard** then deterministically repairs the draft (this is the core
   promise — it never ships a lie):
   - identity, education, links, and **role titles** forced from your profile;
   - **skills** filtered to real ones, grouped by category, backfilled if thin;
   - **bullets** must connect to that role's real facts — fabricated ones are
     dropped, and thin roles are topped up from your profile facts;
   - invented **years/metrics/team-sizes** stripped from headline, summary, bullets,
     **and the cover letter** (whose contact line is rebuilt from your profile);
   - **location** shows your city only for local jobs, otherwise the broader location from your profile.
4. Files are written to `output/<Company>_<Title>_<date>/` (DOCX + PDF + JSON), and a
   `qa_report.json` lists everything that was changed/flagged.

## Stage 5 — Apply (two paths, both with a human gate)

- **Has a contact email** (many Job Bank/HR postings) → **📧 n8n**: the generated
  package (resume + cover + email, base64) is POSTed to your n8n webhook, which sends
  the email. The job is marked applied/sent.
- **No email / company portal** (TD, repeat companies, ATS pages) → the **Playwright
  assistant** opens the portal in a real browser, fills your repeated fields, uploads
  the resume/cover, answers common screening questions, screenshots, and **stops at
  the review page** — you read it and click Submit.

Nothing is sent or submitted without you. That's the safety model: automate the
repetitive typing, keep the human in the loop for the final click.

## Where your data lives

| What | File |
|------|------|
| Truth source (the only facts allowed) | `data/profile/master_profile.yaml` |
| Role framings | `data/profile/personas.yaml` |
| Job sources + filters | `data/sources.yaml` |
| Review queue + dedup | `data/intake/queue/`, `data/intake/seen.json` |
| Generated applications | `output/<folder>/` |
| Autofill answers | `data/apply_profile.json` |
| Repeat companies + saved company details | `data/repeat_companies.json`, `data/companies/` |

## A typical session

1. Save a few jobs in the browser (Tampermonkey) and/or hit **🔄 Fetch new jobs**.
2. Open **Jobs**, filter to *this month* / your status, eyeball the list.
3. Select rows → **⚡ Generate selected** (or one-click **Generate** per row).
4. **Preview** a result; check the truth-guard report; tweak your profile if needed.
5. Apply: **📧 n8n** for email jobs, or run the **Playwright** assistant for portals —
   review, then submit yourself.
6. Tick **Applied**.
