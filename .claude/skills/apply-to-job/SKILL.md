---
name: apply-to-job
description: Apply to job postings on any site (any ATS or company careers page) — either one posting from its URL, or continuously through the generated-jobs queue one after another. Opens each posting in a browser, reads the form, reuses the tailored resume and cover letter already generated for that job, answers screening questions from the answers bank, fills the whole form and uploads the documents, then hands over for the user to click submit and marks the job applied. Use when given a job URL, asked to fill out or apply to a job application, or asked to start applying / work through the job queue / apply to everything generated.
---

# Apply to job postings

You drive the browser. The app owns every decision — what goes in each field,
which answers are reused, what gets banked, what is logged. Don't reimplement any
of it.

**The user clicks submit. You do everything else.** Fill every field, upload the
documents, then hand them a finished form. Never click a submit button yourself.

## Talk to the app through its CLI, not HTTP

Everything runs on this machine, so use the CLI — it works on the database
directly, needs no container, and prints compact text instead of JSON, which
matters when you're doing this fifty times in one session.

```bash
python -m resume_gen.automation.apply_cli <command>
```

Run from the repo root. `next` · `prepare` · `show` · `done` · `skip` ·
`blocked` · `status`. Add `--help` to any of them.

## Read as little of the page as possible

Snapshotting a career page is by far your biggest cost. Three rules:

1. **Try the remembered form first.** `prepare <job_key>` with no `--fields` uses
   the form this site was last seen with. Verify a couple of those selectors
   still exist on the live page; if they do, you never read the page at all. If
   they don't, the site changed — read it and pass `--fields`.
2. **Never read the job description.** The app already has it. There is no
   argument for passing it; `prepare` uses the stored one.
3. **Snapshot the form, not the page.** When you must read, scope it to the form
   element. Nav, footer, cookie banner and "similar jobs" are most of the page
   and none of it matters.

## The loop

### 1. Pick a job

```bash
python -m resume_gen.automation.apply_cli next --limit 5
```

Prints `key_id`, employer, title, ATS, the apply URL, and whether the form is
already known. Attempted jobs drop off automatically, so this always shows what's
actually left — there is no cursor to track and an interrupted run resumes by
just calling it again.

By default it hides LinkedIn/Indeed/Job Bank listing URLs, which are job adverts
with no application form on them. Pass `--all` only if you specifically need to
see those.

### 2. Open it

`browser_navigate` to the apply URL. Follow the Apply button if the form is on a
separate page.

If it needs a login and the browser isn't signed in, **stop and ask the user to
sign in**. Chrome's profile is persistent, so it's once per employer, and its
password manager will offer to save. Let Chrome's autofill handle identity fields
where it offers — that's free and leaves you only the screening questions.

### 3. Read the form (only if the remembered one doesn't fit)

Describe every control as JSON in a file, then pass `--fields`:

```json
[{"selector": "<a selector you can reuse>", "name": "...", "id": "...",
  "label": "<the visible label, verbatim>", "type": "text|textarea|select|radio|checkbox|file",
  "required": true, "options": ["Yes", "No"]}]
```

`label` must be the visible label copied **verbatim** — that text is what the
answers bank matches on, so paraphrasing it breaks reuse. Include every custom
screening question, and always list `options` for selects and radio groups.

### 4. Prepare

```bash
python -m resume_gen.automation.apply_cli prepare <job_key> [--fields form.json]
```

Prints the plan, line by line:

| | |
|---|---|
| `FILL` | from the user's profile |
| `REUSE` | an answer they approved before |
| `PROFILE` | a standing fact (work authorization, notice period) |
| `NEW` | **drafted fresh — unverified, they must read it** |
| `YOURS` | protected characteristic or consent — **leave it entirely alone** |
| `BLANK` | deliberately not filled; never invent a value |

Plus `CLEAN`, or `CHECK` lines naming what needs their eyes.

### 5. Fill — but do not submit

Type each `FILL`/`REUSE`/`PROFILE`/`NEW` value into its selector. Upload the
documents from the printed `rel_path`.

**Never touch `YOURS` or `BLANK` rows.** Demographic questions, e-signatures and
consent checkboxes are the user's to answer — the app deliberately refuses to
answer them, and filling one yourself would be inventing a legally sensitive
disclosure. Leave them blank and name them when you hand over.

### 6. Hand over

Report in this order — what needs judgment first:

1. every `NEW` answer, quoted in full, said plainly to be new and unverified
2. `YOURS` questions and any required `BLANK`s they must complete
3. then one line for the routine part: reused answers, documents attached

If it came back `CLEAN`, say so in one line and stop there.

Then **wait**. Don't nag, and don't poll the page guessing whether they
submitted.

### 7. Record it

They say done/submitted/next:

```bash
python -m resume_gen.automation.apply_cli done <session_id> [--edit "#why=corrected text"]
```

Banks the approved answers and marks the job applied. If they corrected a drafted
answer, pass it with `--edit` — the corrected text is what gets banked, not your
draft.

They skip it → `skip <session_id> --note "why"`.
Something blocked it → `blocked <session_id> --reason "..."`.

**Log every attempt.** An unlogged one is a lost application.

## Batch mode

"start applying", "work through the queue". Same loop, no URLs pasted. Report the
count from `next`, then work continuously: announce each job as
`[n/total] Company — Title`, and after they submit go straight to the next one —
don't ask permission to continue between jobs, they already approved the run.

**Never stall.** Anything blocked gets `blocked` and you move on:

- **Indeed Apply / LinkedIn Easy Apply** — don't automate these, it's against
  their terms. Log and continue.
- **Login wall** with no saved credentials — log, continue, and collect these so
  the user can sign in once and re-run for that employer.
- **CAPTCHA** — never attempt it.
- **Posting gone / form unreadable** — log what you saw, continue.

Pace it like a person. One at a time; waiting for them to click submit *is* the
pace. Every ~10 jobs post a one-line checkpoint from `status`.

If the session grows too long, that's safe: attempted jobs have already dropped
off, so a fresh session picks up exactly where this one stopped. If the user steps
away, stop cleanly at the current job.

At the end, report from `status`: submitted / skipped / blocked, the blocked ones
**grouped by reason** so each group is one fix, and how many answers the bank
gained — that's what makes the next run faster.
