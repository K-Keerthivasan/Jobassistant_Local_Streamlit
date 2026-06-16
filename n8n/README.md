# n8n orchestration

n8n is the glue between job intake and application. It runs in the compose stack
and reaches the generator at `http://resume-api:8088`.

## Starter workflow: "Generate on new job"

1. **Trigger** — choose one:
   - *Local File Trigger* watching `data/jobs/*.json` (new normalized job lands), or
   - *Webhook* that your scraper POSTs a job to, or
   - *Schedule* that pulls a queue (Google Sheet / DB / Indeed connector).
2. **HTTP Request** — `POST http://resume-api:8088/generate`
   - Body (JSON): `{ "company", "title", "description", "location", "apply_url", "contact_email" }`
   - Response: `{ folder, paths, keywordsMatched, email_subject }`.
3. **Review gate (recommended)** — send yourself the `keywordsMatched` + a link to
   the generated files (`GET /file?path=...`) via email/Slack/Telegram, and wait
   for an approval before any submit step.
4. **Apply** (Phase 3) — on approval, either:
   - call the SMTP email path with the resume/cover-letter attached, or
   - hand the `apply_url` + file paths to the Selenium apply service.

## Ready-made workflows (`n8n/workflows/`)

Import each in the n8n UI under *Workflows → Import from File*. All HTTP nodes call
the generator at `http://host.docker.internal:8088` (not `localhost` — inside a
container that's the container itself). Each ships **inactive**; open it, attach
your Gmail/Sheets credential where a node shows an empty `credentials`, then activate.

| File | Trigger | What it does |
|------|---------|--------------|
| `gmail-to-queue.workflow.json` | Gmail (label `job-alerts`, unread) | Parses each job-alert email → `POST /jobs/from-email` → queues it (dedup + repeatable match), marks the mail read. |
| `scheduled-intake-generate.workflow.json` | Schedule (every 6h) | `POST /intake/run` → `GET /jobs?status=new` → `POST /jobs/{key}/generate` per job → emails you a review summary (keywords matched + QA flags). |
| `daily-repeatable-regenerate.workflow.json` | Schedule (daily 07:00) | `GET /repeatable` → for `status=tracked` roles `POST /repeatable/{key}/generate` → emails a refresh summary. |
| `approve-to-send.workflow.json` | Webhook `GET /webhook/approve-send?key=<key_id>` | Approval-link gate: clicking it calls `POST /jobs/{key}/send-n8n`, which emails the HR contact via the existing `resume-apply` workflow and marks the job applied/sent. |
| `email-apply-sweep.workflow.json` | Manual **or** Schedule (every 12h) | `GET /jobs?status=generated` → keep rows with a `contact_email` and `applied=false` → `POST /jobs/{key}/send-n8n` per job (throttled) → emails you a sent summary. Batch version of the one-click email path. |

**How they chain into a review-and-approve loop:** `scheduled-intake-generate`
generates drafts and emails you a summary; you add an *Approve & send* link per job
(`…/webhook/approve-send?key={{ key_id }}`) in that notice; clicking it fires
`approve-to-send`, which triggers `send-n8n` → the original `resume-apply.workflow.json`
sends the email. Nothing auto-sends — the click is the human gate.

Notes:
- `gmail-to-queue` + the two schedule workflows need a **Gmail (OAuth2)** credential on
  their Gmail nodes. The review-notice email is hard-coded to `kkvasan99@gmail.com` —
  change it in the *Email* node.
- `send-n8n` requires `N8N_WEBHOOK_URL` set to the `resume-apply` production URL and the
  job to be **generated with a contact email** (see `docs/auto-apply.md`).

## Export / import

Save built workflows as JSON here (`n8n/workflows/*.json`) so they're version
controlled alongside the code. Import them in the n8n UI under *Workflows → Import*.

## Why a review gate

Auto-submitting applications is high-stakes and easy to get wrong (wrong resume,
duplicate applies, screening questions). Keep a human approval step until the
per-site adapters and dedupe are proven.
