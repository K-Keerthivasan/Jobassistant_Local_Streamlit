# Changelog / Patches

Newest first. Dates are work dates.

## 2026-06-12 — Repeatable roles + email intake, Q&A tool, date filters

- **🔁 Repeatable roles** ([docs/repeatable.md](repeatable.md)) — for companies you reapply
  to (TD, RBC…). Flag a job 🔁 in **Jobs** (`POST /jobs/{key}/repeatable`) to save a
  per-role template keyed by company+title (`data/repeatable/<slug>.json`, `RepeatableRole`).
  The new **Repeatable** tab lists them with applied-count + last date; **⟳ Regenerate**
  (`POST /repeatable/{key}/generate`) builds a freshly tuned resume/cover/email from the
  saved JD, bumps the count, and gives download links. **✎ Edit JD** to paste a refreshed
  posting (`POST /repeatable/{key}/update`).
- **📩 Email intake** — paste a job-alert email (or n8n Gmail → `POST /jobs/from-email`):
  Claude/Ollama extracts company/title/description (`extract_job_from_email`, `JobExtract`,
  `EMAIL_PARSE_SYSTEM`), queues it (source `email`), and refreshes the matching repeatable
  template when the same role comes round again.
- **💬 Q&A tool** — answer screening questions ("Why do you want to join?") grounded in
  your profile, or rephrase your own draft. `POST /answer`, short + de-AI'd output
  (`humanize_answer` strips dashes / AI-tells).
- **Date filters** — Jobs + job picker gained **Today / Last 2 days / Last 3 days**;
  `inRange` now counts calendar days. **Jobs auto-syncs the collector** on open
  (`POST /intake/run?source_type=collector`).

## 2026-06-11 (later 19) — bulk-jobs prompt, email editing, monthly Library

- **[docs/claude-bulk-jobs-prompt.md](claude-bulk-jobs-prompt.md)**: a copy-paste prompt
  for Claude.ai (with the Indeed/LinkedIn connector) to bulk-pull jobs and output a CSV
  whose columns import directly here (RSS Scraping → ⬆ Upload CSV).
- **Inline email edit** on every job row (**✉ add / ✉ edit**) → `POST /jobs/{key}/update`
  — for Job Bank etc. where the HR email is hidden; once set, the 📧 n8n path lights up.
- **Library folds into monthly groups** (newest month first) with month headers; within
  a month, sort by **Newest / Company / Type (persona)**. Persona is now persisted on
  each output (`persona_label` in target_role.json → `/outputs`) and shown as a card tag.

## 2026-06-11 (later 18) — Claude Scraping, engine-by-priority, usage monitor

UI/architecture rework separating *finding jobs* from *generating*:
- **RSS Scraping** (renamed from Automatic Scrape) — the source-driven scrape.
- **🤖 Claude Scraping** (new tab) — `POST /scrape/claude` → `anthropic_client.find_jobs`
  uses Claude + the **web_search** tool to pull real, current jobs and queue them
  (source `claude`, curated → no keyword/Canada filter). Needs `ANTHROPIC_API_KEY`.
- **Engine selector** (sidebar): **Auto** (⭐ priority → Claude, else local), or pick a
  specific local/Claude model. `resolveModel(priority)` drives Generate, Bulk, and
  per-job generation; per-job **⭐ priority** toggle (`POST /jobs/{key}/priority`,
  `QueuedJob.priority`).
- **Cloud usage monitor**: `usage.py` records Anthropic tokens + estimated $ per call;
  `GET /usage`; sidebar shows `☁ $… · N calls`, refreshed after each generation.

## 2026-06-11 (later 17) — Claude cloud engine + scraper-filter fix

- **Claude generation engine**: pick a Claude model from the sidebar **Model**
  picker (grouped "☁ Claude (cloud)") to generate via the Anthropic API instead of
  local Ollama — much higher quality than qwen3:8b. `llm/anthropic_client.py` uses
  `messages.parse()` for schema-validated output (Opus 4.8 default; Sonnet 4.6 /
  Haiku 4.5 also offered). `llm.chat_structured` routes by model id (`claude-*` →
  Anthropic, else Ollama). Set **`ANTHROPIC_API_KEY`** in `.env` to enable; the
  truth-guard still runs on the output. (`anthropic` SDK added to requirements.)
- **Scraper fix**: jobs from **curated sources** (collector / manual / CSV) now
  bypass the title-keyword **and** Canada filters — you saved/entered them on
  purpose, so they always appear in the queue (previously a saved "Executive
  Assistant" was dropped by the dev-keyword filter). Reminder: collector jobs reach
  the app only after **🔄 Fetch new jobs**.

## 2026-06-11 (later 17) — n8n email workflow

- Added an **importable n8n workflow** `n8n/resume-apply.workflow.json`
  (Webhook → Build attachments → IF has-email → Send Gmail → optional Sheet log) that
  receives the `📧 n8n` POST and emails the contact with resume + cover attached.
  Setup steps in [auto-apply.md](auto-apply.md). Completes the email-apply loop.

## 2026-06-11 (later 16) — details, email edit, company sort, CSV import

- **Library**: sort by **Newest** or **Company** (groups same-company entries), and a
  **dup ×N** badge + count for duplicate company/title generations.
- **Jobs**: click a job **title** → detail modal (source/status/date/applied, portal
  link, full description) with an **editable HR email** (Save → `POST /jobs/{key}/update`,
  store.update_fields) and Generate/Preview actions. Editing in an email enables the
  📧 n8n path.
- **CSV import** (Automatic Scrape → **⬆ Upload CSV**): `POST /jobs/import` parses CSV
  (flexible columns: company/title/location/description/contact_email/apply_url/…) →
  queue. For data collected via n8n. Verified: 2-row CSV → 2 jobs with emails.

## 2026-06-11 (later 15)

- Renamed the **Scrape** tab to **Automatic Scrape**.
- It now shows a **Scraped jobs** section (grouped by source with counts + 📧/🔁
  markers), refreshed on open and after Fetch — so you see what each source pulled
  without leaving the tab.

## 2026-06-11 (later 14) — Job Bank scraper

Job Bank's RSS is dead (returns 0 items even with a live session). Built a proper
**`type: jobbank`** source instead (`fetch_jobbank` in sources.py): scrapes the
search results (`a.resultJobItem` → title/company/location/date/posting URL) and
pulls each posting's clean description from `[property='description']` (+
`.job-posting-brief`). Params: `search`, `location`, `limit`, `detail`. Addable from
**⚙️ Setup → Add source → Job Bank (Canada)** (keyword + optional location);
`POST /sources/add` extended. Verified live: a "software developer / Ontario" source
pulled ~25 real postings through intake. (Working RSS test feeds: WeWorkRemotely,
RemoteOK.)

## 2026-06-11 (later 13) — split nav: Scrape / Jobs / Library

Restructured the app into 5 tabs: **Generate · Scrape · Jobs · Bulk Generate ·
Library** (un-merged Jobs+Library per user).
- **Scrape** (new): source management (add/remove, incl. RSS), Fetch new jobs, manual
  add, browser-capture link, and the setup info (filters/repeat/companies/apply-profile).
- **Jobs**: now the queue list only (generated apps live in Library); filters + sort +
  generate + apply actions; manual-add lands here.
- **Library** (restored): card grid of all generated outputs, search + date filter +
  delete + preview.

## 2026-06-11 (later 12) — manage job sources from the UI

- **⚙️ Setup panel** now has an **Add source** form (RSS/Job Bank, Greenhouse, Lever,
  Workday, Generic) and a ✕ to remove each source. Endpoints: `POST /sources/add`,
  `DELETE /sources/{index}`. (Editing rewrites `data/sources.yaml`, dropping comments.)
- So the RSS flow is now fully in-UI: **⚙️ Setup → Add source → RSS → paste the Job
  Bank RSS URL → 🔄 Fetch new jobs** → items appear in Jobs (source `rss`) → Generate.

## 2026-06-11 (later 11) — surface apply features in the UI

The Jobs tab now exposes everything the backend gained:
- **🔁 Repeat badge** on repeat-company rows + a **Repeat only** filter.
- **Open ↗** (apply portal) and **⌨ Autofill** (copies the Playwright command to run
  on your host) on jobs with an apply URL.
- **⚙️ Setup panel** (was "Sources") now shows: configured sources + filters, the
  repeat-company list, saved company details, and the apply-profile summary.
- Capture-dashboard link relabeled **Capture ↗**; subtitle documents the icons.

## 2026-06-11 (later 10) — docs

- Added [`docs/how-it-works.md`](how-it-works.md): the whole flow end to end
  (sources → intake → Jobs tab → generation/truth-guard → the two apply paths).
  Linked from the README as the starting point.

## 2026-06-11 (later 9) — semi-auto apply foundation

Safe "fill the repetitive fields, stop before submit" system (see
[auto-apply.md](auto-apply.md)):
- **`data/apply_profile.json`** (autofill answers) + `GET /apply-profile`.
- **`data/repeat_companies.json`** (TD/RBC/…); `GET /jobs` now adds a `repeat` flag.
- **Company memory** `data/companies/<slug>.json` + `GET/POST /companies/{company}` —
  reuse details when the same company posts again.
- **Job Bank / RSS intake**: `type: rss` source (stdlib XML, no new dep); parsed 25
  items from a live feed in testing.
- **Playwright autofill** `automation/playwright_apply.py`: headed, persistent profile
  (saved logins), per-ATS templates (Workday/Greenhouse/Lever/generic), fills common
  fields + uploads resume/cover + answers common screening Qs, screenshots, **stops
  before submit**. Runs on the host (not the headless API container).
- Email-apply RSS jobs flow into the existing `📧 n8n` send path.

## 2026-06-11 (later 8) — polish: font, skills, location

- **Font → Lato** (clean, modern, ATS-safe). Installed `fonts-lato` + `fonts-ebgaramond`
  in the PDF image (the container had no Calibri, so it was being substituted).
- **Grouped skills**: the Skills section is now categorized — `Languages: …`,
  `Backend & Cloud: …`, `Marketing: …`, etc. (mapped from the master-profile skill
  groups, preserving relevance order; leftovers under `Other`). `render_resume` now
  takes the profile.
- **Adaptive location**: the precise home city (London) shows only for local jobs;
  for jobs elsewhere/remote it shows `contact.location_general` ("Ontario, Canada") so
  applying out of town doesn't surface "London". New `location_general` profile field;
  threaded via `enforce(..., target_location=)` and the cover-letter contact line.

## 2026-06-11 (later 7) — cover letter / email truth fixes

The cover letter came out with a **fabricated identity** ("Amit Patel | amit.patel@
email.com | (416)...") and invented claims (8 years, "team of 12", "10M+ events/day",
Kafka/AWS/Kubernetes). The cover-letter guard only patched the name. Now:
- **Contact line is ALWAYS rebuilt from the profile** (name | location | email | phone
  | links) — kills wholesale fake identities `_fix_name_in_text` couldn't catch.
- **Body + email**: strip invented "N years", team sizes, big counts (10M+, 500k),
  percentages; fix the name. Surfaced in QA (`qa.cover_letter`, `qa.email`).
- **Cover-letter temperature 0.7 → 0.35** (0.7 was inventing freely); prompt got hard
  bans (years/team-sizes/counts/tools-not-in-profile, real name/contact).
- `_strip_metrics` now also drops suffixed figures (10M+, 500k, 2.5B).
- KNOWN LIMIT: for roles far from the real profile (e.g. SRE/infra), an 8B model still
  invents domain tools (Terraform/Ansible/Kubernetes) in prose that can't be cleanly
  stripped without garbling — QA flags that something was scrubbed; review recommended.

## 2026-06-11 (later 6) — truth-guard hardening (fabrication fix)

A generated resume came out as "straight up farce" (8+ years AI/ML, invented
companies "CloudScale Solutions", inflated "Senior Software Engineer", 500k+ users,
"Published two papers", PyTorch/AWS/Hadoop none of which are real). The guard only
*flagged*, never removed. Now (in **strict** mode):
- **Headline + summary**: strip invented "N years of experience" claims and any
  metric not in the profile.
- **Role titles forced verbatim** from the profile (no "Associate Developer" →
  "Senior Software Engineer" inflation).
- **Fabricated jobs dropped**: a generated experience entry that matches no profile
  role is removed.
- **Bullets grounded per role**: a bullet must share a real content word with THAT
  role's facts, else it's dropped (kills misattribution + invented achievements);
  bullets naming a dropped/ungrounded skill are removed.
- **Fallbacks**: if a real role's bullets were all dropped, use its profile facts; if
  ALL experience was fabricated, rebuild the whole section from the profile's real
  roles. So the resume is always truthful, never empty.
- Prompt strengthened (explicit bans on years/team-sizes/publications/tools/inflated
  titles); default temperature 0.3 → **0.2**.
- Bugfix: the expanded `_COUNT_NOUNS` had an unbalanced paren that 500'd every
  generation — fixed.
- **Delete** button added to generated rows in the Jobs view (deletes the output and
  resets the job to `new`).
- **Fullness fix**: the new grounding was making resumes too short. Thin roles are now
  topped up from their truthful profile `facts` (front roles → 5 bullets, others → 3),
  so it stays a full two pages without fabrication.

## 2026-06-11 (later 5)

- **Generate ▸ "📋 From a job"**: a picker in the Generate view loads any job from
  the list (searchable) straight into Company/Title/Location/Description — no more
  copy-pasting a posting by hand.

## 2026-06-11 (later 4)

- **Applied flag**: `QueuedJob.applied` (bool) + `POST /jobs/{key}/applied`. The
  Jobs list has an **Applied** checkbox column and an Applied: all/yes/no filter.
- **Email filter**: Jobs list channel filter — All / 📧 Has email / No email.
- **Email-apply → n8n**: `N8N_WEBHOOK_URL` (.env + compose). `POST /jobs/{key}/send-n8n`
  posts the generated package (company/title/contact_email + email subject/body +
  base64 resume & cover-letter PDFs) to the n8n webhook, then marks the job
  applied + sent. A **📧 n8n** button shows on generated email-apply rows. Jobs
  without an email are left for the separate auto-apply tool (later).

## 2026-06-11 (later 3)

- **Jobs + Library merged** into one **Jobs** view (Library tab removed). The list
  is the union of the review queue + generated outputs: ungenerated rows show
  **Generate** (+ checkbox for bulk), generated rows show **Preview** (modal with
  downloads) + **Regenerate**. Generated queue jobs are matched to their output
  folder; generated apps with no queue job (e.g. from the Generate tab) appear as
  `source: direct`. One date filter + column sort for everything.
- **Date filter defaults to "This month"** (since the 1st); also Last 7 / 30 / 90
  days / All time. Sort defaults to Date desc.
- Saved view `library` now maps to Jobs on load.

## 2026-06-11 (later 2)

- **Browser caching was hiding updates.** Added a `Cache-Control: no-store`
  middleware (and `cache:'no-store'` on client fetches). The browser was serving a
  stale `index.html` (old UI, no date filters) and stale `/outputs`//`jobs` (Library/
  Jobs "not updating"). One hard refresh clears the old page; it stays fresh after.
- **Active tab persists across refresh** (`localStorage 'view'`) — no more jumping
  back to Generate.
- **Jobs default filter = All statuses** so a job stays visible (as "generated")
  after you generate it, instead of vanishing from a "new"-only view.

## 2026-06-11 (later)

### Jobs tab = native list (replaced the embedded dashboard)
- The **Jobs** tab is now a native, sortable/filterable list of the review queue:
  search, filter by status / source / scraped-date, sortable columns, a **Source**
  column, per-row **one-click Generate**, multi-select **Bulk generate**, **Fetch
  new jobs**, a **Sources** panel (`GET /sources`, read from `sources.yaml`), and a
  **Dashboard ↗** button to the collector. Manual-add writes to the queue so it
  appears immediately. (The embedded-iframe dashboard from earlier was removed.)
- **Library**: added a generated-date filter (Today / 3 / 7 / 30 days).

### Bug fixes
- **Generate-from-a-job was broken**: `POST /jobs/{key}/generate` required
  `company/title/description` in the body (it extended `TargetRole`). Split out
  `GenerateOptions` (options-only) for that endpoint. This was the root cause of
  "bulk generate not working / nothing showing in Library".
- **Persona auto-detect**: engineering roles (SRE, DevOps, backend, infra) were
  landing on **Digital Marketing**. Added engineering/SRE/DevOps keywords to the
  software persona and trimmed marketing's over-generic keywords. Verified SRE/
  backend → software, marketing → marketing, sales → sales.

## 2026-06-11

### Scraper UI = embedded dashboard
- Resume Studio's **Scraper** tab now embeds the collector dashboard (`:8765`) in
  an iframe (pixel-identical to the standalone dashboard), instead of a custom view.
- Toolbar glue added: **Add manually** (modal → writes to the collector so it shows
  in the dashboard), **Fetch new jobs** (`POST /intake/run`), **Generate from queue**
  (loads queued jobs into Bulk), Reload, Open↗.
- Collector URL tracks the app host (`location.hostname:8765`) — Tailscale-friendly.

### Dashboard restyled to the app theme
- `Resume_Scraper/Scraper.py` `DASHBOARD_HTML` re-themed to the Resume Studio
  palette (blue accent, sans-serif, subtle shadows, 12px radius); bespoke
  glows/gradients/serif flattened. Light + dark via `data-theme`.
- Dashboard reads `?theme=light|dark`; the app passes its current theme into the
  iframe and reloads it when you toggle theme.

### Userscript: LinkedIn + Indeed
- `tampermonkey/tampermonkey.user.js` v1.1 — replaced CareerBeacon with **Indeed**
  (`*.indeed.com/*`, viewjob + search-panel selectors, smartapply auto-fill).

### Resume quality fixes
- **Skills always render**: truth-guard backfills from the profile (persona-ordered)
  when the model returns < 6 grounded skills.
- **Relevant skills for non-tech roles**: added truthful `marketing`,
  `sales_service`, `creative_media`, `office_admin` skill groups to the profile.
- **Links trimmed** to LinkedIn + K2 Digital Media only (the guard stamps all
  profile links onto every resume).
- **Bill Gosling preserved**: `preserve: true` + a prompt rule so a
  collections/customer-service role is never recast as sales/dev.

### Job search: Canada-only
- `filters.canada_only` (+ `keep_unknown_location`, `location_keywords`) in
  `sources.yaml`; `_in_canada()` matcher. Applies to all sources.
- **Patch:** the remote-keeping rule was too broad and let "Remote, US",
  "Remote, India", etc. through. Now only a **bare** "Remote" (no place named)
  counts as unknown (`_is_bare_remote`); multi-region postings that include
  Canada ("Remote, Canada; Remote, US") are kept, the rest dropped. Set
  `keep_unknown_location: false` to also drop bare "Remote".

### Dark-mode dropdown fix
- Sidebar `<select>` options were dark-on-dark in dark mode — added an explicit
  `html[data-theme="dark"] .side-select option` rule.

### Housekeeping
- Cleared old scraped content (collector CSVs + intake queue/seen) for a fresh start.

## 2026-06-10 / earlier

- **Personas** added: role-aware generation from `personas.yaml`, auto-select +
  manual override, `GET /personas`, sidebar picker. See [personas.md](personas.md).
- **Collector source** (`type: collector`) added to intake; manual-add endpoint;
  Scraper view (later replaced by the embedded dashboard).
- **n8n** wiring documented (host gateway, not `localhost`).
- **Resume Studio** web app (Generate / Bulk / Library), Docker, truth-guard,
  two-page ATS resume — see git history and [architecture.md](architecture.md).
