# Repeatable roles + email intake

Big employers (TD, RBC, CIBC…) post the **same role over and over**. You apply, sometimes
you get it, usually you reapply next cycle. This feature keeps a **per-role template** so
reapplying is: open the role → **Regenerate** → download → tweak → submit.

## The model

A **repeatable role** is one recurring posting, keyed by **company + title**
(`data/repeatable/<slug>.json`). Each `RepeatableRole` stores:

| field | meaning |
|------|---------|
| `company`, `title`, `location` | who/what |
| `description` | the **latest job description** — what regeneration runs against |
| `apply_url`, `contact_email` | where to apply / HR email |
| `persona`, `priority` | how to generate (persona id; ⭐ → Claude in Auto) |
| `times_applied`, `last_applied` | running count + most-recent date |
| `last_folder` / `last_folder_name` | the most recent generated application |

TD · *Software Developer* and TD · *Data Analyst* are **separate** templates.

## Using it

### Flag a job as repeatable
In **Jobs**, click the **🔁** next to a job title. That saves a template from the job
(`POST /jobs/{key}/repeatable`). Click again to remove it. Jobs whose company+title match
a saved template are tagged (`repeatable_role: true` from `GET /jobs`).

This works for **any** job — manual, collector, RSS, Job Bank, email.

### The Repeatable tab
Lists every template, most-recently-applied first. Per role:

- **⟳ Regenerate** — `POST /repeatable/{key}/generate` runs the normal pipeline against the
  saved JD (persona from the sidebar, ⭐ priority → Claude), bumps `times_applied`, stamps
  `last_applied`/`last_folder`, and returns **download links** (resume/cover PDF+DOCX, email).
- **✎ Edit JD** — paste a refreshed posting, **Save JD** (`POST /repeatable/{key}/update`).
- **📂 Last docs** — open the previous generation in Library.
- **🗑** — stop tracking (generated files are kept).

## Email intake — the same job arriving by email

Job alerts land in your inbox with the role you already track. Two ways in, same endpoint:

### In-app (Repeatable tab → 📩 Add from an email)
Paste the whole email. The engine (sidebar picker) extracts company / title / location /
description / apply URL, **strips email boilerplate** (unsubscribe, "view in browser",
tracking links), and:

- if it **matches** an existing repeatable role (same company+title) → refreshes that
  template's JD ("came round again");
- else queues it as a normal job (source `email`); tick **Save as repeatable role** to also
  start tracking it.

It ignores the **sender** as the company (e.g. "LinkedIn Job Alerts") and uses the real
hiring employer named in the body.

### n8n / Gmail (automated)
Point an n8n Gmail trigger at:

```
POST http://<host>:8088/jobs/from-email
Content-Type: application/json

{ "text": "<the email body>", "repeatable": true }
```

Same parsing + matching. `model` is optional (defaults to local Ollama; pass a `claude-*`
id to use Claude). Response: `{ parsed, queued, duplicate, job, matched_repeatable, repeatable_key }`.

## API summary

| method | path | does |
|--------|------|------|
| `POST` | `/jobs/{key}/repeatable` | flag/unflag a queued job; create/remove its template |
| `GET`  | `/repeatable` | list templates |
| `POST` | `/repeatable/{key}/generate` | regenerate from saved JD, bump count, return paths |
| `POST` | `/repeatable/{key}/update` | edit JD / fields |
| `DELETE` | `/repeatable/{key}` | stop tracking |
| `POST` | `/jobs/from-email` | parse an email → job, queue + match template |

Engine selection reuses the sidebar **Auto / Local / Claude** picker (`resolveModel`):
a role marked ⭐ priority regenerates with Claude, the rest with local Ollama.
