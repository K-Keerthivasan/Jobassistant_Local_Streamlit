---
description: Work through the job queue continuously — fills each application, you click submit, repeat
argument-hint: [count] [company=X] [since=YYYY-MM-DD]
---

Batch apply mode. Target for this run: **$ARGUMENTS** (default **50** jobs if no
count was given; a `company=` or `since=` argument narrows the worklist).

Use the `apply-to-job` skill, *Batch mode* section, and work continuously until
the target is hit, the worklist is empty, or the user says stop.

## Start

1. `python -m resume_gen.automation.apply_cli next --limit <target>` (add `--company` / `--since`).
2. Report the count and the makeup — how many are repeat companies, how many are
   flagged `likely_blocked` — then start. Don't ask permission again after this;
   the user invoked the batch deliberately.
3. If the list is empty, say so and stop. Don't invent work.

## Per job

Steps 1–7 of the skill, then log. Announce each as:

```
[n/target] Company — Title          ✅ clean   |   ⚠ 2 to check
```

- **`clean`** → one line, hand over, wait for them to submit.
- **not clean** → quote each newly drafted answer in full and name each required
  blank *before* handing over. This is the only part they must read carefully.
- They say "done"/"submitted"/"next" → log `submitted` with `submitted_by: "me"`
  and go straight to the next job. No "shall I continue?" between jobs.
- They say "skip" → log `rejected`, next.
- Blocked (Indeed Apply, CAPTCHA, login wall, dead posting) → log `failed` with
  the reason, next. **Never stall the batch on a blocked job.**

## Pace

This run is meant to cover its target over a few hours — roughly four minutes a
job, which is the natural rhythm of the user reading and clicking. Don't rush
them and don't fire applications as fast as the browser allows: it's how portals
decide you're a bot, and they're reviewing each one anyway.

Every ~10 jobs, post a one-line checkpoint: done / skipped / blocked / remaining,
and how many answers the bank has gained.

## If the session gets long

A run this size may exhaust the context. That is safe and needs no cleanup:
attempted jobs have already dropped off the worklist, so tell the user to start a
fresh session and run `/apply-batch` again — it resumes exactly where this left
off. There is no cursor to reset and nothing to re-confirm.

If the user steps away mid-run, stop cleanly at the current job rather than
queueing work they haven't seen.

## At the end

Report from `python -m resume_gen.automation.apply_cli status`:

- submitted / skipped / blocked counts
- the blocked ones **grouped by reason**, so each group is one fix (e.g. "6 need
  a Scotiabank login — sign in once and re-run `/apply-batch company=Scotiabank`")
- how many answers the bank gained, since that's what makes the next run faster
