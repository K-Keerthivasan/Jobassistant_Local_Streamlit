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

## 6. Agent-driven apply (any site) — `prepare → confirm → submit → log`

The Playwright script above knows a fixed set of CSS selectors, so it only really
works on portals someone has already taught it. The **agent-driven** path works on
a site nobody has seen before: Claude Code reads whatever form is actually on the
page via the **Playwright MCP** server, and this app makes every decision about
what goes in it.

```
Claude Code + Playwright MCP          resume-api (:8088)
  read posting + form         ──►  POST /apply/prepare      reuse or generate the
                                                            résumé/cover, answer
                                                            questions, plan the fill
  fill the form (no submit)   ◄──  fill plan + summary
  show summary, ASK USER
  user says yes               ──►  POST /apply/{id}/confirm  bank new answers
                              ◄──  may_submit / awaiting_user_submit
  submit + verify  ── OR ──  you submit it yourself
  outcome                     ──►  POST /apply/{id}/log      job → applied
```

**Nothing can submit without `/apply/{id}/confirm` returning `may_submit: true`,**
and that only happens after you say yes. The `apply_sessions` table records every
decision, so the gate is auditable rather than a promise made in a prompt.

### Who clicks submit

`confirm` takes `submit_by`:

- **`"agent"`** (default) — Claude clicks submit and verifies the success state.
- **`"me"`** — the form is left filled and ready and **you** click it. Use this
  behind a login wall, a CAPTCHA, or partway through a multi-step Workday flow.
  `may_submit` stays `false` so nothing can click it for you; the answers are
  still banked.

Either way, `POST /apply/{id}/log {"status": "submitted", "submitted_by": "me"}`
marks the job **applied** in the review queue. An application you finished by hand
is tracked exactly like one Claude submitted — that's the point of the handoff.

### Reusing an application you already generated

`prepare` looks for the run already attached to the queued job (`notes`) before
generating anything, so a job you generated earlier in the Library or in Bulk is
**reused**, not re-run — the difference between seconds and minutes of local
model time. The response sets `reused_run: true` and the summary names the run and
its date. Pass `"regenerate": true` when the posting or your profile has changed.

Each application also saves the company's portal (`last_apply_url` + detected ATS)
into company memory, so repeat postings from the same employer start warm.

### Setup

```bash
claude mcp add playwright -- npx @playwright/mcp@latest \
  --user-data-dir "<repo>/.pw-profile" \
  --output-dir "<repo>/data/job-applications/mcp-output"
```

`--user-data-dir` is what makes saved logins stick between applications (the same
trick the script above uses). Without it the MCP server starts from a throwaway
profile and you re-login on every portal, every time.

Then just give Claude Code a job URL — the `apply-to-job` skill
(`.claude/skills/apply-to-job/SKILL.md`) drives the sequence.

> **Docker note.** The PDFs are rendered wherever the API runs. If `resume-api` is
> in a container, the `path` values in the response are container paths the host
> browser can't read — download from the returned `/download/...` URL instead.
> They're written under `data/job-applications/outbox/` (gitignored) rather than a
> system temp dir, because the MCP server restricts file access to the workspace.

### How each field gets its value

| Source | When | Flagged? |
|---|---|---|
| `apply_profile.<key>` | a plain labelled input (Name, City, LinkedIn) | no — it's your data |
| **answers bank** (`source: bank`) | a question you've answered before, matched fuzzily | no — you approved it once already |
| `apply_profile` standing facts (`source: profile`) | work authorization, sponsorship, salary, notice period | no — no model involved |
| **freshly drafted** (`source: new`) | a question nobody has answered before | **yes — unverified, review it** |
| *left blank* | a plain input with no profile match | **yes — listed, never invented** |

That last row is the important one: an input labelled "Internal referral code" is
reported to you, not filled with plausible-looking prose.

### The answers bank

Every screening question you approve is kept in the `answers` table and reused on
the next form that asks something similar. It is seeded from your
`apply_profile.commonAnswers`, and grows with each confirmed application.

- **Matching** is stdlib-only (normalize → light stemming → sequence similarity +
  keyword overlap) with a 0.72 threshold. British/American spelling and
  noun/verb forms are handled, so "Are you legally authorised…" matches "Are you
  legally authorized…".
- **Semantic** restatements that share no words ("in Canada" vs "in the country of
  employment") can't be matched lexically, so the common ones ship pre-loaded as
  alternate phrasings (`_SEED_TAGS` in `intake/answers.py`).
- A near-miss becomes an **alternate phrasing of the existing answer** on approval
  rather than a duplicate row, so the bank's recall grows while it stays small.
- **Only confirmed applications write to the bank.** Reject one and it learns
  nothing.

Browse and edit it with `GET/POST/DELETE /answers/bank`. To check what a question
*would* reuse before applying:

```bash
curl -G localhost:8088/answers/bank --data-urlencode "q=Do you require visa sponsorship?"
# {"would_reuse": true, "score": 1.0, "match": {"answer": "No", …}}
```

### Tracking

There is no second tracker. The job is resolved into the existing review queue
(matched on apply URL, so a job already there from Job Bank or an ATS source is
reused, not duplicated), and the outcome is appended to that job's `sent_log`
alongside its emails — one timeline per job whatever channel it went out through.
Submitting sets `applied = true` and `status = applied`.

## Roadmap

- **V1 (now)**: scrape → filter → autofill common fields → **stop for review**.
- **V2**: company-specific templates for your repeat companies (extend `run_template`).
- **V3**: allow auto-submit only for trusted, simple portals you've confirmed.
- **V4 (now)**: Resume Studio MCP exposes the seven-day application-candidate
  queue and approval history for browser-controlled application runs.
