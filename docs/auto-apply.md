# Semi-auto apply assistant

Philosophy: **reduce repetitive typing, never auto-submit.** The assistant fills the
fields you re-enter on every portal, uploads your resume, answers common screening
questions, then **stops at the review page**. You read it and click Submit.

It does NOT: solve CAPTCHAs, create accounts, change fingerprints, mass-apply, submit
false answers, or automate LinkedIn Easy Apply / Indeed Apply (against their rules).
Use it for **company career portals and ATS pages** (Workday/Greenhouse/Lever/etc.).

## Pieces (built)

| Piece | Where |
|------|-------|
| **Apply-profile** (your saved answers) | `data/apply_profile.json` · `GET /apply-profile` |
| **Repeat-company list** | `data/repeat_companies.json` (TD, RBC, …) — jobs get a `repeat: true` flag |
| **Company memory** | `data/companies/<slug>.json` · `GET/POST /companies/{company}` — reuse details next time the same company posts |
| **Job Bank / RSS intake** | `type: rss` source → jobs in the queue |
| **Playwright autofill** | `src/resume_gen/automation/playwright_apply.py` (run on your host) |

## 1. Apply-profile

`data/apply_profile.json` holds your standard answers (name, email, phone, city,
work authorization, sponsorship, experience band, resume/cover paths, and a
`commonAnswers` map for screening questions). Edit it to taste — it's mounted, no
rebuild needed.

## 2. Repeat companies

`data/repeat_companies.json` is a list of companies you apply to repeatedly. Any
queued job from one of them shows `repeat: true` (via `GET /jobs`). Branch on it:
repeat company → company-specific autofill; otherwise → normal tracking.

## 3. Company memory

`POST /companies/{company}` saves/merges details (careers URL, ATS, notes, saved
answers). `GET /companies/{company}` reads them. The Playwright script saves the
apply URL + detected ATS automatically, so the next posting reuses them.

## 4. Job Bank / RSS

Add an RSS source to `data/sources.yaml`:

```yaml
- type: rss
  url: "https://www.jobbank.gc.ca/jobsearch/jobsearchRSS?searchstring=developer"
  # company: "override if the feed omits it"
```

Run a search on jobbank.gc.ca and copy its RSS link. Items become jobs in the queue.
RSS jobs that expose a **contact email** go down
the **email-apply path** (generate → `📧 n8n` → n8n sends the email).

## 5. Playwright autofill (run on your host)

The browser must be **visible** and stop for your review, so run it on your machine,
not in the headless API container:

```bash
pip install playwright && playwright install chromium

# from an apply URL
python -m resume_gen.automation.playwright_apply --url "<apply url>" \
    --resume output/<folder>/<Company>_<Title>_KK_Resume.pdf \
    --cover output/<folder>/<Company>_<Title>_KK_Cover.pdf

# or by queued job key (reads apply_url and generated documents from the queue)
python -m resume_gen.automation.playwright_apply --job <key_id>
```

It opens the page with a **persistent profile** (`./.pw-profile`, so saved logins
stick), detects the ATS (Workday/Greenhouse/Lever/generic), fills common fields,
uploads the resume/cover, answers common screening questions, screenshots the page,
saves the company details, then **stops** — you submit. Workday is multi-step; it
fills the current step (re-run after clicking Next).

## n8n email workflow (ready to import)

The **📧 n8n** button POSTs the generated package (resume + cover + email, base64) to
your webhook. Import the ready-made workflow that receives it and sends the email:

1. In n8n: **Workflows → Import from File →** `n8n/resume-apply.workflow.json`.
2. It has: **Webhook → Build attachments (Code) → Has email? (IF) → Send Gmail →
   Log to Sheet (optional)**.
3. Open **Send Gmail**, pick/create your **Gmail (OAuth2)** credential. (Prefer SMTP?
   Swap the Gmail node for an "Send Email" node — same fields: `contact_email`,
   `subject`, `body`, attachments `resume` + `cover`.)
4. *(Optional)* open **Log to Sheet**, set a spreadsheet + your Google Sheets cred, or
   delete that node.
5. **Activate** the workflow, then copy the **Webhook → Production URL**.
6. Put it in `.env` and reload the container:
   ```
   N8N_WEBHOOK_URL=http://host.docker.internal:5678/webhook/resume-apply
   ```
   ```
   docker compose -f docker/docker-compose.yml up -d
   ```

Now: generate an email-apply job → **📧 n8n** → n8n emails the contact with your
resume + cover letter attached, and marks the job applied/sent. The **Build
attachments** Code node turns the base64 files into real PDF attachments; the **IF**
node guards against empty emails. Node param names vary slightly by n8n version — if
Gmail's attachment field differs, point it at the binary properties `resume` and
`cover`.

## n8n workflow shape (full orchestration)

```
Schedule/Manual Trigger
  → POST /intake/run            (scrape Job Bank RSS + ATS + collector)
  → GET  /jobs?status=new       (+ each job's `repeat` flag)
  → Filter: experience ≤ 3 yrs / good match
  → Branch:
       repeat company + portal  → (host) run playwright_apply  → status "Needs Manual Review"
       has contact email        → POST /jobs/{key}/generate → POST /jobs/{key}/send-n8n (email)
  → Update tracker (Google Sheet / the queue status)
```

Tracker statuses: `new → good match → application opened → autofilled → needs manual
review → submitted → rejected → interview`.

## Roadmap

- **V1 (now)**: scrape → filter → autofill common fields → **stop for review**.
- **V2**: company-specific templates for your repeat companies (extend `run_template`).
- **V3**: allow auto-submit only for trusted, simple portals you've confirmed.
