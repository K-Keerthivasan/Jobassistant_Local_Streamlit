# Data changelog

One entry per instruction-set version. This file tracks the knowledge under `data/`
(lanes, NOC table, profile, answer bank, outreach templates), not the app code. App
changes live in `docs/CHANGELOG.md`.

The app reads `version` from `data/lanes.index.json` and every lane file carries the
same value. `npm run validate:data` fails when they disagree.

## v3.5 | 2026-09-14

- Two new lanes: lane 11 game development and game design (NOC 21232, TEER 1, joins the
  Track 1 priority set) and lane 12 VFX artist junior (NOC 52111, 52119, 52120, TEER 2,
  Track 2, never RCIP).
- Credentials added to the index and profile: Visual Effects and Editing for Contemporary
  Media (Fanshawe, 2024 to 2025), Game Development: Advanced Programming (Fanshawe,
  2023 to 2024), and the MCA from Anna University that carries the post-secondary
  requirement for the Ontario Workforce Priority stream.
- Correction: lane 9 listed Nuke as not yet. Nuke is a working tool and compositing now
  reads held in lane 9. Lane 12 carries the full treatment.
- First time the matrices live in this repo as data: twelve lane JSON files generated from
  the source markdown by `npm run sync:lanes`, gated by `npm run validate:data`, plus
  `noc.json`, `profile.json`, `answer-bank.json` and `outreach-templates.json`.
- Two sections appended to every source markdown file so the markdown stays the single
  thing edited by hand: `## Sourcing vocabulary` (where a lane had none) and `## Aliases`
  (the alternate names the grader matches against posting text).

## v3.4 | 2026-09-13

- Every lane has a skill matrix, not just lane 5. Same schema throughout: NOC map, Must,
  Important, Optional, Later and Not required tiers, a Status and Evidence column per
  skill, tier rules, honest positioning and interview watch. `00-index.md` is the map.
- Readiness tiering (Tier A apply now, Tier B apply with a named gap, Tier C drop)
  becomes a system-wide rule in every lane.
- Lane 5 statuses moved to held on Keerthi's review of 2026-09-14: SQL, Excel, Power BI,
  Python, statistics, business analytics, data cleaning, data visualization and data
  storytelling, plus Git, APIs and relational database fundamentals. Junior analyst
  postings grade Tier A rather than Tier C. A plain-language capability statement lives
  in `docs/reference/data-analyst-capability-statement.md`.

## v3.3 | 2026-09-13

- Data and analytics becomes a real lane (lane 5) with a keyword vocabulary, a corrected
  NOC map and the first skills matrix. It joins the priority set.
- NOC corrections: 21223 is TEER 1, not TEER 2. 12112 (records management technicians)
  is not a data analyst code and moves to the trap list. 12113 stays at TEER 2.
- The PNP map is corrected: British Columbia removed its priority technology list on
  23 April 2026, and Ontario replaced eight OINP streams with a single Ontario Workforce
  Priority stream on 26 June 2026, open to any NOC with a qualifying offer. Weight moves
  from British Columbia to Ontario.

## v3.2 | 2026-09-13

- Stream D (US remote roles that can legally hire a Canadian resident) is introduced,
  with the `US-REMOTE` and `HIRE-CA: entity | eor | contractor` tags and the
  `remoteboard` source value. Headers unchanged; no columns added.
