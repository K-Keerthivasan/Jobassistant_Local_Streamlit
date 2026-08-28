---
name: apply-to-job
description: Apply to job postings on any site (any ATS or company careers page) — either one posting from its URL, or continuously through the generated-jobs queue one after another. Opens each posting in a browser, extracts the job and every form field, reuses or generates a tailored resume and cover letter, answers screening questions from the answers bank, fills the whole form and uploads the documents, then hands over for the user to click submit. Use when given a job URL, asked to fill out or apply to a job application, or asked to start applying / work through the job queue / apply to everything generated.
---

# Apply to job postings

## Preferred MCP workflow

Use Resume Studio MCP for the queue, job facts, generated documents, field plans,
approval, and tracking. Use the browser controller only for the live employer
page. Do not use or propose a userscript. Raw HTTP endpoints are a fallback only
when the corresponding MCP tool is unavailable.

For a queue run, keep the user-facing loop short:

1. Call `list_application_candidates(days=7, limit=100)` and take the first
   eligible row. Use `get_job_opportunity` only when the full posting is needed.
2. Open the form, pause only at a real blocker, and inspect the visible controls.
3. Call `prepare_job_application`, fill only its plan, and upload its documents.
4. If the packet is clean, say so in one line. Otherwise show only new answers,
   required blanks, and warnings. Ask one fresh yes/no question for that exact
   application.
5. The user clicks Submit. When they say `done`, record the outcome, return to
   Resume Studio, and continue to the next candidate without repeating setup.

You drive the browser (Playwright MCP). The Resume Studio API owns every
decision — what goes in each field, which answers are reused, what gets banked,
and what is logged. Do not reimplement any of that here; call the endpoints.

**The user clicks submit. You do everything else.** Fill every field, upload the
documents, then hand them a finished form. Never click a submit button yourself
unless the user has explicitly told you to for that specific job — the default,
including in batch runs, is that they submit.

Two modes, same mechanics:

- **One job** — they give you a URL. Run steps 1–8 once.
- **Batch** — "start applying", "work through the queue". Run the loop in
  *Batch mode* at the bottom, which is steps 1–8 per job with no URL pasting.

## Before you start

The API must be reachable at `http://localhost:8088` (`GET /health`). If it
isn't, tell the user to start it (`docker compose -f docker/docker-compose.yml up -d`)
and stop — everything below depends on it.

If the API runs in Docker, the PDF paths it returns are container paths that the
host browser cannot read. Detect this: if the returned `path` doesn't exist on
disk, download the file from `http://localhost:8088<url>` into
`data/job-applications/outbox/` and upload that instead.

## 1. Read the posting

`browser_navigate` to the job URL, then `browser_snapshot`. Extract:

- **job title, company, location**
- **the full job description** — the whole thing, not a summary. It drives the
  résumé, the cover letter, and every drafted answer; a thin description produces
  a generic application.

If the posting and the form are on different pages, follow the Apply button
first, then snapshot again. If applying requires a login and the browser isn't
signed in, stop and ask the user to sign in — the browser profile is persistent
(`.pw-profile`), so they only do it once per site.

## 2. Read the form

From the snapshot, describe **every** control on the application form as JSON:

```json
{"selector": "<a selector or ref you can use again>", "name": "...", "id": "...",
 "label": "<the visible label text, verbatim>", "placeholder": "...",
 "type": "text|textarea|select|radio|checkbox|file", "required": true,
 "options": ["Yes", "No"]}
```

Rules that matter:

- **`label` must be the visible label, copied verbatim** — question wording is
  what the answers bank matches on. Paraphrasing it breaks reuse.
- Include **custom screening questions**, not just the standard fields. Those are
  the whole point.
- Always list `options` for selects and radio groups; answers get snapped onto
  them.
- Mark `"kind": "screening"` on anything you're confident is a question but which
  has an odd label.
- Include file-upload controls; the API skips them and you handle them in step 4.
- Multi-step forms (Workday especially): describe the current step. You'll repeat
  steps 2–4 per step, but you still only submit once, at the end, after
  confirmation.

## 3. Prepare the application

`POST http://localhost:8088/apply/prepare`:

```json
{"job_url": "...", "company": "...", "title": "...", "location": "...",
 "description": "<full text>", "fields": [ ... ]}
```

This queues the job, generates the tailored résumé + cover letter, and returns a
`session_id`, a fill plan, and a `summary`. It takes a while — local models.

The response gives you:

- `standard_fields[]` — `{selector, value}` to type in.
- `screening_answers[]` — `{selector, answer, source}` where source is
  `bank` (reused), `profile` (a standing fact), or `new` (freshly drafted).
- `unfilled_fields[]` — plain inputs it deliberately left blank rather than
  invent. Do not fill these in yourself.
- `documents` — the résumé and cover-letter PDFs for **this** job, to upload.
- `reused_run: true` when this job already had a generated application and it
  was reused instead of regenerating. Say so in the summary, with its date — if
  the posting or their profile has changed since, offer to re-run
  `prepare` with `"regenerate": true`.

## 4. Fill the form — but do not submit

Type every `standard_fields[].value` and `screening_answers[].answer` into its
`selector`. Upload the résumé and cover letter to the file controls.

Leave `unfilled_fields` blank. **Never invent a value for a field the API left
blank** — that's how a made-up employee ID or referral code ends up in a real
application. They're in the summary for the user to handle.

Then take a `browser_take_screenshot` so the user can see the filled form.

## 5. Stop and ask

Show the user the summary. Lead with what needs their judgment:

1. **Newly drafted answers** (`summary.answers_new`) — quote each question and
   answer in full and say plainly that these are new and unverified.
2. **Fields left blank** (`summary.left_blank`), flagging required ones.
3. Any `summary.warnings`.
4. Then the routine part: reused answers, profile-filled fields, documents.

Lead the summary with `summary.review`:

- **`clean: true`** → say so in one line. Everything came from their profile or
  answers they've already approved; there is nothing new to read. "Ready — all
  reused, nothing new. Submit when you like."
- **`needs_review: [...]`** → these are the things to actually read. Quote each
  newly drafted answer in full, name each required blank.

Then the routine detail underneath: what was reused, what came from the profile,
which documents were attached.

## 6. Confirm

Confirm **before** handing over, so the answers get banked:

```
POST /apply/{session_id}/confirm
{"approved": true, "submit_by": "me", "edits": {...}, "note": "..."}
```

`submit_by: "me"` is the default and what you use unless the user explicitly
tells you to click submit for this job. It banks the approved answers and leaves
`may_submit` false, so nothing can submit for them.

If they want a drafted answer changed, edit it in the browser and pass it in
`edits` keyed by selector — the corrected text is what gets banked, not your
draft. If they want to skip the job entirely, send `{"approved": false}`.

## 7. Hand over

**Do not touch the submit button.** Leave the browser on the filled form and tell
them it's ready in one line, naming anything they still have to handle: required
blanks, a CAPTCHA, a login step, the remaining pages of a Workday flow.

Then wait. Don't nag, and don't poll the page guessing whether they submitted.

When they say they've submitted it — "done", "submitted", "next" — log it with
`"submitted_by": "me"` and the job is marked applied. If they say they're skipping
it, log `rejected`. If the site broke, log `failed`.

## 8. Log it — always

```
POST /apply/{session_id}/log
{"status": "submitted|rejected|failed", "submitted_by": "agent"|"me",
 "verified_success": true|false, "note": "..."}
```

`submitted` marks the job applied in the review queue (`applied: true`,
`status: applied`) and appends to its history — the same timeline as its emails.

Call this **every time**: when the user declined, when the site broke, when a
CAPTCHA blocked you, when they finished it by hand, or when you gave up.
`rejected` is already logged by step 6; still log `failed` for anything that
broke. An unlogged attempt is a lost application.

Then tell the user what was logged and what landed in the answers bank.

## Batch mode — working the queue

Triggered by "start applying", "work through the queue", "apply to everything
generated". No URLs are pasted; the worklist comes from the app.

```
GET /apply/candidates?limit=100
```

Returns generated, unapplied jobs that have an apply URL, ordered with pinned
priorities first, then repeat companies (you already have logins and saved
details there), then newest. **Attempted jobs drop off this list automatically**,
so you never track position: to get the next job, just fetch again and take the
first row. An interrupted run resumes by doing exactly that.

Before starting, tell the user how many there are and confirm the run. Then per
job:

1. `browser_navigate` to `apply_url`, then steps 1–7 above.
2. Announce it as `[n/total] Company — Title` so they can see progress.
3. **Wait for them to submit and say so.** Log it, then move to the next job
   immediately — don't ask permission to continue, they already approved the run.
4. `rejected` if they skip it, `failed` if it's blocked.

### Handling what goes wrong — skip, log, keep going

A batch must never stall. When a job is blocked, log `failed` with the reason and
move on; collect the list and report it at the end.

- **Indeed Apply / LinkedIn Easy Apply** (`likely_blocked: true`, or the redirect
  lands on `smartapply.indeed.com`) — don't automate these, it's against their
  terms. Log `failed` with reason "Indeed Apply — apply manually" and continue.
  Many `to.indeed.com` links *do* redirect to a company ATS, which is fine; you
  can only tell after following it.
- **Login required** and the browser isn't signed in — log `failed` with the
  reason and continue. Report these together at the end so they can sign in once
  and re-run for that company: `GET /apply/candidates?company=Rogers`.
- **CAPTCHA** — never attempt it. Log `failed`, continue.
- **Form unreadable / posting gone** — log `failed` with what you saw, continue.

### Pacing

Apply at a human pace. Don't fire off applications as fast as the browser allows:
it's rude to the employer's systems, it's how portals decide you're a bot, and the
user is reading each one anyway. One at a time, and the natural rhythm of waiting
for them to click submit is the pace.

If the user steps away mid-run, stop cleanly at the current job rather than
queueing up work they haven't seen. Nothing is lost — the worklist rebuilds itself.

### Wrapping up

When the run ends (list exhausted, or they say stop), report:

- how many submitted, skipped, blocked
- the blocked ones grouped by reason, so each group is one fix
- how many answers the bank gained — that's what makes the next run faster

`GET /apply/progress` gives you these counts directly.

## Things not to do

- Don't solve CAPTCHAs, create accounts, or defeat bot detection. Hand those to
  the user.
- Don't submit anything on LinkedIn Easy Apply or Indeed Apply — against their
  terms; the user applies there manually.
- Don't invent work history, dates, employers, or credentials. If a question
  needs a fact nobody has, draft the best honest answer, and make sure the user
  sees it flagged as unverified before it goes anywhere.
- Don't apply to a second job in the same run unless the user asked for that.
  Each application gets its own confirmation.
