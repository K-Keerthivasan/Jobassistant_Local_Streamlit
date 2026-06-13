# Bulk-pull jobs in Claude.ai → CSV for this app

The Indeed / LinkedIn connectors live **inside Claude.ai** (not callable from this
self-hosted app). So pull jobs there in bulk, export a CSV, then import it here via
**RSS Scraping → ⬆ Upload CSV**. The CSV columns below are exactly what this app's
importer reads.

## How to use

1. In **Claude.ai**, enable the **Indeed** connector (Settings → Connectors).
2. Paste the prompt below, editing the **SEARCH** block (role, location, count).
3. Claude returns a CSV. Save it as `jobs.csv`.
4. In this app: **RSS Scraping → ⬆ Upload CSV → pick `jobs.csv`** → the jobs land in
   **Jobs** (Canada/keyword filters are skipped for imported jobs — you chose them).

## The prompt (copy, edit the SEARCH block, paste into Claude.ai)

```
You have the Indeed connector. Pull job postings and return them as CSV ONLY.

SEARCH:
- role / keywords: software developer
- location: Ontario, Canada
- how many: 200
- posted within: last 14 days
- only roles asking for 0–3 years of experience (entry/junior/intermediate)

For each posting, collect:
- company           the hiring company name
- title             the exact job title
- location          city/province (or "Remote")
- description       a 2–4 sentence summary of the responsibilities + key requirements
- apply_url         the direct apply / posting URL
- contact_email     the application email IF the posting clearly states one, else leave blank

OUTPUT RULES — follow exactly:
1. Output ONLY a CSV. No prose before or after, no code fences, no commentary.
2. First line is the header, exactly:
   company,title,location,description,apply_url,contact_email
3. One row per job. Wrap every field in double quotes; escape any " inside a field
   as "". Keep each description on a single line (no line breaks inside a field).
4. Do NOT invent jobs, emails, or URLs. Only include real postings you actually
   retrieved. If a field is unknown, leave it empty (still keep the column/comma).
5. De-duplicate: one row per unique company+title.
6. Aim for the requested count; if fewer real postings exist, return what you found.
```

## Tips

- Run it again with different **role / location** to build a big CSV across searches
  (paste the new rows under the same header, or import each CSV separately — the app
  de-dupes on import).
- LinkedIn works the same way — swap "Indeed connector" for "LinkedIn connector".
- Most Indeed/LinkedIn postings are "apply on site" (no email). For email-apply, add
  the HR email **after import** on the job itself (Jobs tab → ✉ on the row, or open the
  job and edit the email) — then it's ready for the 📧 n8n path.
- Column names are matched flexibly on import (`job_title`, `employer`, `url`, `email`,
  etc. also work), so a CSV exported from elsewhere usually imports without edits.
