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

## Export / import

Save built workflows as JSON here (`n8n/workflows/*.json`) so they're version
controlled alongside the code. Import them in the n8n UI under *Workflows → Import*.

## Why a review gate

Auto-submitting applications is high-stakes and easy to get wrong (wrong resume,
duplicate applies, screening questions). Keep a human approval step until the
per-site adapters and dedupe are proven.
