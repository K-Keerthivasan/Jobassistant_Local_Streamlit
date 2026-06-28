# n8n workflows

The old workflows were removed (the app changed a lot). This is the blueprint for the
**two new workflows** — build them in n8n to match these contracts.

Both run on the host; the resume-api container reaches the host at `host.docker.internal`,
and n8n reaches the app at `http://host.docker.internal:8088`. Each workflow has its own
**webhook** and its own **Google Sheet**.

## Environment (`.env`, loaded into the container via `env_file`)

| Var | Used by | Purpose |
|-----|---------|---------|
| `N8N_BULK_HR_WEBHOOK_URL` | Workflow 1 | bulk HR outreach from your CSV |
| `N8N_JOBS_WEBHOOK_URL` | Workflow 2 | job-application emails (Job Bank / email-only) |
| `N8N_WEBHOOK_URL` | fallback | used if the specific one above is unset |

Email is sent by a **Gmail** (or SMTP) node inside n8n — the app never sends mail, it only
POSTs the package. Set your Gmail/SMTP credential once in n8n.

---

## Workflow 1 — Bulk HR email from CSV  → Google Sheet "HR Outreach"

**Flow:** You get a CSV from Claude → upload it in the app → the app **generates a tailored
résumé/cover per row** (company + title), then POSTs the whole batch to
`N8N_BULK_HR_WEBHOOK_URL`. n8n loops the rows, emails each HR, logs to the Sheet, and returns
a per-row result the app shows as the "sent" report. A separate schedule handles follow-ups.

**Webhook payload the app sends (one call, all rows):**
```json
{
  "type": "bulk_hr",
  "batch_id": "2026-06-17T12-30-00",
  "rows": [
    {
      "company": "Acme Inc", "title": "Software Developer",
      "hr_name": "Jane Doe", "hr_email": "jane@acme.com", "location": "Toronto, ON",
      "subject": "Application: Software Developer",
      "body": "Hi Jane, ...",
      "resume": { "filename": "Acme_Software_Developer_K_Resume.pdf", "content_base64": "..." },
      "cover":  { "filename": "Acme_Software_Developer_K_Cover.pdf",  "content_base64": "..." }
    }
  ]
}
```

**n8n nodes:** Webhook (POST, responseNode) → Split Out `rows` → (per row) Gmail "Send"
(To `hr_email`, Subject `subject`, body `body`, attach `resume`/`cover` from base64) →
Google Sheets "Append" to **HR Outreach** → Aggregate → Respond to Webhook with results.

**Google Sheet "HR Outreach" columns:**
`batch_id | date | company | title | hr_name | hr_email | subject | status (sent/failed) | message_id | follow_up_due | followed_up | notes`

**Follow-up (second, scheduled workflow):** Cron (daily) → Google Sheets "Read" HR Outreach
where `follow_up_due <= today` AND `followed_up` is empty → Gmail send a follow-up → set
`followed_up = today`. (Set `follow_up_due` = send date + N days when the row is first logged.)

---

## Workflow 2 — Job-application emails  → Google Sheet "Job Applications"

Same idea, but driven from the app's **queue** for **Job Bank / email-only** jobs. Already
wired app-side: generate the job, then **📧 n8n** on the row (or the email-apply path) POSTs to
`N8N_JOBS_WEBHOOK_URL`. Uses the job's contact email, or the saved company HR email as fallback.

**Webhook payload the app sends (one job per call):**
```json
{
  "type": "job_application", "source": "jobbank",
  "company": "...", "title": "...", "location": "...",
  "contact_email": "hr@company.com", "apply_url": "...",
  "email": { "subject": "...", "body": "..." },
  "folder": "<run_id>",
  "files": {
    "resume":       { "filename": "...", "content_base64": "..." },
    "cover_letter": { "filename": "...", "content_base64": "..." }
  }
}
```

**n8n nodes:** Webhook (POST, responseNode) → Gmail "Send" (To `contact_email`, Subject
`email.subject`, body `email.body`, attach `files.resume` / `files.cover_letter`) →
Google Sheets "Append" to **Job Applications** → Respond to Webhook (`{"sent": true}`).

**Google Sheet "Job Applications" columns:**
`date | company | title | location | source | contact_email | subject | status | applied`

### Follow-ups (reuse Workflow 2's webhook)
Follow-ups do **not** need a new workflow. The app's **🔔 Follow up** button (`POST
/jobs/{key_id}/followup`) posts the **same payload shape** to `N8N_FOLLOWUP_WEBHOOK_URL`
(defaults to `N8N_JOBS_WEBHOOK_URL`), with `"type": "followup"`, a short follow-up `email`,
and **no `files`** (nothing re-attached). The Build node already keys on `type`: follow-ups
log to the sheet with `status = "followup"` and a blank `applied`, so they're distinguishable
from first sends. To split them into their own webhook/sheet, set `N8N_FOLLOWUP_WEBHOOK_URL`
to a second workflow. The app records each follow-up on the job (shown in the ℹ info and
job detail).

> Note: per-company **📧 Email HR (per job)** in the Companies view sends one separate
> Workflow-2 call per *generated* job for that company (each with its own tailored résumé /
> cover / email) — it is not a bulk blast.

---

## App-side status
- **Workflow 2 (job applications)**: wired — `POST /jobs/{key_id}/send-n8n` → `N8N_JOBS_WEBHOOK_URL`.
- **Single HR follow-up**: wired — Companies → **HR follow-ups** tab → compose → `POST
  /companies/hr-followup/send` → **`N8N_BULK_HR_WEBHOOK_URL`** (one row per recipient, → HR Outreach
  sheet, so the scheduled daily follow-up covers it too — same pipeline as the batch).
- **Workflow 1 (bulk HR batch)**: wired — Companies → **HR follow-ups** tab → select companies +
  **📤 Send batch** → `POST /companies/hr-batch/send` → `N8N_BULK_HR_WEBHOOK_URL`. The app builds
  **one row per saved HR contact** from the chosen first/second template and posts them in a single
  call. Payload: `{ batch_id, rows: [ {company, title, hr_name, hr_email, subject, body} ] }` (no
  attachments for HR follow-ups). The workflow fans out, emails each, logs to **HR Outreach**, and
  returns `{ sent, failed, results }`.

### To enable the bulk-HR batch
1. In n8n, build/import **Workflow 1** (`bulk-hr` webhook, **POST**), set the Gmail + Google Sheets
   credentials and the **HR Outreach** spreadsheet ID, then **Publish/Activate** it.
2. In the app `.env`, set `N8N_BULK_HR_WEBHOOK_URL=http://host.docker.internal:5678/webhook/bulk-hr`
   and recreate the container (`docker compose -f docker/docker-compose.yml up -d --force-recreate`).
3. Test with the sidebar **🧪 n8n test mode** ON (arm "Listen for test event" on the `bulk-hr` node).
