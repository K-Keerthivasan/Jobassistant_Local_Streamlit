# Personas

A **persona** is a role-specific *framing* of your one true history. Same facts,
different emphasis: a sales job reads sales, a dev job reads dev. Personas change
framing only — the truth-guard still validates everything against
`master_profile.yaml`.

## Where they come from

The role base resumes in `Sample/kk_Base_*.docx` (Sales, Digital Marketing,
Software, Full-Stack, Content/Video, Admin, Data/Records) were distilled into
`data/profile/personas.yaml`. The renderer does **not** read the `.docx` files;
they are reference only.

## Definition

```yaml
personas:
  - id: sales
    label: "Sales"
    headline: "Sales Professional"
    keywords: ["sales", "account executive", "business development", ...]  # match the job
    links: ["LinkedIn", "K2 Digital Media"]      # (advisory; guard sets links from profile)
    lead_with: "Best Buy (computing sales), then K2 Digital Media ..."
    foreground_skills: "consultative selling, CRM, client relationships, ..."
    summary_seed: >
      Customer-facing sales professional who closes on fit ...   # truthful, from the base resume
```

## Selection

`src/resume_gen/personas.py`:

- **Auto** — `auto_select(target)` scores keyword overlap against the job title
  (weighted 3×) + description; the best-scoring persona wins, or `None` (neutral)
  if nothing matches.
- **Override** — pass a persona `id`; `"auto"`/empty means auto-detect.
- The chosen persona produces a **directive** appended to the prompt (headline,
  summary framing, which experience to lead with, which skills to foreground). It
  is also passed to the truth-guard so the **skills backfill** is role-relevant.

## In the app & API

- Sidebar **Persona** picker (Auto-detect + each role) applies to Generate, Bulk,
  and Scraper generation.
- `GET /personas` → `[{id, label, headline}]`.
- `persona` field on `POST /generate` and `POST /jobs/{key}/generate`
  (`"auto"`/omit = auto-detect). The result reports `persona` and `persona_label`.

## Relevant skills for non-tech roles

`master_profile.yaml` includes non-engineering skill groups (`marketing`,
`sales_service`, `creative_media`, `office_admin`) so sales/marketing/video/admin
resumes show relevant skills instead of programming languages. Persona
`foreground_skills` orders both the model's output and the guard's backfill.
