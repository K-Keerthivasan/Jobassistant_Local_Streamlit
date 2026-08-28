# HTTP API

FastAPI app in `api/server.py`, served at `:8088`. Interactive docs at
`http://localhost:8088/docs`. From n8n or another container, use
`http://host.docker.internal:8088` (not `localhost`).

## Generation

### `POST /generate`
Generate resume + cover letter + email for one role.

Body (a `TargetRole` plus options):
```json
{
  "company": "Shopify", "title": "Full Stack Developer",
  "location": "Remote", "description": "…job text…",
  "persona": "auto", "model": null, "strict": true, "pdf": true
}
```
Returns: `folder`, `paths`, `resume`, `cover_letter`, `email`, `qa`,
`qa_has_violations`, `persona`, `persona_label`, `keywordsMatched`.

### `GET /personas`
`{ "personas": [ { "id", "label", "headline" } ] }`

## Semi-automated apply

See `docs/auto-apply.md` §6 for the full flow. The browser driver reads the form;
these endpoints own the decisions and the audit trail.

### `POST /apply/prepare`
```json
{"job_url": "https://…", "company": "Acme", "title": "Platform Engineer",
 "description": "…full job text…",
 "fields": [{"selector": "#email", "label": "Email Address", "type": "text",
             "required": true, "options": []}]}
```
Queues the job, generates the tailored application, plans every field. Returns
`session_id`, `standard_fields[]`, `screening_answers[]` (each with
`source: bank|profile|new`), `unfilled_fields[]`, `documents`, and a `summary`.
**Submits nothing.**

### `POST /apply/{session_id}/confirm`
`{"approved": true, "submit_by": "agent"|"me", "edits": {"#why": "corrected text"}}`
→ `{"may_submit": …, "awaiting_user_submit": …, "banked": [...]}`. **The only thing
that authorizes a submit.** Approval banks newly drafted answers (edited text
wins); rejection banks nothing and is logged. `submit_by: "me"` keeps
`may_submit` false and hands you the filled form to submit yourself.

### `POST /apply/{session_id}/log`
`{"status": "submitted|rejected|failed", "submitted_by": "agent"|"me",
"verified_success": true, "note": ""}` → appends to the queue job's `sent_log`;
`submitted` sets `applied` whoever clicked it. Call for every outcome.

### `GET /apply/sessions` · `GET /apply/{session_id}`
Recent attempts (optionally `?job_key=`), and one session with its summary.

### `GET /apply/candidates`
`GET /apply/candidates?limit=100&since=YYYY-MM-DD` returns generated, unapplied
jobs for MCP-guided browser application, including their saved description and
generated run id.

### `GET /answers/bank` · `POST /answers/bank` · `DELETE /answers/bank/{id}`
The screening-answers bank. `GET ?q=<question>` also returns `would_reuse`,
`score` and the matching record — what that question would reuse on a real form.

### `GET /models`
Locally installed Ollama models for the picker.

## Intake & queue

### `POST /intake/run?commit=true`
Fetch all configured sources → filter → dedup → queue. `commit=false` = dry run.
Returns `{ fetched, matched, new, committed, new_jobs[], errors[] }`.

### `GET /jobs?status=new`
List the review queue (optionally filtered by status).

### `POST /jobs/manual`
Add a hand-entered job to the queue. Body: `{company,title,location,description,
contact_email,apply_url}`. (The web app's manual-add writes to the **collector**
instead, so it appears in the dashboard; this endpoint remains for API use.)

### `POST /jobs/{key_id}/generate`
Generate directly from a queued job (accepts the same options as `/generate`),
then marks it `generated`.

### `POST /jobs/{key_id}/status`
`{ "status": "...", "notes": "..." }` — update a queued job.

### `POST /jobs/{key_id}/applied`
`{ "applied": true|false }` — mark a job applied / not applied (independent of
generation status).

### `POST /jobs/{key_id}/send-n8n`
Send an **email-apply** job's generated package to the n8n webhook
(`N8N_WEBHOOK_URL`). Requires the job to be **generated** and to **have a contact
email**. On success it marks the job `applied` + status `sent`. Webhook payload:
```json
{
  "company": "...", "title": "...", "location": "...",
  "contact_email": "hr@...", "apply_url": "...",
  "email": { "subject": "...", "body": "..." },
  "folder": "<output folder name>",
  "files": {
    "resume": { "filename": "<Company>_<Title>_KK_Resume.pdf", "content_base64": "..." },
    "cover_letter": { "filename": "<Company>_<Title>_KK_Cover.pdf", "content_base64": "..." }
  }
}
```
Your n8n Webhook node receives this; decode the base64 files as attachments and
send the email. Jobs **without** an email are left for the (separate) auto-apply
tool — they are not sent to n8n.

## Outputs

| Endpoint | Purpose |
|----------|---------|
| `GET /outputs` | List generated application folders |
| `GET /run?folder=` | Full content of one past run (preview) |
| `DELETE /run?folder=` | Delete an output folder |
| `DELETE /jobs/{key_id}` | Delete a scraped/queued job |
| `GET /file?path=` | Download a generated artifact (restricted to output dir) |
| `GET /health` | `{ ollama, model, output_dir }` |
| `GET /` | Resume Studio web app |

## Collector API (port 8765)

Served by `Resume_Scraper/Scraper.py`, used by the userscript and the embedded
dashboard: `GET /api/jobs`, `POST /api/jobs`, `POST /api/jobs/update`,
`POST /api/jobs/delete`, `GET/POST /api/blacklist[/add|/remove]`, `GET /health`.
