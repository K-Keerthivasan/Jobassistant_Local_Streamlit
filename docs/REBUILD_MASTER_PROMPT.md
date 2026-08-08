# Master Build Prompt — Truth-Only, Local-First Job-Application Platform (OSS → Commercial)

> **How to use this document.** Paste the whole thing into a capable coding agent (Claude Code,
> etc.) as the initial brief for a **fresh repository**. It is a from-scratch rebuild of a working
> Python/FastAPI prototype into a modern **Next.js + Node** stack, shipped first as **open source**
> and later as a **commercial SaaS** from the same monorepo. Replace `APPNAME` with the real name.
> Build in the milestone order in §18. Do not invent product scope beyond this document; ask if
> unsure.

---

## 0. Agent role & prime directives

You are the founding engineer. Build a **production-grade, professional, publicly-launchable**
application. Priorities, in order:

1. **Truth-only generation** — the product NEVER fabricates a fact about the user. This is the whole
   brand. Every generated résumé/letter/email line must be grounded in the user's real profile or an
   explicit user-confirmed input. A deterministic "truth-guard" is the crown jewel (see §6).
2. **Local-first** — it runs fully on the user's machine with **local LLMs (Ollama)** and no
   mandatory cloud. One command (`docker compose up`) brings up the whole app.
3. **Clean, typed, modular** — TypeScript everywhere, a monorepo with clear package boundaries so the
   OSS core and the commercial `ee/` layer stay separable.
4. **Streamlined, professional UX** — this is a launch product, not a toy. Cohesive design system,
   fast, responsive, light/dark.

Non-negotiables: no fabricated facts; no telemetry without opt-in; user owns their data; the core is
usable with zero paid API keys.

---

## 1. Product overview

`APPNAME` is a **truth-only, local-first job-application copilot**. From a single **master profile**
(the user's real experience, verbatim), it:

- generates **ATS-friendly résumés**, **cover letters**, and **application + follow-up emails**,
  tailored per job and **grounded only in real facts**;
- **ingests jobs** from many sources (RSS, Job Bank, ATS boards, CSV, a browser capture extension,
  pasted job emails) and dedupes them;
- tracks the **pipeline** (queued → generated → applied → follow-up), including **HR outreach** and a
  special **PR / immigration stream**;
- runs an optional **agentic review** that critiques a résumé vs a job and proposes a
  **truth-guarded rewrite**, plus an interactive **skill-gap Q&A** ("do you have X?" → yes/no → only
  confirmed skills are added);
- sends email + logs outcomes via **connectors / automation** (Gmail, Google Sheets, webhooks, n8n),
  with scheduled follow-ups.

The differentiator vs every "AI résumé" tool: **it will not lie for you**, and it **runs on your own
machine with your own model**.

---

## 2. Editions — OSS vs Commercial (single monorepo)

Follow the **open-core** pattern (like Cal.com / n8n / Postiz): OSS core in the main tree, commercial
features isolated in an `ee/` (enterprise) directory under a separate license.

**Open-source edition (ship first):**
- License: **AGPL-3.0** for the app (keeps SaaS clones honest) — confirm with the owner; MIT is the
  alternative if they prefer max adoption.
- **Single-user per install**, no auth required (local trust). Optional simple password.
- Full generation, truth-guard, intake, review, connectors, local LLM, Docker compose, BYO keys.
- SQLite **or** Postgres (Prisma supports both; default to Postgres-in-Docker for parity).

**Commercial edition (later, same repo, `apps/*` + `ee/`):**
- **Multi-tenant SaaS**: orgs/teams, auth (email + OAuth), RBAC, billing (Stripe), usage metering.
- Managed LLM (hosted inference) + premium connectors + analytics + priority support.
- Gated behind a **license-key / entitlement** check; commercial code lives in `ee/` under a
  commercial license and is tree-shaken out of the OSS build.
- Cloud deploy (Vercel for web + a Node host / Fly.io / Render for API + workers + managed Postgres +
  Redis + object storage).

Build **only the OSS edition now**, but keep every seam (auth, tenancy, entitlements, storage) behind
interfaces so the commercial layer slots in without a rewrite. Add `getCurrentUser()` /
`getTenant()` / `hasEntitlement()` abstractions that, in OSS, resolve to the single local user with
all features on.

---

## 3. Tech stack (with rationale)

**Monorepo:** pnpm workspaces + **Turborepo**. TypeScript strict everywhere. ESLint + Prettier +
`tsc --noEmit` in CI.

**Frontend — `apps/web`:**
- **Next.js (App Router)** + React + TypeScript.
- **Tailwind CSS + shadcn/ui** (Radix) for the design system; `lucide-react` icons.
- **TanStack Query** for server state; **Zustand** for light client state; **react-hook-form + zod**
  for forms.
- Light/dark theme, fully responsive, keyboard-friendly.

**Backend — `apps/api`:**
- **NestJS** (Node, TypeScript) for a structured, testable REST API + DI. (Rationale: modules/guards/
  pipes map cleanly to this domain; it's the same family as the reference stack and scales to the
  commercial edition.)
- **BullMQ + Redis** for background jobs (scraping, generation batches, email sends, scheduled
  follow-ups) in **`apps/worker`**.
- Validation with **zod** (shared schemas in `packages/contracts`).

> Alternative if the owner wants fewer services: Next.js **Route Handlers** as the API + a single
> `apps/worker`. Prefer the NestJS split for the commercial path; document the tradeoff.

**Database — `packages/db`:**
- **PostgreSQL** + **Prisma** (migrations, typed client). SQLite supported for pure-local via a
  Prisma provider switch.

**LLM — `packages/engine`:**
- Provider-agnostic **engine abstraction** (see §7). Default provider: **Ollama** (OpenAI-compatible
  `/v1/chat/completions`), local. Pluggable: any OpenAI-compatible gateway, **Anthropic**, and an
  "agent" provider. **Structured output** via JSON-schema / tool-calling with a robust
  balanced-brace JSON extractor fallback (local models return messy JSON).

**Rendering — `packages/render`:**
- Résumé + cover letter to **PDF and DOCX**. Use `docx` for DOCX and a deterministic HTML→PDF
  (Playwright/Chromium headless, or `react-pdf`) for pixel control. Must support the **2-page
  autofit** behavior (§8).

**Automation / connectors — `packages/connectors`:**
- A connector SDK (see §9). First-party connectors: job sources (RSS, Job Bank, Greenhouse, Lever,
  Workday, generic, browser-capture, Indeed) and delivery (Gmail/SMTP, Google Sheets, generic
  webhook, **n8n**).

**Infra:** Docker + **docker compose** (web, api, worker, postgres, redis; Ollama runs on host or as
an optional compose service). `.env`-driven config. Object storage: local disk (OSS) / S3-compatible
(commercial) behind a storage interface.

**Auth:** OSS = none / single-user. Commercial = **Auth.js (NextAuth)** + orgs + RBAC (interface it
now, implement later).

**Testing:** **Vitest** (unit, esp. truth-guard), **Playwright** (e2e). Truth-guard must have a hard
test suite (§15).

---

## 4. Monorepo layout

```
APPNAME/
  apps/
    web/           # Next.js UI
    api/           # NestJS REST API
    worker/        # BullMQ workers (scrape, generate-batch, email, schedule)
  packages/
    core/          # domain: generation orchestration, prompts, humanize
    truth-guard/   # DETERMINISTIC fact-enforcement (no LLM) — heavily tested
    engine/        # LLM provider abstraction (Ollama default, pluggable)
    db/            # Prisma schema, client, migrations, seed
    contracts/     # zod schemas + shared TS types (API DTOs, domain models)
    connectors/    # job-source + delivery connector SDK and first-party nodes
    render/        # PDF/DOCX rendering + page-fit
    ui/            # shared shadcn components, theme
    config/        # env loading/validation (zod), constants
  ee/              # COMMERCIAL ONLY (separate license): auth, billing, tenancy, premium connectors
  docker/          # compose files, Dockerfiles
  docs/
```

Enforce boundaries: `web` and `api` depend on `packages/*`; `truth-guard` and `engine` have **no UI
or DB deps**; `core` composes `engine` + `truth-guard` + prompts.

---

## 5. Data model (Prisma outline)

Model the domain (names indicative; refine):

- **Profile** (single per install in OSS; per-user in commercial): fullName, preferredName,
  emailSignoffName, contact (email, phone, location, locationGeneral, links[]), summaryBase,
  skills (grouped), experience[], education[], certifications[]. This is the **single source of
  truth**. Add optional `confirmedSkills` (attested but not in base profile).
- **Persona**: role-aware framings + foreground skills (e.g. "IT Support", "Full Stack",
  "Digital Marketing", "AI/Automation").
- **Job**: source, sourceCompany, jobId, company, title, location, description, applyUrl,
  contactEmail, posted, plus tracking: `status` (new|generated|approved|sent|applied|skipped),
  `applied`, `priorityOverride` (''|high|medium|low) + computed `priorityScore/Level`, flags
  `repeatable`, `irrelevant`, `special` (+ `specialProgram` RCIP/RNIP/AIP), `lane`, `nocTeer`,
  `foundAt`, `sentAt`, `sentTo`, `followups[]`, `hrEmailedAt`, `sentLog[]` (audit of everything
  emailed: {at, kind, to, subject, body}), `notes`, link to latest `Run`.
- **Run** (a generated application bundle): résumé JSON, cover JSON, email JSON, QA report, target,
  persona, createdAt, plus a stored `review` (Hermes critique + proposed rewrite). PDFs/DOCX rendered
  on demand from JSON, not stored.
- **Company**: hrContacts[] ({name,email}) with a mirrored primary hrEmail/hrName, hrFollowups[],
  ats, careersUrl, notes, updatedAt.
- **RepeatableRole**: company+title keyed template with JD, status, sector, tags, timesApplied,
  lastApplied.
- **Seen** (dedup keys), **SourceConfig** (per job-source settings), **ConnectorConfig**,
  **UsageStat**.
- Commercial-only: **User, Org, Membership, Subscription, ApiKey, Entitlement** (in `ee/`).

Include a **JSON audit field** convention so the model can evolve without migrations for
non-indexed extras (like the prototype's `data` blob), but prefer real columns for anything queried.

---

## 6. The generation pipeline + truth-guard (the differentiator) — build this carefully

**Pipeline (`packages/core`):** `generate(target, profile, persona) →`
1. **LLM generation** of résumé / cover / email (or the dynamic line of a templated email — see §8).
2. **Agentic QA** (optional, if an agent engine is configured): the LLM audits every résumé claim
   against the profile and removes unsupported ones. No-op if off.
3. **Deterministic truth-guard** (`packages/truth-guard`, NO LLM) — the hard backstop. It:
   - forces identity/contact/education/certifications to come **verbatim from the profile**;
   - keeps only **skills grounded in the profile** (split compound tokens; allow an
     `extraSkills` allowlist for **user-confirmed** skills from the skill-gap Q&A);
   - strips invented **metrics/percentages/years-of-experience/team-sizes** from prose
     (headline, summary, bullets, cover, email) — configurable strict mode;
   - repairs mangled names / sign-offs;
   - returns a **QA report** of everything changed (dropped skills, stripped numbers, fixes).
4. **Humanize** cleanup: remove em/en dashes and AI-slashes, soften AI-tell phrases — while
   **preserving newlines/structure** (line-by-line, never flatten paragraphs).
5. **Page-fit**: scale résumé typography density to fill ~2 pages **without adding content**
   (truth-only), and a **page-check** that reports overflow/wrong size.

The truth-guard and humanize passes are **pure functions with unit tests**. This is the moat — do
not shortcut it. Port the prototype's rules: grounded-skills matching, number/metric stripping,
name/sign-off repair, education/cert verbatim, and the **newline-preserving** email/cover cleaner.

**Emails are assembled deterministically** (fixed, on-brand templates) with only 1–2 dynamic
LLM-written lines, so format never drifts and the signature/links are always correct and truthful
(pulled from the profile). See §8.

---

## 7. LLM engine abstraction (`packages/engine`)

- Interface: `chatStructured(system, user, zodSchema, opts) → T` and `chat(...)`, plus `available()`,
  `listModels()`, `health()`.
- **Providers**: `ollama` (default, local), `openai-compatible` (any gateway), `anthropic`, `agent`
  (an OpenAI-compatible agent gateway). Selected via config; support **"split"** routing (e.g.
  résumé on the local model, prose letters on the agent).
- Robust JSON handling: ask for JSON-only, then extract the first **balanced `{...}`** (handles
  nested/escaped braces and chatty local models); validate with zod; one repair retry.
- Track token/latency usage per call (`UsageStat`); pricing map (all-local = free).
- **Never** required to have a cloud key for the OSS core to function.

---

## 8. Feature modules — port every capability

Recreate the full feature set of the prototype (each becomes a screen + API + service):

1. **Profile** — edit the master profile; import from the current YAML/JSON; a first-run **setup
   wizard**; `emailSignoffName`; portfolio/LinkedIn/site links used in signatures.
2. **Generate** — pick a job/persona/engine, generate résumé + cover + email; show the truth-guard
   QA panel, page-check, and a preview (Résumé / Cover / Email tabs); download PDF/DOCX/JSON.
3. **Résumé** — ATS-friendly; **specific `Mon YYYY` dates** (a hard rule); 2-page autofit; skills
   selected/ordered by persona relevance from real skills only.
4. **Cover letter** — **elite style**: open with a **bold idea** (never "I'm applying for…"), connect
   real experience to their needs, confident/modern/concise, **under ~180 words**, no em dashes.
5. **Application email** — deterministic template + one LLM **opener** + one **hook** (role-aware,
   truth-only), then a fixed "resume attached / portfolio" line and a **letterhead signature**
   (`Thanks,` / name / `phone | linkedin`). No fabricated attachments claims.
6. **Follow-up email** ("reopens doors"): reaffirm fit (1 line) → **new value proposition** (one
   fresh, LLM-written, truth-only line with a safe fallback) → **ask for next steps** → warm,
   confident, not desperate.
7. **HR outreach** — per-company **HR contacts (multiple)**; import via CSV; a **single-click** send
   of a templated first/second follow-up; a **compose modal** (prefilled, editable, pick recipients);
   auto-fill a job's HR email from the saved company.
8. **Jobs** — the queue with search + filters (status/source/channel/applied/company/date), a
   **priority system** (auto-score from signals + manual pin, badge, drives engine + ordering),
   per-row flags (📧 email, 🔁 repeatable, 🚫 irrelevant, 🍁 special), an **ℹ info** popup with last
   generated / emailed / follow-ups / **sent history** (review exactly what was emailed), **format-
   tolerant dedupe**, multi-select **bulk delete**, **bulk add**, and a **compact filter bar**.
9. **RSS & CSV Intake** — configure job sources; **Fetch**; **Upload CSV** (jobs) with a downloadable
   template; **Add manually**; a **browser-capture** collector integration; multi-select + bulk
   delete; a compact **source chip** UI.
10. **Companies** — grouped by company (grid/list toggle, default grid), **collapsible** cards
    (arrow → job count → expand), sort (name / last-scraped / last-applied / needs-follow-up), HR
    editing, per-job send/follow-up, and an **HR follow-ups** sub-tab (window filter + "show all with
    saved HR" toggle).
11. **Repeatable roles** — recurring templates you reapply to; per-run **skills-to-emphasise**;
    tracking (status/sector/job-id/tags); grid/list.
12. **Special (PR) stream** — PR-potential jobs flagged 🍁; filter/sort by **lane** (job category) and
    **NOC/TEER**; optional program tag (RCIP/RNIP/AIP); the full generate + apply + email-HR actions
    scoped to this stream. (Support importing a big CSV of jobs as **applied + special** with
    `priority/lane/noc_teer`.)
13. **Bulk generate** — queue many jobs, auto-generate, from the queue or a filtered slice.
14. **Library** — every generated application (and jobs not yet generated), preview/apply/download.
15. **Q&A** — answer screening questions from the profile, or truthfully rephrase a user draft; short,
    de-AI'd output.
16. **Review with the agent** — critique a résumé vs the JD (scores, strengths/weaknesses, missing
    keywords, risk flags), propose a **truth-guarded rewrite** (apply with one click, re-render
    DOCX/PDF, reversible), accept **specific user change suggestions**, and the interactive
    **skill-gap Q&A** (§6: confirmed skills feed the rewrite AND the truth-guard allowlist).
17. **Automation / connectors** — send emails and log to sheets via the connector layer (§9),
    including **scheduled follow-ups**.

Every action that changes state must **refresh the affected UI** (learned bug: applying a rewrite
must re-render the preview; toggles must reflect immediately). Guard all `localStorage` access in
try/catch (Firefox throws when site storage is blocked).

---

## 9. Connectors framework (`packages/connectors`) — a first-class feature

A small, typed **connector SDK** (n8n-style nodes) with two kinds:

- **Sources** (pull jobs): `rss`, `jobbank`, `greenhouse`, `lever`, `workday`, `generic`,
  `browser-capture`, **`indeed`**, `email-parse`. Each declares config (search terms, board token,
  filters) and returns normalized `Job`s; intake dedupes (format-tolerant company+title+location).
- **Delivery/automation** (push): `gmail`/`smtp`, `google-sheets`, `webhook`, **`n8n`** (post a
  payload to a user's n8n webhook). Support **test vs production** targets, batching, and attachments
  (base64 → binary).

Ship a clean way to **add connectors** (the owner explicitly wants Indeed + more later): a registry,
a config UI, and per-connector credential storage (encrypted at rest in commercial). Keep the n8n
recipes from the prototype as an optional integration, but make the **built-in** connectors the
default path so users don't need n8n.

---

## 10. API surface (REST, versioned `/api`)

Mirror the prototype's endpoints with clean DTOs (zod in `packages/contracts`). At minimum:
`profile`, `personas`, `engines/health`, `generate`, `jobs` (list/create/update/delete/import/dedupe/
status/priority/special/applied/repeatable/irrelevant), `jobs/:id/generate`, `jobs/:id/send`,
`jobs/:id/followup`, `jobs/:id/email-hr`, `companies` (+import, +hr-followup preview/send),
`repeatable`, `special`, `runs` + on-demand `download/:run/:artifact`, `review` (+ `review/skill-gaps`
+ `review/apply`), `answer`, `intake/run`, `sources`, `connectors`. Everything typed end-to-end
(shared contracts package).

---

## 11. Background jobs (`apps/worker`, BullMQ)

Queues: **scrape/intake**, **generate-batch**, **email-send**, **schedule** (daily follow-ups).
Idempotent, retried, observable. The scheduled follow-up job reads due items and sends the
reopens-doors follow-up. All heavy/slow work off the request path.

---

## 12. Rendering (`packages/render`)

Résumé + cover → **PDF and DOCX** from the validated JSON. Deterministic, ATS-safe layout, honoring
the **2-page autofit** (scale density, never add content) and a **page-check** result. Serve
downloads as `attachment` with `nosniff`.

---

## 13. UI/UX

- Next.js App Router; a **collapsible left sidebar** (Generate, Intake, Jobs, Repeatable, Companies,
  Special, Q&A, Bulk, Library, Profile) + engine/persona pickers + usage line.
- shadcn/ui design system, light/dark, responsive; grid/list toggles; compact filter bars; styled
  confirm/prompt/compose **modals** (never native `confirm`/`prompt`).
- Empty/loading/error states everywhere; toasts; optimistic updates that reconcile.
- Accessibility: keyboard nav, focus states, aria labels.

---

## 14. Local dev & config

- **One command:** `docker compose up` starts web + api + worker + postgres + redis. Ollama runs on
  the host (documented) or as an optional compose service; the app reaches it via
  `host.docker.internal`/service name.
- `.env` (zod-validated in `packages/config`): DB url, Redis url, LLM provider + base url + model +
  optional keys, connector creds, app URL. Ship `.env.example`.
- **Personal data externalized**: the master profile and any secrets are gitignored; ship
  `*.sample` templates + the setup wizard.
- `pnpm dev` runs everything with Turborepo; hot reload.

---

## 15. Testing & quality

- **Unit (Vitest):** truth-guard (the big one — grounded skills, metric/number stripping,
  name/sign-off repair, education/cert verbatim, newline-preserving cleaner, extraSkills allowlist),
  humanize, dedupe (format-tolerant), engine JSON extractor, email/cover assembly.
- **Contract tests** for the API (zod DTOs).
- **e2e (Playwright):** generate → truth-guard QA → download; skill-gap Q&A → rewrite → apply;
  intake CSV → job appears; send (mocked connector) → sent_log recorded.
- CI: typecheck + lint + unit + build on every PR. A **"never fabricates" golden test**: feed a JD
  demanding skills the profile lacks, assert none appear unless confirmed.

---

## 16. Security & privacy

- Data ownership is a selling point: **all data local by default**; export/delete everything; clear
  docs on what's stored where. No outbound calls except the user's chosen LLM/connectors.
- Encrypt connector credentials at rest (commercial). CSRF/rate-limit the API. Never log secrets or
  full résumé bodies at info level. Content-Security hardening on the web app.

---

## 17. Licensing & commercialization

- OSS: AGPL-3.0 (recommended) in root; `ee/` under a commercial license header, excluded from the
  OSS Docker build. A `LICENSE`, `LICENSE-EE`, and a clear `README` boundary.
- Commercial (later): Stripe billing, org/team seats, hosted inference, premium connectors, usage
  analytics, SSO, priority support; entitlement checks (`hasEntitlement`) gate `ee/` features.
- A public **landing + docs site** (can be a Next.js route group or a separate `apps/site`).

---

## 18. Build order (milestones)

- **M0 — Scaffold:** monorepo, Turborepo, TS strict, Prisma+Postgres, Docker compose up, CI, design
  system, empty app shell + sidebar.
- **M1 — Profile + Engine + Truth-guard + Render:** master profile CRUD + wizard; Ollama engine;
  truth-guard package **with its test suite**; PDF/DOCX render; page-fit. (No UI polish yet.)
- **M2 — Generate:** résumé + cover + email generation through the full pipeline; preview tabs; QA
  panel; downloads. This proves the moat end-to-end.
- **M3 — Jobs + Intake + Connectors (sources):** job queue, statuses/flags/priority, filters, dedupe,
  CSV import, RSS/JobBank/ATS/**Indeed** sources, browser-capture, bulk actions.
- **M4 — Companies + HR + Delivery connectors:** company grouping, multi HR contacts, send email
  (Gmail/SMTP), sent_log, follow-ups (reopens-doors), scheduled follow-ups, sheets/webhook/n8n.
- **M5 — Review + Skill-gap Q&A:** agent critique, truth-guarded rewrite + apply, confirmed-skills
  loop, Q&A screening answers.
- **M6 — Special (PR) stream, Repeatable, Bulk, Library:** the remaining views; big-CSV import as
  applied+special with lane/NOC.
- **M7 — Polish + launch:** a11y, error states, docs, landing page, one-command install, seed/demo
  data, security pass. Public OSS release.
- **M8+ — Commercial `ee/`:** auth/orgs/billing/entitlements/hosted inference. (Separate track.)

Deliver each milestone as a working, demoable increment with tests green.

---

## 19. Conventions

- TypeScript strict; no `any` without justification. Zod at every boundary. Pure domain logic (no
  side effects in `core`/`truth-guard`). Small, named functions; comments explain **why**.
- Conventional commits; PR-sized changes; every feature has tests. No fabricated data anywhere, ever
  — including seed data, which uses a clearly fictional sample profile.
- Match the reference behaviors precisely: **`Mon YYYY` dates**, **no em dashes / AI-slashes**,
  **cover < ~180 words with a bold opener**, **deterministic email/signature assembly**,
  **format-tolerant dedupe**, **newline-preserving** text cleaning, **guarded localStorage**,
  **refresh-after-mutation**.

---

## 20. Acceptance criteria (definition of done for the OSS release)

1. `docker compose up` on a clean machine yields a working app reachable in the browser, using a
   local Ollama model, with **zero paid keys**.
2. From a sample profile + a pasted job, the app generates a résumé, cover, and email that contain
   **no facts absent from the profile** (verified by the golden test) and render to clean PDF/DOCX.
3. Intake pulls jobs from at least RSS + one ATS + Indeed + CSV, dedupes them, and the pipeline can
   generate, send (mocked/real connector), and follow up — with a full **sent history** to review.
4. The review flow proposes a truth-guarded rewrite; the skill-gap Q&A adds **only user-confirmed**
   skills; applying re-renders and is reversible.
5. Truth-guard, humanize, and dedupe unit tests pass; e2e happy paths pass; CI green.
6. Docs: quickstart, configuration, architecture, data-and-privacy, connector-authoring, and the
   OSS/commercial boundary.

---

**Start with M0 and M1. Confirm the app name, license choice (AGPL vs MIT), and NestJS-vs-Next-API
decision before scaffolding, then proceed.**
