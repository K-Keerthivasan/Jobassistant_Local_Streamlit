# Skill matrix index

One matrix per lane. The sourcing engine reads the matching lane file before gating any role in that lane, and before any Mode C or Mode D work on it.

| Lane | File | Track | Set |
|---|---|---|---|
| 1 | `lane-01-qa-testing.md` | technical | priority |
| 2 | `lane-02-it-support.md` | technical | priority |
| 3 | `lane-03-ai-automation.md` | technical | priority |
| 4 | `lane-04-software-development.md` | technical | secondary |
| 5 | `lane-05-data-analytics.md` | technical | priority |
| 6 | `lane-06-technical-sales.md` | technical | secondary |
| 7 | `lane-07-digital-marketing.md` | creative | Track 2 |
| 8 | `lane-08-social-content.md` | creative | Track 2 |
| 9 | `lane-09-video-multimedia.md` | creative | Track 2 |
| 10 | `lane-10-design.md` | creative | Track 2, opportunistic only |
| 11 | `lane-11-game-development.md` | technical | priority, new v3.5 |
| 12 | `lane-12-vfx.md` | creative | Track 2, new v3.5 |

## The schema every file uses

Each matrix carries the same five things: the NOC map for the lane, the skill list split into Must, Important, Optional, Later and Not required, a Status and Evidence column per skill, the tier rules, and an honest-positioning note.

**Status is the only column that may be treated as fact about what Keerthi can do.**

- `held` - can do it today, Evidence names where it was done. Usable in a fit sentence.
- `partial` - real but incomplete exposure. Usable only with the limit stated in the same sentence, and still a gap flag when the posting hard-requires the full thing.
- `building` - actively learning, not demonstrable. Never evidence. Always a gap flag.
- `not yet` - no exposure. Always a gap flag.

**Keerthi maintains Status and Evidence. The engine reads them and never upgrades them on its own.** A skill appearing in a table is not a claim that he has it. Where a starting status is filled in below, it is drawn from work the project already records: Certify Technologies IT support, Bill Gosling Outsourcing, the Haply Robotics and Materia Bioworks placements, K2 Digital Media client work, the ClubJunk channel, and the public repos at github.com/K-Keerthivasan. Everything else starts at `not yet`.

## Tier rules, identical in every lane

- **Tier A, apply now.** Every Must-tier skill the posting hard-requires is `held`. Gaps sit in Important or below.
- **Tier B, apply with a named gap.** One or two hard-required Must-tier skills are not `held`. Ships, with every missing item named in `gap_flags`.
- **Tier C, drop.** Three or more hard-required Must-tier skills are not `held`, or the posting hard-requires a Later-tier item as a prerequisite rather than an asset.

Tier drives the fit sentence and the gap flags. It does not override any of the twelve filter gates, and it never rescues a role that failed the seniority gate.

## The rule that matters most

Adjacent experience never stands in for a named requirement. Running n8n pipelines is not SQL. Editing Reels is not motion graphics. Resolving tickets is not network administration. Where the gap is real, it goes in `gap_flags` by name, in every lane, every time. Understating is recoverable. Overstating gets found in a technical screen.

## Credentials on file

Named credentials matter in lanes 11 and 12 especially, and they were missing from the earlier matrices.

- **Visual Effects and Editing for Contemporary Media**, Fanshawe College, London ON, 2024 to 2025.
- **Game Development: Advanced Programming**, Fanshawe College, London ON, 2023 to 2024.
- **Master of Computer Applications**, Anna University, Chennai, 2020 to 2022. This carries the post-secondary credential requirement for the Ontario Workforce Priority stream.
- **Bachelor of Commerce**, Ramakrishna Mission Vivekananda College, Chennai, 2017 to 2020.

Portfolio surfaces: `film.kkvasan.ca` for VFX and film, `k2digitalmedia.ca` for agency work, `blog.kkvasan.ca`, and `github.com/K-Keerthivasan` for code.

## Maintenance

Update a Status the day the skill becomes real, not the day the certificate arrives. Re-read the affected lane file before the next run in that lane. When a lane's Must tier goes fully `held`, say so and the engine will start grading its postings Tier A instead of Tier B.
