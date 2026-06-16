# Bulk generate from a CSV

Two ways to bring a CSV of jobs into the app:

1. **Bulk Generate tab → ⬆ Upload CSV** — loads the rows straight into the bulk list so
   you can review/edit and hit **Generate all** (or tick **Auto-generate** to start
   immediately). The CSV is parsed in the browser; nothing is queued.
2. **RSS Scraping → ⬆ Upload CSV** — imports the rows into the **job queue**
   (`POST /jobs/import`, deduped) so they show up in the **Jobs** tab to filter and
   bulk-generate there.

Both accept the same columns. Grab a starter file with **Bulk Generate → ⬇ Template**.

## Columns

First row is the header. Only `company` **or** `title` is required per row; the rest are
optional. Column names are matched flexibly (aliases below), order doesn't matter, and
unknown columns are ignored.

| Column          | Required | Aliases accepted                                  | Notes |
|-----------------|----------|---------------------------------------------------|-------|
| `company`       | one of\* | `employer`, `organization`, `business`            | Hiring company |
| `title`         | one of\* | `job_title`, `position`, `role`                   | Exact job title |
| `location`      | no       | `city`, `place`                                   | e.g. `Toronto, ON` or `Remote` |
| `description`   | no       | `description_summary`, `summary`, `jd`            | The job description — drives tailoring; the more, the better |
| `apply_url`     | no       | `url`, `link`, `source_url`, `job_url`            | Direct posting/apply URL |
| `contact_email` | no       | `email`, `contact_emails`, `hr_email`             | Application email if known (enables the 📧 n8n path) |

\* Each row needs at least a `company` or a `title`; rows with neither are skipped.

## Format rules

- Wrap any field containing a comma, quote, or newline in double quotes; escape a literal
  `"` inside a quoted field by doubling it (`""`).
- Keep each row on one line (newlines inside a quoted `description` are fine).
- UTF-8.

## Example

```csv
company,title,location,description,apply_url,contact_email
"Acme Inc","Full-Stack Developer","Toronto, ON","Build React + Node apps. TypeScript, REST, Postgres. 0-3 yrs.","https://acme.com/jobs/123","jobs@acme.com"
"Globex","Backend Developer","Remote","Python, FastAPI, Docker, AWS.","https://globex.com/careers/45",""
```

Generation still runs the full truth-only pipeline (Hermes QA → deterministic truth-guard
→ page validation) on every row, so imported jobs are tailored against your profile, not
copied verbatim.
