# Lane file migrations

A change to the *shape* of a lane file (a renamed field, a new required field, a
changed enum) ships here as a numbered script plus a version bump in
`data/lanes.index.json` and every lane file. Never a silent shape change.

A change to the *content* of a lane (a status flip, a new keyword, a reworded
evidence line, a new NOC code, a new lane) is not a migration. Edit the markdown
under `data/lanes/source/`, run `npm run sync:lanes`, and `npm run validate:data`
gates it.

## How a migration works

1. Write `NNN_<what>.py` next to this file. It takes the data directory as its
   only argument, rewrites every lane JSON in place, and prints what it changed.
   It must be idempotent: running it twice changes nothing the second time.
2. Update the pydantic schema in `src/resume_gen/lanes/schema.py` and the
   converter in `src/resume_gen/lanes/sync.py` in the same commit, so a fresh
   `sync:lanes` produces the new shape directly.
3. Bump `version` in `data/lanes.index.json`. Add the entry to `data/CHANGELOG.md`.
4. Run the migration, then `npm run validate:data`, then `npm run sync:lanes --check`
   (which must report no changes; if it does, the converter and the migration
   disagree and one of them is wrong).

## History

| Script | Version | What |
|---|---|---|
| (none yet) | 3.5 | Initial shape. `Skill.note` and `Skill.evidence_from_note` were added before the first commit, so no migration was needed. |
