"""CLI for the lane data files.

    python -m resume_gen.lanes validate          # npm run validate:data
    python -m resume_gen.lanes sync [--check]    # npm run sync:lanes
    python -m resume_gen.lanes drift             # npm run drift:lanes
    python -m resume_gen.lanes show <lane>       # print one lane's skills by tier
"""

from __future__ import annotations

import argparse
import json
import sys

# Windows consoles default to cp1252; keep output printable.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="resume_gen.lanes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="validate every file under data/")
    s = sub.add_parser("sync", help="convert data/lanes/source/*.md to data/lanes/*.json")
    s.add_argument("--check", action="store_true", help="report what would change, write nothing")
    sub.add_parser("drift", help="compare lane JSON against the markdown it was generated from")
    sh = sub.add_parser("show", help="print one lane")
    sh.add_argument("lane")
    args = ap.parse_args(argv)

    if args.cmd == "validate":
        from .validate import main as vmain
        return vmain([])

    if args.cmd == "sync":
        from .sync import LaneSyncError, sync_all
        try:
            rep = sync_all(check_only=args.check)
        except LaneSyncError as e:
            print(f"sync:lanes REFUSED, nothing written:\n{e}")
            return 1
        for w in rep["warnings"]:
            print(w)
        for f in rep["written"]:
            print(f"wrote     {f}")
        for f in rep["would_change"]:
            print(f"changed   {f}")
        for f in rep["unchanged"]:
            print(f"unchanged {f}")
        if args.check and rep["would_change"]:
            print("\nsync:lanes --check: JSON is out of date. Run without --check.")
            return 1
        print(f"\nsync:lanes OK: {len(rep['written'])} written, {len(rep['unchanged'])} unchanged.")
        return 0

    if args.cmd == "drift":
        from .sync import drift_report
        rows = drift_report()
        bad = 0
        for r in rows:
            flag = "ok   " if r["status"] == "ok" else "DRIFT"
            bad += r["status"] != "ok"
            print(f"{flag} lane {r['lane']:>2} {r['slug']:<22} {r['detail']}")
        print("\nno drift." if not bad else f"\n{bad} lane(s) drifted.")
        return 1 if bad else 0

    if args.cmd == "show":
        from . import get_lane, resolve_lane
        lane = get_lane(args.lane) or resolve_lane(args.lane)
        if not lane:
            print(f"no lane matches {args.lane!r}")
            return 1
        print(f"Lane {lane.lane} | {lane.title} | {lane.track} / {lane.set} | NOC {', '.join(lane.noc_codes())} | v{lane.version}")
        for tier in ("must", "important", "optional", "later"):
            rows = lane.by_tier(tier)
            if not rows:
                continue
            print(f"\n{tier.upper()}")
            for s in rows:
                lim = f"  [limit: {s.limit}]" if s.status == "partial" else ""
                print(f"  {s.status:<8} {s.name}{lim}")
        print("\nkeywords:", json.dumps(lane.keywords.model_dump(), ensure_ascii=False)[:400])
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
