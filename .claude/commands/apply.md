---
description: Apply to ONE job posting from its URL — fills everything, stops for you to submit
argument-hint: <job-url>
---

Single-job apply mode.

Use the `apply-to-job` skill and run its steps 1–8 **once**, for this posting:

$ARGUMENTS

If no URL was given above, ask for one rather than guessing or falling back to
the queue.

Reminders for this mode:

- The user clicks submit. Confirm with `submit_by: "me"` and hand over the filled
  form. Do not click the submit button unless they explicitly tell you to for
  this job.
- Lead the summary with `summary.review`: if `clean`, say so in one line; if not,
  quote every newly drafted answer in full and name every required blank.
- Log the outcome when they tell you what happened — submitted, skipped, or
  broken. Never leave an attempt unlogged.
